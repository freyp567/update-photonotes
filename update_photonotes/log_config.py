import os
import logging

# TODO refactor, adapt for conventions used by evernote-backup

def setup_logging() -> None:
    if os.getenv('DEBUG') == '1':
        LOG_FORMAT = "%(asctime)-15s %(name)s %(levelname).1s - %(message)s"
        LOG_DATE_FORMAT = "%dT%H:%M:%S"
    else:
        LOG_FORMAT = "%(levelname).1s - %(message)s"
        LOG_DATE_FORMAT = "%H:%M:%S"
    LOGLEVEL = os.getenv("LOGLEVEL", logging.INFO)
    logging.basicConfig(
        level=LOGLEVEL,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
    )

