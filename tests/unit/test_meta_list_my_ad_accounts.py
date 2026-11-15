"""`meta_list_my_ad_accounts` grava uma linha de audit por chamada (A-01, P0).

Até 15/11 a tool não chamava `audit_log` nenhuma vez, e o uso dela não era
medível. A linha segue a forma de `list_my_accounts` (a irmã Google): `read`,
sem conta (`customer_id=None`, a tool lista contas), `target_count` = número de
contas. O audit é bookkeeping: se falhar, a lista sai mesmo assim (F83).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.db.repositories import audit_log, manager_meta_account_access
from src.governance import bookkeeping
from src.mcp.tools import meta_list_my_ad_accounts as mod
from tests.unit.fixtures.fake_pool import FakePool, patch_pool


def _conta(n: int) -> SimpleNamespace:
    return SimpleNamespace(
        ad_account_id=f"act_{n}",
        account_name=f"Conta {n}",
        business_id=None,
        business_name=None,
        currency="BRL",
        timezone_name="America/Sao_Paulo",
        account_status=1,
    )


@pytest.fixture
def ambiente(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    ctx = MagicMock()
    ctx.manager_id = uuid4()
    ctx.session_id = uuid4()
    monkeypatch.setattr(mod, "get_current", lambda: ctx)
    pool = FakePool()
    patch_pool(monkeypatch, pool, "src.db.connection.get_pool")

    async def _contas(_conn: Any, _manager_id: Any) -> list[SimpleNamespace]:
        return [_conta(1), _conta(2)]

    monkeypatch.setattr(manager_meta_account_access, "list_accounts_for_manager", _contas)
    record = AsyncMock(return_value=1)
    monkeypatch.setattr(audit_log, "record", record)
    return SimpleNamespace(ctx=ctx, pool=pool, record=record)


@pytest.mark.asyncio
async def test_lista_grava_uma_linha_de_audit(ambiente: SimpleNamespace) -> None:
    resultado = await mod.handler({})

    assert resultado["total"] == 2
    assert ambiente.record.await_count == 1
    kwargs = ambiente.record.await_args.kwargs
    assert kwargs["manager_id"] == ambiente.ctx.manager_id
    assert kwargs["session_id"] == ambiente.ctx.session_id
    assert kwargs["action_type"] == "read"
    assert kwargs["operation"] == "meta_list_my_ad_accounts"
    assert kwargs["platform"] == "meta"
    assert kwargs["customer_id"] is None
    assert kwargs["target_count"] == 2
    assert kwargs["status"] == "success"
    assert isinstance(kwargs["duration_ms"], int)
    assert kwargs["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_audit_que_falha_nao_derruba_a_lista(
    ambiente: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambiente.record.side_effect = ConnectionError("conexão caiu")

    # O logger do `best_effort` é trocado direto, não via `capture_logs()`: com o
    # cache de logger do structlog, o `capture_logs` não enxerga um logger já
    # usado por outro teste da suíte (verde sozinho, vermelho no gate — medido).
    log_bk = MagicMock()
    monkeypatch.setattr(bookkeeping, "log", log_bk)
    resultado = await mod.handler({})

    assert resultado["total"] == 2
    assert [c["ad_account_id"] for c in resultado["ad_accounts"]] == ["act_1", "act_2"]
    # Controle: o audit foi tentado e falhou (não foi pulado).
    assert ambiente.record.await_count == 1
    log_bk.exception.assert_called_once_with(
        "meta_list_audit_write_failed", operation="meta_list_my_ad_accounts"
    )
