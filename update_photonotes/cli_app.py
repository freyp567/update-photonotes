"""
Implements Update mechanism to create and keep personal photonotes in sync between Evernote and Flickr
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pyclip

from .database import PhotoNotesDB
from .authenticate import authenticate_session
from .updater import NotesUpdater
from .note_creator import NoteCreator
from .blog_creator import BlogCreator

import logging
logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    """ get path to evernote-backup created / maintained sqlite database """
    db_path = Path(os.environ["DB_PATH"])
    if db_path.is_dir():
        db_path /= "en_backup.db"
    if not db_path.is_file():
        raise RuntimeError(f"missing evernote-backup database on path {db_path}")
    return db_path


def get_notes_db(db_path: Path) -> PhotoNotesDB:
    logger.info(f"using evernote-backup db from {db_path}")
    return PhotoNotesDB(db_path)


def text_from_clipboard():
    cb_data = pyclip.paste()
    text = cb_data.decode('latin-1')  # TODO default encoding?
    return text


def authenticate(
        options: SimpleNamespace,
        permissions: str,
) -> None:
    """ authenticate user for requested permissions """
    authenticate_session(options, permissions)


def update_db(
        options: SimpleNamespace,
        notebook: str,
) -> None:
    """ update photonotes db from evernote-backup created db """
    db_path = get_db_path()
    options.db_path = db_path
    notes_db = get_notes_db(db_path)

    ok = NotesUpdater(notes_db, options).update(notebook)
    if ok is True:
        logger.info("update_db completed.")
    else:
        # allow caller of script to handle error
        sys.exit(1)


def create_note(options: SimpleNamespace, flickr_url: Optional[str] = None, ) -> None:
    # to pass configuration dependent options to create handler
    db_path = get_db_path()
    options.db_path = db_path
    notes_db = get_notes_db(db_path)

    url = flickr_url
    if not url:
        url = text_from_clipboard()
        logger.debug(f"use Flickr URL from clipboard: {url!r}")
        if 'https://' not in url:
            raise ValueError(f"expect Flickr URL to be on clipboard")
    elif url == '?':
        # this option was used BEFORE fetching URL from clipboard - what is easier for practical usecases
        # so keep option to ask for URL only for special cases where user does want to explicitly enter URL
        url = input("Enter Flickr URL to create note for:")
        url = url.strip()
        logger.debug(f"use Flickr URL from input {url!r}")
    else:
        logger.debug(f"use Flickr URL specified on commandline: {url!r}")

    if "/people/" in url:
        logger.info(f"creating photonote for user's blog from URL {url!r}")
        ok = BlogCreator(notes_db, options).create_note(url)
    elif "/photos/" in url:
        logger.info(f"creating photonote for photo from URL {url!r}")
        ok = NoteCreator(notes_db, options).create_note(url)
    else:
        raise ValueError(f"unrecognized or unsupported Flickr URL: {url!r}")

    if ok is True:
        logger.info("create_note completed.")
    else:
        # allow caller of script to handle error
        sys.exit(1)
