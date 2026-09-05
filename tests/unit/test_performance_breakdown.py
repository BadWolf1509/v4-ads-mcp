from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from src.google_ads.performance_breakdown import (
    _common_metrics,
    _validate_combo,
    build_performance_breakdown_query,
    parse_performance_row,
)
from src.mcp.tools import get_performance_breakdown as mod


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def test_validate_combo_entity_without_breakdown_ok():
    for level in ["campaign", "ad_group", "ad", "keyword", "audience"]:
        assert _validate_combo(level, None) is None


def test_validate_combo_account_with_breakdown_ok():
    for bd in ["device", "geo", "hourly"]:
        assert _validate_combo("account", bd) is None


def test_validate_combo_account_without_breakdown_rejected():
    msg = _validate_combo("account", None)
    assert msg is not None
    assert "get_account_overview" in msg


def test_validate_combo_entity_with_breakdown_rejected():
    msg = _validate_combo("campaign", "device")
    assert msg is not None
    assert "account" in msg.lower()
    # Fix Minor 3 (revisao final): a mensagem tinha ficado falsa depois que
    # campaign+hourly passou a ser aceito — so mandava pro agregado de conta,
    # escondendo que o combo novo existe. "hourly"/"campaign_ids" so aparecem
    # aqui se o texto documentar de verdade a combinacao nova (o input desta
    # chamada e level="campaign"+breakdown="device", entao nao vazam por eco).
    assert "hourly" in msg.lower()
    assert "campaign_ids" in msg


def test_campaign_ids_schema_recusa_id_repetido_na_borda():
    """Fix Important 1 (revisao final): uniqueItems e a metade 'recusa na
    borda' do fix — a dedup em runtime (test_campaign_hourly_campaign_ids_
    repetido_nao_dobra_linhas_nem_soma) e a outra metade, defesa em profundidade."""
    assert mod._SCHEMA["properties"]["campaign_ids"]["uniqueItems"] is True


def test_common_metrics_happy():
    m = SimpleNamespace(
        impressions=100,
        clicks=10,
        cost_micros=5_000_000,
        conversions=1.0,
        conversions_value=50.0,
    )
    out = _common_metrics(m)
    assert out == {
        "impressions": 100,
        "clicks": 10,
        "cost_brl": 5.0,
        "conversions": 1.0,
        "conversions_value_brl": 50.0,
        "ctr": 0.1,
        "cpc_brl": 0.5,
    }


def test_common_metrics_zero_division():
    m = SimpleNamespace(
        impressions=0,
        clicks=0,
        cost_micros=0,
        conversions=0.0,
        conversions_value=0.0,
    )
    out = _common_metrics(m)
    assert out["ctr"] == 0.0
    assert out["cpc_brl"] == 0.0


_S, _E = date(2026, 1, 1), date(2026, 1, 31)


def test_build_query_entity_levels_from_clause():
    cases = {
        "campaign": "FROM campaign",
        "ad_group": "FROM ad_group",
        "ad": "FROM ad_group_ad",
        "keyword": "FROM keyword_view",
        "audience": "FROM ad_group_audience_view",
    }
    for level, frm in cases.items():
        q = build_performance_breakdown_query(level, None, "enabled", _S, _E, 100)
        assert frm in q


def test_build_query_account_breakdowns():
    q_dev = build_performance_breakdown_query("account", "device", "enabled", _S, _E, 100)
    assert "segments.device" in q_dev and "FROM customer" in q_dev
    q_geo = build_performance_breakdown_query("account", "geo", "enabled", _S, _E, 100)
    assert "geographic_view.country_criterion_id" in q_geo
    q_hr = build_performance_breakdown_query("account", "hourly", "enabled", _S, _E, 100)
    assert "segments.hour" in q_hr and "FROM customer" in q_hr


def test_build_query_status_applied_to_entity_with_status():
    q = build_performance_breakdown_query("campaign", None, "paused", _S, _E, 100)
    assert "campaign.status = 'PAUSED'" in q


