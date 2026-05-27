# Sprint 3b.36 — `audit_zombie_keywords` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `audit_zombie_keywords` (56ª MCP tool) — detecta keywords ENABLED com zero activity (`impressions=0 AND clicks=0`) em window LAST_30_DAYS, ordenadas por ad_group_name (ICE 315, cleanup massivo recurring dogfood MO-JP 19/05).

**Architecture:** Pure aggregator (`src/google_ads/flag_zombie_keywords.py`) + GAQL builder (`src/google_ads/queries/audit_zombie_keywords.py`) + wrapper (`src/mcp/tools/audit_zombie_keywords.py`). Padrão idêntico Sprint 3b.30/3b.31/3b.33/3b.35.

**Tech Stack:** Python 3.12 com frozen+slots dataclasses, pytest com AsyncMock+patch, ruff+mypy strict.

**Reference:** [`docs/superpowers/specs/2026-05-21-sprint-3b-36-audit-zombie-keywords-design.md`](../specs/2026-05-21-sprint-3b-36-audit-zombie-keywords-design.md)

---

## File Structure

**Create:**
- `src/google_ads/flag_zombie_keywords.py` — pure module com 2 dataclasses + `flag_zombie_keywords()` filter+sort+truncate
- `src/google_ads/queries/audit_zombie_keywords.py` — GAQL builder + row parser + dict→dataclass boundary
- `src/mcp/tools/audit_zombie_keywords.py` — tool wrapper MCP
- `tests/unit/test_flag_zombie_keywords.py` — 10 pure module tests
- `tests/unit/test_audit_zombie_keywords_queries.py` — 4 GAQL + boundary parser tests
- `tests/integration/test_audit_zombie_keywords.py` — 3 wire-up tests

**Modify:**
- `tests/unit/test_tools_schemas.py` — bump tool count 55→56 + add `audit_zombie_keywords` ao allowlist

**No new GAQL queries fora do builder em A2. F46 imune (não usa change_event).**

---

## Task A1: `flag_zombie_keywords.py` pure module + 10 unit tests

**Files:**
- Create: `src/google_ads/flag_zombie_keywords.py`
- Create: `tests/unit/test_flag_zombie_keywords.py`

**Sequencial:** Foundational. A2 + A3 importam `KeywordRow` + `ZombieKeyword` + `flag_zombie_keywords`.

- [ ] **Step 1: Create `src/google_ads/flag_zombie_keywords.py`**

```python
"""Pure client-side zombie keyword detection (Sprint 3b.36 audit_zombie_keywords).

Filtra keywords ENABLED com zero activity (impressions=0 AND clicks=0) em
window de N dias. Sort por (ad_group_name ASC, keyword_text ASC) pra
agrupar visualmente. Cleanup massivo recurring MO-JP (dogfood 19/05 lição 41+).

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KeywordRow:
    """Boundary input — dict de keyword_view GAQL converte pra cá."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str  # "EXACT" | "PHRASE" | "BROAD"
    impressions: int
    clicks: int
    cost_brl: float
    conversions: int
    status: str  # "ENABLED" expected (server-side filter)


@dataclass(frozen=True, slots=True)
class ZombieKeyword:
    """Output: KeywordRow flagged as zombie (impressions=0 AND clicks=0)."""

    ad_group_id: str
    ad_group_name: str
    campaign_name: str
    keyword_id: str
    keyword_text: str
    match_type: str
    impressions: int
    clicks: int
    cost_brl: float
    conversions: int
    status: str


def flag_zombie_keywords(
    rows: list[KeywordRow],
    *,
    limit: int,
) -> tuple[list[ZombieKeyword], int]:
    """Filter zombies, sort, truncate.

    Args:
        rows: list[KeywordRow] from GAQL keyword_view (já filtered server-side
              por status=ENABLED + negative=FALSE).
        limit: max output entries.

    Returns:
        (zombies, total_pre_truncate). Sorted by ad_group_name ASC,
        keyword_text ASC.

    Algorithm:
    1. Filter: keep only rows com impressions == 0 AND clicks == 0 (pure waste).
    2. Sort: ad_group_name ASC, keyword_text ASC (stable visual grouping).
    3. Truncate to limit. Return (zombies, total_pre_truncate).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    zombies = [
        ZombieKeyword(
            ad_group_id=r.ad_group_id,
            ad_group_name=r.ad_group_name,
            campaign_name=r.campaign_name,
            keyword_id=r.keyword_id,
            keyword_text=r.keyword_text,
            match_type=r.match_type,
            impressions=r.impressions,
            clicks=r.clicks,
            cost_brl=r.cost_brl,
            conversions=r.conversions,
            status=r.status,
        )
        for r in rows
        if r.impressions == 0 and r.clicks == 0
    ]
    zombies.sort(key=lambda z: (z.ad_group_name, z.keyword_text))
    total = len(zombies)
    return zombies[:limit], total
```

