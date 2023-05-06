"""
utilities for Evernote related stuff
"""

import datetime
from evernote.edam.type.ttypes import Note
from evernote_backup import log_util

class Note2(Note):

    def __init__(self, note: Note):
        self.en_note = note

    def __str__(self) -> str:
        info = f'"{self.en_note.title}"'
        if not self.en_note.active:
            info = " DELETED"
        return info

    def __repr__(self) -> str:
        value = f'Note(title="{self.en_note.title}", guid={self.en_note.guid}'
        if not self.en_note.active:
            value += " DELETED"
        value += ')'
        return value

    def date_updated(self) -> datetime.date:
        value = datetime.datetime.fromtimestamp(self.en_note.updated / 1000.0).date()
        return value


def log_format_note(note):
    if isinstance(note, Note):
        return log_util.log_format_note(note)
    return str(note)


