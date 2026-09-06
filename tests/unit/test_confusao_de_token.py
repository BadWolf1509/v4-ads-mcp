"""C3 — confusão de tipo de token entre state de OAuth e cookie de painel.

Quatro tipos de token compartilham uma chave (`settings.session_signing_key`) e
um formato (`b64url(json).b64url(hmac_sha256)`), e só um carrega claim de
audiência. Medido em 2026-09-06: `verify_panel_session` aceita verbatim o
convite emitido por `admin.py:102`, devolvendo a sessão daquele gestor.
"""

from __future__ import annotations

import time

import pytest

from src.auth.oauth_state import InvalidStateError, sign_state, verify_state
from src.auth.panel_session import InvalidPanelSessionError, verify_panel_session

CHAVE = "chave-de-teste-com-no-minimo-32-caracteres-ok"
GESTOR = "11111111-2222-3333-4444-555555555555"


def test_state_de_oauth_nao_vale_como_cookie_de_painel() -> None:
    """O payload que `admin.py:102` emite como convite não pode virar sessão."""
    convite = sign_state({"manager_id": GESTOR}, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(convite, CHAVE, aud="panel")


def test_cookie_de_painel_nao_vale_como_state_de_oauth() -> None:
    """E o inverso: o cookie não pode ser replayado como state de callback."""
    from src.auth.panel_session import sign_panel_session

    cookie = sign_panel_session(
        manager_id=GESTOR, email="a@v4company.com", signing_key=CHAVE, aud="panel"
    )
    with pytest.raises(InvalidStateError):
        verify_state(cookie, CHAVE, aud="google_oauth")


def test_state_do_google_nao_vale_como_state_do_meta() -> None:
    """As duas audiências de OAuth também são distintas entre si."""
    google = sign_state({"manager_id": GESTOR}, CHAVE, aud="google_oauth")
    with pytest.raises(InvalidStateError):
        verify_state(google, CHAVE, aud="meta_oauth")


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
    with pytest.raises(InvalidStateError):
        verify_state(velho, CHAVE, aud="cli_invite")
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(velho, CHAVE, aud="panel")


def test_payload_sem_manager_id_e_recusado() -> None:
    """`panel_session.py:85` devolvia `manager_id=""` em vez de recusar — sessão
    anônima válida é pior que sessão inválida."""
    from src.auth.panel_session import _b64url  # noqa: PLC2701

    sem_id = sign_state({"mode": "panel_login"}, CHAVE, aud="panel")
    assert _b64url  # o import documenta que o formato é o mesmo
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(sem_id, CHAVE, aud="panel")
