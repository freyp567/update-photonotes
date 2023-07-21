"""
Types for Flickr related data entities
"""

import datetime
from typing import Optional


class FlickrDate(object):
    """ wraps a date value - with serialization from/to SQLite """

    def __init__(self, value: Optional[str]):
        if value is not None:
            value = datetime.date.fromisoformat(value)
        self._value = value

    def __str__(self):
        if self._value is None:
            return '(not set)'
        else:
            return self._value.isoformat()

    def __repr__(self):
        value = str(self)
        return f"Flickrdate({value})"

    def __bool__(self):
        return self._value is not None

    def serialize(self) -> Optional[str]:
        """ serialize for SQLite """
        if self._value is not None:
            return self._value.strftime("%Y-%m-%d")
        return None

    @property
    def value(self) -> Optional[datetime.date]:
        return self._value

    @staticmethod
    def today():  # TODO verify: -> FlickrDate fails: NameError: name 'FlickrDate' is not defined
        now = datetime.date.today()
        return FlickrDate(now.isoformat())


class FlickrPhotoBlog(object):
    """ represents a Flickr photo blog entry """

    def __init__(self, blog_id: str, guid_note: str):
        self.blog_id = blog_id
        self.guid_note = guid_note
        self.is_gone = False
        self.last_upload = FlickrDate(None)
        self.favorite = None
        self.image_count = None
        self.entry_updated = FlickrDate(None)
        self.verified = FlickrDate(None)


class FlickrPhotoNote(object):
    """ represents a Photo-note (Note on flickr image) """

    def __init__(self, image_key: str, guid_note: str):
        self.image_key = image_key
        self.guid_note = guid_note
        self.is_primary = False

        self.note_tags = None
        self.blog_id = None
        self.need_cleanup = ''
        self.date_verified = None
        self.photo_id = None
        self.secret_id = None
        self.size_suffix = None
        self.photo_taken = FlickrDate(None)
        self.photo_uploaded = FlickrDate(None)
        self.entry_updated = FlickrDate(None)
        self.is_gone = False

    def __str__(self):
        return f'image_key={self.image_key}'

    def __repr__(self):
        return f"FlickrPhotoNote({self.image_key}, guid={self.guid_note})"

    def add_cleanup(self, value):
        cleanups = set(self.need_cleanup.split('|'))
        if isinstance(value, str):
            values = [value, ]
        else:
            values = value
        for value in values:
            if value not in cleanups:
                cleanups.add(value)
        self.need_cleanup = '|'.join(cleanups)

    def clear_cleanup(self):
        self.need_cleanup = ''
