# get_performance_breakdown (Fase 2A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidar os 8 reports Google de performance numa tool aditiva `get_performance_breakdown(level, breakdown)`, espelhando o `meta_get_performance_breakdown` (M.4).

**Architecture:** Módulo puro `src/google_ads/performance_breakdown.py` (`_validate_combo` + `_common_metrics` + `build_performance_breakdown_query` + `parse_performance_row`) que ENVOLVE os builders GAQL já isolados em `performance.py`/`tactical.py`. Tool fina em `src/mcp/tools/get_performance_breakdown.py` delega pro módulo + `run_report` (governança herdada). Aditivo: os 8 reports antigos seguem vivos (tombstone = Fase 2B).

**Tech Stack:** Python 3.13, google-ads v24 (proto rows via duck-typing), GAQL, pytest. Spec: `docs/superpowers/specs/2026-06-20-google-performance-breakdown-design.md`.

## Global Constraints

- Matriz válida (8 combos = 8 reports 1:1): `{campaign,ad_group,ad,keyword,audience}`+sem-breakdown; `account`+`{device,geo,hourly}`. Inválidos: `account`+sem-breakdown (→ get_account_overview), `{entity}`+breakdown (→ v1).
- Schema SEM `oneOf`/`allOf`/`anyOf` (convenção 3b.19B.1) — cross-field só em `_validate_combo`.
- `bucket="always"`; `_meta` inclui `"anthropic/alwaysLoad": True` (D3).
- `audit_this_call=True` no `run_report` (semeia o watch da Fase 2B).
- Date presets (10, paridade Google): `TODAY, YESTERDAY, LAST_7_DAYS, LAST_14_DAYS, LAST_30_DAYS, LAST_90_DAYS, THIS_MONTH, LAST_MONTH, THIS_WEEK, LAST_WEEK`. Default `LAST_30_DAYS`. Custom via `start_date`+`end_date` (`^\d{4}-\d{2}-\d{2}$`).
- `status` enum `["enabled","paused","removed","all"]` default `"enabled"` — só nos levels entity com status (campaign/ad_group/ad/keyword). Ignorado em audience + account+breakdown.
- Métricas (idênticas aos formatters atuais): `impressions, clicks, cost_brl (micros→BRL), conversions, conversions_value_brl, ctr, cpc_brl`. Divisão-por-zero → `0.0`.
- Breakdown nested sob `"breakdown": {...}` (simetria M.4), NÃO top-level.
- `customer_id` pattern `^[0-9]{10}$`.

---

### Task 1: Módulo + `_validate_combo` + `_common_metrics`

**Files:**
- Create: `src/google_ads/performance_breakdown.py`
- Test: `tests/unit/test_performance_breakdown.py`

