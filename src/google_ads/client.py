"""Factory for the official google-ads SDK GoogleAdsClient.

Each call constructs a fresh client with the manager's decrypted refresh
token. Clients are NOT cached — the SDK keeps internal connections, and
caching across managers risks privilege confusion. The construction cost
is small.
"""

from typing import Any
from uuid import UUID

# Imported lazily inside the factory to keep this module unit-testable
# without the heavy google-ads SDK import.


def build_client(
    *,
    refresh_token: str,
    developer_token: str,
    client_id: str,
    client_secret: str,
    login_customer_id: str,
) -> Any:
    """Build a GoogleAdsClient ready to make API calls in the manager's name."""
    from google.ads.googleads.client import GoogleAdsClient

    config = {
        "developer_token": developer_token,
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "login_customer_id": login_customer_id,
        "use_proto_plus": True,
    }
    return GoogleAdsClient.load_from_dict(config)


class NoOAuthConnectionError(Exception):
    """Raised by build_client_for_manager when the manager has no active OAuth."""


async def build_client_for_manager(*, manager_id: UUID) -> Any:
    """Build a GoogleAdsClient using the active OAuth refresh token of the given manager.

    Raises NoOAuthConnectionError if the manager has no active connection.
    """
    from src.auth.tokens import (
        InvalidCiphertextError,
        decrypt_refresh_token,
        derive_master_key_from_settings,
    )
    from src.config import get_settings
    from src.db import connection
    from src.db.repositories import google_oauth_connections
    from src.google_ads.errors import to_friendly

    settings = get_settings()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        oc = await google_oauth_connections.get_active_for_manager(conn, manager_id)
    if oc is None:
        raise NoOAuthConnectionError(
            "Gestor nao tem conexao Google Ads ativa. Pede pra ele conectar via "
            "/oauth/google/start."
        )

    master_key = derive_master_key_from_settings(settings.aes_master_key)
    try:
        refresh_token = decrypt_refresh_token(oc.refresh_token_enc, master_key)
    except InvalidCiphertextError as e:
        # Token cifrado com uma AES master key antiga (migração GCP 2026-06-30
        # regenerou a chave). Converte na origem — este factory é chamado por
        # TODOS os executores FORA do wrap de to_friendly deles, então sem isto
        # o erro vazaria cru pro dispatcher e viraria "Erro interno" (F70).
        raise to_friendly(e) from e

    return build_client(
        refresh_token=refresh_token,
        developer_token=settings.google_ads_developer_token,
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        login_customer_id=settings.google_ads_login_customer_id,
    )
