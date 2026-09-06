"""Panel session cookie — signed, time-bounded.

Format: base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload: {manager_id, email, aud, iat}. 24-hour TTL.

Used as the value of an httpOnly Secure SameSite=Lax cookie called
'v4_panel_session'. Verified on every panel route via Depends.

A claim 'aud' distingue este cookie dos outros tokens do projeto, que
compartilham a mesma chave e o mesmo formato — ver `oauth_state`.
"""

import base64
import binascii
import hmac
import json
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

# Audiência tem UMA definição no projeto, e ela mora em `oauth_state`.
from src.auth.oauth_state import Audience

PANEL_SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours
PANEL_SESSION_COOKIE_NAME = "v4_panel_session"


class InvalidPanelSessionError(Exception):
    """Raised when the cookie is missing/expired/tampered/de outra audiência."""


@dataclass(slots=True, frozen=True)
class PanelSession:
    manager_id: str
    email: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def sign_panel_session(
    *,
    manager_id: str,
    email: str,
    signing_key: str,
    aud: Audience,
    issued_at: float | None = None,
) -> str:
    """Build a signed cookie value. `aud` obrigatório — ver oauth_state."""
    payload = {
        "manager_id": manager_id,
        "email": email,
        "aud": aud,
        "iat": int(issued_at if issued_at is not None else time.time()),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verify_panel_session(cookie: str, signing_key: str, *, aud: Audience) -> PanelSession:
    """Verify HMAC + audiência + TTL, return the decoded PanelSession.

    A ordem importa: HMAC primeiro (nada do payload é confiável antes disso),
    audiência depois, TTL por último. A conferência de audiência mora AQUI e
    não no chamador, pelo mesmo motivo de `oauth_state.verify_state`.
    """
    try:
        body_b64, tag_b64 = cookie.split(".", 1)
        body = _b64url_decode(body_b64)
        tag = _b64url_decode(tag_b64)
    except (ValueError, binascii.Error) as e:
        raise InvalidPanelSessionError("Malformed cookie") from e

    expected = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidPanelSessionError("HMAC mismatch")

    try:
        payload: Any = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InvalidPanelSessionError("Bad JSON") from e

    if not isinstance(payload, dict):
        raise InvalidPanelSessionError("Payload is not a dict")

    if payload.get("aud") != aud:
        # Não ecoa o `aud` recebido nem o cookie: a mensagem diz só o esperado.
        raise InvalidPanelSessionError(f"Audiência inválida (esperada: {aud})")

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise InvalidPanelSessionError("Missing iat")
    if (time.time() - iat) > PANEL_SESSION_TTL_SECONDS:
        raise InvalidPanelSessionError("Cookie expired")

    # Antes: `payload.get("manager_id", "")`. Um payload sem manager_id virava
    # sessão com id vazio — sessão anônima VÁLIDA é pior que sessão inválida,
    # porque segue por todo o caminho de autorização parecendo legítima.
    manager_id = payload.get("manager_id")
    email = payload.get("email")
    if not isinstance(manager_id, str) or not manager_id:
        raise InvalidPanelSessionError("Missing manager_id")
    if not isinstance(email, str):
        raise InvalidPanelSessionError("Missing email")

    return PanelSession(manager_id=manager_id, email=email)