def _enum(name):
    return SimpleNamespace(name=name)


def _metrics():
    return SimpleNamespace(
        impressions=100,
        clicks=10,
        cost_micros=5_000_000,
        conversions=1.0,
        conversions_value=50.0,
    )


def test_parse_campaign():
    row = SimpleNamespace(
        campaign=SimpleNamespace(
            id=10,
            name="C1",
            status=_enum("ENABLED"),
            advertising_channel_type=_enum("SEARCH"),
        ),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "campaign", None)
    assert out["campaign_id"] == "10"
    assert out["campaign_name"] == "C1"
    assert out["status"] == "ENABLED"
    assert out["type"] == "SEARCH"
    assert out["cost_brl"] == 5.0 and out["ctr"] == 0.1


def test_parse_ad_group():
    row = SimpleNamespace(
        ad_group=SimpleNamespace(id=1001, name="AG1", status=_enum("ENABLED")),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "ad_group", None)
    assert out["ad_group_id"] == "1001" and out["ad_group_name"] == "AG1"
    assert out["status"] == "ENABLED" and out["campaign_id"] == "10"


def test_parse_ad_rsa_assets():
    ad = SimpleNamespace(
        id=7,
        type=_enum("RESPONSIVE_SEARCH_AD"),
        responsive_search_ad=SimpleNamespace(
            headlines=[SimpleNamespace(text="H1"), SimpleNamespace(text="H2")],
            descriptions=[SimpleNamespace(text="D1")],
        ),
        final_urls=["https://x.com"],
    )
    row = SimpleNamespace(
        ad_group_ad=SimpleNamespace(ad=ad, status=_enum("ENABLED"), ad_strength=_enum("GOOD")),
        ad_group=SimpleNamespace(id=1001, name="AG1"),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "ad", None)
    assert out["ad_id"] == "7" and out["ad_strength"] == "GOOD"
    assert out["headlines"] == ["H1", "H2"] and out["descriptions"] == ["D1"]
    assert out["final_urls"] == ["https://x.com"]


def test_parse_keyword_quality():
    row = SimpleNamespace(
        ad_group_criterion=SimpleNamespace(
            criterion_id=12345,
            keyword=SimpleNamespace(text="airless", match_type=_enum("BROAD")),
            status=_enum("ENABLED"),
            negative=False,
            quality_info=SimpleNamespace(
                quality_score=7,
                creative_quality_score=_enum("ABOVE_AVERAGE"),
                post_click_quality_score=_enum("AVERAGE"),
                search_predicted_ctr=_enum("BELOW_AVERAGE"),
            ),
            position_estimates=SimpleNamespace(
                first_page_cpc_micros=500_000,
                top_of_page_cpc_micros=1_200_000,
            ),
        ),
        ad_group=SimpleNamespace(id=1001, name="AG1"),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "keyword", None)
    assert out["criterion_id"] == "12345" and out["keyword_text"] == "airless"
    assert out["match_type"] == "BROAD" and out["negative"] is False
    assert out["quality_score"] == 7 and out["first_page_cpc_brl"] == 0.5


def test_parse_audience():
    row = SimpleNamespace(
        ad_group_audience_view=SimpleNamespace(resource_name="customers/1/x"),
        ad_group_criterion=SimpleNamespace(
            criterion_id=55,
            user_list=SimpleNamespace(user_list="customers/1/userLists/9"),
            user_interest=SimpleNamespace(user_interest_category=""),
        ),
        ad_group=SimpleNamespace(id=1001, name="AG1"),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=_metrics(),
    )
    out = parse_performance_row(row, "audience", None)
    assert out["criterion_id"] == "55"
    assert out["user_list"] == "customers/1/userLists/9"
    assert out["user_interest_category"] is None


