"""Factory for the official google-ads SDK GoogleAdsClient.

Each call constructs a fresh client with the manager's decrypted refresh
token. Clients are NOT cached — the SDK keeps internal connections, and
caching across managers risks privilege confusion. The construction cost
is small.
"""

from typing import Any

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
