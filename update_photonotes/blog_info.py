"""
encapsulatees information of a photo blog npte

a blog note is expected to have a structure as follows:

    (date last updated)

    images:
    * internal image link
    ...

    more images:
    see:  image info | link to flickr image
    ...

    update info, e.g.
    2023-09-12: #=334,  t=2023-04-08,  u=2023-09-10
    ...
    ---
    Clip-Quelle: (flickr image blog URL)

    (date of update/renewal)
    (date first seen)
    ---
    original blog title
    thunbnail image
    link to blog (should match image blog URL)
    ---
    blog info
    ---
    blog properties (dotted list)
    ---
    Albums:
    * Caminos y huellas | #=120 u=2023-08-26
    ...
    ---
    Galleries:
    (optional list of galleries)

    (date note last updated / renewed)


note that this is the new style format, and that there are variations of this format
currently in use that may or may not be supported

"""

from datetime import datetime, date
from lxml import etree

from .note_utils import Note2
from .conversion import get_note_content

import logging

logger = logging.getLogger('app.blog_info')


class BlogInfo:

    def __init__(self):
        self.note_title = None
        self.guid_note = None
        self.note_updated = None
        self.blog_id = None
        self.user_id = None
        self.date_verified = None  # note: set from database / flickrblog entity, but kept as marker
        self.blog_latest_update = None
        self.images = []
        self.more_images = []
        self.before_images = []
        self.after_images = []
        self.text_at_start = []
        self.text_after_images = []
        self.blog_updates = []
        self.source_url = None
        self.status_xml = []
        self.bloginfo_xml = []
        self.blogdesc_xml = []
        self.properties = []
        self.albums = []  # flickr photosets
        self.galleries = []
        self.timestamp = None

    def extract(self, note: Note2) -> bool:
        self.note_title = note.title
        title2 = note.title.split('|', 1)[1]
        # avoid troubles with exotic user names, e.g. 'P@tH Im@ges | 137473925@N08 | Flickr blog'
        user_id = [info for info in title2.split('|') if '@' in info]
        if len(user_id) == 0:
            self.user_id = None
        elif len(user_id) == 1:
            self.user_id = user_id[0]
        else:
            logger.error(f"unable to determine userid from title {note.title}")
            raise ValueError("failed to determine user id from note title")
        self.guid_note = note.en_note.guid
        self.note_tags = note.en_note.tagNames
        logger.debug(f"updating blog note {self.note_title!r} ...")
        content = get_note_content(note.en_note.content)
        root = etree.fromstring(content)
        try:
            return self._extract_blog_info(root)
        except ValueError as exc:
            logger.error(f"failed to extract blog info from {note.title!r}:\n  {exc}")
            return False
        except Exception as exc:
            logger.exception(f"failed to extract blog info from {note.title!r} - {exc}")
            return False

    def _extract_isodate(self, node: etree.Element) -> datetime:
        value = node.text.strip()
        return self._extract_isodate_text(value)

    def _extract_timestamp(self, value: str) -> datetime:
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M")
        except ValueError:
            return None

    def _extract_isodate_text(self, value: str) -> datetime:
        return datetime.strptime(value, "%Y-%m-%d")

    def _extract_isodate_text_cond(self, value: str) -> datetime | None:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None

    def _is_empty(self, node: etree.Element) -> bool:
        subitems = [n for n in node.getchildren() if n.tag not in ('br',)]
        if subitems:
            # there are child elements, so not empty
            return False

        # test text content of node
        text = " ".join(etree.XPath(".//text()")(node))
        text = text.strip()
        return not text

    def _is_marker(self, node: etree.Element, info: str) -> bool:
        subitems = [n for n in node.getchildren() if n.tag not in ('br',)]
        if subitems:
            return False
        text = " ".join(etree.XPath("./text()")(node))
        text = text.strip()
        return text == info

    def _extract_images(self, node: etree.Element) -> None:
        if node.tag != 'ul':
            # old style image list (using sequence of divs => manual fixup
            raise ValueError(f"expect list of images, got {node.tag}")
        for item in node.getchildren():
            assert item.tag == 'li'
            info = item.getchildren()
            assert len(info) == 1, "expect single div for image list item"
            img_info = self._extract_image_info(info[0])
            self.images.append(img_info)
        return

    def _extract_moreimage(self, node: etree.Element) -> dict:
        image_info = {
            'before': [],
            'after': []
        }
        assert node.tag == 'div'
        pos = 'before'
        prefix = (node.text or '').strip()
        if prefix.startswith('see:'):
            prefix = prefix[5:].strip()
        elif prefix.startswith('see.'):
            # typing dot instead of colon is common mistake, accept it
            prefix = prefix[5:].strip()
        elif prefix.startswith('see\xa0'):
            # dito cases without colon and dot
            prefix = prefix[5:].strip()
        elif prefix:
            # old style blog notes may come without see: prefix
            # detect some typical typing mistakes - to be corrected manually
            context_text = self._extract_node_text(node)
            if prefix.startswith('see.'):
                raise ValueError(f"expect prefix see:, got {context_text!r}")
            if prefix == '...':
                # dummy from generated blog note - indicates end of section
                return None
            if prefix.startswith('scan '):
                return None
            if prefix.startswith('album '):
                return None
            if prefix.startswith('https://'):
                return None
            if self._extract_isodate_text_cond(prefix[:10]):
                # at start of section with blog updates, no section 'more images'
                return None

            # everything else to finish the more images section
            logger.debug(f"detected non-std prefix in more images section: {prefix!r}")
            return None
        if prefix:
            image_info['before'].append(prefix)

        for subnode in node.getchildren():
            if subnode.tag == 'a':
                image_info.update(self._extract_image_link(subnode))
                pos = 'after'
            elif subnode.tag == 'span':
                # e.g. <span style="color:rgb(0, 0, 0);">see:  sacho2000 189108616@N08 52683468083 .. </span>
                # so strip span
                text = self._extract_node_text(subnode)
                if pos == 'before' and text.startswith('see:'):
                    text = text[5:].strip()
                else:
                    # old style, missing see: prefix
                    text = text.strip()
                image_info[pos].append(text)
            elif subnode.tag == 'b':
                image_info[pos].append(self._extract_xml(subnode))
            else:
                raise ValueError(f'troubles with moreimages handling, element {subnode.tag}')

        if 'href' not in image_info:
            if 'before' in image_info:
                # image info without link
                logger.warning(f"missing link for image {image_info['before']}")
                image_info['href'] = None
            else:
                # not an image item
                return None
        return image_info

    def _extract_node_text(self, node: etree.Element):
        text = " ".join(etree.XPath(".//text()")(node))
        return text.strip()

    def _extract_image_link(self, node: etree.Element) -> dict:
        image_info = {}
        assert node.tag == 'a'
        keys = set(node.attrib.keys())
        image_info['href'] = node.attrib['href']
        # anchor text may bewrapped into a <span> element, extract
        image_info['title'] = self._extract_node_text(node)
        keys.discard('href')
        if 'rel' in keys:
            assert node.attrib['rel'] == 'noopener noreferrer'
            keys.discard('rel')
        if 'rev' in keys:
            assert node.attrib['rev'] == 'en_rl_none'
            keys.discard('rev')
        if 'shape' in keys:
            assert node.attrib['shape'] == 'rect'
            keys.discard('shape')
        # all consumed?
        assert not keys, f"unhandled image anchor attrib: {keys}"
        return image_info

    def _extract_image_info(self, node: etree.Element) -> dict:
        image_info = {
            'before': [],
            'after': []
        }
        assert node.tag == 'div'
        pos = 'before'
        for subnode in node.getchildren():
            if subnode.tag == 'a':
                assert pos == 'before', "expect single link per image"
                image_info.update(self._extract_image_link(subnode))
                pos = 'after'
            elif subnode.tag == 'span':
                style = subnode.attrib.get('style') or ''
                if pos == 'after' and style.startswith('--en-highlight:yellow'):
                    # expect image id after link
                    assert len(subnode.getchildren()) == 0
                    image_id = subnode.text.strip()
                    if not image_id.isdigit():
                        logger.error(f"invalid image_id: {image_id!r}")
                    assert 'image_id' not in image_info, "single image_id only"
                    image_info['image_id'] = image_id
                    continue

                # text = " ".join(etree.XPath("./text()")(subnode))
                # passthrough text before / after link
                image_info[pos].append(etree.tostring(subnode))
            elif subnode.tag == 'b':
                image_info[pos].append(etree.tostring(subnode))
            elif subnode.tag == 'br':
                # empty list item (does happen)
                continue
            else:
                raise ValueError(f"unhandled element {subnode.tag}")
        return image_info

    def _extract_blog_updates(self, node: etree.Element) -> bool:
        """ extract blog update innfos - and all text between more images """
        assert node.tag == 'div'
        div_text = self._extract_node_text(node)
        try:
            blog_update = self._extract_isodate_text(div_text[:10])
            self.blog_updates.append(div_text)
            return blog_update
        except ValueError:
            logger.debug(f"not a valid isodate: {div_text}")
            return None

    def _extract_xml(self, node: etree.Element) -> str:
        text = etree.tostring(node, encoding='utf-8').decode('utf-8')
        return text

    def _extract_blogprops(self, node: etree.Element) -> None:
        assert node.tag == 'ul'
        for subnode in node.getchildren():
            assert subnode.tag == 'li'
            prop_text = self._extract_node_text(subnode)
            # FUTURE split into key: value
            self.properties.append(prop_text)
        return

    def _extract_albums(self, node: etree.Element) -> None:
        assert node.tag == 'ul'
        for subnode in node.getchildren():
            assert subnode.tag == 'li'
            info = self._extract_node_text(subnode)
            # split into parts
            # e.g. 'Blumen Flower | #=379 u=2023-04-22'
            props = info.split('|')
            if len(props) < 2:
                raise ValueError(f"cannot interpret album info: {info!r}")
            elif len(props) > 2:
                album_title = '|'.join(props[:-1])
                extras = '|'.join(props[2:])
                props = props[1].strip()
            else:
                album_title = props[0]
                props = props[1].strip()
                extras = ''

            album_info = self._extract_album_item_info(props)
            album_info['title'] = album_title
            if extras:
                album_info['extras'] = extras
            self.albums.append(album_info)

        return

    def _extract_galleries(self, node: etree.Element) -> None:
        assert node.tag == 'ul'
        for subnode in node.getchildren():
            assert subnode.tag == 'li'
            info = self._extract_node_text(subnode)
            # FUTURE split into parts
            self.galleries.append(info)
        return

    def _extract_album_item_info(self, value: str) -> dict:
        info = {}
        if not value.startswith('#'):
            raise ValueError(f"format error in album info: {info!r}")

        for prop_item in value.strip().split(' '):
            key, value = prop_item.split('=')
            if key in ('u',):
                value = self._extract_isodate_text(value)
                value = value.date()
            elif key == '#':
                value = int(value)
            else:
                value = value
            info[key] = value

        return info

    def _extract_albumold_item_info(self, value: str) -> dict:
        info = {}
        keywords = [
            ('photos', '#'),
            ('photo', '#'),
            ('videos', 'm'),
            ('video', 'm'),
            ('views', 'v'),
            ('view', 'v'),
        ]
        value = value.replace('\xb7', ' ')
        for keyword, key in keywords:
            if keyword in value:
                parts = value.split(keyword)
                assert len(parts) == 2
                part0 = parts[0].strip()
                pos = len(part0)
                while pos > 0 and part0[pos-1:].isdigit():
                    pos -= 1
                info[key] = int(part0[pos:])
                part0 = part0[:pos]
                value = f"{part0} {parts[1]}".strip()
                if not value:
                    break
                value = value
        if value:
            logger.warning(f"unrecognized item in albums info: {value}")
        return info

    def _extract_blog_info(self, root: etree.Element) -> bool:
        """ extract information from content of a blog note """
        section = 'start'
        albumold_title = None
        for node in root.getchildren():

            if node.tag == 'div' and self._is_empty(node):
                # ignore empty divs, they are for readability only
                continue

            # first item we expect is the date of last update
            if self.note_updated is None:
                assert node.tag == "div", "expect first div to hold date of last update"
                self.note_updated = self._extract_isodate(node)
                continue

            if self._is_marker(node, 'images:'):
                assert section == 'start', f"images in mode {section}"
                section = 'images'
                continue

            if self._is_marker(node, 'more images:'):
                # ignore prefix of section with additional images
                if section == 'start':
                    logger.warning(f"no images in blog note {self.note_title!r}")
                    # happens, sometimes
                elif section != 'moreimages':
                    raise ValueError(f"more images in mode {section}")
                section = 'moreimages'
                continue

            if section == 'start':
                # text before images section
                xml = self._extract_xml(node)
                if node.tag == 'div':
                    self.text_at_start.append(xml)
                    continue
                else:  # e.g. ul,
                    raise ValueError("unexpected text in start section")

            if section == 'images':
                self._extract_images(node)
                logger.info(f"{len(self.images)} images in {self.note_title}")
                section = 'moreimages'
                continue

            if section == 'moreimages':
                # section is optional, may be skipped
                image_info = self._extract_moreimage(node)
                if image_info is None:
                    section = 'afterimages'
                    # fall through to next section, no continue here
                else:
                    self.more_images.append(image_info)
                    continue

            if section == 'afterimages':
                if node.tag == 'div':
                    updated = self._extract_blog_updates(node)
                    if updated is not None:
                        if not self.blog_latest_update:
                            self.blog_latest_update = updated
                        continue
                    else:
                        # text after image / more image section
                        text_after = self._extract_xml(node)
                        if text_after == '<div>...</div>':
                            pass
                        else:
                            self.text_after_images.append(text_after)
                        continue
                # elif node.tag == 'ul':
                #    self.text_after_images.append(self._extract_xml(node))
                elif node.tag == 'hr':
                    section = 'status'
                    continue

            if section == 'status':
                if node.tag == 'div':
                    div_text = self._extract_node_text(node)
                    src_link = [el for el in node.getchildren() if el.tag == 'a']
                    if src_link:
                        # Clip-Quelle for old style note, ...
                        src_link = src_link[0]
                        self.source_url = src_link.attrib['href']
                    self.status_xml.append(self._extract_xml(node))
                    continue
                elif node.tag == 'hr':
                    section = 'bloginfo'
                    continue

            if section == 'bloginfo':
                if node.tag == 'div':
                    blog_link = [el for el in node.getchildren() if el.tag == 'a']
                    if blog_link:
                        blog_link = blog_link[0]
                        blog_url = blog_link.attrib['href']
                        logger.debug(f"blog url is {blog_url}")
                        if not blog_url.startswith('https://www.flickr.com/'):
                            # e.g. http://www.facebook.com/pages/Soul-of-Snowdonia-Photographic-Gal
                            raise ValueError(f"bad blog url: {blog_url}")
                        parts = blog_url.split('/people/')
                        if len(parts) != 1:
                            self.blog_id = parts[1].split('/')[0]
                        else:
                            # somethines we have not blog url but url of photostream
                            parts = blog_url.split('/photos/')
                            if len(parts) != 2:
                                raise ValueError("expect flickr url to blog or photo stream")
                            self.blog_id = parts[1].split('/')[0]

                    self.bloginfo_xml.append(self._extract_xml(node))
                    continue
                elif node.tag == 'en-media':
                    self.bloginfo_xml.append(self._extract_xml(node))
                    continue
                elif node.tag == 'hr':
                    section = 'blogdesc'
                    if not self.blog_id:
                        logger.error(f"could not determine blog id from note")
                    continue

            if section == 'blogdesc':
                if node.tag in ('div', 'h4', 'ul', 'ol'):
                    self.blogdesc_xml.append(self._extract_xml(node))
                    continue
                elif node.tag == 'hr':
                    # sometimes, there may be more than one <hr> in the description section
                    if node.getnext().tag == 'ul':
                        # detected blog properties list, so end of description
                        section = 'blogprops'
                        continue
                    else:
                        # eliminate empty div
                        if etree.tostring(node.getnext()) != b'<div><br/></div>':
                            self.blogdesc_xml.append(self._extract_xml(node))
                        continue

            if section == 'blogprops':
                if node.tag == 'ul':
                    self._extract_blogprops(node)
                    continue
                elif node.tag == 'hr':
                    section = 'albums'
                    continue

            if section == 'albums':
                if node.tag == 'div':
                    node_text = self._extract_node_text(node)
                    if node_text.startswith("Albums"):
                        continue
                    if node_text == 'No albums':
                        self.albums = None
                        section = 'galleries'
                        continue

                    # have old style album list
                    section = 'albumsold'

                elif node.tag == 'h4':
                    # have old style album list
                    section = 'albumsold'

                elif node.tag == 'ul':
                    self._extract_albums(node)
                    continue

                elif node.tag == 'hr':
                    section = 'galleries'
                    continue

            if section == 'albumsold':
                if node.tag == 'div':
                    div_text = self._extract_node_text(node)
                    if div_text == '':
                        albumold_title = None
                        continue  # skip empty lines

                    album_info = self._extract_albumold_item_info(div_text)
                    if album_info:
                        assert albumold_title is not None
                        album_info['title'] = albumold_title
                        self.albums.append(album_info)
                        albumold_title = None
                        continue

                    if div_text not in ('.',):
                        logger.warning(f"ignored text in old album section: {div_text!r}")
                    continue

                elif node.tag in ('h4',):
                    # title line for album
                    div_text = self._extract_node_text(node)
                    assert albumold_title is None, f"troubles extracting album info (old style), " \
                                                   f"see {albumold_title} | {div_text}"
                    albumold_title = div_text
                    continue

                elif node.tag == 'hr':
                    section = 'galleries'
                    continue

                else:
                    raise ValueError(f"old style album list, unhandled element {node.tag}")

            if section == 'galleries':
                # note this section is optional
                if node.tag == 'div':
                    node_text = self._extract_node_text(node)
                    if node_text.startswith("Galleries"):
                        continue
                    elif node_text.startswith('No galleries'):
                        self.galleries = None
                        section = 'theend'
                        continue
                    else:
                        section = 'theend'
                elif node.tag == 'ul':
                    self._extract_galleries(node)
                    continue
                elif node.tag == 'hr':
                    section = 'theend'
                    continue

            if section == 'theend':
                if node.tag == 'div':
                    # expect timestamp, date and time note last updated
                    node_text = self._extract_node_text(node)
                    if node_text.startswith('Galleries'):
                        # for a yet unknown reason lxml repeats section # HACK
                        # assert len(self.galleries) > 0 or self.galleries is None
                        raise ValueError(f"troubles with galleries extraction")
                    if node_text == '.':
                        continue
                    self.timestamp = self._extract_timestamp(node_text)
                    if self.timestamp:
                        continue
                    section = 'afterend'
                elif node.tag == 'ul':
                    # for a yet unknown reason lxml repeats section - see note above (issue with iterwalk??)
                    assert len(self.galleries) > 0 or self.galleries is None
                    continue

            if section is 'afterend':
                xml = self._extract_xml(node)
                raise ValueError(f'unexpected text at end: {xml}')

            xml = self._extract_xml(node)
            # this can happen for old-style blog notes, with list of albums not formatted as list
            raise ValueError(f"detected unhandled element in {section}:\n  {xml}")

        return True

    def generate(self):
        """ generate html content for a blog note """
        return None  # TODO future

# TODO
# Alan Cressler | alan_cressler | 7449293@N02 | Flickr blog
# fails to dected timestamp at end
