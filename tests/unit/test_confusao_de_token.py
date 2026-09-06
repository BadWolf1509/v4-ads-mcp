"""C3 — confusão de tipo de token entre state de OAuth e cookie de painel.

Quatro tipos de token compartilham uma chave (`settings.session_signing_key`) e
um formato (`b64url(json).b64url(hmac_sha256)`), e só um carrega claim de
audiência. Medido em 2026-09-06: `verify_panel_session` aceita verbatim o
convite emitido por `admin.py:102`, devolvendo a sessão daquele gestor.

Cada `pytest.raises` fixa a MENSAGEM esperada, e não só o tipo da exceção. Sem
isso o teste afirma o adjacente à invariante: medido por sabotagem em
2026-09-06, remover a checagem de audiência de `verify_panel_session` deixava a
suíte inteira verde, porque os payloads de outra audiência também carecem de
`email` e a recusa vinha desse outro ramo.
"""

from __future__ import annotations

import time

import pytest

from src.auth.oauth_state import InvalidStateError, sign_state, verify_state
from src.auth.panel_session import (
    InvalidPanelSessionError,
    sign_panel_session,
    verify_panel_session,
)

CHAVE = "chave-de-teste-com-no-minimo-32-caracteres-ok"
GESTOR = "11111111-2222-3333-4444-555555555555"
AUD_INVALIDA = "Audiência inválida"


def test_state_de_oauth_nao_vale_como_cookie_de_painel() -> None:
    """O payload que `admin.py:102` emite como convite não pode virar sessão."""
    convite = sign_state({"manager_id": GESTOR}, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError, match=AUD_INVALIDA):
        verify_panel_session(convite, CHAVE, aud="panel")


def test_cookie_completo_de_outra_audiencia_e_recusado_pelo_painel() -> None:
    """Isola a checagem de audiência do painel dos demais ramos de recusa.

    Os outros casos usam payloads que também carecem de `email`, então seguiriam
    verdes mesmo sem checagem de audiência nenhuma. Aqui o token é um cookie
    COMPLETO e válido em tudo — HMAC, `manager_id`, `email`, TTL — menos a
    audiência, então só a checagem de `aud` pode recusá-lo.
    """
    outra_aud = sign_panel_session(
        manager_id=GESTOR,
        email="a@v4company.com",
        signing_key=CHAVE,
        aud="cli_invite",
    )
    with pytest.raises(InvalidPanelSessionError, match=AUD_INVALIDA):
        verify_panel_session(outra_aud, CHAVE, aud="panel")


def test_cookie_de_painel_nao_vale_como_state_de_oauth() -> None:
    """E o inverso: o cookie não pode ser replayado como state de callback."""
    cookie = sign_panel_session(
        manager_id=GESTOR, email="a@v4company.com", signing_key=CHAVE, aud="panel"
    )
    with pytest.raises(InvalidStateError, match=AUD_INVALIDA):
        verify_state(cookie, CHAVE, aud="google_oauth")


def test_state_do_google_nao_vale_como_state_do_meta() -> None:
    """As duas audiências de OAuth também são distintas entre si."""
    google = sign_state({"manager_id": GESTOR}, CHAVE, aud="google_oauth")
    with pytest.raises(InvalidStateError, match=AUD_INVALIDA):
        verify_state(google, CHAVE, aud="meta_oauth")


def test_recusa_nao_ecoa_o_aud_recebido() -> None:
    """A mensagem diz a audiência ESPERADA e nada mais — nem token, nem o `aud`
    que veio no payload. Segredo não vaza para log por mensagem de erro."""
    convite = sign_state({"manager_id": GESTOR}, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError) as excinfo:
        verify_panel_session(convite, CHAVE, aud="panel")
    msg = str(excinfo.value)
    assert "panel" in msg
    assert "cli_invite" not in msg
    assert convite not in msg
    assert GESTOR not in msg


def test_ttl_do_state_nao_e_estendido_por_verificacao_de_outra_audiencia() -> None:
    """A inversão de TTL era o que alargava a janela de 10 min para 24 h.

    Medido em 2026-09-06: um token de 1 hora era recusado por `verify_state`
    ("State expired") e ACEITO por `verify_panel_session`, porque o TTL do
    cookie é 24 h. Com audiência, o token sequer chega à checagem de TTL do
    outro lado.
    """
    velho = sign_state(
        {"manager_id": GESTOR}, CHAVE, aud="cli_invite", issued_at=time.time() - 3600
    )
    with pytest.raises(InvalidStateError, match="State expired"):
        verify_state(velho, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError, match=AUD_INVALIDA):
        verify_panel_session(velho, CHAVE, aud="panel")


def test_payload_sem_manager_id_e_recusado() -> None:
    """`panel_session.py:85` devolvia `manager_id=""` em vez de recusar — sessão
    anônima válida é pior que sessão inválida."""
    from src.auth.oauth_state import _b64url as _b64url_do_state  # noqa: PLC2701
    from src.auth.panel_session import _b64url as _b64url_do_painel  # noqa: PLC2701

    # O formato é literalmente o mesmo dos dois lados — é por isso que um token
    # de um módulo é byte-compatível com o outro, e por isso a audiência precisa
    # existir. Afirmar isso (em vez de `assert _b64url`, que é verdade sempre)
    # faz o teste falhar se algum dos dois lados mudar a codificação.
    assert _b64url_do_painel(b"formato") == _b64url_do_state(b"formato")

    # Audiência CERTA de propósito: aqui o que está sob teste é o `manager_id`.
    sem_id = sign_state({"mode": "panel_login"}, CHAVE, aud="panel")
    with pytest.raises(InvalidPanelSessionError, match="Missing manager_id"):
        verify_panel_session(sem_id, CHAVE, aud="panel")
