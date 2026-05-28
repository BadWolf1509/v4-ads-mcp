"""Factory for facebook_business FacebookAdsApi per-manager.

Different from Google SDK: Meta uses GLOBAL state (FacebookAdsApi.set_default_api)
by default — dangerous in async multi-manager. Convention: always construct
FacebookAdsApi(...) instance directly (NOT .init()) and pass api= explicit
in every SDK call site (M.3+ mutates).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# Meta Graph API version used across all Meta SDK call sites.
META_GRAPH_API_VERSION = "v22.0"


class NoMetaConnectionError(Exception):
    """Raised when manager has no active Meta OAuth connection."""


class MetaTokenExpiredError(Exception):
    """Raised when access_token expired (Meta has no refresh; user must reconnect)."""


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

    Extracted from build_meta_api_for_manager pra testing isolation (F48 regression):
    facebook_business v21 FacebookAdsApi.__init__ aceita (session, api_version,
    enable_debug_logger) — NÃO access_token/app_id/app_secret kwargs direto.
    Mirror what FacebookAdsApi.init() does internamente mas mantém convention
    NÃO usar global state.

    Args:
        app_id: Meta App ID (config)
        app_secret: Meta App Secret (config, signed-request validation also uses)
        access_token: per-user OAuth long-lived token (60d expiry)
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

    Unlike build_meta_api_for_manager, no per-manager DB lookup and no expiry
    check (system-user tokens don't expire). Raises if the secret is empty.
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
    )


async def build_meta_api_for_manager(*, manager_id: UUID) -> Any:
    """Decrypt access_token + return FacebookAdsApi instance.

    Raises:
        NoMetaConnectionError: manager hasn't connected Meta yet
        MetaTokenExpiredError: token expired (60d natural expiry)
    """
    from src.auth.tokens import decrypt_refresh_token, derive_master_key_from_settings
    from src.config import get_settings
    from src.db import connection
    from src.db.repositories import meta_oauth_connections

    settings = get_settings()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, manager_id)
    if oc is None:
        raise NoMetaConnectionError(
            "Gestor não tem conexão Meta Ads ativa. Acesse o painel admin → 'Conectar Meta'."
        )
    if oc.token_expires_at <= datetime.now(UTC):
        raise MetaTokenExpiredError("Sua conexão Meta expirou. Reconecte via painel admin.")

    master_key = derive_master_key_from_settings(settings.aes_master_key)
    access_token = decrypt_refresh_token(oc.access_token_enc, master_key)

    return build_facebook_ads_api(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        access_token=access_token,
    )
