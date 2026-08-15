"""F88: as tools Meta truncavam na 1a pagina e ordenavam DEPOIS de truncar.

`run_meta_graph_get` devolvia so o `body` da 1a pagina e ignorava `paging.next`.
O `sort` por spend em `_meta_performance` rodava sobre esse subconjunto
ARBITRARIO, e `total_rows` apresentava o parcial como total.

Numa conta com mais entidades que o `limit` (default 100 — `meta_get_ad_performance`
estoura facil), a description prometia "Ordenado por spend desc" e entregava a
ordenacao de uma amostra enviesada: **o "top gastadores" simplesmente nao era o
top**. Um gestor perguntando "quais campanhas mais gastaram" recebia resposta
confiante e errada, sem nenhum sinal de que faltava dado.

Contraste que deixa o bug obvio: o lado Google ordena e corta SERVER-SIDE
(`ORDER BY metrics.cost_micros DESC LIMIT n`), entao o top dele e o top de
verdade. E as 4 tools de audit Google + `run_gaql` emitem `truncated`; nenhuma
das Meta emitia.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _pagina(rows: list[dict[str, Any]], proxima: str | None) -> dict[str, Any]:
    corpo: dict[str, Any] = {"data": rows}
    if proxima:
        corpo["paging"] = {"next": proxima}
    return corpo


def _campanha(nome: str, spend: str) -> dict[str, Any]:
    return {"campaign_id": nome, "campaign_name": nome, "spend": spend}


# --------------------------------------------------------------------------
# O executor: seguir paging.next
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_segue_paginacao_e_junta_as_paginas() -> None:
    """F88: com max_pages>1, as linhas das paginas seguintes entram no resultado."""
    from src.meta_ads import reports

    paginas = [
        _pagina([_campanha("a", "10")], "https://graph.facebook.com/next-1"),
        _pagina([_campanha("b", "20")], None),
    ]
    chamadas = {"n": 0}

    def fake_call(method: str, path: list[str], params: dict[str, Any]) -> MagicMock:
        resp = MagicMock()
        resp.json = MagicMock(return_value=paginas[chamadas["n"]])
        resp.headers = MagicMock(return_value={})
        chamadas["n"] += 1
        return resp

    api = MagicMock()
    api.call = fake_call

    with (
        patch.object(reports, "build_meta_api", MagicMock(return_value=api)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", AsyncMock(return_value=1)),
    ):
        corpo = await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            edge="/act_1/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
            max_pages=5,
        )

    assert [r["campaign_id"] for r in corpo["data"]] == ["a", "b"]
    assert chamadas["n"] == 2


@pytest.mark.asyncio
async def test_executor_respeita_o_teto_de_paginas_e_preserva_o_sinal() -> None:
    """F88: parar no teto e legitimo, mas o `paging.next` da ultima pagina fica
    visivel pro caller saber que ficou dado pra tras."""
    from src.meta_ads import reports

    def fake_call(method: str, path: list[str], params: dict[str, Any]) -> MagicMock:
        resp = MagicMock()
        resp.json = MagicMock(
            return_value=_pagina([_campanha("x", "1")], "https://graph.facebook.com/sempre-mais")
        )
        resp.headers = MagicMock(return_value={})
        return resp

    api = MagicMock()
    api.call = fake_call

    with (
        patch.object(reports, "build_meta_api", MagicMock(return_value=api)),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.connection, "get_pool", return_value=_pool()),
        patch.object(reports.audit_log, "record", AsyncMock(return_value=1)),
    ):
        corpo = await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            edge="/act_1/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
            max_pages=3,
        )

    assert len(corpo["data"]) == 3  # parou no teto
    assert (corpo.get("paging") or {}).get("next"), "o sinal de 'ha mais' tem que sobreviver"


def _pool() -> MagicMock:
    conn = AsyncMock()
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = cm
    return pool


# --------------------------------------------------------------------------
# A tool: ranking correto + honestidade sobre truncamento
# --------------------------------------------------------------------------


def _rodar_tool(corpo: dict[str, Any]):
    """Contexto com o Graph e o lookup de conta mockados."""
    from src.mcp.tools import _meta_performance

    conta = MagicMock(account_name="Conta X", currency="BRL")
    stack = ExitStack()
    stack.enter_context(
        patch.object(_meta_performance, "run_meta_graph_get", AsyncMock(return_value=corpo))
    )
    stack.enter_context(
        patch.object(_meta_performance.connection, "get_pool", return_value=_pool())
    )
    stack.enter_context(
        patch.object(_meta_performance.meta_ad_accounts, "get_by_id", AsyncMock(return_value=conta))
    )
    return stack


@pytest.mark.asyncio
async def test_maior_gastador_da_pagina_2_aparece_no_topo() -> None:
    """F88 — o coracao do finding: o ranking tem que ser sobre TUDO que foi lido.

    Antes, `rows` vinha so da 1a pagina; uma campanha que gastou 10x mais e
    caiu na 2a simplesmente nao existia pro gestor.
    """
    from src.mcp.tools._meta_performance import run_meta_level_performance

    corpo = {
        "data": [
            _campanha("pagina1-pequena", "10"),
            _campanha("pagina2-gigante", "9999"),
        ]
    }

    with _rodar_tool(corpo):
        resultado = await run_meta_level_performance(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            level="campaign",
            operation_name="meta_get_campaign_performance",
            date_range="LAST_7_DAYS",
            start_date=None,
            end_date=None,
            limit=100,
        )

    assert resultado["status"] == "success"
    assert resultado["rows"][0]["campaign_name"] == "pagina2-gigante"


@pytest.mark.asyncio
async def test_truncated_true_quando_sobrou_pagina() -> None:
    """F88: se o teto de paginas cortou, o ranking pode estar incompleto — e o
    consumidor precisa saber. Nenhuma tool Meta sinalizava isso."""
    from src.mcp.tools._meta_performance import run_meta_level_performance

    corpo = {
        "data": [_campanha("a", "10")],
        "paging": {"next": "https://graph.facebook.com/tem-mais"},
    }

    with _rodar_tool(corpo):
        resultado = await run_meta_level_performance(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            level="campaign",
            operation_name="meta_get_campaign_performance",
            date_range="LAST_7_DAYS",
            start_date=None,
            end_date=None,
            limit=100,
        )

    assert resultado["truncated"] is True
    assert resultado.get("truncated_hint")


@pytest.mark.asyncio
async def test_truncated_false_quando_leu_tudo() -> None:
    from src.mcp.tools._meta_performance import run_meta_level_performance

    corpo = {"data": [_campanha("a", "10")]}

    with _rodar_tool(corpo):
        resultado = await run_meta_level_performance(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_1",
            level="campaign",
            operation_name="meta_get_campaign_performance",
            date_range="LAST_7_DAYS",
            start_date=None,
            end_date=None,
            limit=100,
        )

    assert resultado["truncated"] is False
