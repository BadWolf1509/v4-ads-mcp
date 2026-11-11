"""Caracterização do formato e das mensagens dos tokens assinados.

Fixa o comportamento de `sign_state`/`verify_state` e
`sign_panel_session`/`verify_panel_session` ANTES do codec único: os tokens
abaixo foram gravados a partir do código de 2026-11-10 e as mensagens são as
de hoje. A chave é fictícia.
"""

from __future__ import annotations

import base64
import hmac
import json
from hashlib import sha256
from typing import Any

import pytest

from src.auth.oauth_state import (
    STATE_TTL_SECONDS,
    InvalidStateError,
    sign_state,
    verify_state,
)
from src.auth.panel_session import (
    PANEL_SESSION_TTL_SECONDS,
    InvalidPanelSessionError,
    sign_panel_session,
    verify_panel_session,
)

CHAVE = "chave-fixa-de-teste-com-no-minimo-32-caracteres"
T0 = 1_700_000_000

TOKEN_GOOGLE = (
    "eyJhdWQiOiJnb29nbGVfb2F1dGgiLCJpYXQiOjE3MDAwMDAwMDAsImtpbmQiOiJ4Iiwi"
    "bWFuYWdlcl9pZCI6Im0tMSJ9.Oa0GpoSj6-cvwGuYWZAd6CXPF5OcoRozMlD1ogShW9M"
)
# `issued_at` fracionário (truncado por `int`) e payload não-ASCII (`ensure_ascii`).
TOKEN_CLI = (
    "eyJhdWQiOiJjbGlfaW52aXRlIiwiaWF0IjoxNzAwMDAwMDAwLCJtYW5hZ2VyX2lkIjoibS0x"
    "Iiwibm9uY2UiOiJhXHUwMGU3XHUwMGUzbyJ9.MxKY5whfz2RA5Mr_siUFWIVhFBMKJrY58EF80vH5Lsc"
)
TOKEN_PAINEL = (
    "eyJhdWQiOiJwYW5lbCIsImVtYWlsIjoiYUB2NGNvbXBhbnkuY29tIiwiaWF0IjoxNzAwMDAw"
    "MDAwLCJtYW5hZ2VyX2lkIjoibS0xIn0.WHJA0h75gPA4hwV0mITpRkcAlzYr5Ld3MouG7x_iuxs"
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _cunha(payload: dict[str, Any], chave: str = CHAVE) -> str:
    """Token com HMAC válido, escrito com a stdlib (não com o código sob teste)."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(chave.encode("utf-8"), body, sha256).digest()
    return f"{_b64(body)}.{_b64(tag)}"


def _cunha_corpo(body: bytes) -> str:
    tag = hmac.new(CHAVE.encode("utf-8"), body, sha256).digest()
    return f"{_b64(body)}.{_b64(tag)}"


def test_token_byte_a_byte() -> None:
    assert (
        sign_state({"manager_id": "m-1", "kind": "x"}, CHAVE, aud="google_oauth", issued_at=T0)
        == TOKEN_GOOGLE
    )
    assert (
        sign_state(
            {"manager_id": "m-1", "nonce": "ação"}, CHAVE, aud="cli_invite", issued_at=T0 + 0.9
        )
        == TOKEN_CLI
    )
    assert (
        sign_panel_session(
            manager_id="m-1", email="a@v4company.com", signing_key=CHAVE, aud="panel", issued_at=T0
        )
        == TOKEN_PAINEL
    )


def test_tokens_gravados_ainda_verificam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: T0 + 5)
    assert verify_state(TOKEN_GOOGLE, CHAVE, aud="google_oauth") == {
        "manager_id": "m-1",
        "kind": "x",
    }
    assert verify_state(TOKEN_CLI, CHAVE, aud="cli_invite") == {
        "manager_id": "m-1",
        "nonce": "ação",
    }
    sessao = verify_panel_session(TOKEN_PAINEL, CHAVE, aud="panel")
    assert (sessao.manager_id, sessao.email) == ("m-1", "a@v4company.com")


def _state(token: str) -> Any:
    return verify_state(token, CHAVE, aud="google_oauth")


def _painel(token: str) -> Any:
    return verify_panel_session(token, CHAVE, aud="panel")


# (nome, verificador, exceção, token, mensagem exata) — o `now` é T0 + 5.
def _casos() -> list[Any]:
    def aud_ok(aud: str, **extra: Any) -> dict[str, Any]:
        return {"aud": aud, "iat": T0, **extra}

    painel_ok = {"manager_id": "m-1", "email": "a@v4company.com"}
    casos: list[Any] = []
    for nome, ver, exc, aud, msgs, extra in (
        (
            "state",
            _state,
            InvalidStateError,
            "google_oauth",
            {
                "malformado": "Malformed state",
                "hmac": "HMAC mismatch (tampered or wrong key)",
                "json": "Payload is not valid JSON",
                "nao_dict": "Payload is not a dict",
                "aud": "Audiência inválida (esperada: google_oauth)",
                "iat": "Missing or invalid 'iat'",
                "expirado": "State expired",
            },
            {},
        ),
        (
            "painel",
            _painel,
            InvalidPanelSessionError,
            "panel",
            {
                "malformado": "Malformed cookie",
                "hmac": "HMAC mismatch",
                "json": "Bad JSON",
                "nao_dict": "Payload is not a dict",
                "aud": "Audiência inválida (esperada: panel)",
                "iat": "Missing iat",
                "expirado": "Cookie expired",
            },
            painel_ok,
        ),
    ):
        casos += [
            (nome, ver, exc, "sem-ponto", msgs["malformado"]),
            (nome, ver, exc, "a.b", msgs["malformado"]),  # padding impossível
            # Fora do alfabeto o decode é permissivo (descarta): cai no HMAC.
            (nome, ver, exc, "!!!.@@@", msgs["hmac"]),
            (
                nome,
                ver,
                exc,
                _cunha(aud_ok(aud, **extra), "outra-chave-qualquer-32-caracteres!!"),
                msgs["hmac"],
            ),
            (nome, ver, exc, _cunha_corpo(b"nao e json"), msgs["json"]),
            (nome, ver, exc, _cunha_corpo(b"[1,2]"), msgs["nao_dict"]),
            (nome, ver, exc, _cunha({"aud": "outra", "iat": T0, **extra}), msgs["aud"]),
            (nome, ver, exc, _cunha({"iat": T0, **extra}), msgs["aud"]),
            (nome, ver, exc, _cunha({"aud": aud, **extra}), msgs["iat"]),
            (nome, ver, exc, _cunha({"aud": aud, "iat": "123", **extra}), msgs["iat"]),
            (nome, ver, exc, _cunha({"aud": aud, "iat": 1.5, **extra}), msgs["iat"]),
            (nome, ver, exc, _cunha(aud_ok(aud, **extra) | {"iat": T0 - 10**6}), msgs["expirado"]),
        ]
    return casos


@pytest.mark.parametrize(("nome", "ver", "exc", "token", "mensagem"), _casos())
def test_mensagens_de_erro_iguais(
    monkeypatch: pytest.MonkeyPatch,
    nome: str,
    ver: Any,
    exc: type[Exception],
    token: str,
    mensagem: str,
) -> None:
    monkeypatch.setattr("time.time", lambda: T0 + 5)
    with pytest.raises(exc) as info:
        ver(token)
    assert type(info.value) is exc
    assert str(info.value) == mensagem


@pytest.mark.parametrize(
    ("ver", "aud", "extra", "ttl"),
    [
        (_state, "google_oauth", {}, STATE_TTL_SECONDS),
        (
            _painel,
            "panel",
            {"manager_id": "m-1", "email": "a@v4company.com"},
            PANEL_SESSION_TTL_SECONDS,
        ),
    ],
    ids=["state", "painel"],
)
def test_limite_do_ttl_e_estrito(
    monkeypatch: pytest.MonkeyPatch, ver: Any, aud: str, extra: dict[str, Any], ttl: int
) -> None:
    """`now - iat == ttl` ainda vale; `ttl + 1` expira (`>`, não `>=`)."""
    token = _cunha({"aud": aud, "iat": T0, **extra})
    monkeypatch.setattr("time.time", lambda: T0 + ttl)
    ver(token)
    monkeypatch.setattr("time.time", lambda: T0 + ttl + 1)
    with pytest.raises(Exception, match="expired"):
        ver(token)


def test_token_de_uma_audiencia_nao_vale_na_outra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.time", lambda: T0 + 5)
    with pytest.raises(InvalidPanelSessionError) as p:
        _painel(TOKEN_GOOGLE)
    assert str(p.value) == "Audiência inválida (esperada: panel)"
    with pytest.raises(InvalidStateError) as s:
        _state(TOKEN_PAINEL)
    assert str(s.value) == "Audiência inválida (esperada: google_oauth)"
    with pytest.raises(InvalidStateError) as c:
        _state(TOKEN_CLI)
    assert str(c.value) == "Audiência inválida (esperada: google_oauth)"
