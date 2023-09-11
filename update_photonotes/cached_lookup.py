"""
use cache with photo infos to speed up lookup if creating note for more than one image per site
or for sites that have large number of images
"""

from datetime import datetime
import json
from pathlib import Path
from colorama import Fore, Back, Style
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

    def flag_large_site(self, user: Person) -> None:
        config_path = self.cache_dir / 'lookup_cache_config.json'
        if config_path.is_file():
            config = json.loads(config_path.read_text())
        else:
            config = {'large_sites': {}}
        config['large_sites'][user.id] = 1
        config_path.write_text(json.dumps(config, indent=2))

    def is_large_site(self, user: Person, ) -> bool:
        config_path = self.cache_dir / 'lookup_cache_config.json'
        if not config_path.is_file():
            return False
        else:
            config = json.loads(config_path.read_text())
            return config['large_sites'].get(user.id)

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

    def drop_cache(self, user: Person, ):
        data_path = self.cache_dir / (user.id + '.json')
        data_path.unlink(missing_ok=True)
        self.photos = None
        return

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

    def update_cache(self, user: Person, photos: FlickrList) -> None:
        """ update cache from photolist """
        self._load_cache(user.id)
        updates = [self._extract_photo_info(photo) for photo in photos]
        if self.photos is None:
            # empty cache, simply dump list
            self._store_cache(user.id, updates)
            logger.info(Back.YELLOW + f"setup cache for {user.id}, added {len(photos)} images" + Style.RESET_ALL)
            self.photos = None  # force reload on next access
            return 0

        # if cache is not empty, then merge cache with new list
        # there may be newer photos to be added to cache
        new_photos = []
        pos = 0
        found = None
        newest_before = self.photos[0]
        for photo_info in updates:
            if photo_info['id'] == newest_before['id']:
                # found in cache
                found = photo_info
                break

            # new photo got added since last time, insert in cache at given pos
            new_photos.append(photo_info)
            pos += 1

        if len(new_photos) == 0:
            logger.info(Style.DIM + f"{len(self.photos)} image items in user cache"  + Style.RESET_ALL)
        else:
            prev_photos = self.photos
            if found is None:
                # there are more than len(photos) since last update - drop cache aand fill again to avoid gaps
                logger.warning(Fore.RED + f"detected more new image items than {len(photos)}")
                # add marker to inndiccate that more images since last update
                new_photos.append({
                    'id': -1,
                    # 'title': "***marker***",
                    'taken': datetime.now().isoformat(),
                    'uploaded': '*',
                })
                pos = -1  # indicate pos undetermined

            self.photos = new_photos
            self.photos.extend(prev_photos)
            if pos > 0:
                logger.info(Back.YELLOW + f"added {pos} image items, have now (have {len(self.photos)}) items in cache"
                            + Style.RESET_ALL)

        self._store_cache(user.id, self.photos)
        self.photos = None  # force cache reload on next access
        return pos

    def lookup_photo(self, user: Person, photo_id: str) -> tuple:
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
