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
from tests.unit.fixtures.fake_pool import FakePool

AVISO = "Graph v22.0 was auto-upgraded to v25.0"
BUC = '{"999": [{"call_count": 5}]}'


@pytest.fixture(autouse=True)
def _zera_avisos() -> None:
    graph._avisos_vistos.clear()


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
        patch.object(reports.connection, "get_pool", return_value=FakePool()),
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


# --- Caracterizacao dos dois laços de paginacao (Task D4) ---------------------
# Escritos ANTES de unificar o laço: fixam o comportamento observável dos dois
# adaptadores (levantar x devolver complete=False) para a refatoração não mudá-lo.


def _paginas(statuses: list[int]) -> tuple[Any, list[httpx.Request]]:
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        i = len(vistos)
        status = statuses[i - 1] if i <= len(statuses) else 200
        if status != 200:
            return httpx.Response(
                status,
                json={"error": {"code": 80004, "message": "too many calls"}},
                headers={"x-business-use-case-usage": f"p{i}"},
            )
        return httpx.Response(
            200,
            json={"data": [{"i": i}], "paging": {"next": f"https://graph.facebook.com/v25.0/p{i}"}},
            headers={"x-business-use-case-usage": f"p{i}"},
        )

    return handler, vistos


@pytest.mark.asyncio
async def test_paginar_graph_429_na_segunda_pagina_levanta_e_guarda_headers() -> None:
    handler, vistos = _paginas([200, 429])
    capturados: list[httpx.Headers] = []
    async with _cliente(handler) as http:
        with pytest.raises(reports.MetaGraphHTTPError) as ei:
            await reports._paginar_graph(
                http,
                "https://graph.facebook.com/v25.0/x",
                {"fields": "id"},
                {"Authorization": "Bearer tok"},
                5,
                capturados,
            )
    assert ei.value.status == 429
    assert ei.value.retryable is True
    assert ei.value.code == 80004
    assert [h["x-business-use-case-usage"] for h in capturados] == ["p1", "p2"]
    # F82: o Authorization vai em CADA pagina; params so na primeira.
    assert all(r.headers["Authorization"] == "Bearer tok" for r in vistos)
    assert "fields=id" in str(vistos[0].url)
    assert "fields" not in str(vistos[1].url)


@pytest.mark.asyncio
async def test_paginar_graph_para_no_max_pages_e_devolve_o_paging_da_ultima() -> None:
    handler, vistos = _paginas([])
    async with _cliente(handler) as http:
        corpo, linhas, headers, lidas = await reports._paginar_graph(
            http, "https://graph.facebook.com/v25.0/x", {}, {}, 2, []
        )
    assert (lidas, len(vistos), len(linhas)) == (2, 2, 2)
    assert corpo["paging"]["next"].endswith("/p2")
    assert headers["x-business-use-case-usage"] == "p2"


@pytest.mark.asyncio
async def test_paginar_graph_corpo_nao_json_objeto_levanta() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2])

    async with _cliente(handler) as http:
        with pytest.raises(reports.MetaGraphHTTPError):
            await reports._paginar_graph(http, "https://graph.facebook.com/v25.0/x", {}, {}, 2, [])


@pytest.mark.asyncio
async def test_fetch_paginated_erro_na_segunda_pagina_devolve_incompleto_com_o_que_veio() -> None:
    handler, vistos = _paginas([200, 429])
    async with _cliente(handler) as http:
        out = await graph.fetch_paginated(
            http, "https://graph.facebook.com/v25.0/x", access_token="tok", params={"fields": "id"}
        )
    assert out.complete is False
    assert [r["i"] for r in out.rows] == [1]
    assert all(r.headers["Authorization"] == "Bearer tok" for r in vistos)
    assert "fields" not in str(vistos[1].url)


@pytest.mark.asyncio
async def test_fetch_paginated_corpo_lista_devolve_incompleto() -> None:
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        if len(vistos) == 1:
            return httpx.Response(
                200,
                json={
                    "data": [{"id": "1"}],
                    "paging": {"next": "https://graph.facebook.com/v25.0/p1"},
                },
            )
        return httpx.Response(200, json=[1, 2])

    async with _cliente(handler) as http:
        out = await graph.fetch_paginated(
            http, "https://graph.facebook.com/v25.0/x", access_token="tok", params={}
        )
    assert out == graph.PagedFetch(rows=[{"id": "1"}], complete=False)
    assert len(vistos) == 2


@pytest.mark.asyncio
async def test_fetch_paginated_corpo_lista_na_primeira() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2])

    async with _cliente(handler) as http:
        out = await graph.fetch_paginated(
            http, "https://graph.facebook.com/v25.0/x", access_token="tok", params={}
        )
    assert out == graph.PagedFetch(rows=[], complete=False)


@pytest.mark.asyncio
async def test_fetch_paginated_estourar_max_pages_devolve_incompleto() -> None:
    handler, vistos = _paginas([])
    async with _cliente(handler) as http:
        out = await graph.fetch_paginated(
            http, "https://graph.facebook.com/v25.0/x", access_token="tok", params={}, max_pages=3
        )
    assert out.complete is False
    assert (len(out.rows), len(vistos)) == (3, 3)
