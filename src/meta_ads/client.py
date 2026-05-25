"""Factory for facebook_business FacebookAdsApi per-manager.

Different from Google SDK: Meta uses GLOBAL state (FacebookAdsApi.set_default_api)
by default — dangerous in async multi-manager. Convention: always construct
FacebookAdsApi(...) instance directly (NOT .init()) and pass api= explicit
in every SDK call site (M.3+ mutates).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID


class NoMetaConnectionError(Exception):
    """Raised when manager has no active Meta OAuth connection."""


class MetaTokenExpiredError(Exception):
    """Raised when access_token expired (Meta has no refresh; user must reconnect)."""


async def build_meta_api_for_manager(*, manager_id: UUID) -> Any:
    """Decrypt access_token + return FacebookAdsApi instance.

    Raises:
        NoMetaConnectionError: manager hasn't connected Meta yet
        MetaTokenExpiredError: token expired (60d natural expiry)
    """
    from facebook_business.api import FacebookAdsApi  # noqa: PLC0415
    from facebook_business.session import FacebookSession  # noqa: PLC0415

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

    # facebook_business v21: FacebookAdsApi.__init__ accepts (session, api_version,
    # enable_debug_logger) — NOT access_token/app_id/app_secret kwargs directly.
    # Construct FacebookSession first, then pass to FacebookAdsApi. This pattern
    # mirrors what FacebookAdsApi.init() does internally but avoids global state.
    session = FacebookSession(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        access_token=access_token,
    )
    return FacebookAdsApi(session=session, api_version="v22.0")
