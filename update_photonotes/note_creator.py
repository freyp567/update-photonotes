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
from ratelimit import limits, sleep_and_retry  ### TODO need sleep_and_retry?

from .database import PhotoNotesDB, lookup_note
from .flickr_types import FlickrPhotoNote
from .exceptions import PhotoNoteNotFound, NoteNotFound
from . import utils
from . import flickr_utils
from . import cached_lookup

from evernote.edam.type.ttypes import Note

import flickr_api
from flickr_api.objects import Person, Photo, FlickrList
import requests
import requests_cache  # usefulness for flickr API? looks like Flicker prenvents caching
import fake_useragent


import logging
logger = logging.getLogger('create_note')

# number of images per page - 500 is maximum allowed
# use maximum for flickr_api.Photo.search to reduce number of API calls for larger photo streams
IMAGES_PER_PAGE = 500
IMAGES_PER_PAGE_FIRST = 100


LIMIT_PHOTOS_INTERVAL = 600  # 10 minutes, in seconds
LIMIT_PHOTOS_COUNT = 500  # photos per interval 500 per 10 m => 3000 per hour
# flickr demands to stay under 3600 queries per hour

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

        if os.getenv("DEBUG") == '1' or os.getenv("LOGLEVEL") == "DEBUG":
            # for debugging flickr API lookups
            logging.getLogger('flickr_api.reflection').setLevel('DEBUG')

        # cache photo infos for faster lookup
        photos_cache_dir = self.base_path / "__cache"

        self._lookup_cache = cached_lookup.CachedLookupPhoto(photos_cache_dir)

        template_dir = utils.get_template_dir()
        self.template_file = template_dir / template_name
        assert self.template_file.is_file(), f"missing template {template_name}"

        self.import_path = self.base_path / "import"
        self.import_path.mkdir(exist_ok=True)

        flickr_utils.authenticate(use_auth_session=options.use_auth_session)
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
            note_tags.add("license-other")
            license_info = f'unknown License Type {photo.license}'
            raise ValueError('TODO examine license type {photo.license}')
        elif photo.license != '0':
            note_tags.add("freepic")
            note_tags.add("license-%s" % license_info.replace('CC ', 'CC_').replace(' ', ''))
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

    # throttle API calls to stay below limit of 3600 calls per hhour
    @limits(calls=LIMIT_PHOTOS_COUNT, period=LIMIT_PHOTOS_INTERVAL)
    def get_photo_info(self, photo: Photo, pos: int) -> dict:  ##TODO obsolee?
        photo_title = photo.title or ''
        logger.debug(f"{pos} | {photo.id} - {photo_title!r}")
        photo_description = photo.description or ''
        photo_description = photo_description.strip().replace('\n', '|')

        uploaded = datetime.datetime.fromtimestamp(int(photo.dateuploaded))
        image_info = {
            'pos': pos,
            'photo_id': photo.id,
            'photo_title': photo_title,
            'dateuploaded': uploaded.isoformat()[:10],
            'description': photo_description[:1000],
            # additional properties may cost as causing additional api calls (e.g. .license), so omit
            # 'photo_taken': flickr_utils.get_taken(photo),
            # 'photo_uploaded': flickr_utils.get_uploaded(photo),
            # 'license': photo.license,  # expensive, costs an API call
            # 'lastupdate': flickr_utils.get_lastupdate(photo),
        }
        return image_info

    def lookup_photo_by_id(self, user: Person, photo_id: str, pageno: Optional[int] = None) -> Optional[Photo]:
        """ lookup photo by id """
        photo = Photo(id=photo_id, owner=user, token=user.getToken())
        logger.info(f"loaded photo {photo_id} title={photo.title!r}")

        # EXPERIMENTAL
        pos, photo_info = self._lookup_cache.lookup_photo(user, photo_id)
        if photo_info is not None:
            logger.debug(f"cache lookup succeeded for photo {photo_id}, found at pos {pos}")
        else:
            logger.debug(f"cache lookup failed for photo {photo_id}, not found (cache-size={pos})")
        return photo

    def create_content(self,
                       user: Person,
                       photo: Photo,
                       enex_path: Path,
                       photo_note: Optional[FlickrPhotoNote],
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

        self.params['flickr_title'] = utils.quote_xml(photo.title)
        self.params['note_title'] = utils.quote_xml(note_title)

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
        archive_path = Path(os.environ["PHOTO_ARCHIVE"]) if os.environ.get("PHOTO_ARCHIVE") else None
        img_key_item, s_size = self.pick_size(sizes, ("Large", "Medium"))
        if s_size:
            key_parts = str(img_key_item).split('_')
            archive_name = f"{user.id} {photo.id} {'_'.join(key_parts[1:])}"
            if blog_id != user.id:
                archive_name = f"{blog_id} {archive_name}"
            logger.info(f"image is {img_key_item} size={s_size['label']} ...")
            if archive_path is not None:
                archive_path = archive_path / datetime.datetime.now().strftime("%Y-%m")
                archive_path.mkdir(exist_ok=True)
                img_file_a = archive_path / archive_name
                if not img_file_a.is_file():
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

        logger.info("")
        logger.info(f"api cache stats:\n{self.api_cache}")
        logger.info(f"created note in {enex_path}")
        return not has_error

    def lookup_photonote(self, blog_id: str, photo_id: str) -> Optional[FlickrPhotoNote]:
        image_key = f"{blog_id}|{photo_id}"
        try:
            found = self.notes_db.flickrimages.lookup_image(image_key, is_primary=None)
        except PhotoNoteNotFound:
            logger.debug(f"no photo-note found for image key={image_key}")
            return None
        else:
            logger.info(f"found photo-note / image for {image_key} #={len(found)}")
            # we potentially get more than one - pick first
            return found[0]

    def lookup_en_note(self, photo_note: FlickrPhotoNote) -> Optional[Note]:
        """ lookup Evernote note in evernote-backup db """
        try:
            note = lookup_note(self.notes_db.store, photo_note.guid_note)
        except NoteNotFound:
            return None
        return note

    def is_photo_url(self, url):
        return flickr_utils.is_flickr_url(url, 'photos/')
        return False

    def create_note(self, flickr_url: str) -> bool:
        if not self.is_photo_url(flickr_url):
            raise ValueError(f"not a valid Flickr UR:: {flickr_url}")
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
            raise ValueError(f"unsupported url {flickr_url!r}")

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
        logger.info(f"user for {blog_id} is {user.id} / {user.username!r} - #={photos_count}\n")

        # summary for user / blog
        now = datetime.date.today().isoformat()
        page = 0
        per_page = IMAGES_PER_PAGE_FIRST
        if self._lookup_cache.is_large_site(user):  # use max value for per_page for large site
            per_page = IMAGES_PER_PAGE
        photos = user.getPhotos(
            page=page,
            safe_search=3,
            # min_upload_date, max_upload_date,
            # content_types=[0, 3],
            extras=['dateuploaded', 'datetaken', 'date_upload', 'date_taken'],
            per_page=per_page,
        )
        if len(photos) == 0:
            # rare but may happen
            logger.warning(f"user {user.id} / {user.username!r}  has no (published) photos")
            empty_path = self.import_path / f"{blog_id} {photo_id} .empty"
            empty_path.write_text(f"""No photos yet
            
flickr_url={flickr_url}
loaded={now}
photos_info:
{json.dumps(user.photos_info, indent=4, default=ascii)}
.
""")
            raise ValueError("missing photos")

        # info on latest photo in blog
        latest_photo = photos[0]
        last_taken = flickr_utils.get_taken(latest_photo)
        last_upload = datetime.datetime.fromtimestamp(int(latest_photo.dateuploaded)).isoformat()[:10]

        for pos, photo in enumerate(photos):
            attrs = photo.__dict__.keys()
            # if photo.loaded is False:
            #     # will triggering load when acceesing attributes
            #     # photo.loaded = True # flickr_api.flickrerrors.FlickrError: Readonly attribute
            #     logger.debug(f"#{pos} unloaded Photo id={photo.id} - have {attrs}")
            dateuploaded = ''
            if 'dateuploaded' in attrs:
                dateuploaded = datetime.datetime.fromtimestamp(int(photo.dateuploaded)).isoformat()[0:]
            else:
                dateuploaded = '(not loaded/unknown)'
            logger.debug(f"photo id={photo.id} upload={dateuploaded} title={photo.title!r}")

        # cache latest photos to detect updates
        new_pos = self._lookup_cache.update_cache(user, photos)
        if new_pos < 0:
            if not self._lookup_cache.is_large_site(user):
                # have more new photos than what cache can hold - increase it
                self._lookup_cache.drop_cache(user)
                self._lookup_cache.flag_large_site(user)
                raise ValueError(f"detected user has more than {per_page} new images - set large site mode")
            else:
                logger.warning(f"extra large size with more than 500 additions !!")
            new_photos = f"+(more than {len(photos)})"
        else:
            new_photos = f"+{new_pos}" if new_pos else ""

        # format user info for output
        count_photos = f"{user.photos_info.get('count'):,}".replace(',', '.')
        blog_info = f"{now}: #={count_photos},  t={last_taken},  u={last_upload}"
        date_created = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        user_location = utils.get_safe_property(user, 'location', "")
        user_realname = utils.get_safe_property(user, 'realname', "")

        self.params.update({
            'blog_id': blog_id,
            'user_name': utils.quote_xml(user.username),
            'user_location': utils.quote_xml(user_location) or "(no location)",
            'real_name': user_realname,
            'profile_url': user.profileurl,
            'blog_info': blog_info,
            'note_created': date_created,
            'note_updated': date_created,
            'new_photos': new_photos,
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
        self.params['user_info'] = utils.quote_xml(user_info)

        # lookup photo by id
        photo = self.lookup_photo_by_id(user, photo_id, pageno)

        if photo is None or photo.id != photo_id:
            logger.error(f"image not found: {blog_id}/{photo_id}\n")
            logger.info(f"api cache stats:\n{self.api_cache}")
            return False

        photo_note = self.lookup_photonote(blog_id, photo_id)
        return self.create_content(user, photo, enex_path, photo_note)
