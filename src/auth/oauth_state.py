"""HMAC-signed, time-bounded OAuth state token.

Format:  base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload always includes 'iat' (issued-at unix seconds) and 'aud' (audiência).
Verify checks HMAC tag, exige a audiência esperada e rejeita se 'iat' for mais
velho que STATE_TTL_SECONDS.

Used in /oauth/google/start to encode {manager_id, kind} so the callback
can recover them WITHOUT a server-side session lookup. Stateless across
Cloud Run instances. Defende contra CSRF (atacante não forja HMAC) e LIMITA
replay a STATE_TTL_SECONDS. A audiência impede que o token valha para outro
propósito.
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
    """Raised when state is tampered, wrong key, wrong audience, expired, or malformed."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def sign_state(
    payload: dict[str, Any],
    signing_key: str,
    *,
    aud: str,
    issued_at: float | None = None,
) -> str:
    """Build a signed state string from a JSON-serializable payload.

    `aud` (audiência) é obrigatório e não tem default. Quatro tipos de token
    deste projeto compartilham chave e formato; sem audiência, qualquer um vale
    como qualquer outro — medido em 2026-09-06, o convite de CLI era aceito
    verbatim como cookie de painel, e o TTL de 10 min virava 24 h no caminho.
    Default aqui silenciaria justamente o erro que a claim existe pra impedir.
    """
    full = dict(payload)
    full["aud"] = aud
    full["iat"] = int(issued_at if issued_at is not None else time.time())
    body = json.dumps(full, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verify_state(state: str, signing_key: str, *, aud: str) -> dict[str, Any]:
    """Verify HMAC + audiência + TTL, return decoded payload. Raises on failure.

    A ordem importa: HMAC primeiro (nada do payload é confiável antes disso),
    audiência depois, TTL por último. A conferência de audiência mora AQUI e
    não no chamador — chamador que confere é chamador que pode esquecer, e foi
    o que aconteceu em três dos quatro tokens.

    O payload devolvido não traz 'aud' nem 'iat': são claims da própria
    verificação, e o chamador não deve nem vê-las.
    """
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

    if raw_payload.get("aud") != aud:
        # Não ecoa o `aud` recebido nem o token: a mensagem diz só o esperado.
        raise InvalidStateError(f"Audiência inválida (esperada: {aud})")

    iat = raw_payload.get("iat")
    if not isinstance(iat, int):
        raise InvalidStateError("Missing or invalid 'iat'")
    if (time.time() - iat) > STATE_TTL_SECONDS:
        raise InvalidStateError("State expired")

    raw_payload.pop("iat", None)
    raw_payload.pop("aud", None)
    return raw_payload
