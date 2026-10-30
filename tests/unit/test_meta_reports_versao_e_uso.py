"""Alarme de versao do Graph, contador BUC no erro e audit `best_effort` (Task 12).

- `x-ad-api-version-warning` e o header real que a Meta manda quando auto-atualiza
  a versao; nada o lia. `log.error` aciona a policy `severity>=ERROR`, entao o
  aviso sai UMA vez por texto no processo, nao uma por resposta.
- Chamada throttled (429) levanta no laco de paginacao; os headers tem que
  sobreviver, senao a chamada que mais importa nao conta no BUC.
- O audit e bookkeeping: falhar depois de leitura boa nao pode virar erro cru,
  nem no caminho de erro substituir a mensagem amigavel.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from structlog.testing import capture_logs

from src.meta_ads import graph, reports
from src.meta_ads.errors import MetaAdsFriendlyError

AVISO = "Graph v22.0 was auto-upgraded to v25.0"
BUC = '{"999": [{"call_count": 5}]}'


@pytest.fixture(autouse=True)
def _zera_avisos() -> None:
    graph._avisos_vistos.clear()


class _Acq:
    async def __aenter__(self) -> Any:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    def acquire(self) -> _Acq:
        return _Acq()


def _cliente(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5)


def _avisos(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in logs if e["event"] == "meta_api_version_warning"]


def test_aviso_de_versao_sai_uma_vez_por_texto() -> None:
    with capture_logs() as logs:
        for _ in range(3):
            graph.avisar_versao_meta(httpx.Headers({"x-ad-api-version-warning": AVISO}))
        graph.avisar_versao_meta(httpx.Headers({"x-ad-api-version-warning": AVISO + " (b)"}))
        graph.avisar_versao_meta(httpx.Headers({}))
    avisos = _avisos(logs)
    assert len(avisos) == 2
    assert avisos[0]["log_level"] == "error"
    assert avisos[0]["aviso"] == AVISO


@pytest.mark.asyncio
async def test_paginar_graph_avisa_uma_vez_com_tres_respostas() -> None:
    n = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        corpo: dict[str, Any] = {"data": [{"i": n}]}
        if n < 3:
            corpo["paging"] = {"next": f"https://graph.facebook.com/v25.0/p{n}"}
        return httpx.Response(200, json=corpo, headers={"x-ad-api-version-warning": AVISO})

    capturados: list[httpx.Headers] = []
    with capture_logs() as logs:
        async with _cliente(handler) as http:
            _, linhas, _, lidas = await reports._paginar_graph(
                http, "https://graph.facebook.com/v25.0/x", {}, {}, 5, capturados
            )
    assert (len(linhas), lidas, len(capturados)) == (3, 3, 3)
    assert len(_avisos(logs)) == 1


@pytest.mark.asyncio
async def test_fetch_paginated_avisa_versao() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []}, headers={"x-ad-api-version-warning": AVISO})

    with capture_logs() as logs:
        async with _cliente(handler) as http:
            await graph.fetch_paginated(
                http, "https://graph.facebook.com/v25.0/x", access_token="t", params={}
            )
    assert len(_avisos(logs)) == 1


async def _rodar(handler: Any, *, audit: AsyncMock, rec: AsyncMock | None = None) -> Any:
    with (
        patch.object(reports.connection, "get_pool", return_value=_Pool()),
        patch.object(
            reports.manager_meta_account_access, "can_manager_access", AsyncMock(return_value=True)
        ),
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=_cliente(handler))),
        patch.object(reports.audit_log, "record", audit),
        patch.object(reports, "record_actual_meta", rec or AsyncMock()),
    ):
        return await reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_999",
            edge="/act_999/insights",
            params={},
            operation_name="meta_get_campaign_performance",
            audit_this_call=True,
            params_summary={"ad_account_id": "act_999"},
        )


@pytest.mark.asyncio
async def test_429_com_buc_ainda_conta_no_contador() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"code": 80004, "message": "too many calls"}},
            headers={"x-business-use-case-usage": BUC},
        )

    rec = AsyncMock()
    with pytest.raises(MetaAdsFriendlyError):
        await _rodar(handler, audit=AsyncMock(return_value=1), rec=rec)
    rec.assert_awaited_once()
    kw = rec.call_args.kwargs
    assert kw["ad_account_id"] == "act_999"
    assert kw["buc_header"] == BUC
    assert kw["calls"] >= 1


@pytest.mark.asyncio
async def test_audit_quebrando_na_leitura_boa_devolve_os_dados() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"a": 1}]})

    audit = AsyncMock(side_effect=RuntimeError("conexao stale"))
    resultado = await _rodar(handler, audit=audit)
    assert resultado == {"data": [{"a": 1}]}
    audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_quebrando_no_erro_preserva_a_mensagem_amigavel() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"code": 80004, "message": "too many calls"}})

    audit = AsyncMock(side_effect=RuntimeError("conexao stale"))
    with pytest.raises(MetaAdsFriendlyError) as exc:
        await _rodar(handler, audit=audit)
    assert "conexao stale" not in exc.value.message
    audit.assert_awaited_once()
