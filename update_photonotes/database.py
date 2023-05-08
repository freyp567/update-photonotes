"""
Extension of the SQLight database created and updated by evernote-backup by adding tables to
store and maintain photo nots related info
"""
import lzma
import pickle
from typing import Optional
import sqlite3

from evernote_backup.note_storage import SqliteStorage
from evernote.edam.type.ttypes import Note

from .flickr_types import FlickrPhotoBlog, FlickrPhotoNote, FlickrDate
from .exceptions import PhotoNoteNotFound, NoteNotFound

import logging
logger = logging.getLogger('updater.database')


DB_SCHEMA_PN = """\
CREATE TABLE IF NOT EXISTS flickr_blog(
    blog_id TEXT PRIMARY KEY NOT NULL,
    guid_note TEXT,  -- guid of photo note, or NULL
    note_tags, -- note tags; list joined by '|';  note: '||' if no tags
    entry_updated TEXT, -- ISO8601 string (date only); date db record got last updated / verified
    date_verified TEXT, -- ISO8601 date - date blog has been checked on flickr
    image_count INTEGER,  -- number of (public) images
    favorite INTEGER,  -- personal user rating, NULL = not rated, 1=favorit, 2=favorit+ (evernote tags)
    last_upload TEXT, -- date of last image upload
    is_gone INTEGER DEFAULT FALSE  -- blog unavailable / removed (Flickr 410)
);

CREATE INDEX IF NOT EXISTS idx_blog
  ON flickr_blog(blog_id);


CREATE TABLE IF NOT EXISTS flickr_image(
    image_key TEXT NOT NULL,  -- combination user_id / photo_id (without secret, size suffix)
    guid_note TEXT NOT NULL,  -- guid of photo note, or NULL (if stacked/same location image)
    is_primary INTEGER, -- (BOOEAN) true if image is primary image for photonote
    note_tags, -- note tags; list joined by '|';  note: '||' if no tags
    blog_id TEXT,  -- link to blog entry, see table flickr_blog
    entry_updated TEXT, -- ISO8601 date; date db record got last updated / verified
    date_verified TEXT, -- ISO8601 date - date image has been checked on flickr
    photo_id TEXT NOT NULL,  -- id of photo page on flickr
    secret_id TEXT,  -- if known
    size_suffix TEXT,  -- if known
    photo_taken TEXT,  -- ISO8601 date  (value from photo_uploaded if not known)
    photo_uploaded TEXT,  -- ISO8601 date
    is_gone BOOLEAN DEFAULT FALSE,  -- image unavailable / removed (Flickr 404)
    PRIMARY KEY (image_key, guid_note)
);

CREATE INDEX IF NOT EXISTS idx_key
  ON flickr_image(image_key);
  
CREATE INDEX IF NOT EXISTS idx_image_blog
  ON flickr_image(blog_id);
"""

class PhotoNotesDB:

    def __init__(self, dbpath, reset=False):
        self.wrapped_store = SqliteStorage(dbpath)
        if reset:
            self.reduce_db()
        self.extend_db()

    @property
    def store(self) -> "SqliteStorage":
        return self.wrapped_store

    @property
    def flickrblogs(self) -> "FlickrBlogStorage":
        return FlickrBlogStorage(self.wrapped_store.db)

    @property
    def flickrimages(self) -> "FlickrPhotoStorage":
        return FlickrImageStorage(self.wrapped_store.db)

    def reduce_db(self):
        """ remove tables added """
        with self.wrapped_store.db as con:
            con.execute("BEGIN TRANSACTION;")
            con.execute("DROP TABLE IF EXISTS flickr_image;")
            con.execute("DROP TABLE IF EXISTS flickr_blog;")
            con.execute("COMMIT TRANSACTION;")

    def extend_db(self):
        """ add tables to exixting database - if not already there """
        with self.wrapped_store.db as con:
            try:
                con.execute("SELECT * FROM flickr_image WHERE image_key=NULL")
            except sqlite3.OperationalError as err:
                if "no such table: " not in str(err):
                    raise RuntimeError(f"failed to access flickr_image - {err!r}")
                logger.info("table flickr_blog does not yet exist, need to create first")
            else:
                return
            con.executescript(DB_SCHEMA_PN)
            con.commit()
        return


