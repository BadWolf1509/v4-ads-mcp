"""HMAC-signed, time-bounded OAuth state token.

Format:  base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload always includes 'iat' (issued-at unix seconds). Verify checks
HMAC tag and rejects if iat is older than STATE_TTL_SECONDS.

Used in /oauth/google/start to encode {manager_id, kind} so the callback
can recover them WITHOUT a server-side session lookup. Stateless across
Cloud Run instances. Defends against CSRF (attacker can't mint a valid
HMAC) and replay (TTL).
"""

import base64
import binascii
import hmac
import json
import time
from hashlib import sha256
from typing import Any

STATE_TTL_SECONDS = 10 * 60  # 10 minutes


class InvalidStateError(Exception):
    """Raised when state is tampered, wrong key, expired, or malformed."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def sign_state(
    payload: dict[str, Any],
    signing_key: str,
    *,
    issued_at: float | None = None,
) -> str:
    """Build a signed state string from a JSON-serializable payload."""
    full = dict(payload)
    full["iat"] = int(issued_at if issued_at is not None else time.time())
    body = json.dumps(full, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verify_state(state: str, signing_key: str) -> dict[str, Any]:
    """Verify HMAC + TTL, return decoded payload (without 'iat'). Raises on failure."""
    try:
        body_b64, tag_b64 = state.split(".", 1)
        body = _b64url_decode(body_b64)
        tag = _b64url_decode(tag_b64)
    except (ValueError, binascii.Error) as e:
        raise InvalidStateError("Malformed state") from e

    expected = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidStateError("HMAC mismatch (tampered or wrong key)")

    try:
        raw_payload: Any = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InvalidStateError("Payload is not valid JSON") from e

    if not isinstance(raw_payload, dict):
        raise InvalidStateError("Payload is not a dict")

    iat = raw_payload.get("iat")
    if not isinstance(iat, int):
        raise InvalidStateError("Missing or invalid 'iat'")
    if (time.time() - iat) > STATE_TTL_SECONDS:
        raise InvalidStateError("State expired")

    raw_payload.pop("iat", None)
    return raw_payload
