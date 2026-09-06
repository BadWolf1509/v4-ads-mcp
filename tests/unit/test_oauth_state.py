"""HMAC-signed OAuth state for CSRF prevention."""

import re
import time

import pytest

from src.auth.oauth_state import InvalidStateError, StateAudience, sign_state, verify_state

_SIGNING_KEY = "x" * 32

# Audiência de trabalho destes testes. O que está sob teste aqui é o mecanismo
# (HMAC, URL-safety, TTL), não a audiência — então assinar e conferir com a
# MESMA audiência mantém cada teste falhando pelo motivo de sempre. A ordem de
# `verify_state` é HMAC → audiência → TTL: audiência divergente aqui abortaria
# antes do ramo sob teste e o `match="expired"` deixaria de morder.
_AUD: StateAudience = "google_oauth"

# Só a família `state`. `sign_state`/`verify_state` não aceitam mais `"panel"`:
# varrer as quatro aqui afirmaria como comportamento suportado justamente o
# cruzamento entre famílias que o tipo passou a proibir.
_AUDIENCIAS_DE_STATE: list[StateAudience] = ["google_oauth", "cli_invite", "meta_oauth"]


@pytest.mark.parametrize("aud", _AUDIENCIAS_DE_STATE)
def test_round_trip_recovers_payload(aud: StateAudience) -> None:
    state = sign_state({"manager_id": "uuid-1", "kind": "google"}, _SIGNING_KEY, aud=aud)
    payload = verify_state(state, _SIGNING_KEY, aud=aud)
    assert payload["manager_id"] == "uuid-1"
    assert payload["kind"] == "google"


def test_state_is_url_safe():
    """State is passed in URL query, must use only URL-safe chars."""
    state = sign_state({"manager_id": "uuid"}, _SIGNING_KEY, aud=_AUD)
    assert re.match(r"^[A-Za-z0-9_.-]+$", state), f"Got: {state}"


def test_tampered_state_rejected():
    """An attacker substituting body or tag with a different value must be rejected.

    Robust formulation: stitch the body of state-1 with the tag of state-2.
    The tag won't match the body's HMAC -> InvalidStateError. Avoids the trap
    of flipping the last base64url char (which has 2 unused bits and may decode
    to the same bytes, occasionally letting the test pass-through silently).
    """
    state = sign_state({"manager_id": "uuid-1"}, _SIGNING_KEY, aud=_AUD)
    other = sign_state({"manager_id": "uuid-other"}, _SIGNING_KEY, aud=_AUD)
    body = state.split(".", 1)[0]
    other_tag = other.split(".", 1)[1]
    tampered = f"{body}.{other_tag}"
    with pytest.raises(InvalidStateError):
        verify_state(tampered, _SIGNING_KEY, aud=_AUD)


def test_wrong_key_rejected():
    state = sign_state({"manager_id": "uuid-1"}, _SIGNING_KEY, aud=_AUD)
    with pytest.raises(InvalidStateError):
        verify_state(state, "y" * 32, aud=_AUD)


def test_expired_state_rejected():
    """States older than 10 minutes must be rejected."""
    # Mint a state with timestamp 11 minutes in the past.
    fake_now = time.time() - (11 * 60)
    state = sign_state(
        {"manager_id": "uuid-1"},
        _SIGNING_KEY,
        aud=_AUD,
        issued_at=fake_now,
    )
    with pytest.raises(InvalidStateError, match="expired"):
        verify_state(state, _SIGNING_KEY, aud=_AUD)


def test_state_within_ttl_accepted():
    """States issued in the last 10 minutes accepted."""
    fake_now = time.time() - (5 * 60)
    state = sign_state(
        {"manager_id": "uuid-1"},
        _SIGNING_KEY,
        aud=_AUD,
        issued_at=fake_now,
    )
    payload = verify_state(state, _SIGNING_KEY, aud=_AUD)
    assert payload["manager_id"] == "uuid-1"


def test_garbage_input_rejected_cleanly():
    with pytest.raises(InvalidStateError):
        verify_state("not-a-real-state", _SIGNING_KEY, aud=_AUD)
