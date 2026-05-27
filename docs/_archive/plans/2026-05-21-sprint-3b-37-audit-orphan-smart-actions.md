# Sprint 3b.37 — `audit_orphan_smart_actions` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `audit_orphan_smart_actions` (57ª MCP tool) — detecta ConversionActions ENABLED com `metrics.all_conversions == 0.0` em window LAST_30_DAYS, ordenadas por (category, origin, name) (ICE 288, cleanup recurring dogfood MO-JP 19/05).

**Architecture:** Pure aggregator (`src/google_ads/flag_orphan_smart_actions.py`) + GAQL builder (`src/google_ads/queries/audit_orphan_smart_actions.py`) + wrapper (`src/mcp/tools/audit_orphan_smart_actions.py`). Padrão idêntico Sprint 3b.30/3b.31/3b.33/3b.35/3b.36.

**Tech Stack:** Python 3.12 com frozen+slots dataclasses, pytest com AsyncMock+patch, ruff+mypy strict.

**Reference:** [`docs/superpowers/specs/2026-05-21-sprint-3b-37-audit-orphan-smart-actions-design.md`](../specs/2026-05-21-sprint-3b-37-audit-orphan-smart-actions-design.md)

---

## File Structure

**Create:**
- `src/google_ads/flag_orphan_smart_actions.py` — pure module com 2 dataclasses + `flag_orphan_smart_actions()` filter+sort+truncate
- `src/google_ads/queries/audit_orphan_smart_actions.py` — GAQL builder + row parser + dict→dataclass boundary
- `src/mcp/tools/audit_orphan_smart_actions.py` — tool wrapper MCP
- `tests/unit/test_flag_orphan_smart_actions.py` — 8 pure module tests
- `tests/unit/test_audit_orphan_smart_actions_queries.py` — 5 GAQL + boundary parser tests
- `tests/integration/test_audit_orphan_smart_actions.py` — 3 wire-up tests

**Modify:**
- `tests/unit/test_tools_schemas.py` — bump tool count 56→57 + add `audit_orphan_smart_actions` ao allowlist

---

## Task A1: `flag_orphan_smart_actions.py` pure module + 8 unit tests

**Files:**
- Create: `src/google_ads/flag_orphan_smart_actions.py`
- Create: `tests/unit/test_flag_orphan_smart_actions.py`

**Sequencial:** Foundational. A2 + A3 importam `ConversionActionRow` + `OrphanAction` + `flag_orphan_smart_actions`.

- [ ] **Step 1: Create `src/google_ads/flag_orphan_smart_actions.py`**

```python
"""Pure client-side orphan ConversionAction detection (Sprint 3b.37 audit_orphan_smart_actions).

Filtra ConversionActions ENABLED com zero activity (all_conversions=0.0) em
window de N dias. Sort por (category, origin, name) ASC pra agrupar visualmente.
Cleanup recurring MO-JP (dogfood 19/05 lição 41+).

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConversionActionRow:
    """Boundary input — dict de conversion_action GAQL converte pra cá."""

    conversion_action_id: str
    name: str
    category: str
    origin: str
    primary_for_goal: bool
    status: str
    all_conversions: float


@dataclass(frozen=True, slots=True)
class OrphanAction:
    """Output: ConversionAction flagged como orphan (all_conversions=0)."""

    conversion_action_id: str
    name: str
    category: str
    origin: str
    primary_for_goal: bool
    status: str
    all_conversions: float


def flag_orphan_smart_actions(
    rows: list[ConversionActionRow],
    *,
    limit: int,
) -> tuple[list[OrphanAction], int]:
    """Filter orphans, sort, truncate.

    Args:
        rows: list[ConversionActionRow] from GAQL conversion_action (já filtered
              server-side por status=ENABLED + optional category).
        limit: max output entries.

    Returns:
        (orphans, total_pre_truncate). Sorted by category ASC, origin ASC, name ASC.

    Algorithm:
    1. Filter: keep only rows com all_conversions == 0.0 (zero conversion activity).
    2. Sort: category ASC, origin ASC, name ASC (visual grouping).
    3. Truncate to limit. Return (orphans, total_pre_truncate).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    orphans = [
        OrphanAction(
            conversion_action_id=r.conversion_action_id,
            name=r.name,
            category=r.category,
            origin=r.origin,
            primary_for_goal=r.primary_for_goal,
            status=r.status,
            all_conversions=r.all_conversions,
        )
        for r in rows
        if r.all_conversions == 0.0
    ]
    orphans.sort(key=lambda o: (o.category, o.origin, o.name))
    total = len(orphans)
    return orphans[:limit], total
```

