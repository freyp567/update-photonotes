"""
https://github.com/alexis-mignon/python-flickr-api/wiki/Flickr-API-Keys-and-Authentication
"""
from types import SimpleNamespace

import flickr_api
from update_photonotes import flickr_utils

import logging
LOGGER = logging.getLogger('list_site')


def authenticate_session(
        options: SimpleNamespace,
        permissions = 'read',
):
    # fetch credentials (Flickr API key and secret) from context / environment
    credentials = flickr_utils.get_credentials()
    auth = flickr_api.auth.AuthHandler(
        key = credentials["api_key"],
        secret = credentials["api_secret"],
    )
    LOGGER.info(f"requesting {permissions} permissions from Flickr")
    url = auth.get_authorization_url(permissions)
    print(f"authenticate using url: {url}")
    verifier = input("verifier code from authentication page")
    auth.set_verifier(verifier)
    # auth.secret
    # auth.key

    flickr_api.set_auth_handler(auth)

    auth_file = str(flickr_utils.get_auth_file())
    auth.save(auth_file, include_api_keys=True)
    LOGGER.info(f"Flicker session / credentials saved to {auth_file}")

    return