- [ ] **Step 2: Create `tests/unit/test_flag_zombie_keywords.py` com 10 tests**

```python
"""Unit tests for flag_zombie_keywords pure module (Sprint 3b.36)."""

from src.google_ads.flag_zombie_keywords import (
    KeywordRow,
    flag_zombie_keywords,
)


def _make_kw(
    *,
    ad_group_id: str = "1001",
    ad_group_name: str = "AG1",
    campaign_name: str = "C1",
    keyword_id: str = "K1",
    keyword_text: str = "andaime metálico",
    match_type: str = "BROAD",
    impressions: int = 0,
    clicks: int = 0,
    cost_brl: float = 0.0,
    conversions: int = 0,
    status: str = "ENABLED",
) -> KeywordRow:
    return KeywordRow(
        ad_group_id=ad_group_id,
        ad_group_name=ad_group_name,
        campaign_name=campaign_name,
        keyword_id=keyword_id,
        keyword_text=keyword_text,
        match_type=match_type,
        impressions=impressions,
        clicks=clicks,
        cost_brl=cost_brl,
        conversions=conversions,
        status=status,
    )


def test_empty_rows_returns_empty():
    zombies, total = flag_zombie_keywords([], limit=10)
    assert zombies == []
    assert total == 0


def test_filter_keeps_impressions_zero_clicks_zero():
    rows = [_make_kw(impressions=0, clicks=0)]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 1
    assert total == 1


def test_filter_excludes_impressions_positive():
    """Keyword com impressions>0 NÃO é zombie (visible mas not clicked = outro issue)."""
    rows = [_make_kw(impressions=10, clicks=0)]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert zombies == []
    assert total == 0


def test_filter_excludes_clicks_positive():
    """Keyword com clicks>0 NÃO é zombie (edge case: impressions=0 + clicks>0 rare mas defensive)."""
    rows = [_make_kw(impressions=0, clicks=1)]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert zombies == []
    assert total == 0


def test_sort_by_ad_group_name_asc():
    rows = [
        _make_kw(keyword_id="A", ad_group_name="Zulu Group", keyword_text="alpha"),
        _make_kw(keyword_id="B", ad_group_name="Alpha Group", keyword_text="beta"),
        _make_kw(keyword_id="C", ad_group_name="Mike Group", keyword_text="gamma"),
    ]
    zombies, _ = flag_zombie_keywords(rows, limit=10)
    ad_groups = [z.ad_group_name for z in zombies]
    assert ad_groups == ["Alpha Group", "Mike Group", "Zulu Group"]


def test_sort_tie_break_by_keyword_text_asc():
    rows = [
        _make_kw(keyword_id="A", ad_group_name="Same AG", keyword_text="zulu"),
        _make_kw(keyword_id="B", ad_group_name="Same AG", keyword_text="alpha"),
        _make_kw(keyword_id="C", ad_group_name="Same AG", keyword_text="mike"),
    ]
    zombies, _ = flag_zombie_keywords(rows, limit=10)
    texts = [z.keyword_text for z in zombies]
    assert texts == ["alpha", "mike", "zulu"]


def test_truncation_limit_exceeded():
    """50 zombies + limit=10 → returns 10, total=50."""
    rows = [
        _make_kw(keyword_id=str(i), keyword_text=f"kw_{i:03d}")
        for i in range(50)
    ]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 10
    assert total == 50


def test_truncation_limit_not_exceeded():
    """5 zombies + limit=200 → returns 5, total=5."""
    rows = [_make_kw(keyword_id=str(i)) for i in range(5)]
    zombies, total = flag_zombie_keywords(rows, limit=200)
    assert len(zombies) == 5
    assert total == 5


def test_multiple_keywords_same_ad_group_all_listed():
    rows = [
        _make_kw(keyword_id="A", ad_group_name="Same AG", keyword_text="alpha"),
        _make_kw(keyword_id="B", ad_group_name="Same AG", keyword_text="beta"),
        _make_kw(keyword_id="C", ad_group_name="Same AG", keyword_text="gamma"),
    ]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 3
    assert total == 3


def test_total_count_pre_truncate_preserved():
    """Mix de zombies + non-zombies: total reflete POST-filter, PRE-truncate."""
    rows = [
        _make_kw(keyword_id="A", impressions=0, clicks=0),   # zombie
        _make_kw(keyword_id="B", impressions=10, clicks=0),  # not zombie (visible)
        _make_kw(keyword_id="C", impressions=0, clicks=0),   # zombie
        _make_kw(keyword_id="D", impressions=100, clicks=5), # not zombie (active)
    ]
    zombies, total = flag_zombie_keywords(rows, limit=10)
    assert len(zombies) == 2
    assert total == 2  # only the 2 zombies count
```