**Interfaces:**
- Produces: `_validate_combo(level: str, breakdown: str | None) -> str | None` (None = válido, str = erro PT-BR); `_common_metrics(m: Any) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_performance_breakdown.py
from types import SimpleNamespace

from src.google_ads.performance_breakdown import _common_metrics, _validate_combo


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


def test_common_metrics_happy():
    m = SimpleNamespace(
        impressions=100, clicks=10, cost_micros=5_000_000,
        conversions=1.0, conversions_value=50.0,
    )
    out = _common_metrics(m)
    assert out == {
        "impressions": 100, "clicks": 10, "cost_brl": 5.0,
        "conversions": 1.0, "conversions_value_brl": 50.0,
        "ctr": 0.1, "cpc_brl": 0.5,
    }


def test_common_metrics_zero_division():
    m = SimpleNamespace(
        impressions=0, clicks=0, cost_micros=0,
        conversions=0.0, conversions_value=0.0,
    )
    out = _common_metrics(m)
    assert out["ctr"] == 0.0
    assert out["cpc_brl"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.google_ads.performance_breakdown'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/google_ads/performance_breakdown.py
"""Pure module for get_performance_breakdown (Fase 2A).

Consolida os 8 reports Google numa tool (level + breakdown opcional).
Zero google-ads imports — opera via duck-typing nos protos (testável com
SimpleNamespace). Espelha src/meta_ads/insights.py (M.4).
"""

from datetime import date
from typing import Any

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries.performance import (
    ad_group_performance_query,
    campaign_performance_query,
    device_performance_query,
    geo_performance_query,
    hourly_performance_query,
)
from src.google_ads.queries.tactical import (
    ad_performance_query,
    audience_performance_query,
    keyword_performance_query,
)

_ENTITY_LEVELS = ("campaign", "ad_group", "ad", "keyword", "audience")
_BREAKDOWNS = ("device", "geo", "hourly")


def _validate_combo(level: str, breakdown: str | None) -> str | None:
    """Retorna mensagem PT-BR se o combo (level, breakdown) for inválido, senão None.

    Matriz válida (8 = os 8 reports atuais): entity+sem-breakdown; account+breakdown.
    """
    if level == "account":
        if breakdown is None:
            return (
                "level='account' exige um breakdown (device/geo/hourly). "
                "Pra visão geral da conta com comparativo de período use get_account_overview."
            )
        return None
    # entity level
    if breakdown is not None:
        return (
            f"breakdown só é suportado em level='account' no v0 (você pediu level='{level}'). "
            "Use level='account' + breakdown, ou remova o breakdown."
        )
    return None


def _common_metrics(m: Any) -> dict[str, Any]:
    impr = int(m.impressions)
    clicks = int(m.clicks)
    cost_micros = int(m.cost_micros)
    return {
        "impressions": impr,
        "clicks": clicks,
        "cost_brl": micros_to_currency(cost_micros),
        "conversions": round(float(m.conversions), 2),
        "conversions_value_brl": round(float(m.conversions_value), 2),
        "ctr": round(clicks / impr, 4) if impr else 0.0,
        "cpc_brl": micros_to_currency(cost_micros / clicks) if clicks else 0.0,
    }
```

