"""
command line handling for update-photonotes CLI app

should we make init-db and sync transparently available through update-photonotes?
we could provide a backup command to handle this
e.g. update-photonotes backup sync
"""
import logging
import os
import sys
import traceback
from types import SimpleNamespace
from typing import Optional

import click
from click_option_group import MutuallyExclusiveOptionGroup, optgroup


# extending evernote-backup
from evernote_backup.cli_app_util import ProgramTerminatedError
from evernote.edam.error.ttypes import EDAMErrorCode, EDAMSystemException
from evernote_backup.log_util import get_time_txt, init_logging, init_logging_format
from evernote_backup.cli_app_click_util import (
    DIR_ONLY,
    FILE_ONLY,
    NaturalOrderGroup,
    group_options,
)

from update_photonotes.version import __version__
from update_photonotes.log_config import setup_logging

from . import utils
from . import cli_app

setup_logging()
logger = logging.getLogger('updater')

# limit number of images that are walked to to avoid exceeding limit of 3600 api calls per hour
MAX_PHOtO_POS = 5000

@click.group(cls=NaturalOrderGroup)
@optgroup.group("Verbosity", cls=MutuallyExclusiveOptionGroup)  # type: ignore
@optgroup.option(  # type: ignore
    "--quiet",
    "-q",
    is_flag=True,
    help="Quiet mode, output only critical errors.",
)
@optgroup.option(  # type: ignore
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose mode, output debug information.",
)
@click.version_option(__version__)
def updater(quiet:bool, verbose:bool) -> None:
    """
    Update photo notes in / from Evernote

    \b
    builds upon evernote-backup, see detailed description there

    """

    init_logging()
    init_logging_format()

    if quiet:
        logger.setLevel(logging.ERROR)
    elif verbose:
        logger.setLevel(logging.DEBUG)
    # add option veriy quite / -vv to show only CRITICAL errors - when needed
    else:
        logger.setLevel(logging.INFO)


@updater.command(
    help="""Reset Photonotes db"""
)
def reset_db():
    cli_app.reset_db()


@updater.command(
    help="""Update Photonotes db from Evernote notes in backup db
    
    e.g. 
    update-db --notebook=Bilder_FlickrImages --limit=1000000 --skip=1000
    
    """
)
@click.option(
    '--notebook',
    required=True,
)
@click.option(
    '--tag-name',
    required=False,
)
@click.option(
    '--note-title',
    required=False,
)
@click.option(
    '--limit',
    default=10000,
    type=click.IntRange(1),
    show_default=True,
    help="limit number of notes to update"
)
@click.option(
    '--skip',
    default=0,
    type=click.IntRange(0),
    show_default=False,
    help="Number of notes to skip for update - to restart update at a specific note position"
)
def update_db(
        notebook: str,
        limit: int,
        skip: int = 0,
        tag_name: Optional[str] = None,
        note_title: str = None
) -> None:
    """ Create photonote either from url passed or the one passed on clipboard """
    options = SimpleNamespace()
    options.tag_name = tag_name
    options.export_dir = None
    options.limit = limit
    options.skip = skip
    options.debug = os.getenv("DEBUG") == '1'
    options.warn_href_http = False  # True to output warning if http (non https) links found
    options.note_title = note_title

    cli_app.update_db(
        options,
        notebook,
    )



@updater.command(
    help="""allow authenticated access
    the credentials will be saved to a session file and can be used
    transparently by the other actions
    
    e.g. 
    authenticate --permissions=read
    
    note that this is an *iteractive* process, it will require to open the web url output
    in an external webbrowser, and the user needs to confirm to grant the desired access
    to the update-photonotes application, then copying the created verification code back
    to proceed. 
    
    A session file will be written that afterwards can be detected and used by other actions.
    
    """
)
@click.option(
    '--permissions',
    required=True,
)

def authenticate(
        permissions: str,
) -> None:
    """ Create photonote either from url passed or the one passed on clipboard """
    options = SimpleNamespace()
    options.debug = os.getenv("DEBUG") == '1'

    cli_app.authenticate(
        options,
        permissions,
    )


@updater.command(
    help="""Create photonote from Flickr URL to update Evernote
    
    Expects a Flickr URL to create note from (blog or photo)
    If parameter is omitted, then the URL will be taken from the current Clipboard content.
    """
)
@click.argument(
    'flickr_url',
    required=False,
)
@click.option(
    '--non-interactive', is_flag=True
)
@click.option(
    '--max-pos',
    type=int,
    default=MAX_PHOtO_POS,
    help="for image lookup, limit number of flickr images to scan before giving up"
)
def create_note(
        flickr_url: Optional[str] = None,
        non_interactive: bool = False,
        max_pos: int = 10000,
) -> None:
    """ Create photonote either from url passed or the one passed on clipboard """
    options = SimpleNamespace()
    options.max_pos = max_pos
    # note: using authenticated session influences visibility (e.g. of Albums), so use by default
    options.use_auth_session = True  # use authentication session if available
    options.xml = False  # do not dump .xml by default - only in case of error
    try:
        cli_app.create_note(
            options,
            flickr_url,
        )
    except BaseException as err:
        logger.exception(f"failed to run create-note - {err!r}")
        if not non_interactive:
            input("Note creation failed, see log messages - press any key to terminate")
        raise err


def main() -> None:
    try:
        utils.load_dotenv()
        updater()
    except ProgramTerminatedError as e:
        logger.critical(e)
        sys.exit(2)
    except EDAMSystemException as e:
        if e.errorCode != EDAMErrorCode.RATE_LIMIT_REACHED:
            logger.critical(traceback.format_exc())
            sys.exit(3)

        time_left = get_time_txt(e.rateLimitDuration)

        logger.critical(f"Rate limit reached. Restart program in {time_left}.")
        sys.exit(4)
    except Exception as err:
        logger.exception("updater failed - {err!r}")
        sys.exit(1)
