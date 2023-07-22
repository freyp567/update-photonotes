"""
use cache with photo infos to speed up lookup if creating note for more than one image per site
or for sites that have large number of images
"""

from datetime import datetime
import json
from pathlib import Path
from flickr_api.objects import Person, Photo, FlickrList

import logging
logger = logging.getLogger('cache_lookup')


class CachedLookupPhoto:

    def __init__(self, cache_dir: Path):
        ##self.page_size = page_size
        self.cache_dir = cache_dir
        if not cache_dir.is_dir():
            cache_dir.mkdir()
        self.photos = None
        self.meta = {}

    def _load_cache(self, user_id):
        """ lazy loading of cache from disk """
        if self.photos is not None:
            return  # already loaded
        data_path = self.cache_dir / (user_id + '.json')
        if not data_path.is_file():
            # cache empty / missing
            return
        cached = json.loads(data_path.read_text())
        self.meta = cached['meta']
        self.photos = cached['photos']

    def _extract_photo_info(self, photo: Photo):
        attrs = photo.__dict__.keys()
        info = {
            'id': photo.id,
            # 'title': photo.title,
            'taken': photo.taken if 'taken' in attrs else '',
            'uploaded': photo.dateuploaded if 'dateuploaded' in attrs else '',
        }
        return info

    def _store_cache(self, user_id, photo_infos):
        data_path = self.cache_dir / (user_id + '.json')
        info = {
            'written': datetime.now().isoformat(),
            'size': len(photo_infos),
        }
        cached = {
            'meta': info,
            'photos': photo_infos,
        }
        if len(photo_infos) > 0:
            # add to meta info for easier lookup / grepping
            info['last_upload'] = cached['photos'][0]['uploaded']
        else:
            info['last_upload'] = ''
        data_path.write_text(json.dumps(cached, indent=4))

    def update_cache(self, user: Person, photos: FlickrList, pos: int = 0) -> None:
        """ update cache from photolist """
        self._load_cache(user.id)
        updates = [self._extract_photo_info(photo) for photo in photos]
        if self.photos is None:
            # empty cache, simply dump list
            self._store_cache(user.id,  updates)
            logger.info(f"emtpy cache for {user.id}, added {len(photos)} images")
            self.photos = None  # force reload on next access
            return 0

        # if cache is not empty, then merge cache with new list
        # there may be newer photos to be added to cache
        found = None
        last_before = self.photos[pos]
        for photo_info in updates:
            if photo_info['id'] == last_before['id']:
                # found in cache
                found = photo_info
                break
            # new photo got added since last time, insert in cache at given pos
            self.photos.insert(pos, photo_info)
            pos += 1

        if pos == 0:
            logger.debug(f"no updates to cache for {user.id} (have {len(self.photos)})")
        else:
            logger.info(f"updated cache for {user.id}, added {pos} new images (have {len(self.photos)})")
            self._store_cache(user.id, self.photos)
            if found is None:
                # there are more than len(photos) since last update
                logger.warning(f"detected more new images than loaded ({len(photos)})")
                # return pos to give caller possibility to load and add more
                pos = None
            else:
                logger.info(f"updated cache for {user.id}, added {pos} new images")

        self.photos = None  # force cache reload on next access
        return pos

    def lookup_photo(self,  user: Person, photo_id: str) -> tuple:
        """ lookup photo by id in cache """
        self._load_cache(user.id)
        ##
        if not self.photos or len(self.photos) == 0:
            return 0, None
        found = [(pos, pi) for (pos, pi) in enumerate(self.photos) if pi['id'] == photo_id]
        if not found:
            return (len(self.photos), None)
        else:
            return found[0]