(Os imports de query/`date` são usados nas Tasks 2-4; deixe-os já aqui pra evitar churn de import entre tasks.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/performance_breakdown.py tests/unit/test_performance_breakdown.py
git commit -m "feat(mcp): performance_breakdown _validate_combo + _common_metrics"
```

---

### Task 2: `build_performance_breakdown_query`

**Files:**
- Modify: `src/google_ads/performance_breakdown.py` (adiciona função)
- Test: `tests/unit/test_performance_breakdown.py` (adiciona casos)

**Interfaces:**
- Consumes: query funcs de `performance.py`/`tactical.py` (já importadas na Task 1).
- Produces: `build_performance_breakdown_query(level: str, breakdown: str | None, status: str, start: date, end: date, limit: int) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em tests/unit/test_performance_breakdown.py
from datetime import date

from src.google_ads.performance_breakdown import build_performance_breakdown_query

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -k build_query -v`
Expected: FAIL — `ImportError: cannot import name 'build_performance_breakdown_query'`

- [ ] **Step 3: Write minimal implementation**

```python
# adicionar em src/google_ads/performance_breakdown.py
def build_performance_breakdown_query(
    level: str, breakdown: str | None, status: str, start: date, end: date, limit: int
) -> str:
    if level == "account":
        if breakdown == "device":
            return device_performance_query(start, end)
        if breakdown == "geo":
            return geo_performance_query(start, end, limit)
        if breakdown == "hourly":
            return hourly_performance_query(start, end)
        raise ValueError(f"breakdown invalido pra account: {breakdown!r}")
    if level == "campaign":
        return campaign_performance_query(start, end, status, limit)
    if level == "ad_group":
        return ad_group_performance_query(start, end, status, limit)
    if level == "ad":
        return ad_performance_query(start, end, status, limit)
    if level == "keyword":
        return keyword_performance_query(start, end, status, limit)
    if level == "audience":
        return audience_performance_query(start, end, limit)
    raise ValueError(f"level invalido: {level!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -k build_query -v`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/performance_breakdown.py tests/unit/test_performance_breakdown.py
git commit -m "feat(mcp): build_performance_breakdown_query (dispatch 8 combos)"
```

---

### Task 3: `parse_performance_row` — entity levels

**Files:**
- Modify: `src/google_ads/performance_breakdown.py`
- Test: `tests/unit/test_performance_breakdown.py`

**Interfaces:**
- Consumes: `_common_metrics`.
- Produces: `parse_performance_row(row: Any, level: str, breakdown: str | None) -> dict[str, Any]` (esta task cobre os 5 entity levels; account+breakdown vem na Task 4).

- [ ] **Step 1: Write the failing test**

```python
# adicionar em tests/unit/test_performance_breakdown.py
from src.google_ads.performance_breakdown import parse_performance_row


def _enum(name):
    return SimpleNamespace(name=name)


def _metrics():
    return SimpleNamespace(
        impressions=100, clicks=10, cost_micros=5_000_000,
        conversions=1.0, conversions_value=50.0,
    )


def test_parse_campaign():
    row = SimpleNamespace(
        campaign=SimpleNamespace(
            id=10, name="C1", status=_enum("ENABLED"),
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
        id=7, type=_enum("RESPONSIVE_SEARCH_AD"),
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
            status=_enum("ENABLED"), negative=False,
            quality_info=SimpleNamespace(
                quality_score=7, creative_quality_score=_enum("ABOVE_AVERAGE"),
                post_click_quality_score=_enum("AVERAGE"),
                search_predicted_ctr=_enum("BELOW_AVERAGE"),
            ),
            position_estimates=SimpleNamespace(
                first_page_cpc_micros=500_000, top_of_page_cpc_micros=1_200_000,
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -k parse -v`
Expected: FAIL — `ImportError: cannot import name 'parse_performance_row'`

- [ ] **Step 3: Write minimal implementation**

```python
# adicionar em src/google_ads/performance_breakdown.py
def parse_performance_row(row: Any, level: str, breakdown: str | None) -> dict[str, Any]:
    base = _common_metrics(row.metrics)

    if level == "campaign":
        return {
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            "status": row.campaign.status.name,
            "type": row.campaign.advertising_channel_type.name,
            **base,
        }
    if level == "ad_group":
        return {
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "status": row.ad_group.status.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    if level == "ad":
        ad = row.ad_group_ad.ad
        rsa = ad.responsive_search_ad
        headlines = [h.text for h in rsa.headlines] if rsa else []
        descriptions = [d.text for d in rsa.descriptions] if rsa else []
        final_urls = list(ad.final_urls) if ad.final_urls else []
        return {
            "ad_id": str(ad.id),
            "status": row.ad_group_ad.status.name,
            "type": ad.type.name,
            "ad_strength": row.ad_group_ad.ad_strength.name,
            "headlines": headlines,
            "descriptions": descriptions,
            "final_urls": final_urls,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    if level == "keyword":
        qi = row.ad_group_criterion.quality_info
        pe = row.ad_group_criterion.position_estimates
        return {
            "criterion_id": str(row.ad_group_criterion.criterion_id),
            "keyword_text": row.ad_group_criterion.keyword.text,
            "match_type": row.ad_group_criterion.keyword.match_type.name,
            "status": row.ad_group_criterion.status.name,
            "negative": bool(row.ad_group_criterion.negative),
            "quality_score": int(qi.quality_score) if qi.quality_score else None,
            "quality_creative": qi.creative_quality_score.name
            if qi.creative_quality_score
            else None,
            "quality_post_click": qi.post_click_quality_score.name
            if qi.post_click_quality_score
            else None,
            "quality_search_predicted_ctr": qi.search_predicted_ctr.name
            if qi.search_predicted_ctr
            else None,
            "first_page_cpc_brl": micros_to_currency(pe.first_page_cpc_micros)
            if pe.first_page_cpc_micros
            else None,
            "top_of_page_cpc_brl": micros_to_currency(pe.top_of_page_cpc_micros)
            if pe.top_of_page_cpc_micros
            else None,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    if level == "audience":
        cr = row.ad_group_criterion
        user_list = cr.user_list.user_list if cr.user_list and cr.user_list.user_list else None
        user_interest = (
            str(cr.user_interest.user_interest_category)
            if cr.user_interest and cr.user_interest.user_interest_category
            else None
        )
        return {
            "resource_name": row.ad_group_audience_view.resource_name,
            "criterion_id": str(cr.criterion_id),
            "user_list": user_list,
            "user_interest_category": user_interest,
            "ad_group_id": str(row.ad_group.id),
            "ad_group_name": row.ad_group.name,
            "campaign_id": str(row.campaign.id),
            "campaign_name": row.campaign.name,
            **base,
        }
    raise ValueError(f"level invalido em parse: {level!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -k parse -v`
Expected: PASS (5 testes)

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/performance_breakdown.py tests/unit/test_performance_breakdown.py
git commit -m "feat(mcp): parse_performance_row entity levels (campaign/ad_group/ad/keyword/audience)"
```

---

### Task 4: `parse_performance_row` — account+breakdown

**Files:**
- Modify: `src/google_ads/performance_breakdown.py` (estende `parse_performance_row`)
- Test: `tests/unit/test_performance_breakdown.py`

**Interfaces:**
- Produces: ramo `level == "account"` de `parse_performance_row`, com a dimensão sob `"breakdown": {...}`.

- [ ] **Step 1: Write the failing test**

```python
# adicionar em tests/unit/test_performance_breakdown.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -k account -v`
Expected: FAIL — `ValueError: level invalido em parse: 'account'` (o ramo account ainda não existe)

- [ ] **Step 3: Write minimal implementation**

```python
# em src/google_ads/performance_breakdown.py, INSERIR no topo de parse_performance_row,
# logo após `base = _common_metrics(row.metrics)`:
    if level == "account":
        if breakdown == "device":
            return {"breakdown": {"device": row.segments.device.name}, **base}
        if breakdown == "geo":
            return {
                "breakdown": {"country_criterion_id": str(row.geographic_view.country_criterion_id)},
                **base,
            }
        if breakdown == "hourly":
            return {
                "breakdown": {
                    "hour": int(row.segments.hour),
                    "day_of_week": row.segments.day_of_week.name,
                },
                **base,
            }
        raise ValueError(f"breakdown invalido pra account: {breakdown!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/test_performance_breakdown.py -v`
Expected: PASS (todos — Tasks 1-4)

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/performance_breakdown.py tests/unit/test_performance_breakdown.py
git commit -m "feat(mcp): parse_performance_row account+breakdown (device/geo/hourly)"
```

---

### Task 5: A tool `get_performance_breakdown` + integração + guard

**Files:**
- Create: `src/mcp/tools/get_performance_breakdown.py`
- Test: `tests/integration/test_get_performance_breakdown.py`

**Interfaces:**
- Consumes: `_validate_combo`, `build_performance_breakdown_query`, `parse_performance_row` (Tasks 1-4); `resolve_date_window`, `run_report`, `lookup_country_names`, `get_current`, `register_tool`.
- Produces: tool registrada `get_performance_breakdown` (bucket always).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_get_performance_breakdown.py
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


@pytest.mark.asyncio
async def test_campaign_level_happy(bound_context):
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    fake_rows = [{"campaign_id": "10", "cost_brl": 5.0}]
    with patch(
        "src.mcp.tools.get_performance_breakdown.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        out = await get_performance_breakdown(
            {"customer_id": "1234567890", "level": "campaign"}
        )
    assert out["level"] == "campaign"
    assert out["rows"] == fake_rows


@pytest.mark.asyncio
async def test_invalid_combo_account_without_breakdown(bound_context):
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    out = await get_performance_breakdown({"customer_id": "1234567890", "level": "account"})
    assert out["status"] == "error"
    assert "get_account_overview" in out["error_message"]


@pytest.mark.asyncio
async def test_geo_breakdown_enriches_country(bound_context):
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    fake_rows = [{"breakdown": {"country_criterion_id": "2076"}, "cost_brl": 1.0}]
    with (
        patch(
            "src.mcp.tools.get_performance_breakdown.run_report",
            AsyncMock(return_value=fake_rows),
        ),
        patch(
            "src.mcp.tools.get_performance_breakdown.lookup_country_names",
            AsyncMock(return_value={"2076": {"name": "Brasil", "country_code": "BR"}}),
        ),
    ):
        out = await get_performance_breakdown(
            {"customer_id": "1234567890", "level": "account", "breakdown": "geo"}
        )
    assert out["rows"][0]["breakdown"]["country_name"] == "Brasil"
    assert out["rows"][0]["breakdown"]["country_code"] == "BR"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_get_performance_breakdown.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.mcp.tools.get_performance_breakdown'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mcp/tools/get_performance_breakdown.py
# bucket: always
"""Tool: get_performance_breakdown — consolida os 8 reports Google (Fase 2A).

Aditivo: os reports antigos seguem vivos (tombstone = Fase 2B). Irmão do
meta_get_performance_breakdown (M.4): level + breakdown opcional.
"""

from typing import Any

from src.google_ads.performance_breakdown import (
    build_performance_breakdown_query,
    parse_performance_row,
    _validate_combo,
)
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.reports import lookup_country_names, run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_DATE_PRESETS = [
    "TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS",
    "LAST_90_DAYS", "THIS_MONTH", "LAST_MONTH", "THIS_WEEK", "LAST_WEEK",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "level": {
            "type": "string",
            "enum": ["campaign", "ad_group", "ad", "keyword", "audience", "account"],
            "description": "Granularidade primaria (required).",
        },
        "breakdown": {
            "type": "string",
            "enum": ["device", "geo", "hourly"],
            "description": "Dimensao secundaria. So em level=account no v0.",
        },
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_30_DAYS",
            "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
        },
        "start_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "end_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "status": {
            "type": "string",
            "enum": ["enabled", "paused", "removed", "all"],
            "default": "enabled",
            "description": "So entity levels com status (campaign/ad_group/ad/keyword).",
        },
        "limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
    },
    "required": ["customer_id", "level"],
    "additionalProperties": False,
}


@register_tool(
    name="get_performance_breakdown",
    description=(
        "[CORE] Performance Google quebrada por nivel + dimensao opcional. "
        "level: campaign|ad_group|ad|keyword|audience (rows por entidade) OU "
        "account+breakdown (device|geo|hourly). Metricas: impressions, clicks, "
        "cost_brl, conversions, conversions_value_brl, ctr, cpc_brl. Ordenado por "
        "custo desc. Para visao geral da conta com comparativo use get_account_overview."
    ),
    input_schema=_SCHEMA,
    bucket="always",
)
async def get_performance_breakdown(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    level = args["level"]
    breakdown = args.get("breakdown")

    err = _validate_combo(level, breakdown)
    if err:
        return {"status": "error", "error_message": err}

    start, end = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
    status = args.get("status", "enabled")
    limit = args.get("limit", 100)

    rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=build_performance_breakdown_query(level, breakdown, status, start, end, limit),
        row_formatter=lambda row: parse_performance_row(row, level, breakdown),
        operation_name="get_performance_breakdown",
        audit_this_call=True,
    )

    if breakdown == "geo":
        country_ids = {r["breakdown"]["country_criterion_id"] for r in rows}
        country_map = await lookup_country_names(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            country_ids=country_ids,
        )
        for r in rows:
            info = country_map.get(r["breakdown"]["country_criterion_id"])
            r["breakdown"]["country_name"] = info["name"] if info else None
            r["breakdown"]["country_code"] = info["country_code"] if info else None

    return {
        "customer_id": customer_id,
        "level": level,
        "breakdown": breakdown,
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "rows": rows,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/integration/test_get_performance_breakdown.py -v`
Expected: PASS (3 testes). Os guards globais (`tests/unit/test_tools_schemas.py`) passam a incluir a tool nova automaticamente (auto-discovery) — adicionar `"get_performance_breakdown"` aos sets `expected` em `test_all_phase_2_tools_registered` e `test_no_unexpected_tools`.

- [ ] **Step 5: Atualizar os guards de contagem de tools**

```bash
# Editar tests/unit/test_tools_schemas.py: adicionar "get_performance_breakdown"
# aos dois sets `expected` (test_all_phase_2_tools_registered + test_no_unexpected_tools).
.venv/Scripts/python.exe -m pytest tests/unit/test_tools_schemas.py -v
```
Expected: PASS (sem "Missing tools" / "Unexpected tools").

- [ ] **Step 6: Run full fast gate**

Run: `.venv/Scripts/python.exe scripts/check_pre_push.py`
Expected: All pre-push checks passed (ruff + format + mypy + unit + non-DB integration).

- [ ] **Step 7: Commit**

```bash
git add src/mcp/tools/get_performance_breakdown.py tests/integration/test_get_performance_breakdown.py tests/unit/test_tools_schemas.py
git commit -m "feat(mcp): get_performance_breakdown tool (consolida 8 reports, aditivo)"
```

---

### Task 6: Smoke runbook + ship handoff

**Files:**
- Create: `docs/operacao/phase-2a-bootstrap.md` (runbook)

**Interfaces:** nenhuma de código — gate humano (Wellington) pós-deploy.

- [ ] **Step 1: Escrever o runbook de smoke**

Conteúdo: os **8 combos** contra uma conta **Google** com atividade (customer_id de 10 dígitos da MCC `6436352492` — ex: MO-JP / CAB, já usadas nos smokes anteriores). Por combo registrar: `status:success`, shape correto, e cross-check de paridade com o report antigo equivalente (rodar o report antigo + o novo no mesmo período → métricas batem bit-a-bit). Combos:
1. `level=campaign` 2. `level=ad_group` 3. `level=ad` 4. `level=keyword` 5. `level=audience` 6. `level=account, breakdown=device` 7. `level=account, breakdown=geo` (confirmar `country_name` resolvido) 8. `level=account, breakdown=hourly`.
Mais 2 negativos: `level=account` (sem breakdown) → erro apontando overview; `level=campaign, breakdown=device` → erro "só account".

- [ ] **Step 2: Commit do runbook**

```bash
git add docs/operacao/phase-2a-bootstrap.md
git commit -m "docs(ops): smoke runbook Fase 2A (8 combos + 2 negativos)"
```

- [ ] **Step 3: Ship (push + verificar)**

```bash
git push origin main
# Pegar run IDs: gh run list --branch main --limit 2 --json databaseId,name,status
# Aguardar e CONFIRMAR via: gh run view <id> --json conclusion  (NUNCA pelo exit code de gh run watch)
```
Expected: CI `success` + Deploy `success`. Smoke pós-deploy (Step 1) é o GATE — fix-forward em combo errado (blast radius baixo, read-only, aditivo).

- [ ] **Step 4: Atualizar findings-catalog + sprint-history + memória do roadmap** com o resultado do smoke e marcar Fase 2A done. Apontar Fase 2B (tombstone) como próximo.

---

## Notas de implementação

- **Reuso, não reescrita:** Tasks 2-4 envolvem os builders/formatters EXISTENTES verbatim — paridade bit-a-bit é requisito (Step 1 do smoke cross-checka).
- **`audience`/`device`/`hourly`/`geo` não têm `status`** — o dispatch (Task 2) não passa `status` pra esses (as query funcs nem aceitam). `status` do schema é ignorado nesses combos (documentado na description).
- **geo enrichment** roda no tool (Task 5), não no parser puro (precisa de 2ª chamada API via `lookup_country_names`) — espelha o `get_geo_performance` atual, mas grava sob `breakdown.country_name`/`country_code`.
- **F28 (cache de schema do cliente MCP):** pós-deploy, reconectar a sessão MCP pra ver a tool nova.
