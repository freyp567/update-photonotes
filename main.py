"""
update_photonotes
create and update personal photonotes in and from Evernote
"""

import os
import sys

import logging

if os.getenv('DEBUG') == '1':
    LOG_FORMAT = "%(asctime)-15s %(name)s %(levelname)-8s %(message)s"
    LOG_DATE_FORMAT = "%dT%H:%M:%S"
else:
    LOG_FORMAT = "%(levelname)-8s %(message)s"
    LOG_DATE_FORMAT = "%H:%M:%S"
LOGLEVEL = os.getenv("LOGLEVEL", logging.INFO)
logging.basicConfig(level=LOGLEVEL, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
logger = logging.getLogger('app.main')


# transition from argparse to click in progress
# for transition phase, we provide a stub to delegate to new main
if __name__ == '__main__':
    from update_photonotes.cli import main
    try:
        main()
    except Exception as err:
        logger.exception(f"update_photonotes failed - {err!r}")
        input("check errors, and press any key to continue ... ")
        sys.exit(2)