- [ ] **Step 2: Create `tests/unit/test_flag_orphan_smart_actions.py` com 8 tests**

```python
"""Unit tests for flag_orphan_smart_actions pure module (Sprint 3b.37)."""

from src.google_ads.flag_orphan_smart_actions import (
    ConversionActionRow,
    flag_orphan_smart_actions,
)


def _make_ca(
    *,
    conversion_action_id: str = "1001",
    name: str = "Whatsapp - JPA",
    category: str = "CONTACT",
    origin: str = "WEBSITE",
    primary_for_goal: bool = True,
    status: str = "ENABLED",
    all_conversions: float = 0.0,
) -> ConversionActionRow:
    return ConversionActionRow(
        conversion_action_id=conversion_action_id,
        name=name,
        category=category,
        origin=origin,
        primary_for_goal=primary_for_goal,
        status=status,
        all_conversions=all_conversions,
    )


def test_empty_rows_returns_empty():
    orphans, total = flag_orphan_smart_actions([], limit=10)
    assert orphans == []
    assert total == 0


def test_filter_keeps_zero_conversions():
    rows = [_make_ca(all_conversions=0.0)]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert len(orphans) == 1
    assert total == 1


def test_filter_excludes_positive_conversions():
    """ConversionAction com >0 conversions NÃO é orphan."""
    rows = [_make_ca(all_conversions=5.0)]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert orphans == []
    assert total == 0


def test_filter_excludes_fractional_conversions():
    """ConversionAction com 0.5 conversions NÃO é orphan (Google can return fractional)."""
    rows = [_make_ca(all_conversions=0.5)]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert orphans == []
    assert total == 0


def test_sort_by_category_origin_name():
    rows = [
        _make_ca(conversion_action_id="A", category="PURCHASE", origin="WEBSITE", name="Zulu"),
        _make_ca(conversion_action_id="B", category="CONTACT", origin="CALL_FROM_ADS", name="Alpha"),
        _make_ca(conversion_action_id="C", category="CONTACT", origin="WEBSITE", name="Mike"),
        _make_ca(conversion_action_id="D", category="CONTACT", origin="WEBSITE", name="Alpha"),
    ]
    orphans, _ = flag_orphan_smart_actions(rows, limit=10)
    keys = [(o.category, o.origin, o.name) for o in orphans]
    assert keys == [
        ("CONTACT", "CALL_FROM_ADS", "Alpha"),
        ("CONTACT", "WEBSITE", "Alpha"),
        ("CONTACT", "WEBSITE", "Mike"),
        ("PURCHASE", "WEBSITE", "Zulu"),
    ]


def test_truncation_limit_exceeded():
    """50 orphans + limit=10 → returns 10, total=50."""
    rows = [
        _make_ca(conversion_action_id=str(i), name=f"ca_{i:03d}")
        for i in range(50)
    ]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert len(orphans) == 10
    assert total == 50


def test_truncation_limit_not_exceeded():
    """5 orphans + limit=200 → returns 5, total=5."""
    rows = [_make_ca(conversion_action_id=str(i)) for i in range(5)]
    orphans, total = flag_orphan_smart_actions(rows, limit=200)
    assert len(orphans) == 5
    assert total == 5


def test_total_count_pre_truncate_preserved():
    """Mix de orphans + non-orphans: total reflete POST-filter, PRE-truncate."""
    rows = [
        _make_ca(conversion_action_id="A", all_conversions=0.0),   # orphan
        _make_ca(conversion_action_id="B", all_conversions=3.0),   # not orphan
        _make_ca(conversion_action_id="C", all_conversions=0.0),   # orphan
        _make_ca(conversion_action_id="D", all_conversions=12.5),  # not orphan
    ]
    orphans, total = flag_orphan_smart_actions(rows, limit=10)
    assert len(orphans) == 2
    assert total == 2  # only 2 orphans
```