- [ ] **Step 3: Run tests — expect 10/10 PASS**

```bash
python -m pytest tests/unit/test_flag_zombie_keywords.py -v
```

Expected: 10 passed.

- [ ] **Step 4: Run ruff + mypy**

```bash
python -m ruff check src/google_ads/flag_zombie_keywords.py tests/unit/test_flag_zombie_keywords.py
python -m ruff format --check src/google_ads/flag_zombie_keywords.py tests/unit/test_flag_zombie_keywords.py
python -m mypy src/google_ads/flag_zombie_keywords.py
```

Expected: All checks PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/flag_zombie_keywords.py tests/unit/test_flag_zombie_keywords.py
git commit -m "feat(google_ads): flag_zombie_keywords pure module + 10 unit tests (Sprint 3b.36 A1)"
```

---

## Task A2: GAQL builder + 4 unit tests

**Files:**
- Create: `src/google_ads/queries/audit_zombie_keywords.py`
- Create: `tests/unit/test_audit_zombie_keywords_queries.py`

**Pode rodar PARALELO ao A1** (arquivos isolated).

- [ ] **Step 1: Create `src/google_ads/queries/audit_zombie_keywords.py`**

```python
"""GAQL builder for audit_zombie_keywords tool (Sprint 3b.36).

Single query sobre keyword_view com:
- Date range filter (gaql_date_clause helper)
- status=ENABLED + negative=FALSE hardcoded server-side
- Optional ad_group_ids filter
- 11 fields SELECT (keyword + ad_group + campaign + metrics)
"""

from datetime import date
from typing import Any

from src.google_ads.flag_zombie_keywords import KeywordRow
from src.google_ads.queries._common import gaql_date_clause


