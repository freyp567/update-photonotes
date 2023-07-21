"""
utilities for Evernote related stuff
"""

import datetime
from lxml import etree
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


def extract_enex_content(enex_path):
    assert enex_path.is_file(), f"missing enex path {enex_path}"
    enex_xml = etree.fromstring(enex_path.read_text(encoding='utf-8').encode('utf-8'))
    content = enex_xml.xpath(".//content")
    assert len(content) == 1, "missing content, not found"
    content_xml = etree.fromstring(content[0].text.strip().encode('utf-8'))
    # for better readability / to support manual examination, pretty-print XML
    content_pp = etree.tostring(content_xml, pretty_print=True).decode('utf-8')
    content_path = enex_path.with_suffix('.xml')
    content_path.write_text(content_pp, encoding='utf-8')
    return content_path