def test_parse_account_device():
    row = SimpleNamespace(segments=SimpleNamespace(device=_enum("MOBILE")), metrics=_metrics())
    out = parse_performance_row(row, "account", "device")
    assert out["breakdown"] == {"device": "MOBILE"}
    assert out["cost_brl"] == 5.0


def test_parse_account_geo():
    row = SimpleNamespace(
        geographic_view=SimpleNamespace(country_criterion_id=2076), metrics=_metrics()
    )
    out = parse_performance_row(row, "account", "geo")
    assert out["breakdown"] == {"country_criterion_id": "2076"}


def test_parse_account_hourly():
    row = SimpleNamespace(
        segments=SimpleNamespace(hour=11, day_of_week=_enum("MONDAY")), metrics=_metrics()
    )
    out = parse_performance_row(row, "account", "hourly")
    assert out["breakdown"] == {"hour": 11, "day_of_week": "MONDAY"}


def test_campaign_mais_hourly_deixa_de_ser_recusado():
    assert _validate_combo("campaign", "hourly") is None


def test_outros_breakdowns_seguem_recusados_em_entity_level():
    """Só `hourly` abriu. `geo` continua fora: é regra de merge, não nível."""
    assert _validate_combo("campaign", "geo") is not None
    assert _validate_combo("ad_group", "hourly") is not None


# --- Task 5: campaign+hourly na TOOL (particao default, raw_grid opt-in) -------
#
# Nao existia harness async de tool neste arquivo (so testes puros de
# _validate_combo/parse_performance_row) — _wire_bd e a fixture _ctx acima
# seguem o mesmo padrao de _fake_run_report (test_get_ad_schedule.py) e _wire
# (test_update_ad_schedule.py).


def _wire_bd(monkeypatch, *, celulas: list[dict[str, Any]]) -> list[str]:
    """run_report falso: devolve `celulas` pra query com segments.hour, [] no resto.

    day_hour_metrics_query e as demais queries de campaign (build_performance_
    breakdown_query) comecam todas com `FROM campaign` — o despacho tem que casar
    `segments.hour`, a marca exclusiva da conjunta dia x hora, ANTES de qualquer
    despacho generico por `FROM <recurso>` (mesmo cuidado do _fake_run_report).
    """
    chamadas: list[str] = []

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q = kwargs["query"]
        chamadas.append(q)
        if "segments.hour" in q:
            return celulas
        return []

    monkeypatch.setattr("src.mcp.tools.get_performance_breakdown.run_report", _run)
    return chamadas


@pytest.mark.asyncio
async def test_campaign_hourly_devolve_particao_e_nao_168_celulas(monkeypatch):
    """3 linhas por campanha, nao 168. O default de limit=100 truncaria antes
    de terminar UMA campanha, e tool que trunca em uso normal nasce quebrada."""
    _wire_bd(
        monkeypatch,
        celulas=[
            {
                "campaign_id": "1",
                "day_of_week": "MONDAY",
                "hour": 9,
                "cost_micros": 100_000_000,
                "conversions": 5.0,
            },
            {
                "campaign_id": "1",
                "day_of_week": "SUNDAY",
                "hour": 3,
                "cost_micros": 40_000_000,
                "conversions": 1.0,
            },
        ],
    )
    out = await mod.get_performance_breakdown(
        {
            "customer_id": "1234567890",
            "level": "campaign",
            "breakdown": "hourly",
            "campaign_ids": ["1"],
        }
    )
    blocos = {r["bloco"] for r in out["rows"]}
    assert blocos == {"comercial", "fora_de_hora", "fim_de_semana", "outros"}
    assert len(out["rows"]) == 4
    assert out["truncated"] is False
    # Achado 1 (fix round 1): o caminho novo passa a devolver o mesmo envelope
    # do caminho generico da tool (customer_id/level/breakdown/period), aditivo
    # ao truncated que so este caminho tem — sem isso, o consumidor recebe
    # formas diferentes conforme o combo, e period e a unica forma de saber a
    # janela concreta que o preset resolveu (no fuso da conta).
    assert out["customer_id"] == "1234567890"
    assert out["level"] == "campaign"
    assert out["breakdown"] == "hourly"
    assert set(out["period"]) == {"from", "to"}
    assert date.fromisoformat(out["period"]["from"]) <= date.fromisoformat(out["period"]["to"])


