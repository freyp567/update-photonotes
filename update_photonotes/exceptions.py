"""
custom exceptions for update-photonotes
"""

class FlickrImageNotFound(Exception):
    """ could not find Flickr image in photonotes db """

class NoteNotFound(Exception):
    """ Evernote note not found """
