"""
update_photonotes
create and update personal photonotes in and from Evernote
"""

import os
import sys
import argparse
from pathlib import Path
import pyclip

from update_photonotes.database import PhotoNotesDB
#from authenticate import authenticate

#from list_site import SiteLister



import logging
if os.getenv('DEBUG') == '1':
    LOG_FORMAT = "%(asctime)-15s %(name)s %(levelname)-8s %(message)s"
    LOG_DATE_FORMAT = "%dT%H:%M:%S"
else:
    LOG_FORMAT = "%(levelname)-8s %(message)s"
    LOG_DATE_FORMAT = "%H:%M:%S"
LOGLEVEL = os.getenv("LOGLEVEL", logging.INFO)
logging.basicConfig(level=LOGLEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
LOGGER = logging.getLogger('updater.main')

#
# def getargs(args):
#     parser = argparse.ArgumentParser(
#         prog='update_photonotes',
#         description='Update personal notes from/in Evernote for flickr images',
#         epilog='.')
#     parser.add_argument('action', type=str, nargs='?', default='+')
#     parser.add_argument('param', type=str, nargs='?', default=None)
#     parser.add_argument('--notebook')
#     parser.add_argument('--dbpath', type=Path, default=Path().cwd())
#     parser.add_argument('--target_dir', type=Path, default=None)
#     parser.add_argument('--limit', type=int, default=100)
#     parser.add_argument('--warn-http', dest="warn_href_http", action='store_true')
#     parser.add_argument('--requests_cache', action='store_true')
#     parser.add_argument('--debug', action='store_true')
#     parser.add_argument('--xml', action='store_true')
#     parser.add_argument('--skip', type=int, default=0)
#     return parser.parse_args()
#
#
# def text_from_clipboard():
#     cb_data = pyclip.paste()
#     text = cb_data.decode('latin-1')
#     return text
#
#
# def truncate_db(dbpath):
#     try:
#         LOGGER.info(f"truncating photo notes in {dbpath}")
#         notes_db = PhotoNotesDB(dbpath, truncate=True)
#         LOGGER.info(f"photo notes runcated")
#     except Exception as err:
#         LOGGER.exception("failed to truncte {dbpath}")
#
#
# def main(args):
#     LOGGER.debug('starting update_personal_photo9notes')
#     args = getargs(args)
#     dbpath = args.dbpath.resolve()
#     if dbpath.is_dir():
#         dbpath /= "en_backup.db"
#     assert dbpath.is_file(), f"missing .db on path {dbpath}"
#     args.dbpath = dbpath
#     LOGGER.info(f"using backup db from {dbpath}")
#     target_dir = args.target_dir
#     if target_dir is not None:
#         target_dir = target_dir.resolve()
#         assert target_dir.is_dir(), f"missing target directory {target_dir}"
#         args.target_dir = target_dir
#
#     if os.getenv('DEBUG') == '1':
#         args.debug = True
#
#     action = args.action
#     if action == 'truncate':
#         truncate_db(dbpath)
#         return
#
#     notes_db = PhotoNotesDB(dbpath)
#     if action == '?':
#         action = input('Enter Flickr URL to create note for:')
#         action = action.strip()
#     elif action == '+':
#         action = text_from_clipboard()
#     elif action == '*':
#         assert False, "TODO detrmine URL of currently active browser window"
#
#     if action == 'authenticate':
#         permissions = args.param
#         ok = authenticate(permissions)
#     elif action == 'update':
#         ok = NotesUpdater(notes_db, target_dir, args).update()
#     elif action == 'list':
#         url = args.param
#         ok = SiteLister(notes_db, target_dir, args).list_site(url)
#     elif "/people/" in action:
#         ok = BlogCreator(notes_db, args, target_dir).create_note(action)
#     elif "/photos/" in action:
#         url = action
#         ok = NoteCreator(notes_db, target_dir, args).create_note(url)
#     else:
#         raise RuntimeError(f"unrecognized href or action: {action!r}")
#
#     if ok is not False:
#         LOGGER.info('update_photonotes completed.')
#     else:
#         # allow script to handle error
#         sys.exit(1)
#     return
#
#
# if __name__ == '__main__':
#     try:
#         main(sys.argv)
#     except Exception as err:
#         LOGGER.exception(f"update_photonotes failed - {err!r}")
#         input("check errors, and press any key to continue ... ")
#         sys.exit(2)

# transition from argparse to click in progress
# for transition phase, we provide a stub to delegate to new main
if __name__ == '__main__':
    from update_photonotes.cli import main
    try:
        main()
    except Exception as err:
        LOGGER.exception(f"update_photonotes failed - {err!r}")
        input("check errors, and press any key to continue ... ")
        sys.exit(2)
