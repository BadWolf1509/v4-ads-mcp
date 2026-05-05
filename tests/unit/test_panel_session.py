"""Panel session cookie tests."""

import time

import pytest

from src.auth.panel_session import (
    InvalidPanelSessionError,
    PanelSession,
    sign_panel_session,
    verify_panel_session,
)

_SIGNING_KEY = "x" * 32


def test_round_trip_recovers_payload():
    cookie = sign_panel_session(
        manager_id="abc123",
        email="t@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    s = verify_panel_session(cookie, _SIGNING_KEY)
    assert isinstance(s, PanelSession)
    assert s.manager_id == "abc123"
    assert s.email == "t@v4company.com"


def test_tampered_cookie_rejected():
    """Stitch the body of cookie-1 with the tag of cookie-2 — guaranteed mismatch.

    Avoids the base64url boundary trap: flipping the last char of an HMAC tag
    can decode to the same bytes (last char encodes only 4 of its 6 bits when
    the tag is 32 bytes / 256 bits), occasionally letting the test pass-through.
    """
    cookie = sign_panel_session(
        manager_id="abc",
        email="t@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    other = sign_panel_session(
        manager_id="other",
        email="o@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    body = cookie.split(".", 1)[0]
    other_tag = other.split(".", 1)[1]
    tampered = f"{body}.{other_tag}"
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(tampered, _SIGNING_KEY)


def test_wrong_key_rejected():
    cookie = sign_panel_session(
        manager_id="abc",
        email="t@v4company.com",
        signing_key=_SIGNING_KEY,
    )
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(cookie, "y" * 32)


def test_expired_cookie_rejected():
    fake_now = time.time() - (25 * 60 * 60)  # 25 hours ago
    cookie = sign_panel_session(
        manager_id="abc",
        email="t@v4company.com",
        signing_key=_SIGNING_KEY,
        issued_at=fake_now,
    )
    with pytest.raises(InvalidPanelSessionError, match="expired"):
        verify_panel_session(cookie, _SIGNING_KEY)


def test_within_ttl_accepted():
    fake_now = time.time() - (12 * 60 * 60)  # 12 hours ago
    cookie = sign_panel_session(
        manager_id="abc",
        email="t@v4company.com",
        signing_key=_SIGNING_KEY,
        issued_at=fake_now,
    )
    s = verify_panel_session(cookie, _SIGNING_KEY)
    assert s.manager_id == "abc"


def test_garbage_input_rejected():
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session("not-a-real-cookie", _SIGNING_KEY)