@pytest.mark.asyncio
async def test_campaign_hourly_exige_campaign_ids(monkeypatch):
    out = await mod.get_performance_breakdown(
        {"customer_id": "1234567890", "level": "campaign", "breakdown": "hourly"}
    )
    assert out["status"] == "error"
    assert "campaign_ids" in out["error_message"]


# raw_grid nao vem no Step 1 do brief, mas o proprio brief documenta o contrato
# ("Interfaces": sem a flag particao, com ela grade crua + teto) — sem estes dois
# testes o ramo raw_grid ia pra producao com zero cobertura.


@pytest.mark.asyncio
async def test_raw_grid_devolve_celulas_cruas_sem_particao(monkeypatch):
    celulas = [
        {
            "campaign_id": "1",
            "day_of_week": "MONDAY",
            "hour": 9,
            "cost_micros": 100_000_000,
            "conversions": 5.0,
        },
        {
            "campaign_id": "1",
            "day_of_week": "SUNDAY",
            "hour": 3,
            "cost_micros": 40_000_000,
            "conversions": 1.0,
        },
    ]
    _wire_bd(monkeypatch, celulas=celulas)
    out = await mod.get_performance_breakdown(
        {
            "customer_id": "1234567890",
            "level": "campaign",
            "breakdown": "hourly",
            "campaign_ids": ["1"],
            "raw_grid": True,
        }
    )
    assert out["rows"] == celulas, "raw_grid devolve as celulas como vieram, sem passar por bloco"
    assert all("bloco" not in r for r in out["rows"])
    assert out["truncated"] is False
    # Achado 1 (fix round 1): envelope aditivo tambem no ramo raw_grid.
    assert out["customer_id"] == "1234567890"
    assert out["level"] == "campaign"
    assert out["breakdown"] == "hourly"
    assert set(out["period"]) == {"from", "to"}
    assert date.fromisoformat(out["period"]["from"]) <= date.fromisoformat(out["period"]["to"])


@pytest.mark.asyncio
async def test_raw_grid_trunca_no_teto_168_por_campanha(monkeypatch):
    """teto = 168 x len(campaign_ids); acima disso `truncated` tem que avisar."""
    celulas = [
        {
            "campaign_id": "1",
            "day_of_week": "MONDAY",
            "hour": i % 24,
            "cost_micros": 1_000_000,
            "conversions": 1.0,
        }
        for i in range(170)
    ]
    _wire_bd(monkeypatch, celulas=celulas)
    out = await mod.get_performance_breakdown(
        {
            "customer_id": "1234567890",
            "level": "campaign",
            "breakdown": "hourly",
            "campaign_ids": ["1"],
            "raw_grid": True,
        }
    )
    assert len(out["rows"]) == 168
    assert out["truncated"] is True
    # Achado 1 (fix round 1): envelope aditivo tambem quando trunca.
    assert out["customer_id"] == "1234567890"
    assert out["level"] == "campaign"
    assert out["breakdown"] == "hourly"
    assert set(out["period"]) == {"from", "to"}
    assert date.fromisoformat(out["period"]["from"]) <= date.fromisoformat(out["period"]["to"])


# --- Fix round 1, Achado 2: teto e filtro nunca exercitados com >1 campanha ---
#
# Os 4 testes acima usam todos campaign_ids=["1"]. Com N=1, teto=168*len(...)
# e um 168 cravado sao indistinguiveis, e "filtra celulas por campanha" e "usa
# todas as celulas pra cada campanha" tambem — as duas regressoes passariam
# verdes. So a segunda campanha separa os dois pares.


