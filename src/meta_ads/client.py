"""Factory for facebook_business FacebookAdsApi.

Different from Google SDK: Meta uses GLOBAL state (FacebookAdsApi.set_default_api)
by default — dangerous in async multi-manager. Convention: always construct
FacebookAdsApi(...) instance directly (NOT .init()) and pass api= explicit
in every SDK call site (M.3+ mutates).
"""

from typing import Any

# Meta Graph API version used across all Meta SDK call sites.
META_GRAPH_API_VERSION = "v22.0"


class MetaSystemUserTokenMissingError(Exception):
    """Raised when the shared system-user token secret isn't configured."""


class MetaAccessDeniedError(Exception):
    """Raised when a manager has no grant for the requested Meta ad account."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def build_facebook_ads_api(
    *,
    app_id: str,
    app_secret: str,
    access_token: str,
    api_version: str = META_GRAPH_API_VERSION,
) -> Any:
    """Pure factory — construct FacebookSession + FacebookAdsApi sem IO.

    F48: facebook_business v21 FacebookAdsApi.__init__ aceita (session, api_version,
    enable_debug_logger) — NÃO access_token/app_id/app_secret kwargs direto.
    Mirror what FacebookAdsApi.init() does internamente mas mantém convention
    NÃO usar global state.

    Args:
        app_id: Meta App ID (config)
        app_secret: Meta App Secret (config, signed-request validation also uses)
        access_token: system-user token or per-user long-lived token
        api_version: Graph API version (default v22.0)

    Returns:
        FacebookAdsApi instance ready pra .call() em call sites
    """
    from facebook_business.api import FacebookAdsApi  # noqa: PLC0415
    from facebook_business.session import FacebookSession  # noqa: PLC0415

    session = FacebookSession(app_id=app_id, app_secret=app_secret, access_token=access_token)
    return FacebookAdsApi(session=session, api_version=api_version)


def build_meta_api(
    *,
    system_user_token: str,
    app_id: str,
    app_secret: str,
    api_version: str = META_GRAPH_API_VERSION,
) -> Any:
    """Build a FacebookAdsApi from the shared system-user token (Modelo B).

    System-user tokens don't expire (unlike per-manager OAuth tokens).
    Raises MetaSystemUserTokenMissingError if the secret is empty.
    """
    if not system_user_token:
        raise MetaSystemUserTokenMissingError(
            "Token do system user Meta não configurado. "
            "O admin precisa subir o secret meta-system-user-token."
        )
    return build_facebook_ads_api(
        app_id=app_id,
        app_secret=app_secret,
        access_token=system_user_token,
        api_version=api_version,
    )
