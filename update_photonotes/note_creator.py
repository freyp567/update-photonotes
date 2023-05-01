"""
Create a photo note for given Flickr image URL
"""

from types import SimpleNamespace
from typing import Optional

import os
import time
import json
import base64
import datetime
import re
import traceback
from pathlib import Path
import hashlib
import csv

from .database import PhotoNotesDB, lookup_note
from .flickr_types import FlickrImage
from .exceptions import FlickrImageNotFound, NoteNotFound
from . import utils
from . import flickr_utils

from evernote.edam.type.ttypes import Note

import flickr_api
from flickr_api.objects import Person, Photo
import requests
import requests_cache  # usefulness for flickr API? looks like Flicker prenvents caching
import fake_useragent


import logging
logger = logging.getLogger('create_note')

# limit number of images that are walked to to avoid exceeding limit of 3600 api calls per hour
MAX_PHOtO_POS = 10000

# number of images per page - 500 is maximum allowed
# use maximum for flickr_api.Photo.search to reduce number of API calls for larger photo streams
IMAGES_PER_PAGE = 500

class NoteCreator:

    def __init__(
            self,
            notes_db: PhotoNotesDB,
            options: SimpleNamespace,
            target_dir: Optional[Path] = None,
            template_name: str = "FlickrImage - Template.enex",
    ):
        self.options = options
        self.params = {}
        self.notes_db = notes_db
        if target_dir is None:
            self.base_path = options.db_path.parent / "update_photonotes"
        else:
            self.base_path = target_dir
        assert self.base_path.is_dir(), "missing directory: {self.base_path"

        template_dir = utils.get_template_dir()
        self.template_file = template_dir / template_name
        assert self.template_file.is_file(), f"missing template {template_name}"

        self.import_path = self.base_path / "import"
        self.import_path.mkdir(exist_ok=True)

        flickr_utils.authenticate(use_auth_session=False)
        if os.environ.get('REQUESTS_CACHE') != '1':
            self.session = requests.session()
        else:
            # cache as much as we can to reduce number of API calls
            # but useful only while debugging and repeatedly call methods for same url
            self.session = requests_cache.CachedSession(
                'note_creator',
                expire_after=datetime.timedelta(days=6)
            )
            requests_cache.install_cache('note_creator')

        self.api_cache = flickr_utils.CountingAPIcallsCache(
                timeout=3600 * 12,  # 12 hours
                max_entries=1000,
        )
        # defaults are: timeout=300, max_entries=200
        # len(self.api_cache) is number of entries in cache
        flickr_api.enable_cache(
            self.api_cache
        )

    def pick_size(self, sizes, candidates):
        all_size_labels = set(sizes.keys())
        for size_label in candidates:
            if size_label in all_size_labels:
                s_item = sizes[size_label]
                img_key = Path(s_item["source"].split('/')[-1])
                return img_key, s_item
        logger.warning(f"missing sizes: {candidates} - have {all_size_labels}")
        return None, {}

    def get_license_info(self, photo: Photo, note_tags: list) -> None:
        self.params['license'] = photo.license
        license_info = flickr_utils.get_license_info(photo)
        if not license_info:
            logger.info(f"unknown license_id={photo.license!r} for {photo.urls}")
            license_info = f'License Type {photo.license}'
        elif photo.license != '0':
            extratags.append("freepic")
            extratags.append("license-%s" % license_info.replace('CC ', 'CC_').replace(' ', ''))
            license_info += f' (License Type {photo.license})'
        self.params['license_info'] = license_info
        if license_info and photo.license != '0':
            self.params['license_text'] = f"License: {license_info}"
        else:
            self.params['license_text'] = ""
        return

    def lookup_photo(self, user, photo_id):
        """ lookup page in stream photo is on using photo url and requests """
        photo_url = f"{user.photosurl}/with/{photo_id}/"
        headers = {'User-Agent': fake_useragent.UserAgent().chrome}
        page_no = 0
        retry = 0
        sleep = 2.0
        while retry < 3:
            response = requests.get(photo_url, headers=headers)
            time.sleep(sleep)  # async?
            if response.status_code != 200:
                logger.error(f"lookup pageno failed for href={photo_url}")
                return None
            html = response.text
            pos = html.find('"is-current"')  # <span class="is-current"
            logger.debug(f"lookup pageno succeeded for href={photo_url}, is_current at pos={pos}")
            if pos > 0:
                pos2 = html.find('<', pos)
                pageval = html[pos + 13:pos2]
                page_no = int(pageval)
                assert page_no > 0, f"expect integer >= 1, failed for {pageval!r} on href={photo_url}"
                break
            else:
                # happens on first access, need to delay and repeat request
                retry += 1
                time.sleep(sleep)
                sleep = sleep *2
        if page_no == 0:
            logger.error(f"lookup pageno unable to extract for href={photo_url}")
            # dump flickr page for examination
            (self.import_path / 'flickr_findpage_failed.html').write_text(html, encoding='utf-8')
            page_no = 1  # guess
        return page_no

    def get_location_info(self, photo) -> None:
        """ determine location info and update params """

        class PhotoLocation:

            def __init__(self, photo):
                self.location = photo.location

            def get_text(self, prop_name: str) -> Optional[str]:
                prop_val = self.location.get(prop_name)
                if isinstance(prop_val, dict):
                    return prop_val.get('text')
                return prop_val

        try:
            location = photo.getLocation()
            # latitude=-41.032843, longitude=173.021184, accuracy=15
        except Exception as err:
            # flickr_api.flickrerrors.FlickrAPIError: 2 : Photo has no location information.
            logger.debug(f"image {photo.id} getLocation failed - {err}")
            location_info = "(no location info)"
            self.params["location_info"] = ""
            self.params["location_text"] = f'''<span>{location_info}</span>'''
        else:
            # photo.location:
            # {'accuracy': '15', 'context': '0', 'country': 'New Zealand', 'latitude': '-41.032843',
            #  'locality': 'Kaiteriteri', 'longitude': '173.021184', 'neighbourhood': '', 'region': 'Nelson'}
            location = PhotoLocation(photo)
            location_info = [
                location.get_text('neighbourhood'),
                location.get_text('locality'),
                location.get_text('region'),
                location.get_text('country'),
            ]
            location_info = [info for info in location_info if info]
            location_info = ", ".join(location_info)
            self.params["location_info"] = location_info
            location_lat = photo.location.get('latitude')
            location_lon = photo.location.get('longitude')
            location_url = "https://www.flickr.com/map/?" \
                                     f"fLat={location.get_text('latitude')}&amp;" \
                                     f"fLon={location.get_text('longitude')}&amp;" \
                                     f"zl={location.get_text('accuracy') or 13}&amp;" \
                                     f"photo={photo.id}"
            # omitted: "everyone_nearby=1&amp;"
            self.params["location_text"] = f'''<span style="color:rgb(0, 0, 0);">{location_info}</span> |
            <a href="{location_url}"
                rev="en_rl_none">
                <span style="color:rgb(0, 0, 0);">map/?fLat={location_lat}&amp;fLon={location_lon}</span>
            </a>
            '''
        return

    def update_context(self, photo):
        """ provide groups and albums info for given photo """
        groups = []
        photosets = []
        for context in photo.getAllContexts():
            for item in context:
                if isinstance(item, flickr_api.objects.Photoset):
                    photosets.append({
                        'id': item.id,
                        'album_title': item.title,
                        'href': f"{item.owner.photosurl}albums/{item.id}",
                        'count': item.count_photos
                    })
                elif isinstance(item, flickr_api.objects.Group):
                    # .name
                    groups.append({
                        'id': item.id,
                        'group_title': item.title,
                        'href': item.url,
                        'count': int(item.pool_count)
                    })
                else:
                    # what else?
                    logger.debug(f"ignored")

        self.params['albums_count'] = len(photosets)
        if photosets:
            albums_info = [ '<ul>', ]
            for item in photosets:
                albums_info.append('<li><div>')
                item_title = utils.quote_xml(item['album_title'])
                album_title = f"""<span style="color:rgb(0, 0, 0);">{item_title}</span>"""
                count_photos = f"{item['count']:,}".replace(',', '.')
                albums_info.append(
                    f"""<a href="{item['href']}" rev="en_rl_none">{album_title}</a> (#={count_photos})"""
                )
                albums_info.append('</div></li>')
            albums_info.append('</ul>')
            self.params['albums_info'] = '\n'.join(albums_info)
        else:
            self.params['albums_info'] = "no albums"

        self.params['groups_count'] = len(groups)
        if groups:
            groups.sort(key=lambda value: value['count'])
            groups_info = ['<ul>', ]
            for item in groups:
                groups_info.append('<li><div>')
                item_title = utils.quote_xml(item['group_title'])
                group_title = f"""<span style="color:rgb(0, 0, 0);">{item_title}</span>"""
                count_photos = f"{item['count']:,}".replace(',', '.')
                groups_info.append(
                    f"""<a href="{item['href']}" rev="en_rl_none">{group_title}</a> (#={count_photos})"""
                )
                groups_info.append('</div></li>')
            groups_info.append('</ul>')
            groups_info.append('<br/>')
            self.params['groups_info'] = '\n'.join(groups_info)
        else:
            self.params['groups_info'] = 'no groups'
        return

    def lookup_photo_by_id(self, user: Person, photo_id: str, pageno: Optional[int] = None) -> Optional[Photo]:
        """ lookup photo by id """
        # not always working but slowing down creation, so commented out:
        # # due to missing (or unknown API) guess from photostreak lookup of image what page it is on
        # if pageno is None:
        #     pageno = self.lookup_photo_page(user, photo_id)
        #     if pageno is not None:
        #         LOGGER.info(f"located image {photo_id} on page {pageno}")

        pos = 0
        if pageno is not None:
            # note that using pageno is not symmetrical to use of Walker in respect to params passed
            # check if we can harmonize that, or else check usecase for lookup starting at page (pageno)
            for photo in user.getPhotos(page=pageno):
                pos += 1
                if photo.id == photo_id:
                    logger.debug(f"found image at pos={pos} on page={pageno}")
                    return photo

            logger.error(f"image not found for {photo_id} pos={pos} page={pageno}")
            return None

        logger.warning(f"lookup image {photo_id} in photostream")
        image_list = []
        # walk through all images of user to locate it
        search_params = {
            "user_id": user.id,
            "privacy_filter": 1,  # public photos
            "safe_search!": 3,
            # "content_types": 0,  # photos only? mostly photos, so unimportant to restrict
            "per_page": IMAGES_PER_PAGE,
            "extras": "description,license,date_upload,date_taken,owner_name,last_update",
        }
        for photo in flickr_api.Walker(
                flickr_api.Photo.search,
                **search_params,
        ):
            # unfortunately cannot pass photo_id, ignored
            pos += 1
            if photo.id == photo_id:
                logger.info(f"image found for {photo_id} at pos={pos}")
                return photo
            photo_title = photo.title
            logger.debug(f"{pos} | {photo.id} - {photo_title!r}")

            image_list.append({
                'pos': pos,
                'photo_id': photo.id,
                'photo_title': photo_title,
                # additional properties may cost as causing additional api calls (e.g. .license), so omit
                # 'photo_taken': flickr_utils.get_taken(photo),
                # 'photo_uploaded': flickr_utils.get_uploaded(photo),
                # 'license': photo.license,  # expensive, costs an API call
                # 'lastupdate': flickr_utils.get_lastupdate(photo),
            })

            if pos > self.options.max_pos:
                # limit to avoid excessive api calls
                logger.warning(f"failed to find image before pos={pos}, stop")
                break

        logger.error(f"image not found for {photo_id} pos={pos}")

        # dump image_list for manual inspection
        csv_path = self.import_path / f"{user.id} photos.csv"
        with csv_path.open(encoding='utf-8-sig', mode='w') as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=image_list[0].keys())
            writer.writerows(image_list)
        return None

    def create_content(self,
                       user: Person,
                       photo: Photo,
                       enex_path: Path,
                       photo_note: Optional[FlickrImage],
                       ):
        """ generate content for photo found """

        note_tags = set()
        note_tags.add('flickr-photonote')
        note_tags.add('flickr-image')
        note_tags.add('image')
        note_tags.add('image-update')
        note_tags.add(datetime.date.today().strftime("%Y"))  # year note created/updated

        if photo_note is not None:
            # have photo-note in notes db, so preset tags from existing note
            note_tags.update(photo_note.note_tags.split('|'))

            en_note = self.lookup_en_note(photo_note)

            # make note title visually different as it is a update for an already existing note
            if en_note:
                # sometimes note title and flickr title differ (as intellectually updated)
                # prefer / keep evernote note title
                note_title = f"[new] {en_note.title}"
            else:
                note_title = f"[new] {photo.title}"

        else:
            en_note = None
            note_title = photo.title

        self.params['flickr_title'] = photo.title
        self.params['note_title'] = note_title

        blog_id = user.path_alias or user.id
        img_path = self.base_path / "blogs" / blog_id / "images"
        img_path.mkdir(parents=True, exist_ok=True)
        img_key = f"{blog_id} {photo.id}.json"
        img_file = img_path / f"{blog_id} {photo.id}.json"
        if img_file.is_file():
            # keep only initial and current version of photo info
            img_file = img_file.with_suffix('.current.json')
        # dump json data for examination / reference
        img_file.write_text(json.dumps(photo.__dict__, indent=4, default=str))
        logger.debug(f"output photo info for {img_key} to {img_file}")

        self.get_license_info(photo, note_tags)

        uploaded = datetime.datetime.fromtimestamp(int(photo.dateuploaded))
        photo_taken = photo.taken
        if photo_taken and len(photo_taken) > 16:
            photo_taken = photo_taken[:16]  # reduce precision
        if photo.takengranularity != 0:
            photo_taken = photo_taken
        if photo.takenunknown == '0':
            photo_taken = photo_taken
        elif photo.takenunknown == '1':
            photo_taken += ' (unknown)'
        else:
            photo_taken += f' (unknown-{photo.takenunknown})'
        lastupdate = datetime.datetime.fromtimestamp(photo.lastupdate)
        # .posted ?
        description = flickr_utils.cleanup_description(photo.description)

        self.params.update({
            'photo_url': photo.getPageUrl(),
            'description': description,
            'image_id': photo.id,
            'photo_taken': photo_taken,
            'photo_uploaded': uploaded.strftime("%Y-%m-%d"),
            'lastupdate': lastupdate,
        })

        self.get_location_info(photo)
        if self.params.get("location_info"):
            # append location to image title
            location_parts = self.params.get("location_info").split(',')

            if not photo_note:
                self.params['note_title'] += " | "
                self.params['note_title'] += ",".join(location_parts)

        sizes = photo.getSizes()
        for s_key in ('Medium', 'Medium 500', 'Small'):
            s_item = sizes.get(s_key)
            if s_item:
                break
            s_item = None

        # generate preview for photo note
        img_data = None
        if s_item:
            size_key = s_item['url'].split('/')[-2]
            source_name = Path(s_item["source"].split('/')[-1])
            img_key = f"{source_name.stem}_{size_key}{source_name.suffix}"
            logger.debug(f"picked size {s_item['label']} for preview: {img_key}")
            self.params['preview_width'] = s_item['width']
            self.params['preview_height'] = s_item['height']

            img_file = img_path / img_key
            # response = self.session.get(url=s_item["source"])  # unreliable
            if not img_file.is_file():
                img_file_s = photo.save(str(img_file), s_key)  # save preview
            else:
                # use cached image
                img_file_s = str(img_file)

            if img_file_s:
                self.params['preview_fn'] = img_key
                img_data_raw = img_file.read_bytes()
                img_data = base64.b64encode(img_data_raw).decode()
                self.params['filehash'] = hashlib.md5(img_data_raw).hexdigest()
                self.params['preview_width'] = s_item['width']
                self.params['preview_height'] = s_item['height']
                img_suffix = Path(img_key).suffix
                if img_suffix in ('.jpg', '.jpeg',):
                    self.params['mimetype'] = "image/jpeg"
                elif img_suffix in ('.png',):
                    self.params['mimetype'] = "image/png"
                else:
                    # what else?
                    logger.warning(f"detected unknown image suffix for {img_key}: {img_suffix}")
                    self.params['mimetype'] = f"image/{img_suffix}"

        if not img_data:
            logger.warning("missing image for preview")
            missing_image = self.template_file.parent / "missing_image.png"
            img_data_raw = missing_image.read_bytes()
            self.params['filehash'] = hashlib.md5(img_data_raw).hexdigest()
            img_data = base64.b64encode(img_data_raw).decode()
            self.params['preview_fn'] = '-NA-'
            self.params['preview_width'] = 142
            self.params['preview_height'] = 142
            self.params['mimetype'] = "image/png"

        # ensure padding
        while len(img_data) % 4 != 0:
            img_data += '='
        self.params['resource_data'] = img_data

        # extract tags
        tag_items = []
        for tag_item in photo.tags:
            tag_info = f"""<span style="color:rgb(0, 0, 0);">{tag_item.text}</span>"""
            tag_items.append(tag_info)
        if tag_items:
            tags_info = "</div></li>\n<li><div>".join(tag_items)
            self.params['tags_info'] = f"<ul>\n<li><div>{tags_info}\n</div></li>\n</ul>"
        else:
            self.params['tags_info'] = f"<div>(no tags)</div>"

        self.update_context(photo)

        # archive image (size Large or Medium)
        archive_name = "(not archived)"
        archive_path = Path(os.environ.get("PHOTO_ARCHIVE", self.base_path))
        img_key_item, s_size = self.pick_size(sizes, ("Large", "Medium"))
        if s_size:
            archive_path = Path(os.environ.get("PHOTO_ARCHIVE", self.base_path))
            if archive_path.is_dir():
                archive_path = archive_path / datetime.datetime.now().strftime("%Y-%m")
                archive_path.mkdir(exist_ok=True)
                key_parts = str(img_key_item).split('_')
                archive_name = f"{user.id} {photo.id} {'_'.join(key_parts[1:])}"
                if blog_id != user.id:
                    archive_name = f"{blog_id} {archive_name}"
                img_file_a = archive_path / archive_name
                if not img_file_a.is_file():
                    # archive image
                    logger.info(f"archiving {img_key_item} size={s_size['label']} ...")
                    photo.save(str(img_file_a), s_size['label'])
            else:
                archive_path = None

        self.params['archive_name'] = archive_name
        if not archive_path:
            logger.info(f"not archive: {img_key_item}")
            self.params['archive_info'] = ""
        else:
            # indicate month
            self.params['archive_info'] = " | " + datetime.datetime.now().strftime('%Y-%m')

        if s_size:
            self.params['filename'] = str(img_key_item)
        else:
            self.params['filename'] = '-NA-'

        # for en-media item, --en-naturalWidth ...
        self.params['media_width'] = self.params['preview_width']
        self.params['media_height'] = self.params['preview_height']

        note_tags_xml = [f"<tag>{tag_name}</tag>" for tag_name in note_tags if tag_name]
        self.params['note_tags'] = "\n".join(note_tags_xml)

        content = utils.from_template(self.template_file.with_suffix(".xml"), self.params)
        content, has_error = utils.validate_content(content)

        if has_error:
            # output XML content for examination in case of errors - for troubleshooting only
            enex_path.with_suffix('.xml').write_text(f'<!-- {has_error} -->\n' + content, encoding='utf-8')
        elif self.options.xml:
            enex_path.with_suffix('.xml').write_text(f'<!-- OK -->\n' + content, encoding='utf-8')
        self.params['content'] = content

        if not has_error:
            # save generated enex file
            enex = utils.from_template(self.template_file, self.params)
            enex2, has_error = utils.validate_content(enex.encode('utf-8'))
            if has_error:
                enex = f"<!-- {has_error} -->\n" + enex2.decode('utf-8')
            enex_path.write_text(enex, encoding='utf-8')

        logger.info(f"api cache stats:\n{self.api_cache}")
        logger.info(f"created note in {enex_path}")
        return not has_error

    def lookup_photonote(self, blog_id: str, photo_id: str) -> Optional[FlickrImage]:
        image_key = f"{blog_id}|{photo_id}"
        try:
            found = self.notes_db.flickrimages.lookup_image_by_key(image_key)
        except FlickrImageNotFound:
            logger.debug(f"no photo-note / image found for {image_key}")
            return None
        if found:
            logger.info(f"found photo-note / image for {image_key}")
            return found
        else:
            return None

    def lookup_en_note(self, photo_note: FlickrImage) -> Optional[Note]:
        """ lookup Evernote note in evernote-backup db """
        try:
            note = lookup_note(self.notes_db.store, photo_note.guid_note)
        except NoteNotFound:
            return None
        return note

    def create_note(self, flickr_url: str) -> bool:
        assert flickr_url.startswith('https://www.flickr.com/photos/'), "must have a Flickr URL"
        if re.search(r':\d+$', flickr_url):
            parts = flickr_url.split(':')
            pageno = int(parts[-1])
            flickr_url = ':'.join(parts[:-1])
            logger.info(f"create photo-note from {flickr_url} page={pageno}")
        else:
            pageno = None
            logger.info(f"create photo-note from {flickr_url}")

        steps = flickr_url.split('/')
        blog_id = steps[4]
        photo_id = (len(steps) >=6) and steps[5].strip()
        if not photo_id:
            logger.error(f"missing required photo id in URL")
            raise ValueError("unsupported url {flickr_url!r}")

        enex_path = self.import_path / f"{blog_id} {photo_id} .enex"

        # output .txt file to indicate that note creation has been started - and indicate what url
        info_path = enex_path.with_suffix('.txt')
        info_path.write_text(flickr_url)

        # initialize parameter for .enex and .xml templates
        self.params = {
            'flickr_url': flickr_url,
        }

        ok = False
        try:
            ok = self.create_note_for_photo(
                flickr_url, blog_id, photo_id, enex_path, pageno
            )
        except Exception as err:
            error_info = f"""ERROR create-note failed
            
url: {flickr_url}
error: {err!r}

error details:
"""
            error_info += "\n".join(traceback.format_exception(err))
            info_path.write_text(error_info, encoding="utf-8")
            raise err

        if ok:
            info_path.unlink(missing_ok=True)
        return ok

    def create_note_for_photo(
            self,
            flickr_url: str,
            blog_id: str,
            photo_id: str,
            enex_path: Path,
            pageno: Optional[int] = None,
    ) -> bool:
        """ create photo-note from given url """

        if not photo_id.isdigit():
            logger.error(f"not a valid flickr photo id: {photo_id!r}")
            raise ValueError("invalid url")

        now_date = datetime.datetime.now().strftime('%Y-%m-%d')
        data_path = self.base_path / "person" / blog_id
        data_path.mkdir(parents=True, exist_ok=True)
        user_data = data_path / f"user_{blog_id}.{now_date}.json"

        # if user_data.is_file():
        #     # avoid lookup by using cached info
        #     LOGGER.debug(f"loading user info from cache file {user_data}")
        #     user_data_c = SimpleNamespace(**json.loads(user_data.read_text()))
        #     LOGGER.info(f" user info from cache: {blog_id} is {user.id} / {user.username}")
        # else:
        # have too little advantage in caching user data to be worth the hazzle, so commented out

        user = flickr_api.Person.findByUrl(flickr_url)
        if not user:
            raise ValueError(f"user not found by url={flickr_url}")

        user_data.write_text(json.dumps(user.__dict__, indent=4, default=str), encoding='utf-8')
        # user_data_c = SimpleNamespace(**json.loads(user_data.read_text()))
        photos_count = user.photos_info.get('count') or 'NA'
        logger.info(f"user for {blog_id} is {user.id} / {user.username!r} - #={photos_count}")

        # summary for user / blog
        now = datetime.date.today().isoformat()
        photos = user.getPhotos(page=1)
        if photos:
            photo = photos[0]
            last_taken = photo.taken
            if last_taken:
                last_taken = str(last_taken)[:10]  # date only
                if photo.takenunknown == '1':
                    last_taken = "?" + last_taken
            else:
                last_taken = "---"
            last_upload = datetime.datetime.fromtimestamp(int(photo.dateuploaded)).isoformat()[:10]
        else:
            last_taken = '---'
            last_upload = '---'

        count_photos = f"{user.photos_info.get('count'):,}".replace(',', '.')
        blog_info = f"{now}: #={count_photos},  t={last_taken},  u={last_upload}"
        date_created = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        user_location = utils.get_safe_property(user, 'location', "")
        user_realname = utils.get_safe_property(user, 'realname', "")

        self.params.update({
            'blog_id': blog_id,
            'user_name': user.username,
            'user_location': utils.quote_xml(user_location) or "(no location)",
            'real_name': user_realname,
            'profile_url': user.profileurl,
            'blog_info': blog_info,
            'note_created': date_created,
            'note_updated': date_created,
            'today': datetime.date.today().isoformat(),
            'timestamp': datetime.datetime.now().isoformat()[:16]
        })

        user_info = ""
        if user_realname and user_realname != user.username:
            user_realnamex = utils.quote_xml(user_realname)
            user_info = f"{user_realnamex} | "
        user_info += f"{user.username} | {blog_id}"
        if user_location:
            user_info += f" || {user_location}"
        self.params['user_info'] = user_info

        # lookup photo by id
        photo = self.lookup_photo_by_id(user, photo_id, pageno)

        if photo is None or photo.id != photo_id:
            logger.error(f"image not found: {blog_id}/{photo_id}")
            logger.info(f"api cache stats:\n{self.api_cache}")
            return False

        photo_note = self.lookup_photonote(blog_id, photo_id)
        return self.create_content(user, photo, enex_path, photo_note)