@pytest.mark.asyncio
async def test_campaign_hourly_duas_campanhas_teto_multiplica_e_celulas_nao_vazam(monkeypatch):
    """2 campanhas x 100 celulas (200 < 336 = 168*2 -> so falso se o teto
    multiplicar; um 168 cravado daria truncated=True aqui) com custo por
    celula diferente entre elas: se celulas vazassem entre campanhas (bug
    'usa todas pra cada'), a soma por campanha nao bateria com as 100 dela."""
    celulas_1 = [
        {
            "campaign_id": "1",
            "day_of_week": "MONDAY",
            "hour": i % 24,
            "cost_micros": 1_000_000,  # R$1,00 por celula
            "conversions": 0.0,
        }
        for i in range(100)
    ]
    celulas_2 = [
        {
            "campaign_id": "2",
            "day_of_week": "MONDAY",
            "hour": i % 24,
            "cost_micros": 5_000_000,  # R$5,00 por celula
            "conversions": 0.0,
        }
        for i in range(100)
    ]
    _wire_bd(monkeypatch, celulas=celulas_1 + celulas_2)
    out = await mod.get_performance_breakdown(
        {
            "customer_id": "1234567890",
            "level": "campaign",
            "breakdown": "hourly",
            "campaign_ids": ["1", "2"],
        }
    )
    assert out["truncated"] is False

    rows_1 = [r for r in out["rows"] if r["campaign_id"] == "1"]
    rows_2 = [r for r in out["rows"] if r["campaign_id"] == "2"]
    assert len(rows_1) == 4
    assert len(rows_2) == 4

    # partition_by_blocks e TOTAL por construcao (todo celula cai em exatamente
    # um balde) — a soma dos 4 blocos de cada campanha tem que bater exatamente
    # com as 100 celulas dela, nem uma a mais vazada da outra campanha.
    assert sum(r["cost_brl"] for r in rows_1) == pytest.approx(100.0)
    assert sum(r["cost_brl"] for r in rows_2) == pytest.approx(500.0)
    assert sum(r["cells"] for r in rows_1) == 100
    assert sum(r["cells"] for r in rows_2) == 100


# --- Fix Important 1 (revisao final): campaign_ids com id repetido dobrava --
#
# O schema tem uniqueItems agora, mas o loop (`for cid in campaign_ids`) tinha
# que deduplicar por conta propria — defesa em profundidade caso o schema mude
# ou seja contornado. Chamando a funcao direto (sem passar pela validacao de
# schema do MCP) para provar que a PROPRIA funcao nao confia somente no schema.


@pytest.mark.asyncio
async def test_campaign_hourly_campaign_ids_repetido_nao_dobra_linhas_nem_soma(monkeypatch):
    """Medido pela revisao: campanha com R$170,00, campaign_ids=["1","1"]
    devolvia 8 linhas (2 blocos de 4 identicos) somando R$340,00 — o dobro do
    gasto real, sem nenhum sinal pro chamador. Com o fix, tem que devolver as
    MESMAS 4 linhas de campaign_ids=["1"], somando R$170,00."""
    _wire_bd(
        monkeypatch,
        celulas=[
            {
                "campaign_id": "1",
                "day_of_week": "MONDAY",
                "hour": 9,
                "cost_micros": 170_000_000,  # R$170,00
                "conversions": 4.0,
            },
        ],
    )
    out = await mod.get_performance_breakdown(
        {
            "customer_id": "1234567890",
            "level": "campaign",
            "breakdown": "hourly",
            "campaign_ids": ["1", "1"],
        }
    )
    assert len(out["rows"]) == 4, "id repetido nao pode multiplicar os blocos (8 seria o bug)"
    assert sum(r["cost_brl"] for r in out["rows"]) == pytest.approx(170.0)
    assert sum(r["conversions"] for r in out["rows"]) == pytest.approx(4.0)
    assert out["truncated"] is False
