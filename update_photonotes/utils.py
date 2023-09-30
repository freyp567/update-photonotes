"""
collection of utility functions
"""

import os
import re
from pathlib import Path

import dotenv
from lxml import etree

import logging
logger = logging.getLogger('utils')


def load_dotenv():
    """ get credentials, load from .env file """
    debug = os.getenv("DEBUG") == "1"
    # load_dotenv, verbose is True: output warning if .env is missing
    # but as user may also use project env or user/system level environment variables
    # do not show warning by default
    #
    # does not override existing environment variables
    # so while debugging, you may specify alternate values in your project configuration
    #
    # assumes .env to be in location looked up by .find_dotenv
    # see https://github.com/theskumar/python-dotenv
    #
    if not dotenv.load_dotenv(
            verbose=debug,
            dotenv_path=os.getenv("DOTENV_PATH"),
    ):
        raise RuntimeError("failed to load .env file")
    if "DB_PATH" not in os.environ:
        raise RuntimeError("missing DB_PATH= in .env or your environment")
    return


def quote_xml(value):
    """ quote characters in value for XML """
    if not value:
        return value
    xml = value
    if '&' in xml:
        assert '&#' not in xml
        xml = xml.replace('&', '&amp;')
    xml = xml.replace('<', '&lt;')
    xml = xml.replace('>', '&gt;')
    return xml


def get_script_dir():
    script_dir = Path(globals().get("__file__", "./_")).absolute().parent
    return script_dir


def get_template_dir():
    script_parent = get_script_dir().parent
    template_dir = script_parent / "templates"
    assert template_dir.is_dir(), f"missing template dir: {template_dir}"
    return template_dir


def get_log_dir():
    script_parent = get_script_dir().parent
    log_dir = script_parent / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def get_safe_property(obj, name, default=None):
    if name in obj.__dict__ or not obj.loaded:
        missing = object()
        value = getattr(obj, name, missing)
        if value is not missing:
            return value

    logger.debug(f"missing property {name!r}")
    return default


def from_template(template, params, encoding='utf-8'):
    data = template.read_text(encoding=encoding)
    for key in params:
        data = data.replace(f'${{{key}}}', str(params[key]))

    match = re.search(r'\${(.*?)}', data)
    if match:
        logger.warning("detected placeholders in template not replaced: %s" % match.group(1))
    return data


def validate_content(content: str) -> tuple:
    """ validate and prettyprint content to ensure evernote can import it """
    try:
        xml = etree.fromstring(content)
        has_error = ""
    except Exception as err:
        logger.error(f"failed to load content as well-formed XML - {err!r}")
        has_error = str(err)
    return content, has_error


def drop_empty_tags(tree, tag_name):
    """ drop elements (e.g div's) without content """
    for child in tree.xpath(f"//{tag_name}"):
        if not child.text:
            child.getparent().remove(child)


def get_mimetype(img_suffix: str) -> str:
    if img_suffix in ('.jpg', '.jpeg',):
        return "image/jpeg"
    elif img_suffix in ('.png',):
        return "image/png"
    else:  # what else?
        logger.warning(f"detected unknown image suffix {img_suffix}")
        return f"image/{img_suffix}"


def get_int_value(value: str) -> int | None:
    if '.' in value:
        # thousands separators, decoracted for better readability
        value = value.replace('.', '')
    try:
        return int(value)
    except ValueError:
        return None