"""Caracterizacao das leituras de colecao Meta (paginas, segmentacao, historico, criativos).

Afirma o que o codigo faz HOJE, inclusive as diferencas entre modulos, para proteger a
extracao de um helper comum. Nao e especificacao: se uma diferenca for deliberada ou
acidental, a task que a mudar atualiza o teste com o motivo.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.meta_ads import criativos, historico, paginas, segmentacao
from src.meta_ads.errors import MetaAdsFriendlyError

CTX = SimpleNamespace(manager_id="m1", session_id="s1")
ACT = "act_1"


def _falso(resp: dict[str, Any]) -> AsyncMock:
    return AsyncMock(return_value=resp)


def _kw(g: AsyncMock) -> dict[str, Any]:
    g.assert_awaited_once()
    return g.await_args.kwargs


def _linhas_pag(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i), "name": f"P{i}"} for i in range(n)]


# ---------------------------------------------------------------- listar_paginas


async def test_paginas_kwargs_e_truncated_abaixo_do_limite() -> None:
    g = _falso({"data": _linhas_pag(3)})
    with patch.object(paginas, "run_meta_graph_get", g):
        regs, truncated = await paginas.listar_paginas(CTX, ACT, 10)
    kw = _kw(g)
    assert kw["manager_id"] == "m1" and kw["session_id"] == "s1"
    assert kw["ad_account_id"] == ACT
    assert kw["edge"] == "/act_1/promote_pages"
    assert kw["params"]["limit"] == 11
    assert kw["operation_name"] == "meta_get_pages"
    assert kw["estimated_calls"] == 1 and kw["max_pages"] == 1
    assert kw["audit_this_call"] is True
    assert kw["params_summary"] == {"ad_account_id": ACT}
    assert len(regs) == 3
    assert truncated is False


async def test_paginas_limit_mais_um_corta_e_marca_truncated() -> None:
    g = _falso({"data": _linhas_pag(11)})
    with patch.object(paginas, "run_meta_graph_get", g):
        regs, truncated = await paginas.listar_paginas(CTX, ACT, 10)
    assert len(regs) == 10
    assert truncated is True


async def test_paginas_exatamente_limit_sem_next_nao_e_truncated() -> None:
    g = _falso({"data": _linhas_pag(10)})
    with patch.object(paginas, "run_meta_graph_get", g):
        regs, truncated = await paginas.listar_paginas(CTX, ACT, 10)
    assert len(regs) == 10
    assert truncated is False


async def test_paginas_next_presente_marca_truncated_abaixo_do_limite() -> None:
    g = _falso({"data": _linhas_pag(2), "paging": {"next": "https://x"}})
    with patch.object(paginas, "run_meta_graph_get", g):
        regs, truncated = await paginas.listar_paginas(CTX, ACT, 10)
    assert len(regs) == 2
    assert truncated is True


async def test_paginas_limit_grande_pagina_no_teto_e_calcula_max_pages() -> None:
    g = _falso({"data": []})
    with patch.object(paginas, "run_meta_graph_get", g):
        await paginas.listar_paginas(CTX, ACT, 250)
    kw = _kw(g)
    assert kw["params"]["limit"] == 100
    assert kw["estimated_calls"] == 3 and kw["max_pages"] == 3


async def test_paginas_data_ausente_ou_nula_vira_vazio() -> None:
    for resp in ({}, {"data": None}):
        g = _falso(resp)
        with patch.object(paginas, "run_meta_graph_get", g):
            regs, truncated = await paginas.listar_paginas(CTX, ACT, 5)
        assert regs == [] and truncated is False


# ---------------------------------------------------------------- buscar_segmentacao


def _linhas_seg(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i), "name": f"I{i}"} for i in range(n)]


async def test_segmentacao_kwargs_e_truncated_none_abaixo_do_limite() -> None:
    g = _falso({"data": _linhas_seg(3)})
    with patch.object(segmentacao, "run_meta_graph_get", g):
        regs, truncated = await segmentacao.buscar_segmentacao(CTX, ACT, "futebol", 10)
    kw = _kw(g)
    assert kw["manager_id"] == "m1" and kw["session_id"] == "s1"
    assert kw["edge"] == "/act_1/targetingsearch"
    assert kw["params"]["q"] == "futebol" and kw["params"]["limit"] == 11
    assert kw["operation_name"] == "meta_search_targeting"
    assert kw["estimated_calls"] == 1 and kw["max_pages"] == 1
    assert kw["audit_this_call"] is True
    assert kw["params_summary"] == {"ad_account_id": ACT, "q": "futebol"}
    assert len(regs) == 3
    # Diferenca deliberada: sem evidencia de corte e None, nunca False.
    assert truncated is None


async def test_segmentacao_limit_mais_um_corta_e_marca_truncated() -> None:
    g = _falso({"data": _linhas_seg(11)})
    with patch.object(segmentacao, "run_meta_graph_get", g):
        regs, truncated = await segmentacao.buscar_segmentacao(CTX, ACT, "q", 10)
    assert len(regs) == 10
    assert truncated is True


async def test_segmentacao_exatamente_limit_ja_e_truncated() -> None:
    # Diferenca de paginas/historico: aqui `>= limit` marca, la `> limit` nao.
    g = _falso({"data": _linhas_seg(10)})
    with patch.object(segmentacao, "run_meta_graph_get", g):
        regs, truncated = await segmentacao.buscar_segmentacao(CTX, ACT, "q", 10)
    assert len(regs) == 10
    assert truncated is True


async def test_segmentacao_next_presente_marca_truncated() -> None:
    g = _falso({"data": _linhas_seg(2), "paging": {"next": "https://x"}})
    with patch.object(segmentacao, "run_meta_graph_get", g):
        _, truncated = await segmentacao.buscar_segmentacao(CTX, ACT, "q", 10)
    assert truncated is True


async def test_segmentacao_pagina_unica_mesmo_com_limit_grande() -> None:
    g = _falso({"data": []})
    with patch.object(segmentacao, "run_meta_graph_get", g):
        _, truncated = await segmentacao.buscar_segmentacao(CTX, ACT, "q", 250)
    kw = _kw(g)
    assert kw["params"]["limit"] == 100
    assert kw["estimated_calls"] == 1 and kw["max_pages"] == 1
    assert truncated is None


# ---------------------------------------------------------------- listar_atividades

FUSO = "America/Maceio"  # UTC-3, sem horario de verao
SINCE, UNTIL = date(2026, 10, 10), date(2026, 10, 12)


def _ev(i: int, event_time: str | None) -> dict[str, Any]:
    linha: dict[str, Any] = {"actor_id": str(i), "object_id": str(i), "event_type": "x"}
    if event_time is not None:
        linha["event_time"] = event_time
    return linha


def _dentro(n: int) -> list[dict[str, Any]]:
    return [_ev(i, "2026-10-11T15:00:00+0000") for i in range(n)]


def _patch_hist(g: AsyncMock, fuso: str | None = FUSO):  # type: ignore[no-untyped-def]
    return (
        patch.object(historico, "run_meta_graph_get", g),
        patch.object(historico, "resolve_meta_account_zone", AsyncMock(return_value=fuso)),
    )


async def test_historico_kwargs_e_truncated_abaixo_do_limite() -> None:
    g = _falso({"data": _dentro(3)})
    p1, p2 = _patch_hist(g)
    with p1, p2:
        regs, truncated = await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 10)
    kw = _kw(g)
    assert kw["manager_id"] == "m1" and kw["session_id"] == "s1"
    assert kw["edge"] == "/act_1/activities"
    # Margem: since-1 dia, until+2 dias; pagina sempre no teto.
    assert kw["params"]["since"] == "2026-10-09"
    assert kw["params"]["until"] == "2026-10-14"
    assert kw["params"]["limit"] == 100
    assert kw["operation_name"] == "meta_get_change_history"
    # ceil(11/100)=1 pagina + 2 de margem
    assert kw["estimated_calls"] == 3 and kw["max_pages"] == 3
    assert kw["audit_this_call"] is True
    assert kw["params_summary"] == {
        "ad_account_id": ACT,
        "since": "2026-10-10",
        "until": "2026-10-12",
        "since_graph": "2026-10-09",
        "until_graph": "2026-10-14",
    }
    assert len(regs) == 3
    assert truncated is False


async def test_historico_max_pages_cresce_com_limit() -> None:
    g = _falso({"data": []})
    p1, p2 = _patch_hist(g)
    with p1, p2:
        await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 250)
    kw = _kw(g)
    assert kw["estimated_calls"] == 5 and kw["max_pages"] == 5  # ceil(251/100)=3, +2


async def test_historico_limit_mais_um_corta_e_marca_truncated() -> None:
    g = _falso({"data": _dentro(11)})
    p1, p2 = _patch_hist(g)
    with p1, p2:
        regs, truncated = await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 10)
    assert len(regs) == 10
    assert truncated is True


async def test_historico_exatamente_limit_sem_next_nao_e_truncated() -> None:
    g = _falso({"data": _dentro(10)})
    p1, p2 = _patch_hist(g)
    with p1, p2:
        regs, truncated = await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 10)
    assert len(regs) == 10
    assert truncated is False


async def test_historico_next_presente_marca_truncated_abaixo_do_limite() -> None:
    g = _falso({"data": _dentro(2), "paging": {"next": "https://x"}})
    p1, p2 = _patch_hist(g)
    with p1, p2:
        regs, truncated = await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 10)
    assert len(regs) == 2
    assert truncated is True


async def test_historico_filtra_antes_de_cortar() -> None:
    # 5 linhas fora da janela (margem) + 3 dentro, limit 3: as de fora nao consomem o limite
    # nem marcam truncated.
    fora = [_ev(i, "2026-10-09T15:00:00+0000") for i in range(5)]
    dentro = [_ev(10 + i, "2026-10-11T15:00:00+0000") for i in range(3)]
    g = _falso({"data": fora + dentro})
    p1, p2 = _patch_hist(g)
    with p1, p2:
        regs, truncated = await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 3)
    assert [r["objeto_id"] for r in regs] == ["10", "11", "12"]
    assert truncated is False


async def test_historico_usa_data_local_do_fuso_da_conta() -> None:
    # 2026-10-13T01:00Z = 12/10 22:00 em Maceio (dentro); 2026-10-10T02:00Z = 09/10 23:00 (fora).
    g = _falso(
        {
            "data": [
                _ev(1, "2026-10-13T01:00:00+0000"),
                _ev(2, "2026-10-10T02:00:00+0000"),
            ]
        }
    )
    p1, p2 = _patch_hist(g)
    with p1, p2:
        regs, _ = await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 10)
    assert [r["objeto_id"] for r in regs] == ["1"]


async def test_historico_evento_sem_data_legivel_fica_marcado() -> None:
    g = _falso({"data": [_ev(1, None), _ev(2, "lixo"), _ev(3, "2026-10-11T15:00:00")]})
    p1, p2 = _patch_hist(g)
    with p1, p2:
        regs, _ = await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 10)
    assert len(regs) == 3
    assert all(r.get("data_nao_verificada") is True for r in regs)


async def test_historico_exige_fuso_mas_so_depois_da_graph() -> None:
    g = _falso({"data": _dentro(1)})
    p1, p2 = _patch_hist(g, fuso=None)
    with p1, p2, pytest.raises(MetaAdsFriendlyError):
        await historico.listar_atividades(CTX, ACT, SINCE, UNTIL, 10)
    # A Graph (e o gate de acesso dentro dela) rodou antes da checagem do fuso.
    g.assert_awaited_once()


# ---------------------------------------------------------------- criativos


def _linhas_cri(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i), "name": f"C{i}"} for i in range(n)]


async def test_criativos_kwargs_e_truncated_abaixo_do_limite() -> None:
    g = _falso({"data": _linhas_cri(3)})
    with patch.object(criativos, "run_meta_graph_get", g):
        regs, truncated = await criativos.listar_criativos(CTX, ACT, 10, None, "meta_get_creatives")
    kw = _kw(g)
    assert kw["manager_id"] == "m1" and kw["session_id"] == "s1"
    assert kw["edge"] == "/act_1/adcreatives"
    assert kw["params"]["limit"] == 11
    assert kw["operation_name"] == "meta_get_creatives"
    assert kw["estimated_calls"] == 1 and kw["max_pages"] == 1
    assert kw["audit_this_call"] is True
    assert kw["params_summary"] == {"ad_account_id": ACT, "ad_id": None}
    assert len(regs) == 3 and all(r["ads_vinculados"] is None for r in regs)
    assert truncated is False


async def test_criativos_limit_mais_um_corta_e_marca_truncated() -> None:
    g = _falso({"data": _linhas_cri(11)})
    with patch.object(criativos, "run_meta_graph_get", g):
        regs, truncated = await criativos.listar_criativos(CTX, ACT, 10, None, "op")
    assert len(regs) == 10
    assert truncated is True


async def test_criativos_exatamente_limit_sem_next_nao_e_truncated() -> None:
    g = _falso({"data": _linhas_cri(10)})
    with patch.object(criativos, "run_meta_graph_get", g):
        regs, truncated = await criativos.listar_criativos(CTX, ACT, 10, None, "op")
    assert len(regs) == 10
    assert truncated is False


async def test_criativos_next_presente_marca_truncated() -> None:
    g = _falso({"data": _linhas_cri(2), "paging": {"next": "https://x"}})
    with patch.object(criativos, "run_meta_graph_get", g):
        _, truncated = await criativos.listar_criativos(CTX, ACT, 10, None, "op")
    assert truncated is True


async def test_criativos_ignora_linha_que_nao_e_dict() -> None:
    g = _falso({"data": [{"id": "1"}, "lixo", None]})
    with patch.object(criativos, "run_meta_graph_get", g):
        regs, _ = await criativos.listar_criativos(CTX, ACT, 10, None, "op")
    assert [r["id"] for r in regs] == ["1"]


def test_criativos_pagina_e_max_pages() -> None:
    assert criativos._pagina_e_max(10) == (11, 1)
    assert criativos._pagina_e_max(99) == (100, 1)
    assert criativos._pagina_e_max(250) == (100, 3)


async def test_percorrer_kwargs_e_next() -> None:
    g = _falso({"data": [{"id": "1"}, "lixo"], "paging": {"next": "https://x"}})
    with patch.object(criativos, "run_meta_graph_get", g):
        linhas, tem_mais = await criativos._percorrer(CTX, ACT, "ads", "id,creative{id}", "op")
    kw = _kw(g)
    assert kw["edge"] == "/act_1/ads"
    assert kw["params"] == {"fields": "id,creative{id}", "limit": 200}
    assert kw["operation_name"] == "op"
    assert kw["estimated_calls"] == 5 and kw["max_pages"] == 5
    assert kw["audit_this_call"] is True
    assert kw["params_summary"] == {"ad_account_id": ACT, "call": "posse_ads"}
    assert linhas == [{"id": "1"}]
    assert tem_mais is True


async def test_percorrer_sem_next_nao_tem_mais() -> None:
    g = _falso({"data": [{"id": "1"}]})
    with patch.object(criativos, "run_meta_graph_get", g):
        _, tem_mais = await criativos._percorrer(CTX, ACT, "adcreatives", "id", "op")
    assert tem_mais is False
    assert _kw(g)["params_summary"]["call"] == "posse_adcreatives"