- [ ] **Step 3: Run tests — expect 8/8 PASS**

```bash
python -m pytest tests/unit/test_flag_orphan_smart_actions.py -v
```

Expected: 8 passed.

- [ ] **Step 4: Run ruff + mypy**

```bash
python -m ruff check src/google_ads/flag_orphan_smart_actions.py tests/unit/test_flag_orphan_smart_actions.py
python -m ruff format --check src/google_ads/flag_orphan_smart_actions.py tests/unit/test_flag_orphan_smart_actions.py
python -m mypy src/google_ads/flag_orphan_smart_actions.py
```

Expected: All checks PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/flag_orphan_smart_actions.py tests/unit/test_flag_orphan_smart_actions.py
git commit -m "feat(google_ads): flag_orphan_smart_actions pure module + 8 unit tests (Sprint 3b.37 A1)"
```

---

## Task A2: GAQL builder + 5 unit tests

**Files:**
- Create: `src/google_ads/queries/audit_orphan_smart_actions.py`
- Create: `tests/unit/test_audit_orphan_smart_actions_queries.py`

**Pode rodar PARALELO ao A1** (arquivos isolated).

- [ ] **Step 1: Create `src/google_ads/queries/audit_orphan_smart_actions.py`**

```python
"""GAQL builder for audit_orphan_smart_actions tool (Sprint 3b.37).

Single query sobre conversion_action com:
- Date range filter (gaql_date_clause helper) — segments.date
- status=ENABLED hardcoded server-side
- Optional category filter
- 6 fields + metrics.all_conversions SELECT
"""

from datetime import date
from typing import Any

from src.google_ads.flag_orphan_smart_actions import ConversionActionRow
from src.google_ads.queries._common import gaql_date_clause


