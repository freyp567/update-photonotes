"""
utilities to handle Flickr objects
"""

import os
from datetime import datetime
from lxml import etree
import flickr_api
from flickr_api.objects import Photo, Person

from . import utils

import logging
logger = logging.getLogger('flickr_utils')


def get_auth_file():
    script_dir = utils.get_script_dir()
    return script_dir / "session.auth"


def authenticate(use_auth_session=True):
    auth_file = get_auth_file()
    if not auth_file.is_file() or not use_auth_session:
        credentials = get_credentials()
        api_key = credentials['api_key']
        flickr_api.set_keys(
            api_key=api_key,
            api_secret=credentials['api_secret'],
        )
        logger.info(f"authenticated using api_key={api_key!r}")
    else:
        auth_file_path = str(auth_file)
        # see authenticate.py, to save authentication session
        flickr_api.set_auth_handler(
            auth_file_path,
            set_api_keys=True,
        )
        logger.info(f"authenticated using session file {auth_file_path!r}")
    return


def get_credentials():
    """ get credentials, load from .env file """
    # see .utils.load_dotenv for fetching environment variables from .env
    credentials = {
        'api_key': os.environ['API_KEY'],
        'api_secret': os.environ['API_SECRET'],
    }
    return credentials


def get_firstdate(user: Person) -> str:
    value = user.photos_info["firstdate"]
    if value:
        value = datetime.fromtimestamp(int(value))
        value = value.strftime("%Y-%m-%d")
    else:
        value = "---"
    return value


def get_firstdatetaken(user: Person) -> str:
    value = user.photos_info.get("firstdatetaken")
    if value:
        value = value[:10]
    else:
        value = "---"
    return value


def get_lastupdate(photo: Photo) -> str:
    update = datetime.fromtimestamp(photo.lastupdate)
    return update.isoformat()[:10]


def get_uploaded(photo: Photo) -> str:
    uploaded = datetime.fromtimestamp(int(photo.dateuploaded))
    return uploaded.isoformat()[:10]


def get_taken(photo: Photo) -> str:
    photo_taken = photo.taken  # APIcall,
    if photo_taken and len(photo_taken) > 16:
        photo_taken = photo_taken[:10]  # reduce precision
    if photo.takengranularity != 0:
        photo_taken = photo_taken
    if photo.takenunknown == '0' or photo.takenunknown == 0:  #TODO cleanup
        photo_taken = photo_taken
    elif photo.takenunknown == '1':
        photo_taken += ' (unknown)'
    else:
        photo_taken += f' (unknown-{photo.takenunknown})'
    return photo_taken


def get_license_info(photo: Photo) -> str:
    license_info = {
        '0': 'All Rights reserved',
        '1': 'CC BY-NC-SA 2.0',
        '2': 'CC BY-NC 2.0',
        '3': 'CC BY-NC-ND 2.0',
        '4': 'CC BY 2.0',
        '5': 'CC BY-SA 2.0',
        # '6': 'License Type 6',
        # '7': 'License Type 7',
        # '8': 'License Type 8',
        '9': 'CC0 1.0 Public Domain',
        '10': 'Public Domain Mark 1.0',
        # '11': 'License Type 11',
        #
        #
    }.get(photo.license)
    return license_info


def cleanup_description(desc: str) -> str:
    """ cleanup description of flickr photo """
    desc = desc.replace('\n\n', '<br/>\n')

    # replace HTML style links by markup style ones
    xml = etree.fromstring('<div class="note-description">' + desc + '</div>')
    for anchor in xml.xpath("//a"):
        href = anchor.attrib.get("href")
        link_text = anchor.text.strip()
        if link_text == href:
            href = utils.quote_xml(href)
            markup_text = f'<span><br/>[link]({href})<br/></span>'
        else:
            href = utils.quote_xml(href)
            markup_text = f'<span><br/>[{link_text}]({href})<br/></span>'
        try:
            markup_link = etree.fromstring(markup_text)
        except Exception as err:  # XMLSyntaxError
            logger.error(f"failed to transform html anchor to markup link - {err!r}")
        else:
            markup_link.attrib["style"] = "--en-highlight:blue"
            anchor.getparent().replace(anchor, markup_link)

    # get pretty-printed description
    result = etree.tostring(xml,
                            encoding='utf-8',
                            xml_declaration=False,
                            pretty_print=True
                            ).decode('utf-8').strip()
    return result


class CountingAPIcallsCache(flickr_api.cache.SimpleCache):
    """ extension to flickr_api cache: count cache misses """

    def __init__(self, **kwargs):
        self.cache_hit = {}
        self.cache_miss = {}
        super().__init__(**kwargs)

    def reset_counters(self):
        for cache_map in (self.cache_hit, self.cache_miss):
            cache_map.clear()

    def __str__(self):
        info = ""
        keys = set(self.cache_miss.keys())
        keys.update(self.cache_hit.keys())
        keys = sorted(keys)
        info += "cache hits / misses:\n"
        for key in keys:
            info += f"  {key}: "
            info += f"{self.cache_hit.get(key, 0)} / "
            info += f"{self.cache_miss.get(key, 0)}\n"
        info += '\n.'
        return info

    # @locking  # reuse locking from base class?
    # assume usage is synchronously / single-threaded, so live without
    def has_key(self, key):
        found = super().has_key(key)

        # track cache miss / hit
        cache_map = self.cache_miss if not found else self.cache_hit
        cache_map['_all'] = cache_map.get('_all', 0) +1

        # determine flickr api method, track per method
        items = key.split('&')
        method = [ item for item in items if item.startswith('method=')]
        method_name = method[0].split('=')[1] if method else 'unknown'
        cache_map[method_name] = cache_map.get(method_name, 0) +1

        return found

