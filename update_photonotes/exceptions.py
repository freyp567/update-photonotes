"""
custom exceptions for update-photonotes
"""


class FlickrImageNotFound(Exception):
    """ could not find Flickr image """


class NoteNotFound(Exception):
    """ note in / from Evernote not found """


class PhotoNoteNotFound(Exception):
    """ photo-note not found """


# candidate for cleanup - no duplicates allowed, currently
# class MultiplePhotoNotes(Exception):
#     """ found more than one photo-note for given search criterias """
#     notes_found = []
#
#     def __str__(self):
#         error_msg = str(self)
#         return error_msg
