"""
conversion utility functions (and classes)
"""
from typing import Optional

from evernote_backup.note_formatter import NoteFormatter


def get_note_content(content_body: Optional[str]) -> Optional[str]:
    if content_body is None:
        return content_body

    body = content_body.strip()

    # <?xml version="1.0" encoding="UTF-8"?>
    if body.startswith("<?xml") and body.find(">") != -1:
        content_start = body.find(">") + 1
        body = body[content_start:].strip()

    return body


# ##TODO verify do we need that?
#
# class NoteFormatterEx(NoteFormatter):
#     """ extended note formatter, providing access to note content """
#
#     def format_note(self, note: Note) -> str:
#         self._raw_elements = {}
#
#         note_skeleton = {
#             "note": {
#                 "title": note.title,
#                 "created": fmt_time(note.created),
#                 "updated": fmt_time(note.updated),
#                 "tag": note.tagNames,
#                 "note-attributes": None,
#                 "content": self._fmt_raw(fmt_content(note.content)),
#                 "resource": map(self._fmt_resource, note.resources or []),
#             }
#         }
#
#         if note.attributes:
#             note_skeleton["note"]["note-attributes"] = {
#                 "subject-date": fmt_time(note.attributes.subjectDate),
#                 "latitude": note.attributes.latitude,
#                 "longitude": note.attributes.longitude,
#                 "altitude": note.attributes.altitude,
#                 "author": note.attributes.author,
#                 "source": note.attributes.source,
#                 "source-url": note.attributes.sourceURL,
#                 "source-application": note.attributes.sourceApplication,
#                 "reminder-order": note.attributes.reminderOrder,
#                 "reminder-time": note.attributes.reminderTime,
#                 "reminder-done-time": note.attributes.reminderDoneTime,
#                 "place-name": note.attributes.placeName,
#                 "content-class": note.attributes.contentClass,
#             }
#
#         note_template = xmltodict.unparse(
#             note_skeleton,
#             pretty=True,
#             short_empty_elements=True,
#             full_document=False,
#             indent="  ",
#             depth=1,
#         )
#
#         # Remove empty tags
#         note_template = re.sub(r"^\s+<.*?/>\n", "", note_template, flags=re.M)
#
#         for r_uuid, r_body in self._raw_elements.items():
#             note_template = note_template.replace(r_uuid, r_body)
#
#         return str(note_template)
