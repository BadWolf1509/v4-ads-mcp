"""get_experiments (G1, spec 2026-11-14): experimentos + comparativo base x variacao.

A API nao liga braco a anuncio (F181): `experiment_arm` volta so com
`resource_name`/`experiment`. A atribuicao das variacoes (`AD_VARIATIONS`) a um
experimento e por ELIMINACAO e so vale com exatamente UM AD_VARIATION ENABLED.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.queries import experiments as q
from src.mcp.tools import get_experiments as mod
from src.mcp.tools._registry import get_tool

_HOJE = date(2026, 11, 14)


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


@pytest.fixture(autouse=True)
def _relogio(monkeypatch):
    async def _hoje(customer_id: str, **_: Any) -> date:
        return _HOJE

    monkeypatch.setattr(mod, "resolve_account_today", _hoje)


def _exp(
    eid="10061805617", tipo="AD_VARIATION", status="ENABLED", ini="2026-10-15", fim="2027-01-07"
):
    return {
        "experiment_id": eid,
        "nome": f"exp {eid}",
        "tipo": tipo,
        "status": status,
        "inicio": ini,
        "fim": fim,
    }


def _ad(ad_id: str, *, ag="500", variacao=False) -> dict[str, Any]:
    return {
        "ad_group_id": ag,
        "ad_group": f"grupo {ag}",
        "campanha": "Campanha X",
        "ad_id": ad_id,
        "variacao": variacao,
    }


def _met(ad_id: str, *, ag="500", imp=100, clk=10, cost=50_000_000, conv=2.0) -> dict[str, Any]:
    return {
        "ad_group_id": ag,
        "ad_id": ad_id,
        "impressions": imp,
        "clicks": clk,
        "cost_micros": cost,
        "conversions": conv,
    }


def _wire(monkeypatch, *, exps, ads=(), mets=()):
    chamadas: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        query = kwargs["query"]
        chamadas.append(query)
        if "FROM experiment" in query:
            # honra o filtro do GAQL como o Google faria: filtrar ali esconderia da regra
            # de eliminacao os outros experimentos da conta
            _, _, filtro = query.partition("experiment.experiment_id = ")
            return [e for e in exps if not filtro or e["experiment_id"] == filtro.strip()]
        if "FROM ad_group_ad" in query and "metrics." in query:
            return list(mets)
        if "FROM ad_group_ad" in query:
            return list(ads)
        return []

    monkeypatch.setattr(mod, "run_report", _run)
    return chamadas


async def _call(**args: Any) -> dict[str, Any]:
    return await get_tool("get_experiments").handler({"customer_id": "7862230676", **args})


async def test_um_enabled_atribui_por_eliminacao(monkeypatch):
    _wire(
        monkeypatch,
        exps=[_exp("1", status="REMOVED"), _exp("2")],
        ads=[_ad("11"), _ad("12"), _ad("21", variacao=True), _ad("22", variacao=True)],
        mets=[
            _met("11", imp=100, clk=10, cost=50_000_000, conv=2.0),
            _met("12", imp=50, clk=5, cost=10_000_000, conv=1.0),
            _met("21", imp=30, clk=3, cost=9_000_000, conv=0.0),
            _met("22", imp=20, clk=2, cost=3_000_000, conv=0.0),
        ],
    )
    r = await _call()
    assert r["atribuicao"] == "inferida_por_eliminacao"
    por_id = {e["experiment_id"]: e for e in r["experimentos"]}
    assert por_id["1"]["grupos"] is None  # REMOVED nao se atribui
    (g,) = por_id["2"]["grupos"]
    assert g["base_ad_ids"] == ["11", "12"]
    assert g["variacao_ad_ids"] == ["21", "22"]
    assert g["base"] == {
        "impressions": 150,
        "clicks": 15,
        "cost_brl": 60.0,
        "conversions": 3.0,
        "cpa_brl": 20.0,
    }
    assert g["variacao"]["cost_brl"] == 12.0
    assert g["variacao"]["cpa_brl"] is None  # 0 conversao: denominador zero
    assert r["janela"] == {"inicio": "2026-10-15", "fim": "2026-11-13"}  # ontem na conta
    assert r["como_aplicar"] == (
        "Para aplicar o resultado: update_rsa nos base_ad_ids do grupo — a variacao herda "
        "a mudanca em minutos (F181); ler cedo demais devolve o estado antigo sem erro."
    )
    assert r["aviso"] == (
        "Comparativo somado por grupo; nao e o teste de significancia da UI (a API nao o "
        "expoe). A API nao liga braco a anuncio (F181)."
    )


async def test_dois_enabled_atribuicao_null(monkeypatch):
    chamadas = _wire(
        monkeypatch,
        exps=[_exp("1"), _exp("2")],
        ads=[_ad("11"), _ad("21", variacao=True)],
    )
    r = await _call()
    assert r["atribuicao"] is None
    assert "F181" in r["atribuicao_motivo"]
    assert all(e["grupos"] is None for e in r["experimentos"])
    assert r["janela"] is None
    # sem atribuicao nao ha o que comparar: nem anuncio nem metrica se consulta
    assert not any("ad_group_ad" in c for c in chamadas)


async def test_filtro_nao_muda_regra_da_conta(monkeypatch):
    """A eliminacao e sobre a CONTA: filtrar um id nao faz dele o unico ENABLED."""
    _wire(monkeypatch, exps=[_exp("1"), _exp("2")], ads=[_ad("21", variacao=True)])
    r = await _call(experiment_id="2")
    assert [e["experiment_id"] for e in r["experimentos"]] == ["2"]
    assert r["experimentos"][0]["grupos"] is None
    assert r["atribuicao"] is None


async def test_anuncio_sem_trafego_aparece_com_zero(monkeypatch):
    _wire(
        monkeypatch,
        exps=[_exp("2")],
        ads=[_ad("11"), _ad("21", variacao=True)],
        mets=[_met("11")],
    )
    r = await _call()
    (g,) = r["experimentos"][0]["grupos"]
    assert g["variacao_ad_ids"] == ["21"]
    assert g["variacao"] == {
        "impressions": 0,
        "clicks": 0,
        "cost_brl": 0.0,
        "conversions": 0.0,
        "cpa_brl": None,
    }


async def test_grupo_sem_base_enabled(monkeypatch):
    """Review Focus 5: todas as bases pausadas -> base [] e metricas de base None."""
    _wire(
        monkeypatch,
        exps=[_exp("2")],
        ads=[_ad("21", variacao=True)],
        mets=[_met("21")],
    )
    r = await _call()
    (g,) = r["experimentos"][0]["grupos"]
    assert g["base_ad_ids"] == []
    assert g["base"] is None
    assert g["variacao"]["impressions"] == 100


async def test_so_grupos_com_variacao_entram(monkeypatch):
    _wire(
        monkeypatch,
        exps=[_exp("2")],
        ads=[_ad("11", ag="500"), _ad("21", ag="500", variacao=True), _ad("31", ag="600")],
    )
    r = await _call()
    assert [g["ad_group_id"] for g in r["experimentos"][0]["grupos"]] == ["500"]


async def test_bracos_vazios_nao_quebram(monkeypatch):
    chamadas = _wire(monkeypatch, exps=[_exp("2")], ads=[], mets=[])
    r = await _call()
    assert r["experimentos"][0]["grupos"] == []
    assert chamadas, "a tool tem de consultar algo"
    assert not any("experiment_arm" in c for c in chamadas)


async def test_query_metricas_sem_data_no_select(monkeypatch):
    chamadas = _wire(monkeypatch, exps=[_exp("2")], ads=[_ad("11"), _ad("21", variacao=True)])
    await _call()
    (metrica,) = [c for c in chamadas if "metrics." in c]
    select, _, where = metrica.partition(" FROM ")
    assert "segments.date" not in select
    assert "segments.date BETWEEN '2026-10-15' AND '2026-11-13'" in where


async def test_experimento_de_campanha_sem_comparativo(monkeypatch):
    _wire(
        monkeypatch,
        exps=[_exp("2"), _exp("9", tipo="SEARCH_CUSTOM")],
        ads=[_ad("21", variacao=True)],
    )
    r = await _call()
    por_id = {e["experiment_id"]: e for e in r["experimentos"]}
    assert por_id["9"]["grupos"] is None
    assert por_id["2"]["grupos"] is not None


async def test_experimento_nao_iniciado_sem_janela(monkeypatch):
    chamadas = _wire(
        monkeypatch,
        exps=[_exp("2", ini="2026-11-20", fim="2027-01-07")],
        ads=[_ad("11"), _ad("21", variacao=True)],
    )
    r = await _call()
    assert r["janela"] is None
    (g,) = r["experimentos"][0]["grupos"]
    assert g["base"] is None and g["variacao"] is None
    assert g["variacao_ad_ids"] == ["21"]
    assert not any("metrics." in c for c in chamadas)


async def test_janela_corta_no_fim_do_experimento(monkeypatch):
    _wire(
        monkeypatch,
        exps=[_exp("2", ini="2026-09-19", fim="2026-10-15")],
        ads=[_ad("21", variacao=True)],
    )
    r = await _call()
    assert r["janela"] == {"inicio": "2026-09-19", "fim": "2026-10-15"}


# --- queries e parsers -------------------------------------------------------


def test_metricas_query_f87_e_data_so_no_where():
    sql = q.metricas_query(["500", "600"], start=date(2026, 10, 15), end=date(2026, 11, 13))
    select, _, where = sql.partition(" FROM ")
    assert "segments.date" not in select
    assert "ad_group.id IN (500,600)" in where
    with pytest.raises(ValueError):
        q.metricas_query(["500 OR 1=1"], start=date(2026, 10, 15), end=date(2026, 11, 13))
    with pytest.raises(ValueError):
        q.metricas_query([], start=date(2026, 10, 15), end=date(2026, 11, 13))


def test_experimentos_query_filtra_id_com_f87():
    assert "experiment.experiment_id = 42" in q.experimentos_query("42")
    assert "WHERE" not in q.experimentos_query(None)
    with pytest.raises(ValueError):
        q.experimentos_query("42 OR 1=1")


def test_parse_experimento_le_type_underscore():
    row = SimpleNamespace(
        experiment=SimpleNamespace(
            experiment_id=10061805617,
            name="Teste URL",
            type_=SimpleNamespace(name="AD_VARIATION"),
            status=SimpleNamespace(name="ENABLED"),
            start_date="2026-10-15",
            end_date="2027-01-07",
        )
    )
    assert q.parse_experimento_row(row) == {
        "experiment_id": "10061805617",
        "nome": "Teste URL",
        "tipo": "AD_VARIATION",
        "status": "ENABLED",
        "inicio": "2026-10-15",
        "fim": "2027-01-07",
    }


def test_parse_anuncio_base_tem_source_unspecified():
    def _row(src: str) -> SimpleNamespace:
        return SimpleNamespace(
            ad_group=SimpleNamespace(id=500, name="G"),
            campaign=SimpleNamespace(name="C"),
            ad_group_ad=SimpleNamespace(
                ad=SimpleNamespace(
                    id=11, system_managed_resource_source=SimpleNamespace(name=src), final_urls=[]
                )
            ),
        )

    assert q.parse_anuncio_row(_row("UNSPECIFIED"))["variacao"] is False
    assert q.parse_anuncio_row(_row("AD_VARIATIONS"))["variacao"] is True


def test_schema_e_descricao():
    t = get_tool("get_experiments")
    assert t.description.startswith("[DEFER]")
    assert t.input_schema["required"] == ["customer_id"]
    assert t.input_schema["properties"]["experiment_id"]["pattern"] == "^[0-9]+$"
    assert t.input_schema["additionalProperties"] is False


def test_anuncios_query_filtra_status_e_tipo():
    """Restricao medida: a MO-JP tem 3 variacoes REMOVED que nao podem entrar no comparativo."""
    _, _, where = q.anuncios_query().partition(" WHERE ")
    assert "ad_group_ad.status = 'ENABLED'" in where
    assert "ad_group_ad.ad.type = 'RESPONSIVE_SEARCH_AD'" in where