def build_audit_zombie_keywords_query(
    *,
    start_date: str,
    end_date: str,
    ad_group_ids: list[str] | None,
) -> str:
    """GAQL pra keyword_view com fields necessários (audit_zombie_keywords).

    Filters: date range via gaql_date_clause + status=ENABLED +
    negative=FALSE + optional ad_group_ids IN clause.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    date_clause = gaql_date_clause(start, end)

    ad_group_clause = ""
    if ad_group_ids:
        ids = ",".join(ad_group_ids)
        ad_group_clause = f" AND ad_group.id IN ({ids})"

    return f"""
        SELECT
          ad_group_criterion.criterion_id,
          ad_group_criterion.keyword.text,
          ad_group_criterion.keyword.match_type,
          ad_group_criterion.status,
          ad_group.id,
          ad_group.name,
          campaign.name,
          metrics.impressions,
          metrics.clicks,
          metrics.cost_micros,
          metrics.conversions
        FROM keyword_view
        WHERE {date_clause}
          AND ad_group_criterion.status = 'ENABLED'
          AND ad_group_criterion.negative = FALSE{ad_group_clause}
    """.strip()


def parse_keyword_view_row(row: Any) -> dict[str, Any]:
    """Parse keyword_view GAQL row → dict (boundary).

    Uses `.name` on match_type/status enums (Sprint 3b.7 lesson: proto-plus
    v20+ repr regression — `str(enum)` retorna integer, `.name` retorna 'BROAD').
    """
    return {
        "ad_group_id": str(row.ad_group.id),
        "ad_group_name": row.ad_group.name,
        "campaign_name": row.campaign.name,
        "keyword_id": str(row.ad_group_criterion.criterion_id),
        "keyword_text": row.ad_group_criterion.keyword.text,
        "match_type": row.ad_group_criterion.keyword.match_type.name,
        "impressions": int(row.metrics.impressions),
        "clicks": int(row.metrics.clicks),
        "cost_brl": float(row.metrics.cost_micros) / 1_000_000.0,
        "conversions": int(row.metrics.conversions),
        "status": row.ad_group_criterion.status.name,
    }


def dict_to_keyword_row(d: dict[str, Any]) -> KeywordRow:
    """Convert keyword_view row dict to KeywordRow dataclass (defensive)."""
    return KeywordRow(
        ad_group_id=str(d.get("ad_group_id", "")),
        ad_group_name=str(d.get("ad_group_name", "")),
        campaign_name=str(d.get("campaign_name", "")),
        keyword_id=str(d.get("keyword_id", "")),
        keyword_text=str(d.get("keyword_text", "")),
        match_type=str(d.get("match_type", "")),
        impressions=int(d.get("impressions", 0)),
        clicks=int(d.get("clicks", 0)),
        cost_brl=float(d.get("cost_brl", 0.0)),
        conversions=int(d.get("conversions", 0)),
        status=str(d.get("status", "")),
    )
```

- [ ] **Step 2: Create `tests/unit/test_audit_zombie_keywords_queries.py` com 4 tests**

```python
"""Unit tests for audit_zombie_keywords GAQL builder + boundary parser (Sprint 3b.36)."""

from src.google_ads.queries.audit_zombie_keywords import (
    build_audit_zombie_keywords_query,
    dict_to_keyword_row,
)


def test_build_query_includes_required_fields():
    q = build_audit_zombie_keywords_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        ad_group_ids=None,
    )
    required_fields = [
        "ad_group_criterion.criterion_id",
        "ad_group_criterion.keyword.text",
        "ad_group_criterion.keyword.match_type",
        "ad_group_criterion.status",
        "ad_group.id",
        "ad_group.name",
        "campaign.name",
        "metrics.impressions",
        "metrics.clicks",
        "metrics.cost_micros",
        "metrics.conversions",
    ]
    for field in required_fields:
        assert field in q
    assert "FROM keyword_view" in q


def test_build_query_filters_enabled_and_not_negative():
    q = build_audit_zombie_keywords_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        ad_group_ids=None,
    )
    assert "ad_group_criterion.status = 'ENABLED'" in q
    assert "ad_group_criterion.negative = FALSE" in q


def test_build_query_ad_group_ids_filter():
    q = build_audit_zombie_keywords_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        ad_group_ids=["123", "456"],
    )
    assert "ad_group.id IN (123,456)" in q


def test_dict_to_keyword_row_handles_missing_fields():
    """Boundary parser defensive defaults."""
    d: dict = {"keyword_text": "test"}
    row = dict_to_keyword_row(d)
    assert row.keyword_text == "test"
    assert row.ad_group_id == ""
    assert row.impressions == 0
    assert row.clicks == 0
    assert row.cost_brl == 0.0
    assert row.conversions == 0
    assert row.status == ""
```

- [ ] **Step 3: Run tests — expect 4/4 PASS**

```bash
python -m pytest tests/unit/test_audit_zombie_keywords_queries.py -v
```

Expected: 4 passed.

- [ ] **Step 4: Run ruff + mypy**

```bash
python -m ruff check src/google_ads/queries/audit_zombie_keywords.py tests/unit/test_audit_zombie_keywords_queries.py
python -m ruff format --check src/google_ads/queries/audit_zombie_keywords.py tests/unit/test_audit_zombie_keywords_queries.py
python -m mypy src/google_ads/queries/audit_zombie_keywords.py
```

Expected: All checks PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/queries/audit_zombie_keywords.py tests/unit/test_audit_zombie_keywords_queries.py
git commit -m "feat(queries): audit_zombie_keywords GAQL builder + parser (Sprint 3b.36 A2)"
```

---

## Task A3: Tool wrapper + 3 integration tests + schema

**Files:**
- Create: `src/mcp/tools/audit_zombie_keywords.py`
- Create: `tests/integration/test_audit_zombie_keywords.py`
- Modify: `tests/unit/test_tools_schemas.py`

**Depende de A1 + A2** (importa dataclasses + função + GAQL builder + parsers).

- [ ] **Step 1: Create `src/mcp/tools/audit_zombie_keywords.py`**

```python
"""Tool: audit_zombie_keywords — detectar keywords waste (impressions=0 + clicks=0).

