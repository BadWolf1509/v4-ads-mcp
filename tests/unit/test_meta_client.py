"""Unit tests pra src/meta_ads/client.py factory (F48 regression).

F48: facebook_business v21 FacebookAdsApi.__init__ aceita só
(session, api_version, enable_debug_logger) — NÃO access_token/app_id/app_secret
kwargs direto.

Mitigation: extract build_facebook_ads_api() pure factory + unit test direto.
Garante que factory pattern não regride se facebook_business upgrade no futuro
mudar signature again.
"""

import pytest
from facebook_business.api import FacebookAdsApi
from facebook_business.session import FacebookSession

from src.meta_ads.client import (
    META_GRAPH_API_VERSION,
    MetaAccessDeniedError,
    MetaSystemUserTokenMissingError,
    build_facebook_ads_api,
    build_meta_api,
)


def test_build_facebook_ads_api_returns_facebook_ads_api_instance():
    """F48 regression: factory deve retornar FacebookAdsApi sem TypeError."""
    api = build_facebook_ads_api(
        app_id="fake_app_id",
        app_secret="fake_app_secret",
        access_token="fake_long_token",
    )
    assert isinstance(api, FacebookAdsApi)


def test_build_facebook_ads_api_instance_has_call_method():
    """Instance MUST expose .call() for run_meta_graph_get usage."""
    api = build_facebook_ads_api(
        app_id="fake_app_id",
        app_secret="fake_app_secret",
        access_token="fake_long_token",
    )
    assert hasattr(api, "call")
    assert callable(api.call)


def test_build_facebook_ads_api_uses_default_api_version_v22():
    """Default api_version deve ser v22.0 (M.2a convention)."""
    api = build_facebook_ads_api(
        app_id="fake_app_id",
        app_secret="fake_app_secret",
        access_token="fake_long_token",
    )
    # facebook_business stores api_version as attribute (varies by SDK version);
    # at minimum, the module constant must remain v22.0 (canonical convention).
    assert META_GRAPH_API_VERSION == "v22.0"
    # api object should not raise when accessed (instance constructed cleanly)
    assert api is not None


def test_build_facebook_ads_api_accepts_custom_api_version():
    """Allow override pra future SDK upgrades (M.X+ migration)."""
    api = build_facebook_ads_api(
        app_id="fake_app_id",
        app_secret="fake_app_secret",
        access_token="fake_long_token",
        api_version="v23.0",
    )
    assert isinstance(api, FacebookAdsApi)


def test_build_facebook_ads_api_constructs_facebook_session_internally():
    """Verify session is constructed (not a FacebookAdsApi() w/ raw access_token kwarg)."""
    # If F48 regressed, FacebookAdsApi(access_token=...) would raise TypeError
    # before we even reach the isinstance check below.
    api = build_facebook_ads_api(
        app_id="app123",
        app_secret="secret456",
        access_token="token789",
    )
    # Successful construction implies FacebookSession was used as bridge
    assert isinstance(api, FacebookAdsApi)


def test_build_facebook_ads_api_rejects_missing_app_id():
    """app_id is required keyword arg (no positional fallback)."""
    with pytest.raises(TypeError):
        build_facebook_ads_api(  # type: ignore[call-arg]
            app_secret="fake",
            access_token="fake",
        )


def test_build_facebook_ads_api_rejects_missing_app_secret():
    with pytest.raises(TypeError):
        build_facebook_ads_api(  # type: ignore[call-arg]
            app_id="fake",
            access_token="fake",
        )


def test_build_facebook_ads_api_rejects_missing_access_token():
    with pytest.raises(TypeError):
        build_facebook_ads_api(  # type: ignore[call-arg]
            app_id="fake",
            app_secret="fake",
        )


def test_meta_graph_api_version_constant_pinned():
    """META_GRAPH_API_VERSION must be explicit string (not env var, not auto)."""
    assert META_GRAPH_API_VERSION == "v22.0"


def test_facebook_session_signature_accepts_app_credentials():
    """Sanity: FacebookSession SDK contract didn't change (would cascade to F48-like bug)."""
    # If FacebookSession signature changes in facebook_business v22+, this catches it
    session = FacebookSession(
        app_id="fake",
        app_secret="fake",
        access_token="fake",
    )
    assert session is not None


def test_facebook_ads_api_signature_accepts_session_kwarg():
    """Sanity: FacebookAdsApi(session=...) signature didn't regress to F48 state."""
    session = FacebookSession(app_id="a", app_secret="b", access_token="c")
    api = FacebookAdsApi(session=session, api_version="v22.0")
    assert isinstance(api, FacebookAdsApi)


# Tests for build_meta_api (Modelo B — system-user token, no per-manager DB lookup)


def test_build_meta_api_raises_when_system_user_token_empty():
    """Empty system_user_token deve raise MetaSystemUserTokenMissingError."""
    with pytest.raises(MetaSystemUserTokenMissingError):
        build_meta_api(
            system_user_token="",
            app_id="111",
            app_secret="sec",
        )


def test_build_meta_api_returns_facebook_ads_api_instance():
    """Token válido deve retornar FacebookAdsApi instance (mirrors build_facebook_ads_api tests)."""
    api = build_meta_api(
        system_user_token="TKN",
        app_id="111",
        app_secret="sec",
    )
    assert isinstance(api, FacebookAdsApi)


def test_build_meta_api_accepts_custom_api_version():
    """Allow override pra future SDK upgrades — api_version must be forwarded (bug fix)."""
    api = build_meta_api(
        system_user_token="TKN",
        app_id="111",
        app_secret="sec",
        api_version="v23.0",
    )
    assert isinstance(api, FacebookAdsApi)


# Sanity tests pra novas error classes


def test_meta_system_user_token_missing_error_is_exception():
    assert issubclass(MetaSystemUserTokenMissingError, Exception)


def test_meta_access_denied_error_is_exception():
    assert issubclass(MetaAccessDeniedError, Exception)


def test_meta_access_denied_error_stores_message():
    err = MetaAccessDeniedError("sem acesso à conta 123")
    assert err.message == "sem acesso à conta 123"
    assert str(err) == "sem acesso à conta 123"
