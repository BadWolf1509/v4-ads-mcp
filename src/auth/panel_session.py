"""Panel session cookie — signed, time-bounded.

Format: base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload: {manager_id, email, aud, iat}. 24-hour TTL.

Used as the value of an httpOnly Secure SameSite=Lax cookie called
'v4_panel_session'. Verified on every panel route via Depends.

A claim 'aud' distingue este cookie dos outros tokens do projeto, que
compartilham a mesma chave e o mesmo formato — ver `oauth_state`.
"""

from dataclasses import dataclass

# Audiência tem UMA definição no projeto, e ela mora em `oauth_state`. Daqui
# só entra a audiência da família PAINEL: o tipo é quem impede que este
# módulo assine ou confira um token de `state`, e vice-versa.
from src.auth.oauth_state import PanelAudience
from src.auth.token_assinado import MENSAGENS_PAINEL, assinar, verificar

PANEL_SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours
PANEL_SESSION_COOKIE_NAME = "v4_panel_session"


class InvalidPanelSessionError(Exception):
    """Raised when the cookie is missing/expired/tampered/de outra audiência."""


@dataclass(slots=True, frozen=True)
class PanelSession:
    manager_id: str
    email: str


def sign_panel_session(
    *,
    manager_id: str,
    email: str,
    signing_key: str,
    aud: PanelAudience,
    issued_at: float | None = None,
) -> str:
    """Build a signed cookie value. `aud` obrigatório — ver oauth_state."""
    claims = {"manager_id": manager_id, "email": email}
    return assinar(claims, signing_key, aud=aud, issued_at=issued_at)


def verify_panel_session(cookie: str, signing_key: str, *, aud: PanelAudience) -> PanelSession:
    """Verify HMAC + audiência + TTL, return the decoded PanelSession.

    A ordem importa: HMAC primeiro (nada do payload é confiável antes disso),
    audiência depois, TTL por último. A conferência de audiência mora AQUI e
    não no chamador, pelo mesmo motivo de `oauth_state.verify_state`.
    """
    payload = verificar(
        cookie,
        signing_key,
        aud=aud,
        ttl=PANEL_SESSION_TTL_SECONDS,
        erro=InvalidPanelSessionError,
        mensagens=MENSAGENS_PAINEL,
    )

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