Sprint 3b.36 — ICE 315 (#11 backlog dogfood 2026-05-19 cleanup massivo MO-JP).
Cleanup recurring tool: gestor identifica keywords ENABLED com zero activity
em window LAST_30_DAYS, pausa/remove pra reduzir waste.
"""

from typing import Any

from src.google_ads.flag_zombie_keywords import flag_zombie_keywords
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.audit_zombie_keywords import (
    build_audit_zombie_keywords_query,
    dict_to_keyword_row,
    parse_keyword_view_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "ad_group_ids": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]+$"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Opcional. Filtra audit a estes ad_group_ids. Default: conta inteira.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000,
            "default": 200,
            "description": "Máximo zombies retornados. truncated:true se exceder.",
        },
        "date_range": {
            "type": "string",
            "enum": ["LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS", "LAST_90_DAYS"],
            "default": "LAST_30_DAYS",
            "description": "Preset. Override por start_date+end_date se ambos passados.",
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="audit_zombie_keywords",
    description=(
        "Detecta keywords zumbis: ENABLED com zero activity (impressions=0 AND "
        "clicks=0) em window LAST_30_DAYS (default). Pre-cleanup decision tool — "
        "use pra identificar waste antes de pausar/remover em massa. Output flat "
        "list ordenada por ad_group_name ASC + keyword_text ASC pra agrupar "
        "visualmente. Filtros: ad_group_ids[] opcional, limit (default 200, max "
        "1000), date_range preset OR start_date+end_date custom. Server-side "
        "hardcoded: status=ENABLED + negative=FALSE. Sempre auditado."
    ),
    input_schema=_SCHEMA,
)
async def audit_zombie_keywords(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    ad_group_ids = args.get("ad_group_ids")
    limit = args.get("limit", 200)

    start_date_obj, end_date_obj = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )

    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    query = build_audit_zombie_keywords_query(
        start_date=start_date,
        end_date=end_date,
        ad_group_ids=ad_group_ids,
    )

    raw_rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=parse_keyword_view_row,
        operation_name="audit_zombie_keywords",
        audit_this_call=True,
        params_summary={
            "ad_group_ids": ad_group_ids,
            "limit": limit,
            "date_window": f"{start_date} to {end_date}",
        },
    )

    keyword_rows = [dict_to_keyword_row(d) for d in raw_rows]
    zombies, total = flag_zombie_keywords(keyword_rows, limit=limit)

    days = (end_date_obj - start_date_obj).days + 1

    return {
        "customer_id": customer_id,
        "date_range_resolved": {
            "start": start_date,
            "end": end_date,
            "days": days,
        },
        "filters_applied": {
            "ad_group_ids": ad_group_ids,
            "limit": limit,
        },
        "total_zombies": total,
        "truncated": total > limit,
        "returned_count": len(zombies),
        "zombies": [
            {
                "ad_group_id": z.ad_group_id,
                "ad_group_name": z.ad_group_name,
                "campaign_name": z.campaign_name,
                "keyword_id": z.keyword_id,
                "keyword_text": z.keyword_text,
                "match_type": z.match_type,
                "impressions": z.impressions,
                "clicks": z.clicks,
                "cost_brl": z.cost_brl,
                "conversions": z.conversions,
                "status": z.status,
            }
            for z in zombies
        ],
    }
```

- [ ] **Step 2: Create `tests/integration/test_audit_zombie_keywords.py` com 3 tests**

```python
"""Integration tests for audit_zombie_keywords (Sprint 3b.36)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.asyncio
async def test_returns_zombies_shape(bound_context):
    """T1 cenário smoke: wire-up fake rows → response shape correto."""
    from src.mcp.tools.audit_zombie_keywords import audit_zombie_keywords

    fake_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": "K1",
            "keyword_text": "andaime metálico",
            "match_type": "BROAD",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        },
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": "K2",
            "keyword_text": "andaime suspenso",
            "match_type": "PHRASE",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        },
    ]
    with patch(
        "src.mcp.tools.audit_zombie_keywords.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_zombie_keywords({"customer_id": "1234567890"})

    assert result["customer_id"] == "1234567890"
    assert result["total_zombies"] == 2
    assert result["truncated"] is False
    assert result["returned_count"] == 2
    assert len(result["zombies"]) == 2
    # Sorted by ad_group_name + keyword_text ASC
    assert result["zombies"][0]["keyword_text"] == "andaime metálico"
    assert result["zombies"][1]["keyword_text"] == "andaime suspenso"


@pytest.mark.asyncio
async def test_ad_group_ids_filter_passthrough(bound_context):
    """T2 cenário smoke: ad_group_ids passa ao GAQL builder."""
    from src.mcp.tools.audit_zombie_keywords import audit_zombie_keywords

    captured_query: dict = {}

    async def fake_run_report(*args, **kwargs):
        captured_query["query"] = kwargs.get("query", "")
        return []

    with patch(
        "src.mcp.tools.audit_zombie_keywords.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        await audit_zombie_keywords(
            {"customer_id": "1234567890", "ad_group_ids": ["123", "456"]}
        )

    assert "ad_group.id IN (123,456)" in captured_query["query"]


@pytest.mark.asyncio
async def test_truncation_when_total_exceeds_limit(bound_context):
    """T4 cenário smoke: 50 zombies + limit=10 → truncated=true."""
    from src.mcp.tools.audit_zombie_keywords import audit_zombie_keywords

    fake_rows = [
        {
            "ad_group_id": "1001",
            "ad_group_name": "AG1",
            "campaign_name": "C1",
            "keyword_id": f"K{i}",
            "keyword_text": f"kw_{i:03d}",
            "match_type": "BROAD",
            "impressions": 0,
            "clicks": 0,
            "cost_brl": 0.0,
            "conversions": 0,
            "status": "ENABLED",
        }
        for i in range(50)
    ]
    with patch(
        "src.mcp.tools.audit_zombie_keywords.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_zombie_keywords({"customer_id": "1234567890", "limit": 10})

    assert result["total_zombies"] == 50
    assert result["truncated"] is True
    assert result["returned_count"] == 10
```

- [ ] **Step 3: Bump tool count em `tests/unit/test_tools_schemas.py`**

Add `"audit_zombie_keywords"` alfabético em ambos:
- `test_all_phase_2_tools_registered`
- `test_no_unexpected_tools`

Position: entre `audit_quality_score` e `bulk_pause_by_query`.

```bash
grep -n "audit_quality_score" tests/unit/test_tools_schemas.py
```

Auto-discovery test usa contagem dinâmica — não precisa hardcode 56.

- [ ] **Step 4: Run tests + pre-push gate**

```bash
python -m pytest tests/integration/test_audit_zombie_keywords.py tests/unit/test_tools_schemas.py -v
python scripts/check_pre_push.py
```

Expected: 3 integration + tool count tests PASS. Pre-push 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/tools/audit_zombie_keywords.py tests/integration/test_audit_zombie_keywords.py tests/unit/test_tools_schemas.py
git commit -m "feat(mcp): audit_zombie_keywords tool wrapper + integration tests (Sprint 3b.36 A3)"
```

---

## Task A4: Smoke runbook via subagent

**Files:**
- Create: `docs/operacao/phase-3b-36-bootstrap.md`

**PARALELO ao A3** (geração não depende código).

- [ ] **Step 1: Dispatch smoke-runbook-generator subagent**

Prompt:
```
Generate phase-3b-36-bootstrap.md smoke runbook para Sprint 3b.36 (audit_zombie_keywords, 56ª tool).
Spec: docs/superpowers/specs/2026-05-21-sprint-3b-36-audit-zombie-keywords-design.md
Plan: docs/superpowers/plans/2026-05-21-sprint-3b-36-audit-zombie-keywords.md

6 cenários a cobrir (referência spec Section 6):
- T1: Default LAST_30_DAYS panorâmico MO-JP 7862230676
- T2: ad_group_ids filter MO-JP (1 ad_group específico)
- T3: Custom date range MO-JP
- T4: limit truncation MO-JP (limit=10 em conta com 20+ zombies)
- T5: Conta clean (poucos zombies) ML Antiguidades 7455088726
- T6: Caso real dogfood 19/05 — MO-JP cleanup recurring (detecta keywords ENABLED zumbi candidates pra pause/remove)

Production URL: https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app
```

- [ ] **Step 2: Review generated runbook + commit**

```bash
git add docs/operacao/phase-3b-36-bootstrap.md
git commit -m "docs(smoke): phase-3b-36-bootstrap.md runbook (Sprint 3b.36 A4)"
```

---

## Task A5: Pre-push + push + smoke + signoff

- [ ] **Step 1: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS em ~40s.

- [ ] **Step 2: Push origin/main**

```bash
git push origin main
```

Expected: 4 commits pushed (A1 + A2 + A3 + A4).

- [ ] **Step 3: Watch CI + Deploy + verify /health**

```bash
gh run list --limit 3
gh run watch <deploy-run-id> --exit-status
curl -s -o /dev/null -w "%{http_code}\n" https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: CI green + Deploy green + /health 200.

- [ ] **Step 4: Execute 6 smoke tests em produção**

Após reload Claude se necessário (MCP schema cache), executar T1-T6 do runbook. Preencher result blocks in-place no runbook.

- [ ] **Step 5: Catalog F-findings se houver** (zero expected — pattern bem cravado)

- [ ] **Step 6: Append Sprint 3b.36 entry em sprint-history.md**

Format consistente. Inclui: production rev, tool count 55→56, smoke X/6, F-findings, references.

- [ ] **Step 7: Bump CLAUDE.md**

- `Sprint 3b.1 → 3b.35 (35 sprints)` → `3b.1 → 3b.36 (36 sprints)`
- `**Shipped (55 tools)**` → `**Shipped (56 tools)**`
- Production revision update
- Pending/future: bump candidate list

- [ ] **Step 8: Commit signoff + push**

```bash
git add docs/operacao/sprint-history.md CLAUDE.md docs/operacao/phase-3b-36-bootstrap.md
git commit -m "docs(signoff): Sprint 3b.36 audit_zombie_keywords smoke X/6 PASS"
git push origin main
```

---

## Self-Review

**1. Spec coverage check:**

| Spec section | Task que implementa |
|---|---|
| Section 1 Architecture | A1 (módulo) + A2 (queries) + A3 (wrapper) |
| Section 2 Schema | A3 Step 1 |
| Section 3 Output shape | A3 Step 1 (return dict) |
| Section 4 Algorithm | A1 Step 1 (flag_zombie_keywords function) |
| Section 5 V0 cuts | N/A (documentation only) |
| Section 6 Testing | A1 (10 unit) + A2 (4 unit) + A3 (3 integration) + A4 (runbook) + A5 (smoke) |

Todas sections cobertas.

**2. Placeholder scan:** zero "TBD/TODO". Cada step tem código concreto.

**3. Type consistency:**
- `KeywordRow` definido em A1, importado em A2 (queries/audit_zombie_keywords) + A3 (via dict_to_keyword_row) ✅
- `ZombieKeyword` output type em A1, serialized em A3 wrapper ✅
- `flag_zombie_keywords(rows, *, limit) → tuple[list[ZombieKeyword], int]` signature consistente A1→A3 ✅
- GAQL builder name: `build_audit_zombie_keywords_query` consistente A2→A3 ✅
- Parser names: `parse_keyword_view_row` + `dict_to_keyword_row` consistente ✅

**Estimated total:** ~90 min (A1 ~20 + A2 ~15 + A3 ~20 + A4 ~5 + A5 ~30).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-21-sprint-3b-36-audit-zombie-keywords.md`.

**Recomendação:** Subagent-Driven (padrão das últimas 5 sprints).
