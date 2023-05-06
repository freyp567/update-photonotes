"""
Encapsulates update handling
"""

import datetime
from pathlib import Path
from typing import Optional
from lxml import etree

from evernote_backup.note_exporter import ENEX_HEAD, ENEX_TAIL
from evernote_backup.note_formatter import NoteFormatter
from evernote_backup.note_exporter_util import SafePath
from evernote.edam.type.ttypes import Note


from .conversion import get_note_content
from .flickr_types import FlickrPhotoNote, FlickrDate
from .database import PhotoNotesDB, lookup_note
from .exceptions import NoteNotFound,  PhotoNoteNotFound
from .note_utils import Note2

import logging
logger = logging.getLogger('app.updater')


FLICKR_URL = "https://www.flickr.com/"
FLICKR_PHOTO_URL = "https://www.flickr.com/photos/"
NO_UPDATE_AGE = 3*30  # do not update photo notes that got updated in last 3 months

TAG_NAME_PHOTONOTE = "flickr-image"
TAG_NAME_BLOGNOTE = "flickr-blog"

class NotesUpdater:

    def __init__(self, notes_db: PhotoNotesDB, options):
        self.notes_db = notes_db
        self.safe_paths = SafePath(options.export_dir, True)
        self.options = options
        self.limit = options.limit
        self.count = None
        self.pos = 0
        self.warnings = {}  # categorized list of warnings

    def update(self, notebook: str) -> None:
        self.count = 0
        export_enex = (self.options.export_dir is not None)

        notes = self.notes_db.store.notes
        if not self.options.debug:
            # calculating total number of notes costs some seconds, so show only if not debugging
            count_notes = notes.get_notes_count()
            count_trash = notes.get_notes_count(is_active=False)
            logger.info(f"have {count_notes} notes in store ({count_trash} inactive)")

        self.pos = 0
        processed = []
        notebooks = tuple(self.notes_db.store.notebooks.iter_notebooks())
        for nb in notebooks:
            if notebook not in("*", "all") and nb.name != notebook:
                logger.debug(f"skip notebook: {nb.name}")
                continue
            processed.append(nb.name)
            self._update_notes(nb, export_enex)
        logger.info(f"updated notebook: {processed} ")
        return

    def _need_update_blog(self, blog_note) -> bool:
        """ verify content of blog note """
        content = get_note_content(blog_note.content)
        try:
            xml = etree.fromstring(content)
            for anchor in xml.xpath('//a'):
                href = anchor.attrib.get("href")
                if 'flickr.com' not in href:
                    continue
                if href.startswith(FLICKR_PHOTO_URL):
                    # 'href': 'https://www.flickr.com/photos/27297062@N02/51089206529/in/pool-inexplore/',
                    # ..., 'rev': 'en_rl_none', 'target': '_blank'}
                    self._handle_image_link(blog_note, href)
                else:
                    logger.debug(f"ignored href={href!r}")

            # 'www.flickr.com/people/'
            if 'www.flickr.com/photos' not in content_text:
                return False
            return True
        except Exception as err:
            logger.exception('update check failed')
        return False

    def _extract_see_v1(self, xml, note: Note):
        """
        extract image info - first implementation
        this is a bit troublesome as the links contained in the photonotes are not always properly formatted
        and there may be also misleading links after the image thumbnal in the description from the photo author
        """
        cleanup_required = False
        divs = xml.xpath('//div[substring-after(text(), "see:")]')
        if not divs:
            return None, None
        if len(divs) > 1:
            # a photo note may contain a stack of related / similar images
            logger.debug(f"photo note with stacked images ({len(divs)-1}), last: {etree.tostring(divs[-1])}")
            # we assume last 'see:' is the one related to the main image

        ## DODO accumulate div_info items found, but show only if there is a mismatch - and drop debugging prints
        print(f'\n\n[#{self.pos}] - {note!r}')  ##debugging
        highlighted = []
        found = None
        for div in divs:
            div_info = etree.tostring(div)
            print(f"[see] - {div_info}")  ## debugging

            found = div.xpath("span", _style="--en-highlight:yellow")
            if found:
                assert len(found) == 1, f"found multiple highlight sections in see-info div: {div_info}"
                found = found[0].text
                if found:
                    found = found.strip()
                if found:
                    highlighted.append((div, found))
                else:
                    # highlight on whitespace - hard to see but it happes; just ignore
                    logger.warning(f"ignore highlight on whitespace, see {div_info}")
                    found = None

            else:
                # assume stacked image without highlight
                found = div.xpath(".//text()")
                if not found:
                    # TODO examine
                    found = div.text or '(see-info missing)'
                    logger.warning(f"{self.pos}| see-info found: {found}")
                    # TODO examine
                else:
                    found = ' '.join([f.strip() for f in found])
                    logger.debug(f"{self.pos}| found see-info for stacked image: {found}")

        if found is None:
            return None, None

        if found.startswith('see:'):
            found = found[4:].strip()
        if '|' in found:
            found = found.split('|')[0].strip()
        if found in ('(not archived)', '-NA-'):
            return None, None
        if not highlighted:
            logger.warning(f'{self.pos}| missing highlighted see-info for main image of {note}')
            cleanup_required = "see-info not highlighted"
        elif len(highlighted) > 1:
            # unexpected to have more than one, need to verify manually
            logger.warning(f'{self.pos}| failed to detect highlighted see-nfo for {found} - {note}')
            cleanup_required = "see-info not found"
        elif highlighted[-1][1] != found:
            logger.warning(f'{self.pos}| mismatch with highlighted see-info for "{found}" in {note}')
            cleanup_required = "see-info mismatch"
        else:
            pass
        return found, cleanup_required

    def _next_link_href(self, node):
        """ get href of anchor element following given node (sibling of) """
        while True:
            node = node.getnext()
            if node is None:
                cleanup_required = "failed to find main image link for photo note"
                break
            anchor = node.xpath('a')
            if anchor:
                assert len(anchor) == 1
                return node, anchor[0].attrib.get("href")
        return None, None

    def _extract_see(self, xml: etree.Element, note: Note):
        """
        extract image info - second edition / replaces _extract_see_v1
        """

        def get_see_text(node):
            node_info = etree.tostring(node)
            see_info = ' '.join([f.strip() for f in node.xpath(".//text()")])
            see_info = see_info[4:].strip()   # strip see: prefix
            is_highlight = node.xpath("span", _style="--en-highlight:yellow")
            if is_highlight:
                if len(is_highlight) > 1:
                    self.add_warning("cleanup required", "multiple highlights in see-info")
                    logger.warning(f"found multiple highlight sections in see-info div: {node_info}")
                value = ' '.join([f.strip() for f in is_highlight[0].xpath(".//text()")])
                if value:
                    value = value.strip()
                if not value:
                    logger.warning(f"ignore highlight with only whitespace in {node_info}")
                    return ""
            else:
                # stacked see-info, prepend plus to indicate
                if '|' in see_info:
                    see_info = see_info.split('|')[0].strip()
                if not see_info:
                    see_info = " (no text)"
                value = '+' + see_info
            return value

        see_divs = xml.xpath('//div[substring-after(text(), "see:")]')
        if not see_divs:
            self.add_warning("cleanup required", "missing see-info")
            return None

        see_highlight = []
        see_found = []  # accumlate see-infos for stacked images
        for node in see_divs:
            see_info = get_see_text(node)
            if not see_info:
                self.add_warning("cleanup required", "highlight on whitespaces in see-info")
                continue
            see_found.append(see_info)
            if not see_info.startswith('+'):
                see_highlight.append(see_info)

        if see_highlight:
            if len(see_highlight) > 1:
                self.add_warning("cleanup required", "more than one highlighted see-info")
                return see_highlight[-1]
            else:
                return see_highlight[0]

        if see_found and see_found[-1] in ('+(not archived)', '+-NA-'):
            logger.debug(f'{self.pos}| found see-info, is {see_found[-1][1:]!r} for {note}')
            return None

        all_sees = "\n   ".join(see_found)
        logger.warning(f'''{self.pos}| missing highlighted see-info in {note}
found see:
   {all_sees}
''')
        self.add_warning("cleanup required", "see-info not highlighted")
        return None

    def _fetch_photonote(self, note: Note2, image_key: str) -> tuple:
        """ fetch photo-note (if one exists), handle updates and moves in EN """
        def log_note(note: Note2):
            updated = datetime.datetime.fromtimestamp(note.date_updated)
            return f"{note} updated={updated}"

        other_note = None

        # lookup photo-note for given image_key
        try:
            photo_note = self.notes_db.flickrimages.lookup_by_key(image_key)
        except PhotoNoteNotFound:
            photo_note = None

        if photo_note is None:
            # not found, new photo-note
            return None, None

        # detect moved and duplicated notes
        if note.en_note.guid != photo_note.guid_note:
            # ensure uniqueness per image, but handle replacement of old note when gone
            try:
                other_note = Note2(lookup_note(self.notes_db.store, photo_note.guid_note))
            except NoteNotFound:
                logger.info(f"detected old note is replaced by new one for image {image_key}")
            else:
                if other_note.en_note.deleted is None:
                    # have existing note
                    logger.error(f"found different note describing same image {image_key}\n"
                                 f"have photo-note:   {log_note(other_note)}\n"
                                 f"new note rejected: {log_note(note)}\n"
                                 )
                    # nsure that no new note is created by caller by returning other_note
                    photo_note = None

                else:
                    logger.info(f"replacing deleted note by {note}\n")
                    other_note = None  # ignore note, is in bin
        elif note.en_note.deleted is not None:
            logger.error(f"cannot update note marked for deletion: {note}")
            raise ValueError("attemt to update deleted note")
        else:
            logger.debug(f"existing note: {note}")

        return photo_note, other_note

    def _handle_image_link(self, note: Note, href: str) -> dict:
        """ have image link (potentially) identifying photo-note; get details on it """
        # 'https://www.flickr.com/photos/27297062@N02/51089206529/in/pool-inexplore/'
        found = {}
        assert href.startswith(FLICKR_PHOTO_URL)
        href_img = href[len(FLICKR_PHOTO_URL):]
        parts = href_img.split('/')
        if len(parts) < 2:
            # e.g. http://www.flickr.com/photos/shannonroseoshea
            logger.debug(f"ignore url to blog page: {href}")
            return None
        found['image_key'] = f"{parts[0]}|{parts[1]}"
        found['blog_id'] = parts[0]
        found['photo_id'] = parts[1]
        if not found['photo_id']:
            # ignore photostream url
            return None

        found_pn = self._fetch_photonote(note, found['image_key'])
        # expect tuple (this photonote, other photonote)
        found['photo_note'], found['other_photonote'] = found_pn

        # lookup blog note for found['blog_id']
        try:
            found['blog_note'] = self.notes_db.flickrblogs.lookup_blog_by_id(found['blog_id'])
        except ValueError:
            found['blog_note'] = None

        if len(parts) == 3:
            if not parts[-1]:
                # ignore trailing slash
                parts = parts[:-1]
            elif parts[-1] == '#':
                parts = parts[:-1]

        if len(parts) > 2:
            if parts[2] == 'in':
                context = parts[3]
                # e.g. (blog_id)/(image_id)/in/pool-(pool_id)/'
                if context.startswith('photolist-'):
                    # can become lengthy, so reduce to prefix
                    context = 'photolist'
                #
                found['context'] = context
            elif parts[2] == 'undefined':
                # happens because WebClipper had a bug (in past)
                logger.debug("ignore undefined in image link")
                context = None
            elif not parts[2]:
                # empty part, caused by trailing slash
                context = None
            else:
                # e.g. '190022557@N04/51159019066/sizes/l/'
                # '190022557@N04/with/51159019066/'
                logger.info(f"failed to detect context for href={href_img}")
                context = None
        else:
            context = None
        return found

    def add_warning(self, category: str, text:str, href: Optional[str] = "") -> None:
        info = self.warnings.get(category, [])
        text_warn = text or "(no text)"
        if len(text_warn) > 42:
            # truncate overlong warning texts
            text_warn = text_warn[:40] + '...'
        if href:
            if not href.startswith('http'):
                logger.warning(f"detected href not starting with http or https: {href}")
        else:
            href = ''
        info.append((href, text_warn))
        self.warnings[category] = info

    def output_warnings(self, note: Note) -> set:
        """ output warning messages to log and return cleanup info for note
        """
        need_cleanup = set()

        # show warnings, e.g. "found secure link"
        for warning in self.warnings:
            infos = list(self.warnings[warning])
            lines = []
            while infos:
                href, text = infos.pop()
                if not href:
                    lines.append(text)
                else:
                    lines.append(f"{href} | {text}")
                if len(lines) >= 3:
                    lines.append(f'... {len(lines) - 3} more ...')
                    break

            lines.append('')  # for better readability
            logger.warning(f'{self.pos}| {warning} in {note}\n  + %s' % "\n  + ".join(lines))

            # signal cleanup required - using set to avoid duplicates
            need_cleanup.add(warning)
        return need_cleanup

    def _analyze_photo_note(self, note: Note2) -> dict:
        """ verify content of photo note """

        result = {'photo_note': None}
        content = get_note_content(note.en_note.content)
        try:
            # extract see:
            xml = etree.fromstring(content)
            result['see'] = self._extract_see(xml, note)
            link_info = None
            image_anchors = []
            links = {}
            for anchor in xml.xpath('//a'):
                href = anchor.attrib.get("href")
                if not href or 'flickr.com' not in href:
                    continue
                if href.startswith('http://www.flickr.com/'):
                    # differentiate if url from photo author (in description) or own
                    media_before = anchor.xpath("preceding::en-media")
                    if not media_before and self.options.warn_href_http:
                        self.add_warning("found non-https link", anchor.text, href)
                    href = 'https://www.flickr.com' + href[21:]
                if href.startswith('https://secure.flickr.com/'):
                    self.add_warning("found secure link", anchor.text, href)
                    href = 'https://www.flickr.com' + href[25:]
                if href.startswith('https://www.flickr.com/photos/tags/'):
                    continue
                if '/sets/' in href:
                    # e.g. 'https://www.flickr.com/photos/(blog_id))/sets/(set_id))'
                    if href.split('/')[5] != 'sets':
                        logger.warning(f"{self.pos}| ignore non-standard album link {href}")
                    continue
                if '/albums/' in href:
                    # e.g. 'https://www.flickr.com/photos/(blog_id)/albums/(album_id)'
                    if href.split('/')[5] != 'albums':
                        logger.warning(f"{self.pos}| ignore non-standard album link {href}")
                    continue
                if '/galleries/' in href:
                    # e.g. 'https://www.flickr.com/photos/(blog_id)/galleries/(gallery_id)/'
                    if href.split('/')[5] != 'galleries':
                        logger.warning(f"{self.pos}| ignore non-standard galleries link {href}")
                    continue
                if href.startswith("https://www.flickr.com/photos/"):
                    # 'href': 'https://www.flickr.com/photos/27297062@N02/51089206529/in/pool-inexplore/',
                    # ..., 'rev': 'en_rl_none', 'target': '_blank'}
                    before_thumbnail = True
                    candidate = self._handle_image_link(note, href)
                    if candidate is None:
                        # ignore - degenerated link, photostream url, ...
                        logger.debug(f"ignore link href={href!r}")
                        continue
                    else:
                        # check if before or after image thumbnail (en-media element)
                        media_before = anchor.xpath("preceding::en-media")
                        before_thumbnail = not media_before
                        image_anchors.append(anchor)

                    link_info = candidate
                    if link_info['image_key'] in links:
                        # same image link again, log only if significantly different
                        link_info2 = links[link_info['image_key']]
                        # different FlickrImage objects => force equal
                        link_info['photo_note'] = link_info2['photo_note']
                        context = link_info.get('context')
                        context2 = link_info2.get('context')
                        if context != context2:
                            if context2 is None:
                                link_info2['context'] = context
                            elif context is None:
                                # update context from latter link
                                link_info['context'] = context2
                            else:
                                # e.g. photolist vs datetaken
                                logger.debug(f"{self.pos}| context differs for {link_info['image_key']}: {context} vs {context2}")
                                link_info['context'] = context2
                        if link_info2 != link_info:
                            logger.warning("{self.pos}| detected difference in link info:\n{link_info2}\n{link_info]")

                    links[link_info['image_key']] = link_info
                    if not before_thumbnail:
                        # first image link after the preview image / photo thumbnail is the link we need
                        # do not handle further links, especially not links from photo description the owner
                        # may have added
                        break

                elif href.startswith('https://www.flickr.com/search/'):
                    # location info, e.g. 'https://www.flickr.com/search/?lat=...'
                    pass

                elif href.startswith('https://flickr.com/groups'):
                    pass

                elif href.startswith('https://www.flickr.com/map/'):
                    # flickr map url, e.g. 'https://www.flickr.com/map/?fLat=...&fLon=...8...'
                    pass

                elif href.startswith('https://www.flickr.com/groups/'):
                    # e.g. 'https://www.flickr.com/groups/(groupid))/'
                    pass

                elif href.startswith('https://www.flickr.com/people/'):
                    # e.g. 'https://www.flickr.com/people/(blogid))/'
                    pass  # TODL extract link to photo blog - but need to check blogid to match note

                elif href.startswith('https://www.flickr.com/explore/'):
                    # e.g. https://www.flickr.com/explore/2022/10/03
                    pass

                elif href.startswith('https://www.flickr.com/redirect?url='):
                    # e.g. 'https://www.flickr.com/redirect?url=https://www.instagram.com/(userid)'
                    pass

                elif href == 'https://www.flickr.com/account/upgrade/pro':
                    pass

                else:
                    # link to be verified
                    # 'https://secure.flickr.com/photos/gerba007/50500915507/in/datetaken/'  # TODO handle
                    # 'http://flickr.com/gp/enlightenedfellow/C8vb16/'
                    # 'https://flickr.com/groups/400faves//'
                    # "https://help.flickr.com/en_us/change-your-photo's-license-in-flickr-B1SxTmjkX"
                    # 'https://www.flickr.com/about'
                    #
                    self.add_warning("ignored href", anchor.text, href)

            # assume last link is the link of the primary image
            result['link'] = link_info

            need_cleanup = self.output_warnings(note)

            result['all'] = links
            see_info = result.get('see')
            if link_info:
                if not see_info:
                    logger.debug(f'missing see-info for photo note {note}')
                elif link_info['photo_id'] not in see_info:
                    logger.warning(f'{self.pos}| see-info not related to photo id {link_info["photo_id"]}: "{see_info}"')
                    # need to check correspondence manually
                    need_cleanup.add("see-info mismatch with image link")

                if link_info.get('other_photonote'):
                    # already have a photo-note, but a different one
                    logger.debug(f"already have photo-note - but different one")  # already logged
                    # avoid that wrong / other note gets updated
                    photo_note = None
                elif not link_info.get('photo_note'):
                    # create photo note from link_info
                    photo_note = self._create_photo_note(link_info, result, note)
                else:
                    # use already existing note
                    photo_note = link_info['photo_note']
                result['photo_note'] = photo_note

                if photo_note is not None:
                    if need_cleanup:
                        # store detailed info (string) on required cleanup
                        photo_note.add_cleanup(need_cleanup)
                    else:
                        photo_note.clear_cleanup()

            else:
                logger.warning(f'no link info found for note {note}')
                result['photo_note'] = None

            return result
        except Exception as err:
            logger.exception('update check failed')
            result['error'] = err
        return result

    def _update_notes(self, notebook, export_enex: bool) -> None:
        parent_dir = [notebook.stack] if notebook.stack else []
        if self.options.skip:
            logger.info(f"updating notebook {notebook.name} (skip {self.options.skip})...")
        else:
            logger.info(f"updating notebook {notebook.name} ...")
        store = self.notes_db.store
        notes_source = store.notes.iter_notes(notebook.guid)

        for note in notes_source:
            assert isinstance(note, Note), "expect note instance"
            self.pos += 1
            note2 = Note2(note)

            if not note.tagNames:
                logger.warning(f'ignore note {self.pos} without tags: {note2}')
                continue  # ignore notes without tags

            if 'inaccessible' in note.tagNames:  ##TODO make configurable
                logger.debug(f'skip inaccessible note: {note2}')
                continue

            if self.options.tag_name and self.options.tag_name not in note.tagNames:
                logger.info(f"skip note {self.pos} not having desired tag name")
                continue

            # classify note depending on tags
            if TAG_NAME_PHOTONOTE in note.tagNames:
                # LOGGER.debug(f'accept note {self.pos} tagged as image: {note2}')  # ATTN bloat - commented out
                handler = self._update_flickr_image
            elif TAG_NAME_BLOGNOTE in note.tagNames:
                logger.debug(f'accept note {self.pos} tagged as blog: {note2}')
                handler = self._update_flickr_blog
            else:
                handler = None

            if handler is not None:
                if self.options.skip > 0:
                    # for testing skip first N notes
                    if not self.options.debug:
                        logger.warning(f"skipping note {self.pos}: {note.title}")
                    self.options.skip -= 1
                    continue

                if note.deleted is not None:
                    logger.debug(f"ignore deleted note {note2}")
                    continue

                # for debugging, it is somethimes useful to be able to pick a photo-note by title
                if self.options.note_title and note.title != self.options.note_title:
                    continue
                handler(note2, export_enex)


        return

    def _update_flickr_blog(self, note: Note, export_enex: bool):
        """ analyze and uodae blog note """
        note_content = get_note_content(note.content)

        # check if note needs update
        if self._need_update_blog(note):
            self.count += 1
            # TODO implement proper throttling, ensuring no more than (.limit) notes per (interval)
            if self.count > self.limit:
                logger.warning(f"reached notes limit")
                return

            if export_enex:
                # export as enex for reimport to Evernote
                # TODO evaluate/decide:
                #    can we update existing note from .enex or should we rather use the Evernote API?
                logger.debug(f"Exporting note {note.title!r} updated={note.updated}")
                _write_export_file(note_path, note)

    def _update_flickr_image(self, note: Note2, export_enex: bool) -> None:
        """ examine and update photo note """
        self.warnings = {}  # drop warnings from previous notes

        photo_info = self._analyze_photo_note(note)
        photo_note = photo_info.get('photo_note')  # info from database

        need_update = True
        if photo_note:
            # already have entry on photo_note in db
            entry_verified = photo_note.date_verified.value
            note_updated = note.date_updated()
            if note.en_note.guid != photo_note.guid_note:
                logger.debug(f'replacing  photo note {photo_note.image_key} by note: {note}')
                # happens if new note is created (for same image),
                # to replace an old note, then deleting the old note (moving to Bin)
                photo_note.guid_note = note.en_note.guid
                need_update = True
            elif not entry_verified or note_updated > entry_verified:
                # note got updated since last verification
                need_update = True
            elif photo_note.entry_updated:
                # photo note entry from db, check when it got last updated (or created)
                age = photo_note.entry_updated.value - datetime.date.today()
                if age < datetime.timedelta(days=NO_UPDATE_AGE):
                    # avoid updating notes that have been updated recently  # TODO verify usecase
                    need_update = False
                else:
                    logger.debug(f'photonote last updated {age} days ago: {note}')
        elif photo_info.get('link'):
            # new photo note, always update
            need_update = True
        elif photo_info.get('see'):
            # missing link to flickr photo
            logger.warning(f'note with see-info but no image link: {note}')
            # photo_info['need_cleanup'] = 'missing image link'
            # need_update = XXX - need photo_note for update, but dont have one
            TODO = 1
        else:
            # no photo note or incomplete; cleanup required
            logger.warning(f'note without link to photo: {note}')
            need_update = False

        if photo_info.get('need_cleanup'):
            need_update = True

        if not need_update:
            return

        if photo_info.get('photo_note') is None:
            logger.warning(f'cannot update, have no photo note for {note}')
            return

        self.count += 1

        # TODO fetch photo info from Flickr and update photo note

        # update note in SQLite db
        self.notes_db.flickrimages.update(photo_info['photo_note'])

        # TODO export enex only if note requires update in Evernote
        # but currently cannot detect / handle / no sync (yet) from Flickr so commented out
        # if export_enex:
        #     # export as enex for reimport to Evernote
        #     # TODO evaluate/decide:
        #     #    can we update existing note from .enex or should we rather use the Evernote API?
        #     logger.debug(f"Exporting note {note} updated={note.date_updated()}")
        #     note_path = None  #T
        #     _write_export_file(note_path, note)

        # TODO change to use ratelimit to avoid excessive use of Flickr API
        # for debugging limit number of updates to a predefined limit
        if self.count > self.limit:
            logger.warning(f"reached notes limit at pos={self.pos}")
            raise RuntimeError("reached notes limit")
        return

    def _create_photo_note(self, link_info: dict, result: dict, note: Note, reference: Optional[dict] = None) -> FlickrPhotoNote:
        """ factory method to create photo note from note info and Flickr image link """
        logger.debug(f'new photo note image key={link_info["image_key"]}: {note}')
        pnote = FlickrPhotoNote(link_info["image_key"], note.guid)
        photo_id = link_info.get('photo_id')
        if photo_id in ('albums', ):
            # happens when a link to an album is embedded in photo description
            logger.error(f'invalid photo_id={photo_id} for note {note}')
            return None


        # extract image specific properties from see-info
        if result.get('see'):
            see = result['see']
            if photo_id not in see:
                logger.warning(f'{self.pos}| missing image id {photo_id} in {see} for {note}')
                # needs manual verification. so set need_cleanup
                pnote.add_cleanup("missing image_id in see-info")

            pnote.see_info = see
            if '|' in see:
                logger.debug(f"{self.pos}| truncate see-info at slash: {see}")
                see = see.split('|')[0].strip()
            see_parts = see.split('.')
            if len(see_parts) > 1:
                if see_parts[-1] == 'crdownload':
                    logger.warning(f"{self.pos}| detected bad see-info: {see}")
                    pnote.add_cleanup("missing image_id in see-info")
                    see_parts = see_parts[:-1]
                see_filetype = see_parts[-1].split(' ')[0].strip()
                if see_filetype in ('png',):
                    logger.warning(f"{self.pos}| detected see-info referencing non JPEG: {see}")
                    # candidate for cleanup, should not use .png
                    pnote.add_cleanup(f"undesired image type {see_filetype}")
                elif see_filetype not in ('jpeg', 'jpg', 'mp4', ):
                    logger.warning(f"unexpected suffix in see-info: {see}")
                    pnote.add_cleanup("{self.pos}| unrecognized filetype suffix in see-info")
                fn_parts = see_parts[-2].split('_')
                while fn_parts and not fn_parts[-1]:
                    # drop trailing underscore, e.g. in 'jeffstamer 52148827555 _Tower of Terror_.jpeg'
                    # or 'petrapetruta 50627873916 About time___.jpeg'
                    fn_parts = fn_parts[:-1]
                if len(fn_parts) >= 3 and is_size_suffix(fn_parts[-1]):
                    # len restriction to avoid false positives, see e.g.
                    # '_ The Vikings _ 137473925@N08 41831720970.jpeg'
                    pnote.secret_id = fn_parts[-2].split(' ')[-1]
                    pnote.size_suffix = fn_parts[-1]
                else:
                    pnote.size_suffix = None

        pnote.reference = reference
        pnote.note_tags = '|%s|' % '|'.join(note.tagNames)
        pnote.blog_id = link_info['blog_id']
        # note: .entry_updated will be set later on by update method - need None to detect that new record
        pnote.entry_updated = FlickrDate(None)
        pnote.date_verified = FlickrDate.today()
        pnote.photo_id = link_info['photo_id']

        #pnote.photo_taken =  FlickrDate(TODO)  # from Flickr
        #pnote.photo_uploaded =  FlickrDate(TODO)  # from Flickr

        return pnote


def is_size_suffix(value):
    if value.endswith('k') and value[:-1].isdigit():
        # 3k, 4k, 6k, ...
        return True
    if value == 'o':
        return True
    if value in ('k', 'h', 'b',):  # large
        return True
    if value in ('?', ):
        return False
    return False

def _write_export_file(
    file_path: Path, note: Note
) -> None:
    with open(file_path, "w", encoding="utf-8") as f:
        logger.debug(f"Writing file {file_path}")

        f.write(ENEX_HEAD)

        updated = note.updated # .utcnow().strftime("%Y%m%dT%H%M%SZ")
        f.write(
            f'<en-export export-date="{updated}"'
            f' application="Evernote" version="10.10.5">'
        )

        ## TODO refactor - usecase?
        assert isinstance(note, Note)
        note_content = NoteFormatter().format_note(note)
        f.write(note_content)

        f.write(ENEX_TAIL)