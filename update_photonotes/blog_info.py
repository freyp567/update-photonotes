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
        self.note_updated = None
        self.blog_latest_update = None
        self.images = []
        self.more_images = []
        self.before_images = []
        self.after_images = []
        self.text_after_images = []
        self.blog_updates = []
        self.status_xml = []
        self.bloginfo_xml = []
        self.blogdesc_xml = []
        self.properties = []
        self.albums = []
        self.galleries = []
        self.timestamp = None

    def extract(self, note: Note2) -> bool:
        self.note_title = note.title
        logger.debug(f"updating blog note {self.note_title!r} ...")
        content = get_note_content(note.en_note.content)
        root = etree.fromstring(content)
        try:
            return self._extract_blog_info(root)
        except ValueError as exc:
            logger.error(f"failed to extract blog info from {note.title!r}:\n  {exc}")
            return False
        except Exception:
            logger.exception(f"failed to extract blog info from {note.title!r}")
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

    def _extract_isodate_text_cond(self, value: str) -> datetime|None:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None



    def _is_empty(self, node: etree.Element) -> bool:
        subitems = [n for n in node.getchildren() if n.tag not in ('br', )]
        if subitems:
            # there are child elements, so not empty
            return False

        # test text content of node
        text = " ".join(etree.XPath(".//text()")(node))
        text = text.strip()
        return not text


    def _is_marker(self, node: etree.Element, info: str) -> bool:
        subitems = [n for n in node.getchildren() if n.tag not in ('br', )]
        if subitems:
            return False
        text = " ".join(etree.XPath("./text()")(node))
        text = text.strip()
        return text == info

    def _extract_images(self, node: etree.Element) -> None:
        if node.tag != 'ul':
            raise ValueError("expect list of images")
        for item in node.getchildren():
            assert item.tag == 'li'
            info = item.getchildren()
            assert len(info) == 1, "expect single div for image list item"
            img_info = self._extract_image_info(info[0])
            self.images.append(img_info)
        return

    def _extract_moreimage(self, node: etree.Element) -> dict:
        image_info = {
            'text_before': [],
            'text_after': []
        }
        assert node.tag == 'div'
        pos = 'before'
        prefix = (node.text or '').strip()
        if prefix.startswith('see:'):
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
            if self._extract_isodate_text_cond(prefix[:10]):
                # at start of section with blog updates, no section 'more images'
                return None
            logger.info(f"accept non-std prefix in more images section: {prefix!r}")
        if prefix:
            image_info['text_before'].append(prefix)

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
                    text = text.strip()
                image_info[f"text_{pos}"].append(text)
            else:
                subnode = subnode

        if 'href' not in image_info:
            # not a more image info
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
        # all consumed?
        assert not keys, f"unhandled image anchor attrib: {keys}"
        return image_info

    def _extract_image_info(self, node: etree.Element) -> dict:
        image_info = {
            'text_before': [],
            'text_after': []
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
                    assert image_id.isdigit(), f"invalid image_id: {image_id}"
                    assert 'image_id' not in image_info, "single image_id only"
                    image_info['image_id'] = image_id
                    continue

                # text = " ".join(etree.XPath("./text()")(subnode))
                # passthrough text before / after link
                image_info[pos].append(etree.tostring(subnode))
            else:
                assert False
                node = node
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
            album_info = {}
            info = self._extract_node_text(subnode)
            # split into parts
            # e.g. 'Blumen Flower | #=379 u=2023-04-22'
            props = info.split('|')
            if len(props) < 2:
                raise ValueError(f"cannot interpret album info: {info!r}")
            elif len(props) > 2:
                album_info['title'] = '|'.join(props[:-1])
                props = props[-1].strip()
            else:
                album_info['title'] = props[0]
                props = props[1].strip()

            if not props.startswith('#'):
                raise ValueError(f"format error in album info: {info!r}")

            for prop_item in props[1].strip().split(' '):
                key, value = prop_item.split('=')
                if key in ('u', ):
                    value = self._extract_isodate_text(value)
                    value = value.date()
                elif key == '#':
                    value = int(value)
                else:
                    value = value
                album_info[key] = value
            self.albums.append(info)
        return

    def _extract_galleries(self, node: etree.Element) -> None:
        assert node.tag == 'ul'
        for subnode in node.getchildren():
            assert subnode.tag == 'li'
            info = self._extract_node_text(subnode)
            # FUTURE split into parts
            self.galleries.append(info)
        return

    def _extract_blog_info(self, root: etree.Element) -> bool:
        """ extract information from content of a blog note """
        section = "start"
        context = etree.iterwalk(root, events=('start', 'end'))
        for action, node in context:
            if node == root:
                continue

            if action == 'start':
                if node.getparent() == root:
                    # toplevel node
                    if node.tag == 'div' and self._is_empty(node):
                        # ignore empty divs, they are for readability only
                        context.skip_subtree()
                        continue

                    # first item we expect is the date of last update
                    if self.note_updated is None:
                        assert node.tag == "div", "expect first div to hold date of last update"
                        self.note_updated = self._extract_isodate(node)
                        continue

                    if self._is_marker(node, 'images:'):
                        assert section == 'start', f"images in mode {section}"
                        section = 'images'
                        context.skip_subtree()
                        continue

                    if self._is_marker(node, 'more images:'):
                        # ignore prefix of section with additional images
                        assert section == 'moreimages', f"more images in mode {section}"
                        section = 'moreimages'
                        context.skip_subtree()
                        continue

                    if section == 'start':
                        # maybe to be supported, but skip for now
                        raise ValueError("unexpected text in start section")

                    if section == 'images':
                        self._extract_images(node)
                        context.skip_subtree()
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
                            context.skip_subtree()
                            continue

                    if section == 'afterimages':
                        if node.tag == 'div':
                            updated = self._extract_blog_updates(node)
                            if updated is not None:
                                if not self.blog_latest_update:
                                    self.blog_latest_update = updated
                                    # TODO verify blog_update and blog_latst_update, should match - normally
                                continue
                            else:
                                # text after image / more image section
                                text_after = self._extract_xml(node)
                                self.text_after_images.append(text_after)
                                context.skip_subtree()
                                continue
                        elif node.tag == 'hr':
                            section = 'status'
                            continue

                    if section == 'status':
                        if node.tag == 'div':
                            self.status_xml.append(self._extract_xml(node))
                            context.skip_subtree()
                            continue
                        elif node.tag == 'hr':
                            section = 'bloginfo'
                            continue

                    if section == 'bloginfo':
                        if node.tag == 'div':
                            self.bloginfo_xml.append(self._extract_xml(node))
                            context.skip_subtree()
                            continue
                        elif node.tag == 'en-media':
                            self.bloginfo_xml.append(self._extract_xml(node))
                            context.skip_subtree()
                            continue
                        elif node.tag == 'hr':
                            section = 'blogdesc'
                            continue

                    if section == 'blogdesc':
                        if node.tag == 'div':
                            self.blogdesc_xml.append(self._extract_xml(node))
                            context.skip_subtree()
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
                            context.skip_subtree()
                            continue
                        elif node.tag == 'hr':
                            section = 'albums'
                            continue

                    if section == 'albums':
                        if node.tag == 'div':
                            node_text = self._extract_node_text(node)
                            context.skip_subtree()
                            if node_text.startswith("Albums"):
                                continue
                            node_text = node_text
                        elif node.tag == 'ul':
                            self._extract_albums(node)
                            context.skip_subtree()
                            continue
                        elif node.tag == 'hr':
                            section = 'galleries'
                            continue

                    if section == 'galleries':
                        # note this section is optional
                        if node.tag == 'div':
                            context.skip_subtree()
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
                            context.skip_subtree()
                            continue
                        elif node.tag == 'hr':
                            section = 'theend'
                            context.skip_subtree()
                            continue

                    if section == 'theend':
                        if node.tag == 'div':
                            context.skip_subtree()
                            # expect timestamp, date and time note last updated
                            node_text = self._extract_node_text(node)
                            if node_text.startswith('Galleries'):
                                # for a yet unknown reason lxml repeats section # HACK
                                assert len(self.galleries) > 0 or self.galleries is None
                                continue
                            if node_text == '.':
                                continue
                            self.timestamp = self._extract_timestamp(node_text)
                            if self.timestamp:
                                continue
                            section = 'afterend'
                        elif node.tag == 'ul':
                            # for a yet unknown reason lxml repeats section - see note above
                            assert len(self.galleries) > 0 or self.galleries is None
                            context.skip_subtree()
                            continue

                    if section is 'afterend':
                        xml = self._extract_xml(node)
                        raise ValueError(f'unexpected text at end: {xml}')

                    xml = self._extract_xml(node)
                    # this can happen for old-style blog notes, with list of albums not formatted as list
                    raise ValueError(f"detected unhandled toplevel element in {section}: {xml}")
                else:
                    xml = self._extract_xml(node)
                    raise ValueError(f"detected unhandled element in {section} on sublevel; {xml}")

            else:
                assert action == 'end'

        return True

    def generate(self):
        """ generate html content for a blog note """
        return None  # TODO future

"""
old code, to be dropped:

            # for anchor in xml.xpath('//a'):
            #     href = anchor.attrib.get("href")
            #     if 'evernote:///view/' in href:
            #         # TODO test if image link
            #         internal.append(href[17:])
            #         continue
            #     if 'flickr.com' not in href:
            #         continue
            #     if href.startswith(FLICKR_PHOTO_URL):
            #         # 'href': 'https://www.flickr.com/photos/27297062@N02/51089206529/in/pool-inexplore/',
            #         # ..., 'rev': 'en_rl_none', 'target': '_blank'}
            #         self._handle_image_link(blog_note, href)
            #     else:
            #         logger.debug(f"ignored href={href!r}")
            #
            # # 'www.flickr.com/people/'
            # if 'www.flickr.com/photos' not in content_text:
            #     return None


"""