def build_audit_orphan_smart_actions_query(
    *,
    start_date: str,
    end_date: str,
    category: str | None,
) -> str:
    """GAQL pra conversion_action com metrics aggregadas em window.

    Filters: date range via gaql_date_clause + status=ENABLED + optional category.
    Returns one row per conversion_action with metrics aggregated over date window.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    date_clause = gaql_date_clause(start, end)

    category_clause = ""
    if category:
        category_clause = f" AND conversion_action.category = '{category}'"

    return f"""
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.category,
          conversion_action.origin,
          conversion_action.primary_for_goal,
          conversion_action.status,
          metrics.all_conversions
        FROM conversion_action
        WHERE {date_clause}
          AND conversion_action.status = 'ENABLED'{category_clause}
    """.strip()


def parse_conversion_action_row(row: Any) -> dict[str, Any]:
    """Parse conversion_action GAQL row → dict (boundary).

    Uses `.name` on category/origin/status enums (Sprint 3b.7 lesson:
    proto-plus v20+ regression — `str(enum)` retorna integer, `.name`
    retorna 'CONTACT'/'WEBSITE'/'ENABLED').
    """
    ca = row.conversion_action
    return {
        "conversion_action_id": str(ca.id),
        "name": ca.name,
        "category": ca.category.name,
        "origin": ca.origin.name,
        "primary_for_goal": bool(ca.primary_for_goal),
        "status": ca.status.name,
        "all_conversions": float(row.metrics.all_conversions),
    }


def dict_to_conversion_action_row(d: dict[str, Any]) -> ConversionActionRow:
    """Convert conversion_action row dict to ConversionActionRow dataclass (defensive)."""
    return ConversionActionRow(
        conversion_action_id=str(d.get("conversion_action_id", "")),
        name=str(d.get("name", "")),
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        primary_for_goal=bool(d.get("primary_for_goal", False)),
        status=str(d.get("status", "")),
        all_conversions=float(d.get("all_conversions", 0.0)),
    )
```

- [ ] **Step 2: Create `tests/unit/test_audit_orphan_smart_actions_queries.py` com 5 tests**

```python
"""Unit tests for audit_orphan_smart_actions GAQL builder + boundary parser (Sprint 3b.37)."""

from types import SimpleNamespace

from src.google_ads.queries.audit_orphan_smart_actions import (
    build_audit_orphan_smart_actions_query,
    dict_to_conversion_action_row,
    parse_conversion_action_row,
)


def test_build_query_includes_required_fields():
    q = build_audit_orphan_smart_actions_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        category=None,
    )
    required_fields = [
        "conversion_action.id",
        "conversion_action.name",
        "conversion_action.category",
        "conversion_action.origin",
        "conversion_action.primary_for_goal",
        "conversion_action.status",
        "metrics.all_conversions",
    ]
    for field in required_fields:
        assert field in q
    assert "FROM conversion_action" in q


def test_build_query_filters_enabled():
    q = build_audit_orphan_smart_actions_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        category=None,
    )
    assert "conversion_action.status = 'ENABLED'" in q


def test_build_query_category_filter():
    q = build_audit_orphan_smart_actions_query(
        start_date="2026-04-21",
        end_date="2026-05-21",
        category="CONTACT",
    )
    assert "conversion_action.category = 'CONTACT'" in q


def test_parse_conversion_action_row_handles_enums_and_floats():
    """Regression guard against proto-plus v20+ regression (str(enum) returns int)
    + float casting on all_conversions + int → str on id."""
    fake_row = SimpleNamespace(
        conversion_action=SimpleNamespace(
            id=12345,
            name="Whatsapp - JPA",
            category=SimpleNamespace(name="CONTACT"),
            origin=SimpleNamespace(name="WEBSITE"),
            primary_for_goal=True,
            status=SimpleNamespace(name="ENABLED"),
        ),
        metrics=SimpleNamespace(all_conversions=0.0),
    )
    result = parse_conversion_action_row(fake_row)
    assert result["conversion_action_id"] == "12345"  # int → str
    assert result["category"] == "CONTACT"  # .name resolution
    assert result["origin"] == "WEBSITE"  # .name resolution
    assert result["status"] == "ENABLED"  # .name resolution
    assert result["primary_for_goal"] is True
    assert result["all_conversions"] == 0.0  # float casting
    assert result["name"] == "Whatsapp - JPA"


def test_dict_to_conversion_action_row_handles_missing_fields():
    """Boundary parser defensive defaults."""
    d: dict = {"name": "test"}
    row = dict_to_conversion_action_row(d)
    assert row.name == "test"
    assert row.conversion_action_id == ""
    assert row.category == ""
    assert row.origin == ""
    assert row.primary_for_goal is False
    assert row.status == ""
    assert row.all_conversions == 0.0
```

- [ ] **Step 3: Run tests — expect 5/5 PASS**

```bash
python -m pytest tests/unit/test_audit_orphan_smart_actions_queries.py -v
```

Expected: 5 passed.

- [ ] **Step 4: Run ruff + mypy**

```bash
python -m ruff check src/google_ads/queries/audit_orphan_smart_actions.py tests/unit/test_audit_orphan_smart_actions_queries.py
python -m ruff format --check src/google_ads/queries/audit_orphan_smart_actions.py tests/unit/test_audit_orphan_smart_actions_queries.py
python -m mypy src/google_ads/queries/audit_orphan_smart_actions.py
```

Expected: All checks PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/queries/audit_orphan_smart_actions.py tests/unit/test_audit_orphan_smart_actions_queries.py
git commit -m "feat(queries): audit_orphan_smart_actions GAQL builder + parser (Sprint 3b.37 A2)"
```

---

## Task A3: Tool wrapper + 3 integration tests + schema

**Files:**
- Create: `src/mcp/tools/audit_orphan_smart_actions.py`
- Create: `tests/integration/test_audit_orphan_smart_actions.py`
- Modify: `tests/unit/test_tools_schemas.py`

**Depende de A1 + A2** (importa dataclasses + função + GAQL builder + parsers).

- [ ] **Step 1: Create `src/mcp/tools/audit_orphan_smart_actions.py`**

```python
"""Tool: audit_orphan_smart_actions — detectar ConversionActions sem uso real.

