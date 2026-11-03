"""meta_get_change_history: janela, paginacao, truncated e erro."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_change_history as modulo
from src.meta_ads import historico, reports

_CONTA = "act_1"
_HOJE = date(2026, 11, 1)
_FUSO = "America/Sao_Paulo"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _patches(side_effect: Any, *, hoje: date = _HOJE, fuso: str | None = _FUSO) -> Any:
    g = AsyncMock(side_effect=side_effect)
    return (
        g,
        patch.object(historico, "run_meta_graph_get", g),
        patch.object(modulo, "resolve_meta_account_today", AsyncMock(return_value=hoje)),
        patch.object(historico, "resolve_meta_account_zone", AsyncMock(return_value=fuso)),
    )


def _graph_paginada(linhas: list[dict[str, Any]]) -> Any:
    """Le ate `limit` x `max_pages` linhas, como o paginador, e deixa `next` se sobrar."""

    async def chamada(**kw: Any) -> dict[str, Any]:
        lidas = int(kw["params"]["limit"]) * int(kw["max_pages"])
        resposta: dict[str, Any] = {"data": linhas[:lidas]}
        if len(linhas) > lidas:
            resposta["paging"] = {"next": "https://x"}
        return resposta

    return chamada


def _graph_como_medida(linhas: list[dict[str, Any]]) -> Any:
    """`since` e `until` como medidos: data UTC do evento, `since` inclusivo, `until` exclusivo."""

    async def chamada(**kw: Any) -> dict[str, Any]:
        since, until = kw["params"]["since"], kw["params"]["until"]
        return {"data": [ln for ln in linhas if since <= ln["event_time"][:10] < until]}

    return chamada


def _evento(event_time: Any, objeto: str = "1") -> dict[str, Any]:
    return {"event_time": event_time, "event_type": "t", "object_id": objeto}


def _linhas(n: int) -> list[dict[str, Any]]:
    return [
        {
            "event_time": f"2026-11-01T00:{i % 60:02d}:00+0000",
            "event_type": "t",
            "object_id": str(i),
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_padrao_sete_dias_e_declara_a_janela() -> None:
    g, p1, p2, p3 = _patches([{"data": _linhas(2)}])
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA})
    assert r["status"] == "success"
    assert r["date_range"] == {"start": "2026-10-26", "end": "2026-11-01", "days": 7}
    assert r["total_returned"] == 2 and r["truncated"] is False
    assert r["changes"][0]["tipo"] == "t"


@pytest.mark.asyncio
async def test_edge_params_since_until_e_auditoria() -> None:
    g, p1, p2, p3 = _patches([{"data": []}])
    with p1, p2, p3:
        await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 30, "limit": 20})
    kw = g.await_args_list[0].kwargs
    assert kw["edge"] == "/act_1/activities"
    assert kw["ad_account_id"] == "act_1"
    assert kw["operation_name"] == "meta_get_change_history"
    assert kw["audit_this_call"] is True
    assert kw["params"]["since"] == "2026-10-02"  # um dia antes
    assert kw["params"]["until"] == "2026-11-03"  # dois depois: `until` e exclusivo
    assert kw["params"]["limit"] == 100
    assert kw["max_pages"] == 3
    assert kw["params_summary"]["since"] == "2026-10-03"  # a auditoria guarda as duas janelas
    assert kw["params_summary"]["since_graph"] == "2026-10-02"


@pytest.mark.asyncio
async def test_limite_menor_que_o_total_marca_truncated() -> None:
    g, p1, p2, p3 = _patches([{"data": _linhas(6)}])
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is True and len(r["changes"]) == 5
    assert r["truncated_hint"]


@pytest.mark.asyncio
async def test_paging_next_sem_linha_extra_marca_truncated() -> None:
    g, p1, p2, p3 = _patches([{"data": _linhas(5), "paging": {"next": "https://x"}}])
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is True


@pytest.mark.asyncio
async def test_exatamente_no_limite_nao_marca_truncated() -> None:
    g, p1, p2, p3 = _patches([{"data": _linhas(5)}])
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert r["truncated"] is False and "truncated_hint" not in r


@pytest.mark.asyncio
async def test_janela_e_a_data_local_da_conta_nos_dois_lados() -> None:
    # Medido: days=3 declarou inicio em 31/10 e veio evento de 30/10 22:25 local (31/10 01:25 UTC).
    fora_antes = _evento("2026-10-31T01:25:00+0000", "fora_antes")
    borda_inicio = _evento("2026-10-31T03:30:00+0000", "borda_inicio")  # 31/10 00:30 local
    borda_fim = _evento("2026-11-03T02:59:00+0000", "borda_fim")  # 02/11 23:59 local
    fora_depois = _evento("2026-11-03T03:00:00+0000", "fora_depois")  # 03/11 00:00 local
    g, p1, p2, p3 = _patches(
        [{"data": [fora_depois, borda_fim, borda_inicio, fora_antes]}], hoje=date(2026, 11, 2)
    )
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 3})
    assert r["date_range"]["start"] == "2026-10-31" and r["date_range"]["end"] == "2026-11-02"
    assert [c["objeto_id"] for c in r["changes"]] == ["borda_fim", "borda_inicio"]
    assert r["total_returned"] == 2 and r["truncated"] is False
    assert all("data_nao_verificada" not in c for c in r["changes"])


@pytest.mark.asyncio
async def test_noite_do_ultimo_dia_no_oeste_de_utc_cai_no_dia_utc_seguinte_e_fica() -> None:
    noite = _evento("2026-11-03T02:30:00+0000", "noite")  # 02/11 23:30 em Sao Paulo
    g, p1, p2, p3 = _patches(_graph_como_medida([noite]), hoje=date(2026, 11, 2))
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 3})
    assert g.await_args_list[0].kwargs["params"]["until"] == "2026-11-04"
    assert [c["objeto_id"] for c in r["changes"]] == ["noite"]


@pytest.mark.asyncio
async def test_inicio_do_primeiro_dia_no_leste_de_utc_cai_no_dia_utc_anterior_e_fica() -> None:
    cedo = _evento("2026-10-30T15:30:00+0000", "cedo")  # 31/10 00:30 em Toquio
    g, p1, p2, p3 = _patches(_graph_como_medida([cedo]), hoje=date(2026, 11, 2), fuso="Asia/Tokyo")
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 3})
    assert g.await_args_list[0].kwargs["params"]["since"] == "2026-10-30"
    assert [c["objeto_id"] for c in r["changes"]] == ["cedo"]


@pytest.mark.asyncio
async def test_fuso_de_outra_conta_muda_o_filtro() -> None:
    # 02:30 UTC: 00:30 de 31/10 em Noronha (-02), 23:30 de 30/10 em Sao Paulo (-03).
    evento = _evento("2026-10-31T02:30:00+0000")
    for fuso, esperado in (("America/Noronha", 1), ("America/Sao_Paulo", 0)):
        g, p1, p2, p3 = _patches([{"data": [evento]}], hoje=date(2026, 11, 2), fuso=fuso)
        with p1, p2, p3:
            r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 3})
        assert r["total_returned"] == esperado


@pytest.mark.asyncio
async def test_linhas_fora_da_janela_nao_consomem_o_limite_nem_marcam_truncated() -> None:
    fora = [_evento("2026-11-02T04:00:00+0000", f"f{i}") for i in range(30)]  # 02/11 local
    dentro = [_evento("2026-11-01T12:00:00+0000", f"d{i}") for i in range(5)]
    g, p1, p2, p3 = _patches(_graph_paginada(fora + dentro))
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert [c["objeto_id"] for c in r["changes"]] == [f"d{i}" for i in range(5)]
    assert r["truncated"] is False and "truncated_hint" not in r


@pytest.mark.asyncio
async def test_paginacao_alcanca_o_limite_depois_da_margem() -> None:
    fora = [_evento("2026-11-02T04:00:00+0000", f"f{i}") for i in range(150)]
    dentro = [_evento("2026-11-01T12:00:00+0000", f"d{i}") for i in range(6)]
    g, p1, p2, p3 = _patches(_graph_paginada(fora + dentro))
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert [c["objeto_id"] for c in r["changes"]] == [f"d{i}" for i in range(5)]
    assert r["truncated"] is True


@pytest.mark.asyncio
async def test_limite_maximo_ainda_tem_paginas_de_margem() -> None:
    g, p1, p2, p3 = _patches([{"data": []}])
    with p1, p2, p3:
        await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 500})
    assert g.await_args_list[0].kwargs["max_pages"] == 8  # 6 para 501 linhas + 2 de margem


@pytest.mark.asyncio
async def test_next_sobrando_marca_truncated_mesmo_abaixo_do_limite() -> None:
    fora = [_evento("2026-11-02T04:00:00+0000", f"f{i}") for i in range(400)]
    g, p1, p2, p3 = _patches(_graph_paginada(fora))
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "limit": 5})
    assert r["changes"] == [] and r["truncated"] is True and r["truncated_hint"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fuso", [None, ""])
async def test_sem_fuso_da_conta_erra_depois_da_graph(fuso: str | None) -> None:
    g, p1, p2, p3 = _patches([{"data": _linhas(1)}], fuso=fuso)
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA})
    assert r["status"] == "error" and "fuso" in r["error_message"]
    g.assert_awaited_once()  # o gate mora na Graph: tem de rodar antes da exigencia do fuso


class _Aquisicao:
    async def __aenter__(self) -> MagicMock:
        return MagicMock()

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("fuso", [None, "America/Sao_Paulo"])
async def test_gestor_sem_acesso_ve_a_negacao_e_gera_auditoria_com_ou_sem_fuso(
    fuso: str | None,
) -> None:
    # Sem mock de `run_meta_graph_get`: a ordem so se prova com o gate verdadeiro.
    pool = MagicMock()
    pool.acquire.return_value = _Aquisicao()
    gravar = AsyncMock(return_value=1)
    with (
        patch.object(reports.connection, "get_pool", return_value=pool),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=False),
        ),
        patch.object(reports.audit_log, "record", gravar),
        patch.object(modulo, "resolve_meta_account_today", AsyncMock(return_value=_HOJE)),
        patch.object(historico, "resolve_meta_account_zone", AsyncMock(return_value=fuso)),
    ):
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA})
    assert r["status"] == "denied" and "não tem acesso" in r["error_message"]
    gravar.assert_awaited_once()
    assert gravar.await_args.kwargs["status"] == "denied"
    assert gravar.await_args.kwargs["operation"] == "meta_get_change_history"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_time", ["ontem", "", None, 1730000000, "2026-11-01T12:00:00"], ids=str
)
async def test_event_time_ilegivel_fica_e_vem_marcado(event_time: Any) -> None:
    g, p1, p2, p3 = _patches([{"data": [_evento(event_time, "x"), *_linhas(1)]}])
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA})
    assert r["status"] == "success" and r["total_returned"] == 2
    assert r["changes"][0]["objeto_id"] == "x"
    assert r["changes"][0]["data_nao_verificada"] is True
    assert "data_nao_verificada" not in r["changes"][1]


@pytest.mark.asyncio
async def test_days_acima_de_30_e_recusado() -> None:
    g, p1, p2, p3 = _patches([{"data": []}])
    with p1, p2, p3:
        r = await modulo.meta_get_change_history({"ad_account_id": _CONTA, "days": 31})
    assert r["status"] == "error"
    g.assert_not_awaited()


@pytest.mark.asyncio
async def test_erro_da_graph_vira_erro_em_pt() -> None:
    g, p1, p2, p3 = _patches(RuntimeError("boom"))
    with p1, p2, p3, pytest.raises(RuntimeError, match="boom"):
        await modulo.meta_get_change_history({"ad_account_id": _CONTA})


def test_registrada_como_defer_e_somente_leitura() -> None:
    from src.mcp.tools._registry import get_tool

    t = get_tool("meta_get_change_history")
    assert t is not None
    assert t.bucket == "defer"
    assert t.description.startswith("[DEFER]")
    assert t.input_schema["properties"]["ad_account_id"]["pattern"] == r"^act_\d+$"
