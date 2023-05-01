"""
Create a blog note for given Flickr blog URL

costs: 7 API calls
  flickr.urls.lookupUser: 1
  flickr.people.getPhotos: 1
  flickr.photos.getInfo: 1
  flickr.people.getInfo: 1
  flickr.photosets.getList: 1
  flickr.galleries.getList: 1
  flickr.photos.getSizes: 1

"""

from typing import Optional
from types import SimpleNamespace

import os
import json
import base64
import datetime
import re
from io import StringIO
from pathlib import Path
import hashlib

from lxml import etree

# from flickr_types import FlickrImage  # FUTURE, to lookup photo notes
from .database import PhotoNotesDB
from . import utils

import flickr_api
from flickr_api.objects import Photo, Person
from . import flickr_utils

import requests
import requests_cache  # usefulness for flickr API? looks like Flicker prenvents caching


import logging
logger = logging.getLogger('create_blog')


class BlogCreator:

    def __init__(self,
                 notes_db: PhotoNotesDB,
                 options: SimpleNamespace,
                 target_dir: Optional[Path] = None,
                 template_name: str = "FlickrBlog - Template.enex",
                 ):
        self.notes_db = notes_db
        self._options = options
        
        if target_dir is None:
            self.base_path = options.db_path.parent / "update_photonotes"
        else:
            self.base_path = target_dir
        assert self.base_path.is_dir(), f"missing directory: {self.base_path}"

        self.blog_path = self.base_path / "blogs"
        self.blog_path.mkdir(exist_ok=True)

        template_dir = utils.get_template_dir()
        self.template_file = template_dir / template_name
        assert self.template_file.is_file(), f"missing template {template_name!r} in {template_dir}"

        self.output_path = self.base_path / "import"
        self.output_path.mkdir(exist_ok=True)

        date_created = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        self.params = {
            'note_created': date_created,
            'note_updated': date_created,
            'today': datetime.date.today().isoformat(),
            'timestamp': datetime.datetime.now().isoformat()[:16],
        }
        flickr_utils.authenticate(use_auth_session=True)
        if os.environ.get('REQUESTS_CACHE') != "1":
            # no caching, but create a session
            self.session = requests.session()
        else:
            # cache as much as we can to reduce number of API calls
            self.session = requests_cache.CachedSession('note_creator', expire_after=datetime.timedelta(days=6))
            requests_cache.install_cache('note_creator')
            # note: need to cache POST requests, what is not by default

        self.api_cache = flickr_utils.CountingAPIcallsCache(
                timeout=3600 * 12,  # 12 hours
                max_entries=1000,
        )
        # defaults are: timeout=300, max_entries=200
        # len(self.api_cache) is number of entries in cache
        flickr_api.enable_cache(
            self.api_cache
        )

    def get_recent_photo(self, user: Person) -> tuple:
        photo = user.getPhotos(page=1)[0]
        last_taken = photo.taken
        if last_taken:
            if len(last_taken) > 10:
                last_taken = last_taken[:10]  # date only
        else:
            last_taken = str(last_taken)
        if photo.takenunknown == '1':
            last_taken = "?" + last_taken

        self.params["last_taken"] = last_taken
        last_upload = datetime.datetime.fromtimestamp(int(photo.dateuploaded)).isoformat()[:10]
        self.params["last_upload"] = last_upload
        return photo, last_taken, last_upload

    def from_template(self, template, params, encoding='utf-8'):
        data = template.read_text(encoding=encoding)
        for key in params:
            data = data.replace(f'${{{key}}}', str(params[key]))

        match = re.search(r'\${(.*?)}', data)
        if match:
            logger.warning("detected placeholders in template not replaced: %s" % match.group(1))
        return data

    def pick_photo_size(self, photo: Photo, acceptable: tuple) -> dict:
        sizes = photo.getSizes()
        for s_key in acceptable:
            s_item = sizes.get(s_key)
            if s_item:
                return s_item
        logger.warning(f"no suitable photo size found, available: {sizes.keys()}")
        return {}

    def fetch_blog_thumbnail(self, blog_id: str, photo: Photo, acceptable=('Thumbnail', 'Small',)) -> None:
        """ build image to use for blog note and update params """
        s_item = self.pick_photo_size(photo, acceptable)
        assert s_item, f"photo size unavailable"

        # generate preview for note
        # size_key = s_item['url'].split('/')[-2]
        source_name = Path(s_item["source"].split('/')[-1])
        img_key = f"{source_name.stem}{source_name.suffix}"
        logger.debug(f"picked size {s_item['label']} for preview: {img_key}")
        self.params['preview_width'] = s_item['width']
        self.params['preview_height'] = s_item['height']

        # save thumbnail image
        img_file = self.output_path / img_key
        # response = self.session.get(url=s_item["source"])  # unreliable
        if not img_file.is_file():
            img_file_s = photo.save(str(img_file), s_item['label'])
            logger.info(f"saved image for blog thumbnail: {img_file_s}")
        else:
            # use cached image - useful while debugging to reduce api calls
            logger.debug(f"use cached image for blog thumbnail: {img_file}")

        self.params['preview_fn'] = img_key
        img_data_raw = img_file.read_bytes()
        img_data = base64.b64encode(img_data_raw).decode()
        self.params['filehash'] = hashlib.md5(img_data_raw).hexdigest()
        self.params['preview_width'] = s_item['width']
        self.params['preview_height'] = s_item['height']
        self.params['mimetype'] = utils.get_mimetype(Path(img_key).suffix)

        # ensure base64 padding
        while len(img_data) % 4 != 0:
            img_data += '='
        self.params['resource_data'] = img_data
        return

    def get_description(self, user: Person) -> None:
        """ get user description and update paraams """
        description = utils.get_safe_property(user, "description", None)
        if description:
            description = description.replace('\n', '<br/>')
            parser = etree.HTMLParser()
            tree = etree.parse(StringIO(description), parser)
            # drop all photo_container items from description
            for item in tree.xpath("//span[contains(@class, 'photo_container')]"):
                item.getparent().remove(item)
            body = tree.find("./body")
            utils.drop_empty_tags(body, "div")
            for item in body.xpath("//img"):
                # drop layzloading (and other) images
                item.getparent().remove(item)

            # extract html fragment from body
            html = etree.tostring(body, pretty_print=True).decode('utf-8')
            fragment = re.search('<body>(.*?)</body>', html, re.DOTALL).group(1)
            user_description = fragment

            blog_details = ""  # FUTURE
        else:
            user_description = "<div>(no description)</div>"

        current_city = utils.get_safe_property(user, "location")
        current_city = utils.quote_xml(current_city) if current_city else "---"
        props = [
            ("Joined", flickr_utils.get_firstdate(user)),
            ("First taken", flickr_utils.get_firstdatetaken(user)),
            ("Current city", current_city),
        ]
        if user.ispro:
            props.append(("FlickrPro", "Yes"))
        blog_details = "<li>%s</li>" % "</li><li>".join([f"{k}:  {v}" for k, v in props])
        self.params['blog_details'] = user_description
        self.params['blog_props'] = blog_details

        # flickr.places.placesForUser
        # https://www.flickr.com/services/api/flickr.places.placesForUser.html
        # places = flickr_api.Place.placesForUser(
        #     id=user.id,  ##TODO how to specify user ??
        #     place_type_id=8.  # region
        #     # place_type="region", # deprecated
        #     # threshold=3
        # )
        # if places:
        #     LOGGER.warning(f"found places: {len(places)}")
        return

    def get_galleries(self, user: Person, extra_tags: list) -> None:
        """ get list of galleries of user """
        galleries = []
        for gal_item in user.getGalleries():
            galleries.append((gal_item.get('count_photos', 0), gal_item))

        galleries.sort(reverse=True, key=lambda value: value[0])
        gal_items = []
        for photo_count, gal_item in galleries:
            gal_title = utils.quote_xml(utils.quote_xml(gal_item['title']))
            # .id, .description, .count_total, .count_views, .url
            gal_id = gal_item["gallery_id"]
            created = datetime.datetime.fromtimestamp(int(gal_item['date_create'])).isoformat()[:10]
            updated = datetime.datetime.fromtimestamp(int(gal_item['date_update'])).isoformat()[:10]
            count_photos = f"{photo_count:,}".replace(',', '.')
            gal_info = f"{gal_title} | {gal_id} | #={count_photos} c={created} u={updated}"
            gal_items.append(f"<li>{gal_info}</li>")

        if gal_items:
            extra_tags.append("blog_galleries")
            self.params['gallery_list'] = "<ul>%s</ul>" % "\n".join(gal_items)
        else:
            self.params['gallery_list'] = "<div><span>No galleries</span></div>"
        return

    def get_albums(self, user: Person) -> None:
        """ get list of albums for user """
        self.params['albums_list'] = ''
        albums_list = []
        for album in user.getPhotosets():
            if album.photos != album.count_photos:
                logger.warning(f"verify album count: {album.title} #={album.photos} ##={album.count_photos}")
            albums_list.append((album.count_photos, album, ))

        # sort by number of photos (descending)
        albums_list.sort(reverse=True, key=lambda value: value[0])

        # and generate list of albums
        album_items = []
        for photo_count, album in albums_list:
            album_title = utils.quote_xml(album.title)
            updated = datetime.datetime.fromtimestamp(int(album.date_update)).isoformat()[:10]
            count_photos = f"{photo_count:,}".replace(',', '.')
            album_info = f"{album_title} | #={count_photos} u={updated}"
            album_items.append(f"<li>{album_info}</li>")

        if album_items:
            self.params['albums_list'] = "<ul>%s</ul>" % "\n".join(album_items)
        else:
            self.params['albums_list'] = "<div><span>No albums</span></div>"
        return

    def create_note(self, flickr_url: str) -> bool:
        logger.info(f"create blognote for {flickr_url}")
        assert flickr_url.startswith('https://www.flickr.com/people/'), "must have a Flickr URL to a blog entry"
        steps = flickr_url.split('/')
        blog_id = steps[4]
        # note: using spaces in filename allowes easier picking of photo id from Windows Explorer
        enex_path = self.output_path / f"{blog_id} .enex"

        # output .txt file to indicate that note creation has been started - and indicate what url
        enex_path.with_suffix('.txt').write_text(flickr_url)

        extra_tags = []  # FUTURE auto-generate tags from user info
        now_date = datetime.datetime.now().strftime('%Y-%m-%d')
        data_path = self.blog_path / blog_id
        data_path.mkdir(exist_ok=True)
        user_data = data_path / f"user_{blog_id}.{now_date}.json"

        user = flickr_api.Person.findByUrl(flickr_url)
        if not user:
            raise ValueError(f"user not found by url={flickr_url}")

        user_data.write_text(json.dumps(user.__dict__, indent=4, default=str), encoding='utf-8')
        # user_info = SimpleNamespace(**json.loads(user_data.read_text()))
        logger.info(f"lookup by url succeeded, user for {blog_id} is {user.id} / {user.username}")

        # summary for user / blog
        now = datetime.date.today().isoformat()
        photo, last_taken, last_upload = self.get_recent_photo(user)
        count_photos = f"{user.photos_info.get('count', 0):,}".replace(',', '.')
        if last_taken:
            blog_info = f"{now}: #={count_photos},  t={last_taken},  u={last_upload}"
        else:
            blog_info = f"{now}: #={count_photos},  u={last_upload}"

        self.get_description(user)

        # provide additional tags for blog note
        if extra_tags:
            self.params['extratags'] = "<tag>%s</tag>" % "</tag>\n<tag>".join(extra_tags)
        else:
            self.params['extratags'] = ""

        real_name = utils.get_safe_property(user, 'realname', "")
        if real_name and real_name != user.username:
            parts = [ real_name, user.username, blog_id, ]
        else:
            parts = [ user.username, blog_id, ]
        if blog_id != user.id:
            parts.append(user.id)
        note_title = ' | '.join([p.strip() for p in parts if p.strip()]) + ' | Flickr blog'
        note_title = '[new] ' + note_title
        location = utils.get_safe_property(user, 'location', None)
        if not location:
            # user.timezone if no location??
            location = "(no location)"
        # show user.path_alias ?
        self.params.update({
            'note_title': note_title,
            'flickr_url': flickr_url,
            'blog_url': user.profileurl,
            'blog_id': blog_id,
            'user_name': user.username,
            'user_location': utils.quote_xml(location),
            'real_name': real_name,
            'profile_url': user.profileurl,
            'blog_info': blog_info,
        })

        self.params['blog_link'] = f'<a href="{flickr_url}">\n{flickr_url}\n</a>'
        self.get_albums(user)
        self.get_galleries(user, extra_tags)

        self.fetch_blog_thumbnail(blog_id, photo)

        # for en-media item, --en-naturalWidth ...
        self.params['media_width'] = self.params['preview_width']
        self.params['media_height'] = self.params['preview_height']

        content = utils.from_template(self.template_file.with_suffix(".xml"), self.params)
        self.params['content'], has_error = utils.validate_content(content)

        ok = True
        if has_error:
            # output XML content for examination in case of errors - for troubleshooting only
            enex_path.with_suffix('.xml').write_text(self.params['content'], encoding='utf-8')
        else:
            # save generated enex file
            enex = self.from_template(self.template_file, self.params)
            enex2, has_error = utils.validate_content(enex.encode('utf-8'))

            if has_error:
                enex = f"<!-- {has_error} -->\n" + enex2.decode('utf-8')
            enex_path.write_text(enex, encoding='utf-8')

        logger.info(f"api cache stats:\n{self.api_cache}")
        if not has_error:
            # successfully createed .nex, can delete .txt
            enex_path.with_suffix('.txt').unlink(missing_ok=True)
            logger.info(f"successfully created blog note in {enex_path}")
        else:
            logger.warning(f"created blog note in {enex_path}, detected errors")
            ok = False
        return ok

