"""build_client_for_manager: refresh fora do event loop e OAuth com mensagem acionavel."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from google.auth.exceptions import RefreshError

from src.google_ads import client as client_mod
from src.google_ads.errors import GoogleAdsFriendlyError
from src.mcp.server import _error_envelope

TEXTO_REFRESH = (
    "A conexão Google Ads deste gestor expirou ou foi revogada. "
    "Reconecte pelo painel (Conectar Google)."
)


@pytest.fixture
def _oauth_ativo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gestor com OAuth ativo: so o build_client (SDK) fica por conta do teste."""
    from src.auth import tokens
    from src.db import connection

    async def _run(op: Any) -> Any:
        return SimpleNamespace(refresh_token_enc=b"x")

    monkeypatch.setattr(connection, "run_with_reconnect", _run)
    monkeypatch.setattr(tokens, "derive_master_key_from_settings", lambda _k: b"k")
    monkeypatch.setattr(tokens, "decrypt_refresh_token", lambda _enc, _k: "rt")
    monkeypatch.setattr(
        "src.config.get_settings",
        lambda: SimpleNamespace(
            aes_master_key="m",
            google_ads_developer_token="d",
            google_oauth_client_id="i",
            google_oauth_client_secret="s",
            google_ads_login_customer_id="1",
        ),
    )


@pytest.mark.asyncio
async def test_build_client_nao_roda_no_event_loop(
    monkeypatch: pytest.MonkeyPatch, _oauth_ativo: None
) -> None:
    """load_from_dict faz HTTP sincrono de refresh: tem que sair do loop."""
    visto: list[threading.Thread] = []

    def _fake(**_kw: Any) -> str:
        visto.append(threading.current_thread())
        return "client"

    monkeypatch.setattr(client_mod, "build_client", _fake)
    out = await client_mod.build_client_for_manager(manager_id=uuid4())
    assert out == "client"
    assert visto and visto[0] is not threading.main_thread()


@pytest.mark.asyncio
async def test_sem_oauth_chega_ao_gestor() -> None:
    env = _error_envelope("x", client_mod.NoOAuthConnectionError(client_mod.TEXTO_SEM_OAUTH))
    assert env["status"] == "error"
    assert "painel (Conectar Google)" in env["error_message"]
    assert "/oauth/google/start" not in env["error_message"]


@pytest.mark.asyncio
async def test_refresh_revogado_chega_ao_gestor(
    monkeypatch: pytest.MonkeyPatch, _oauth_ativo: None
) -> None:
    def _revoga(**_kw: Any) -> Any:
        raise RefreshError("invalid_grant")

    monkeypatch.setattr(client_mod, "build_client", _revoga)
    with pytest.raises(GoogleAdsFriendlyError) as ei:
        await client_mod.build_client_for_manager(manager_id=uuid4())
    assert str(ei.value) == TEXTO_REFRESH
    env = _error_envelope("x", ei.value)
    assert env["error_message"] == TEXTO_REFRESH


def test_to_friendly_refresh_error() -> None:
    from src.google_ads.errors import to_friendly

    assert str(to_friendly(RefreshError("invalid_grant"))) == TEXTO_REFRESH


TEXTO_TRANSITORIO = "Falha temporária ao renovar a credencial Google. Tente de novo em instantes."


@pytest.mark.parametrize(
    "excecao",
    [
        RefreshError("invalid_grant"),
        RefreshError("invalid_grant: Token has been expired or revoked.", {"error": "x"}),
    ],
)
def test_invalid_grant_manda_reconectar(excecao: RefreshError) -> None:
    from src.google_ads.errors import to_friendly

    amigavel = to_friendly(excecao)
    assert str(amigavel) == TEXTO_REFRESH
    assert amigavel.code == "OAUTH_REFRESH_FAILED"


@pytest.mark.parametrize(
    "excecao",
    [
        RefreshError("Unable to acquire impersonated credentials"),
        RefreshError("503 backendError", {"error": "backendError"}),
        RefreshError(),
    ],
)
def test_refresh_sem_invalid_grant_e_transitorio(excecao: RefreshError) -> None:
    """RefreshError tambem vem de falha passageira: "revogada" afirmaria o que nao se
    mediu e mandaria o gestor refazer um OAuth que esta bom."""
    from src.google_ads.errors import to_friendly

    amigavel = to_friendly(excecao)
    assert str(amigavel) == TEXTO_TRANSITORIO
    assert amigavel.code == "OAUTH_REFRESH_TRANSIENT"


@pytest.mark.asyncio
async def test_refresh_transitorio_chega_ao_gestor(
    monkeypatch: pytest.MonkeyPatch, _oauth_ativo: None
) -> None:
    def _falha(**_kw: Any) -> Any:
        raise RefreshError("503 backendError")

    monkeypatch.setattr(client_mod, "build_client", _falha)
    with pytest.raises(GoogleAdsFriendlyError) as ei:
        await client_mod.build_client_for_manager(manager_id=uuid4())
    assert _error_envelope("x", ei.value)["error_message"] == TEXTO_TRANSITORIO


@pytest.mark.parametrize("motivo", ["invalid_client", "unauthorized_client"])
def test_credencial_do_servidor_recusada_nao_e_temporaria(motivo: str) -> None:
    """Client id/secret do servidor recusados: repetir nao resolve, so o admin."""
    from src.google_ads.errors import to_friendly

    amigavel = to_friendly(RefreshError(f"{motivo}: Unauthorized", {"error": motivo}))
    assert (
        str(amigavel) == "Credencial OAuth do servidor recusada pelo Google. Avise o administrador."
    )
    assert amigavel.code == "OAUTH_CLIENT_REJECTED"