Sprint 3b.37 — ICE 288 (#12 backlog dogfood 2026-05-19 cleanup massivo MO-JP).
Cleanup recurring: gestor identifica ConversionActions ENABLED com zero
conversions em window LAST_30_DAYS, pausa/remove pra reduzir noise no dashboard.
"""

from typing import Any

from src.google_ads.flag_orphan_smart_actions import flag_orphan_smart_actions
from src.google_ads.queries._common import resolve_date_window
from src.google_ads.queries.audit_orphan_smart_actions import (
    build_audit_orphan_smart_actions_query,
    dict_to_conversion_action_row,
    parse_conversion_action_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

# Sprint 3b.19A whitelist — 13 V4-focused categorias (idêntica audit_goal_attribution 3b.35)
_V4_CATEGORIES = [
    "DEFAULT",
    "PAGE_VIEW",
    "PURCHASE",
    "SIGNUP",
    "SUBMIT_LEAD_FORM",
    "BOOK_APPOINTMENT",
    "REQUEST_QUOTE",
    "GET_DIRECTIONS",
    "OUTBOUND_CLICK",
    "CONTACT",
    "ENGAGEMENT",
    "STORE_VISIT",
    "STORE_SALE",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "category": {
            "type": "string",
            "enum": _V4_CATEGORIES,
            "description": (
                "Opcional. Filtra audit a uma única ConversionAction.category. "
                "Whitelist V4 13 valores (F17/F18/F19-safe — mesma de "
                "create_conversion_action 3b.19A e audit_goal_attribution 3b.35)."
            ),
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": (
                "Máximo orphans retornados. truncated:true se exceder. "
                "Default 100 (lição 3b.36: limit=200 estourou MCP cap em "
                "conta com 500+ entries)."
            ),
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
    name="audit_orphan_smart_actions",
    description=(
        "Detecta ConversionActions orphan: ENABLED com zero conversions "
        "(metrics.all_conversions=0.0) em window LAST_30_DAYS (default). "
        "Pre-cleanup decision tool — use pra identificar tracking pixels "
        "obsoletos, ações de campanhas removidas, conversion actions criadas "
        "em testes que continuam ENABLED sem trackar nada útil. Output flat "
        "list ordenada por (category, origin, name) ASC pra agrupar "
        "visualmente. Filtros: category opcional (whitelist 13 V4 valores), "
        "limit (default 100, max 500), date_range preset OR start_date+"
        "end_date custom. Server-side hardcoded: status=ENABLED. Sempre auditado."
    ),
    input_schema=_SCHEMA,
)
async def audit_orphan_smart_actions(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    category = args.get("category")
    limit = args.get("limit", 100)

    start_date_obj, end_date_obj = resolve_date_window(
        date_range=args.get("date_range", "LAST_30_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )

    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    query = build_audit_orphan_smart_actions_query(
        start_date=start_date,
        end_date=end_date,
        category=category,
    )

    raw_rows = await run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=parse_conversion_action_row,
        operation_name="audit_orphan_smart_actions",
        audit_this_call=True,
        params_summary={
            "category": category,
            "limit": limit,
            "date_window": f"{start_date} to {end_date}",
        },
    )

    action_rows = [dict_to_conversion_action_row(d) for d in raw_rows]
    orphans, total = flag_orphan_smart_actions(action_rows, limit=limit)

    days = (end_date_obj - start_date_obj).days + 1

    return {
        "customer_id": customer_id,
        "date_range_resolved": {
            "start": start_date,
            "end": end_date,
            "days": days,
        },
        "filters_applied": {
            "category": category,
            "limit": limit,
        },
        "total_orphans": total,
        "truncated": total > limit,
        "returned_count": len(orphans),
        "orphans": [
            {
                "conversion_action_id": o.conversion_action_id,
                "name": o.name,
                "category": o.category,
                "origin": o.origin,
                "primary_for_goal": o.primary_for_goal,
                "status": o.status,
                "all_conversions": o.all_conversions,
            }
            for o in orphans
        ],
    }
```

- [ ] **Step 2: Create `tests/integration/test_audit_orphan_smart_actions.py` com 3 tests**

```python
"""Integration tests for audit_orphan_smart_actions (Sprint 3b.37)."""

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
async def test_returns_orphans_shape(bound_context):
    """T1 cenário smoke: wire-up fake rows → response shape correto."""
    from src.mcp.tools.audit_orphan_smart_actions import audit_orphan_smart_actions

    fake_rows = [
        {
            "conversion_action_id": "1001",
            "name": "Whatsapp - Antigo",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "status": "ENABLED",
            "all_conversions": 0.0,
        },
        {
            "conversion_action_id": "1002",
            "name": "Email Form",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": False,
            "status": "ENABLED",
            "all_conversions": 0.0,
        },
    ]
    with patch(
        "src.mcp.tools.audit_orphan_smart_actions.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_orphan_smart_actions({"customer_id": "1234567890"})

    assert result["customer_id"] == "1234567890"
    assert result["total_orphans"] == 2
    assert result["truncated"] is False
    assert result["returned_count"] == 2
    assert len(result["orphans"]) == 2
    # Sorted by category, origin, name ASC
    assert result["orphans"][0]["name"] == "Email Form"
    assert result["orphans"][1]["name"] == "Whatsapp - Antigo"


@pytest.mark.asyncio
async def test_category_filter_passthrough(bound_context):
    """T2 cenário smoke: category filter passa ao GAQL builder."""
    from src.mcp.tools.audit_orphan_smart_actions import audit_orphan_smart_actions

    captured: dict = {}

    async def fake_run_report(*args, **kwargs):
        captured["query"] = kwargs.get("query", "")
        return []

    with patch(
        "src.mcp.tools.audit_orphan_smart_actions.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        await audit_orphan_smart_actions(
            {"customer_id": "1234567890", "category": "PURCHASE"}
        )

    assert "conversion_action.category = 'PURCHASE'" in captured["query"]


@pytest.mark.asyncio
async def test_truncation_when_total_exceeds_limit(bound_context):
    """T4 cenário smoke: 50 orphans + limit=10 → truncated=true."""
    from src.mcp.tools.audit_orphan_smart_actions import audit_orphan_smart_actions

    fake_rows = [
        {
            "conversion_action_id": str(i),
            "name": f"ca_{i:03d}",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": False,
            "status": "ENABLED",
            "all_conversions": 0.0,
        }
        for i in range(50)
    ]
    with patch(
        "src.mcp.tools.audit_orphan_smart_actions.run_report",
        AsyncMock(return_value=fake_rows),
    ):
        result = await audit_orphan_smart_actions({"customer_id": "1234567890", "limit": 10})

    assert result["total_orphans"] == 50
    assert result["truncated"] is True
    assert result["returned_count"] == 10
```

- [ ] **Step 3: Bump tool count em `tests/unit/test_tools_schemas.py`**

Add `"audit_orphan_smart_actions"` alfabético em ambos allowlists:
- `test_all_phase_2_tools_registered`
- `test_no_unexpected_tools`

Position: entre `audit_goal_attribution` e `audit_quality_score`.

```bash
grep -n "audit_goal_attribution" tests/unit/test_tools_schemas.py
```

- [ ] **Step 4: Run tests + pre-push gate**

```bash
python -m pytest tests/integration/test_audit_orphan_smart_actions.py tests/unit/test_tools_schemas.py -v
python scripts/check_pre_push.py
```

Expected: 3 integration + tool count PASS. Pre-push 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/tools/audit_orphan_smart_actions.py tests/integration/test_audit_orphan_smart_actions.py tests/unit/test_tools_schemas.py
git commit -m "feat(mcp): audit_orphan_smart_actions tool wrapper + integration tests (Sprint 3b.37 A3)"
```

---

## Task A4: Smoke runbook via subagent

**Files:**
- Create: `docs/operacao/phase-3b-37-bootstrap.md`

**PARALELO ao A3** (geração não depende código).

- [ ] **Step 1: Dispatch smoke-runbook-generator subagent**

```
Generate phase-3b-37-bootstrap.md smoke runbook para Sprint 3b.37 (audit_orphan_smart_actions, 57ª tool).
Spec: docs/superpowers/specs/2026-05-21-sprint-3b-37-audit-orphan-smart-actions-design.md
Plan: docs/superpowers/plans/2026-05-21-sprint-3b-37-audit-orphan-smart-actions.md

6 cenários:
- T1: Default LAST_30_DAYS panorâmico MO-JP 7862230676
- T2: category=CONTACT filter MO-JP
- T3: Custom date range MO-JP
- T4: limit truncation (limit=5 em conta com 10+)
- T5: category=PURCHASE ML Antiguidades 7455088726
- T6: Caso real cleanup ConversionActions MO-JP

Production URL: https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app
```

- [ ] **Step 2: Review generated runbook + commit**

```bash
git add docs/operacao/phase-3b-37-bootstrap.md
git commit -m "docs(smoke): phase-3b-37-bootstrap.md runbook (Sprint 3b.37 A4)"
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

- [ ] **Step 3: Watch CI + Deploy + verify /health**

```bash
gh run list --limit 3
gh run watch <deploy-run-id> --exit-status
curl -s -o /dev/null -w "%{http_code}\n" https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

- [ ] **Step 4: Execute 6 smoke tests em produção** (controller — reload Claude se MCP cache stale)

- [ ] **Step 5: Catalog F-findings se houver**

- [ ] **Step 6: Append Sprint 3b.37 entry em sprint-history.md**

- [ ] **Step 7: Bump CLAUDE.md tool count 56→57 + sprint count 36→37**

- [ ] **Step 8: Commit signoff + push**

---

## Self-Review

**1. Spec coverage check:**

| Spec section | Task |
|---|---|
| Section 1 Architecture | A1 + A2 + A3 |
| Section 2 Schema | A3 Step 1 |
| Section 3 Output shape | A3 Step 1 |
| Section 4 Algorithm | A1 Step 1 |
| Section 5 V0 cuts | N/A docs |
| Section 6 Testing | A1 (8) + A2 (5) + A3 (3) + A4 + A5 |

Todas sections cobertas.

**2. Placeholder scan:** zero TBD/TODO.

**3. Type consistency:**
- `ConversionActionRow` em A1, importado em A2 + A3 ✅
- `OrphanAction` em A1, serialized em A3 ✅
- `flag_orphan_smart_actions(rows, *, limit) → tuple[list[OrphanAction], int]` consistente ✅
- GAQL builder name `build_audit_orphan_smart_actions_query` consistente ✅
- Parser names `parse_conversion_action_row` + `dict_to_conversion_action_row` consistente ✅

**Estimated total:** ~90 min (A1 ~20 + A2 ~15 + A3 ~20 + A4 ~5 + A5 ~30).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-21-sprint-3b-37-audit-orphan-smart-actions.md`.

**Recomendação:** Subagent-Driven (padrão das últimas 6 sprints).