class FlickrBlogStorage(SqliteStorage):
    """ wraps CRUD operations on flickr_blog """

    def _create_blog(self, row):
        """ factory method to create FlickrBlog from SQLite row """
        blog = FlickrPhotoBlog(row["blog_id"], row["guid_note"])
        blog.is_gone = row["is_gone"]
        blog.last_upload = FlickrDate(row["last_upload"])
        blog.favorite = row["favorite"]
        blog.image_count = row["image_count"]
        blog.entry_updated = FlickrDate(row["entry_updated"])
        blog.verified = FlickrDate(row["verified"])
        return blog

    def lookup_blog_by_note(self, guid_note):
        with self.db as con:
            cur = con.execute(
                "SELECT * FROM flickr_blog WHERE guid_note=?",
                (guid_note,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Flickr blog not found for photo note guid={guid_note}")

            blog = self._create_blog(row)
            return blog

    def lookup_blog_by_id(self, blog_id):
        with self.db as con:
            cur = con.execute(
                "SELECT * FROM flickr_blog WHERE blog_id=?",
                (blog_id,)
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Flickr blog not found for blog id={blog_id}")

            blog = self._create_blog(row)
            return blog


class FlickrImageStorage(SqliteStorage):
    """ wraps CRUD operations on flickr_image """
    # note that 'FlickrImage' is used symonymously for photo-note / PhotoNote
    # we actually have a description of a Flickr image in an Evernote note identified
    # by this object - naming should be updated / improved (FUTURE)

    def _load_photo_note(self, row):
        """ factory method to create FlickrPhotoNote from SQLite row """
        image = FlickrPhotoNote(row["image_key"], row["guid_note"])

        image.is_primary = row["is_primary"]
        image.note_tags = row["note_tags"]
        image.blog_id = row["blog_id"]
        image.entry_updated = FlickrDate(row["entry_updated"])
        image.date_verified = FlickrDate(row["date_verified"])
        image.photo_id = row["photo_id"]
        image.secret_id = row["secret_id"]
        image.size_suffix = row["size_suffix"]
        image.photo_taken = FlickrDate(row["photo_taken"])
        image.photo_uploaded = FlickrDate(row["photo_uploaded"])
        image.is_gone = row["is_gone"]
        return image

    def count_images(self, filter: str = ""):
        with self.db as con:
            query = "SELECT COUNT(*) FROM flickr_image WHERE "
            if filter:
                query += filter
            else:
                query += "1=1"
            cur = con.execute(query)
            return int(cur.fetchone()[0])

    def lookup_by_note(self, guid_note):
        with self.db as con:
            cur = con.execute(
                "SELECT * FROM flickr_image WHERE guid_note=?",
                (guid_note,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Flickr image not found for photo note guid={guid_note}")

            image = self._load_photo_note(row)
            return image

    def lookup_image(self, image_key, is_primary=True):
        """ lookup note for Flickr """
        with self.db as con:
            query = "SELECT * FROM flickr_image WHERE image_key=?"
            if is_primary is not None:
                query += " AND is_primary=1"
                query += " ORDER BY photo_uploaded DESC"
            else:
                query += " ORDER BY is_primary DESC, photo_uploaded DESC"
            cur = con.execute(query, (image_key, ),)
            rows = cur.fetchall()
            if len(rows) == 0:
                raise PhotoNoteNotFound(f"Photo-note not found for image key={image_key}")
            else:
                photo_notes = [self._load_photo_note(row) for row in rows]
                return photo_notes


    def lookup_primary(self, image_key: str, guid_note: str) -> FlickrPhotoNote:
        """ lookup primary Flickr image for given note """
        with self.db as con:
            cur = con.execute(
                "SELECT * FROM flickr_image WHERE image_key=? AND guid_note=? AND is_primary=1",
                (image_key, guid_note),
            )
            # note that image_key is primary key, so expect one row or nothing
            row = cur.fetchone()
            if not row:
                raise PhotoNoteNotFound(f"Photo-note not found for image key={image_key}")
            else:
                photo_note = self._load_photo_note(row)
                return photo_note

    def update_image(self, photonote, flickr_link, is_primary, log_changes=True):
        """ create or update image in database """
        updated_before = photonote.entry_updated
        values = {
            'entry_updated': FlickrDate.today().serialize(),
            'is_primary': is_primary,
            'image_key': flickr_link['image_key'],
            'photo_id': flickr_link['photo_id'],
            'blog_id': flickr_link['blog_id'],
            'guid_note': photonote.guid_note,
            'note_tags': photonote.note_tags,
            'date_verified': photonote.date_verified.serialize(),
            # info from Flickr we currently do not yet have - FUTURE addition
            # 'secret_id',
            # 'size_suffix',
            # 'photo_taken',
            # 'photo_uploaded',
            # 'is_gone'
        }
        dbkeys = list(values.keys())
        dbvalues = []
        for key in dbkeys:
            dbvalues.append(values[key])

        markers = ('?, '*len(dbkeys))[:-2]
        with self.db as con:
            con.execute(
                "replace into flickr_image(%s) values (%s)" % (', '.join(dbkeys), markers),
                tuple(dbvalues),
            )

        if log_changes:
            info = f"photo-note entry for image key={flickr_link['image_key']} "
            if is_primary:
                info += "[primary] "
            if updated_before:
                logger.info(f"updated {info} updated_before={updated_before}")
            else:
                logger.info(f"created {info}")


def lookup_note(store: SqliteStorage, note_guid: str) -> Optional[Note]:
    """ lookup Evernote note in evernote-backup db """
    # to download from Evernote directly, use:
    # .note_store.getNote(note_guid)
    # maybe future extension not to use evernote-backup sqllite db
    #
    # in evernote-backup, have no method to lookup note by guid_note
    # so directly access table notes
    # SQLite table notes having fields guid, title, notebook_guid, is_active, raw_note
    # see evernote-backup, note_storage.py
    #
    with store.db as con:
        cur = con.execute(
            "SELECT raw_note FROM notes WHERE guid=?",
            (note_guid, )
        )
        row = cur.fetchone()
        if row is None:
            raise NoteNotFound(f"Evernote note not found for guid={note_guid!r}")

        note = pickle.loads(lzma.decompress(row["raw_note"]))
        return note
