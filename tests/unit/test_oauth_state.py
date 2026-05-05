"""HMAC-signed OAuth state for CSRF prevention."""

import re
import time

import pytest

from src.auth.oauth_state import InvalidStateError, sign_state, verify_state

_SIGNING_KEY = "x" * 32


def test_round_trip_recovers_payload():
    state = sign_state({"manager_id": "uuid-1", "kind": "google"}, _SIGNING_KEY)
    payload = verify_state(state, _SIGNING_KEY)
    assert payload["manager_id"] == "uuid-1"
    assert payload["kind"] == "google"


def test_state_is_url_safe():
    """State is passed in URL query, must use only URL-safe chars."""
    state = sign_state({"manager_id": "uuid"}, _SIGNING_KEY)
    assert re.match(r"^[A-Za-z0-9_.-]+$", state), f"Got: {state}"


def test_tampered_state_rejected():
    """An attacker substituting body or tag with a different value must be rejected.

    Robust formulation: stitch the body of state-1 with the tag of state-2.
    The tag won't match the body's HMAC -> InvalidStateError. Avoids the trap
    of flipping the last base64url char (which has 2 unused bits and may decode
    to the same bytes, occasionally letting the test pass-through silently).
    """
    state = sign_state({"manager_id": "uuid-1"}, _SIGNING_KEY)
    other = sign_state({"manager_id": "uuid-other"}, _SIGNING_KEY)
    body = state.split(".", 1)[0]
    other_tag = other.split(".", 1)[1]
    tampered = f"{body}.{other_tag}"
    with pytest.raises(InvalidStateError):
        verify_state(tampered, _SIGNING_KEY)


def test_wrong_key_rejected():
    state = sign_state({"manager_id": "uuid-1"}, _SIGNING_KEY)
    with pytest.raises(InvalidStateError):
        verify_state(state, "y" * 32)


def test_expired_state_rejected():
    """States older than 10 minutes must be rejected."""
    # Mint a state with timestamp 11 minutes in the past.
    fake_now = time.time() - (11 * 60)
    state = sign_state(
        {"manager_id": "uuid-1"},
        _SIGNING_KEY,
        issued_at=fake_now,
    )
    with pytest.raises(InvalidStateError, match="expired"):
        verify_state(state, _SIGNING_KEY)


def test_state_within_ttl_accepted():
    """States issued in the last 10 minutes accepted."""
    fake_now = time.time() - (5 * 60)
    state = sign_state(
        {"manager_id": "uuid-1"},
        _SIGNING_KEY,
        issued_at=fake_now,
    )
    payload = verify_state(state, _SIGNING_KEY)
    assert payload["manager_id"] == "uuid-1"


def test_garbage_input_rejected_cleanly():
    with pytest.raises(InvalidStateError):
        verify_state("not-a-real-state", _SIGNING_KEY)
