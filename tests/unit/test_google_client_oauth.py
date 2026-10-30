"""build_client_for_manager: refresh fora do event loop e OAuth com mensagem acionavel."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.google_ads import client as client_mod


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
