# Sprint 3b.35 — `audit_goal_attribution` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `audit_goal_attribution` (55ª MCP tool) — pure aggregator + wrapper que cruza `conversion_action` com `customer_conversion_goal` pra revelar `biddable` flag por (category, origin), emitindo warning PT-BR quando primary→secondary impacta Smart Bidding (W3 dogfood 21/05 ICE 360).

**Architecture:** Pure aggregator (`src/google_ads/goal_attribution.py`) + 2 GAQL queries paralelas via `asyncio.gather` em wrapper (`src/mcp/tools/audit_goal_attribution.py`). Convert dict→dataclass na boundary, agrupar por (category, origin) tuple, gerar warning se biddable=true. Padrão idêntico Sprint 3b.30/3b.31/3b.33.

**Tech Stack:** Python 3.12 com frozen+slots dataclasses, asyncio.gather, pytest com AsyncMock+patch, ruff+mypy strict.

**Reference:** [`docs/superpowers/specs/2026-05-21-sprint-3b-35-audit-goal-attribution-design.md`](../specs/2026-05-21-sprint-3b-35-audit-goal-attribution-design.md)

---

## File Structure

**Create:**
- `src/google_ads/goal_attribution.py` — pure module com 5 dataclasses + `audit_goal_attribution()` + boundary parsers
- `src/google_ads/queries/audit_goal_attribution.py` — 2 GAQL builders + 2 row parsers
- `src/mcp/tools/audit_goal_attribution.py` — tool wrapper MCP
- `tests/unit/test_goal_attribution.py` — 18 pure module tests
- `tests/unit/test_audit_goal_attribution_queries.py` — 4 GAQL builder + 4 boundary parser tests
- `tests/integration/test_audit_goal_attribution.py` — 3 wire-up tests

**Modify:**
- `tests/unit/test_tools_schemas.py` — bump tool count 54→55 + add `audit_goal_attribution` ao allowlist

**No new GAQL queries fora dos 2 builders deste plan. F46 fix imune (tool não usa change_event).**

---

## Task A1: `goal_attribution.py` pure module + 18 unit tests

**Files:**
- Create: `src/google_ads/goal_attribution.py`
- Create: `tests/unit/test_goal_attribution.py`

**Sequencial:** Foundational task. A2 + A3 importam dataclasses + função `audit_goal_attribution`.

- [ ] **Step 1: Create `src/google_ads/goal_attribution.py`**

```python
"""Pure client-side goal attribution audit (Sprint 3b.35 audit_goal_attribution).

Cruza conversion_action com customer_conversion_goal pra revelar biddable flag
por (category, origin) — pre-flight check antes de mexer em primary_for_goal
via update_conversion_action. Resolve falsa premissa "cosmético KPI" descoberta
em dogfood 2026-05-21 lição 47.

Pure function, zero Google SDK imports — testable standalone.
"""

from dataclasses import dataclass
from typing import Any

# Status filter: tool retorna apenas ENABLED actions (PAUSED/REMOVED não afetam Smart Bidding).
_INCLUDED_STATUSES = frozenset({"ENABLED"})

_WARNING_BIDDABLE_TRUE = (
    "biddable=true: promover Secondary→Primary AFETA Smart Bidding "
    "(action vira biddable em todas campaigns que usam esta "
    "category+origin). NÃO é cosmético KPI."
)


@dataclass(frozen=True, slots=True)
class ConversionActionRow:
    """Boundary input — dict de conversion_action GAQL converte pra cá."""

    id: str
    name: str
    category: str
    origin: str
    primary_for_goal: bool
    include_in_conversions_metric: bool
    status: str


@dataclass(frozen=True, slots=True)
class CustomerConversionGoalRow:
    """Boundary input — dict de customer_conversion_goal GAQL converte pra cá."""

    category: str
    origin: str
    biddable: bool


@dataclass(frozen=True, slots=True)
class ActionSummary:
    """Output action representation (subset de ConversionActionRow)."""

    id: str
    name: str
    include_in_conversions_metric: bool
    status: str


@dataclass(frozen=True, slots=True)
class OriginSummary:
    category: str
    origin: str
    biddable: bool
    warning: str | None
    primary_count: int
    secondary_count: int
    primary_actions: tuple[ActionSummary, ...]
    secondary_actions: tuple[ActionSummary, ...]


@dataclass(frozen=True, slots=True)
class GoalAttributionResult:
    customer_id: str
    category_filter: str | None
    origin_summary: dict[str, OriginSummary]
    total_actions_audited: int
    origins_audited: tuple[str, ...]
    categories_audited: tuple[str, ...]


def dict_to_conversion_action_row(d: dict[str, Any]) -> ConversionActionRow:
    """Convert conversion_action row dict to ConversionActionRow dataclass.

    Defensive: missing fields default to "" or False.
    """
    return ConversionActionRow(
        id=str(d.get("id", "")),
        name=str(d.get("name", "")),
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        primary_for_goal=bool(d.get("primary_for_goal", False)),
        include_in_conversions_metric=bool(d.get("include_in_conversions_metric", False)),
        status=str(d.get("status", "")),
    )


def dict_to_customer_conversion_goal_row(d: dict[str, Any]) -> CustomerConversionGoalRow:
    """Convert customer_conversion_goal row dict to CustomerConversionGoalRow dataclass.

    Defensive: missing fields default to "" or False.
    """
    return CustomerConversionGoalRow(
        category=str(d.get("category", "")),
        origin=str(d.get("origin", "")),
        biddable=bool(d.get("biddable", False)),
    )


def audit_goal_attribution(
    actions: list[ConversionActionRow],
    goals: list[CustomerConversionGoalRow],
    *,
    category_filter: str | None,
    customer_id: str,
) -> GoalAttributionResult:
    """Aggregate conversion_actions by (category, origin), cross-ref biddable.

    Algorithm:
    1. Filter actions: status ∈ _INCLUDED_STATUSES (ENABLED-only) — defensive,
       complementa o `WHERE status='ENABLED'` server-side; protege contra
       Google retornar inadvertidamente PAUSED/REMOVED em edge cases.
       If category_filter, also filter by category.
    2. Build goals_lookup: {(category, origin): biddable} from goals list.
    3. Group filtered actions by (category, origin) tuple.
    4. Per group: split into primary_actions (primary_for_goal=true)
       + secondary_actions (primary_for_goal=false).
    5. Lookup biddable from goals_lookup; default False if absent (defensive).
    6. Generate warning_pt only if biddable=true (else None).
    7. Build origin_summary dict — key strategy:
       - if category_filter set: key = origin (e.g., "WEBSITE")
       - else: key = "{category}__{origin}" composite (e.g., "CONTACT__WEBSITE")
    8. Sort actions within primary/secondary lists by name ASC (stable display).
    9. Build metadata: total_actions_audited, origins_audited (sorted unique),
       categories_audited (sorted unique).

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    # 1. Filter actions
    filtered: list[ConversionActionRow] = []
    for action in actions:
        if action.status not in _INCLUDED_STATUSES:
            continue
        if category_filter is not None and action.category != category_filter:
            continue
        filtered.append(action)

    # 2. Goals lookup
    goals_lookup: dict[tuple[str, str], bool] = {
        (g.category, g.origin): g.biddable for g in goals
    }

    # 3. Group by (category, origin)
    groups: dict[tuple[str, str], list[ConversionActionRow]] = {}
    for action in filtered:
        key = (action.category, action.origin)
        groups.setdefault(key, []).append(action)

    # 4-8. Build origin_summary
    origin_summary: dict[str, OriginSummary] = {}
    for (category, origin), group_actions in groups.items():
        # 4. Split primary/secondary
        primary = [a for a in group_actions if a.primary_for_goal]
        secondary = [a for a in group_actions if not a.primary_for_goal]

        # 5. Lookup biddable (default False)
        biddable = goals_lookup.get((category, origin), False)

        # 6. Warning only if biddable=true
        warning = _WARNING_BIDDABLE_TRUE if biddable else None

        # 8. Sort by name ASC
        primary_sorted = sorted(primary, key=lambda a: a.name)
        secondary_sorted = sorted(secondary, key=lambda a: a.name)

        # Build ActionSummary tuples
        primary_summaries = tuple(
            ActionSummary(
                id=a.id,
                name=a.name,
                include_in_conversions_metric=a.include_in_conversions_metric,
                status=a.status,
            )
            for a in primary_sorted
        )
        secondary_summaries = tuple(
            ActionSummary(
                id=a.id,
                name=a.name,
                include_in_conversions_metric=a.include_in_conversions_metric,
                status=a.status,
            )
            for a in secondary_sorted
        )

        # 7. Key strategy
        if category_filter is not None:
            key_str = origin
        else:
            key_str = f"{category}__{origin}"

        origin_summary[key_str] = OriginSummary(
            category=category,
            origin=origin,
            biddable=biddable,
            warning=warning,
            primary_count=len(primary_summaries),
            secondary_count=len(secondary_summaries),
            primary_actions=primary_summaries,
            secondary_actions=secondary_summaries,
        )

    # 9. Metadata
    total_audited = len(filtered)
    origins_audited = tuple(sorted({a.origin for a in filtered}))
    categories_audited = tuple(sorted({a.category for a in filtered}))

    return GoalAttributionResult(
        customer_id=customer_id,
        category_filter=category_filter,
        origin_summary=origin_summary,
        total_actions_audited=total_audited,
        origins_audited=origins_audited,
        categories_audited=categories_audited,
    )
```

- [ ] **Step 2: Create `tests/unit/test_goal_attribution.py` com 18 tests**

```python
"""Unit tests for goal_attribution pure module (Sprint 3b.35)."""

from src.google_ads.goal_attribution import (
    ConversionActionRow,
    CustomerConversionGoalRow,
    audit_goal_attribution,
)


def _make_action(
    *,
    id: str = "1",
    name: str = "Whatsapp - JPA",
    category: str = "CONTACT",
    origin: str = "WEBSITE",
    primary_for_goal: bool = False,
    include_in_conversions_metric: bool = True,
    status: str = "ENABLED",
) -> ConversionActionRow:
    return ConversionActionRow(
        id=id,
        name=name,
        category=category,
        origin=origin,
        primary_for_goal=primary_for_goal,
        include_in_conversions_metric=include_in_conversions_metric,
        status=status,
    )


def _make_goal(
    *,
    category: str = "CONTACT",
    origin: str = "WEBSITE",
    biddable: bool = True,
) -> CustomerConversionGoalRow:
    return CustomerConversionGoalRow(category=category, origin=origin, biddable=biddable)


def test_empty_actions_returns_empty_summary():
    result = audit_goal_attribution(
        actions=[], goals=[], category_filter=None, customer_id="1234567890"
    )
    assert result.origin_summary == {}
    assert result.total_actions_audited == 0
    assert result.origins_audited == ()
    assert result.categories_audited == ()


def test_paused_action_excluded():
    result = audit_goal_attribution(
        actions=[_make_action(status="PAUSED")],
        goals=[_make_goal()],
        category_filter=None,
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 0
    assert result.origin_summary == {}


def test_removed_action_excluded():
    result = audit_goal_attribution(
        actions=[_make_action(status="REMOVED")],
        goals=[_make_goal()],
        category_filter=None,
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 0


def test_category_filter_match_keeps_action():
    result = audit_goal_attribution(
        actions=[_make_action(category="CONTACT")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 1
    assert "WEBSITE" in result.origin_summary


def test_category_filter_no_match_excludes_action():
    result = audit_goal_attribution(
        actions=[_make_action(category="PURCHASE")],
        goals=[_make_goal(category="PURCHASE")],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 0
    assert result.origin_summary == {}


def test_no_filter_groups_all_categories_composite_key():
    """Sem category_filter, key = '{cat}__{origin}' composite."""
    result = audit_goal_attribution(
        actions=[
            _make_action(category="CONTACT", origin="WEBSITE"),
            _make_action(id="2", category="PURCHASE", origin="WEBSITE"),
        ],
        goals=[_make_goal(category="CONTACT"), _make_goal(category="PURCHASE")],
        category_filter=None,
        customer_id="1234567890",
    )
    assert "CONTACT__WEBSITE" in result.origin_summary
    assert "PURCHASE__WEBSITE" in result.origin_summary


def test_filter_set_uses_origin_only_key():
    """Com category_filter, key = origin simple."""
    result = audit_goal_attribution(
        actions=[_make_action(category="CONTACT", origin="WEBSITE")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert "WEBSITE" in result.origin_summary
    assert "CONTACT__WEBSITE" not in result.origin_summary


def test_primary_for_goal_true_in_primary_bucket():
    result = audit_goal_attribution(
        actions=[_make_action(primary_for_goal=True, name="Primary Action")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.primary_count == 1
    assert summary.secondary_count == 0
    assert summary.primary_actions[0].name == "Primary Action"


def test_primary_for_goal_false_in_secondary_bucket():
    result = audit_goal_attribution(
        actions=[_make_action(primary_for_goal=False, name="Secondary Action")],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.primary_count == 0
    assert summary.secondary_count == 1
    assert summary.secondary_actions[0].name == "Secondary Action"


def test_biddable_true_emits_warning_pt():
    result = audit_goal_attribution(
        actions=[_make_action()],
        goals=[_make_goal(biddable=True)],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.biddable is True
    assert summary.warning is not None
    assert "AFETA Smart Bidding" in summary.warning


def test_biddable_false_warning_is_null():
    result = audit_goal_attribution(
        actions=[_make_action()],
        goals=[_make_goal(biddable=False)],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.biddable is False
    assert summary.warning is None


def test_goal_absent_for_origin_defaults_biddable_false():
    """Action sem customer_conversion_goal correspondente → biddable=False default."""
    result = audit_goal_attribution(
        actions=[_make_action(origin="APP")],
        goals=[_make_goal(origin="WEBSITE")],  # APP missing
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["APP"]
    assert summary.biddable is False
    assert summary.warning is None


def test_multiple_actions_same_origin_all_listed():
    """Multiple actions com mesmo (cat, origin) → todas em primary OU secondary."""
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", name="A", primary_for_goal=True),
            _make_action(id="2", name="B", primary_for_goal=True),
            _make_action(id="3", name="C", primary_for_goal=False),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    assert summary.primary_count == 2
    assert summary.secondary_count == 1


def test_actions_sorted_by_name_asc_in_primary():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", name="Zebra", primary_for_goal=True),
            _make_action(id="2", name="Alpha", primary_for_goal=True),
            _make_action(id="3", name="Mike", primary_for_goal=True),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    names = [a.name for a in summary.primary_actions]
    assert names == ["Alpha", "Mike", "Zebra"]


def test_actions_sorted_by_name_asc_in_secondary():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", name="Zulu", primary_for_goal=False),
            _make_action(id="2", name="Charlie", primary_for_goal=False),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    summary = result.origin_summary["WEBSITE"]
    names = [a.name for a in summary.secondary_actions]
    assert names == ["Charlie", "Zulu"]


def test_metadata_total_audited_counts_post_filter():
    """total_actions_audited reflete POST-status-filter + POST-category-filter."""
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", status="ENABLED", category="CONTACT"),
            _make_action(id="2", status="PAUSED", category="CONTACT"),
            _make_action(id="3", status="ENABLED", category="PURCHASE"),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.total_actions_audited == 1  # só id=1 passa ambos filters


def test_metadata_origins_audited_unique_sorted():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", origin="WEBSITE"),
            _make_action(id="2", origin="APP"),
            _make_action(id="3", origin="WEBSITE"),
        ],
        goals=[_make_goal()],
        category_filter="CONTACT",
        customer_id="1234567890",
    )
    assert result.origins_audited == ("APP", "WEBSITE")


def test_metadata_categories_audited_unique_sorted():
    result = audit_goal_attribution(
        actions=[
            _make_action(id="1", category="PURCHASE"),
            _make_action(id="2", category="CONTACT"),
            _make_action(id="3", category="CONTACT"),
        ],
        goals=[_make_goal()],
        category_filter=None,
        customer_id="1234567890",
    )
    assert result.categories_audited == ("CONTACT", "PURCHASE")
```

- [ ] **Step 3: Run tests — expect 18/18 PASS**

```bash
python -m pytest tests/unit/test_goal_attribution.py -v
```

Expected: 18 passed.

- [ ] **Step 4: Run ruff + mypy**

```bash
python -m ruff check src/google_ads/goal_attribution.py tests/unit/test_goal_attribution.py
python -m ruff format --check src/google_ads/goal_attribution.py tests/unit/test_goal_attribution.py
python -m mypy src/google_ads/goal_attribution.py
```

Expected: All checks PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/goal_attribution.py tests/unit/test_goal_attribution.py
git commit -m "feat(google_ads): goal_attribution pure module + 18 unit tests (Sprint 3b.35 A1)"
```

---

## Task A2: GAQL builders + 8 unit tests

**Files:**
- Create: `src/google_ads/queries/audit_goal_attribution.py`
- Create: `tests/unit/test_audit_goal_attribution_queries.py`

**Pode rodar PARALELO ao A1** (arquivos diferentes).

- [ ] **Step 1: Create `src/google_ads/queries/audit_goal_attribution.py`**

```python
"""GAQL builders for audit_goal_attribution tool (Sprint 3b.35).

2 queries paralelas:
- conversion_action: actions com category/origin/primary_for_goal/etc
- customer_conversion_goal: goals com biddable flag per (category, origin)

Tool wrapper invoca via asyncio.gather paralelo.
"""

from typing import Any


def build_conversion_action_query() -> str:
    """GAQL pra conversion_action com fields necessários (audit_goal_attribution).

    Filters: status = ENABLED (PAUSED/REMOVED não afetam Smart Bidding ativo).
    """
    return """
        SELECT
          conversion_action.id,
          conversion_action.name,
          conversion_action.category,
          conversion_action.origin,
          conversion_action.primary_for_goal,
          conversion_action.include_in_conversions_metric,
          conversion_action.status
        FROM conversion_action
        WHERE conversion_action.status = 'ENABLED'
    """.strip()


def build_customer_conversion_goal_query() -> str:
    """GAQL pra customer_conversion_goal (category, origin, biddable)."""
    return """
        SELECT
          customer_conversion_goal.category,
          customer_conversion_goal.origin,
          customer_conversion_goal.biddable
        FROM customer_conversion_goal
    """.strip()


def parse_conversion_action_row(row: Any) -> dict[str, Any]:
    """Parse conversion_action GAQL row → dict (boundary)."""
    ca = row.conversion_action
    return {
        "id": str(ca.id),
        "name": ca.name,
        "category": ca.category.name,
        "origin": ca.origin.name,
        "primary_for_goal": bool(ca.primary_for_goal),
        "include_in_conversions_metric": bool(ca.include_in_conversions_metric),
        "status": ca.status.name,
    }


def parse_customer_conversion_goal_row(row: Any) -> dict[str, Any]:
    """Parse customer_conversion_goal GAQL row → dict (boundary)."""
    ccg = row.customer_conversion_goal
    return {
        "category": ccg.category.name,
        "origin": ccg.origin.name,
        "biddable": bool(ccg.biddable),
    }
```

- [ ] **Step 2: Create `tests/unit/test_audit_goal_attribution_queries.py` com 8 tests**

```python
"""Unit tests for audit_goal_attribution GAQL builders + boundary parsers (Sprint 3b.35)."""

from src.google_ads.goal_attribution import (
    dict_to_conversion_action_row,
    dict_to_customer_conversion_goal_row,
)
from src.google_ads.queries.audit_goal_attribution import (
    build_conversion_action_query,
    build_customer_conversion_goal_query,
)


# === GAQL builder tests (4) ===


def test_build_conversion_action_query_includes_required_fields():
    q = build_conversion_action_query()
    required_fields = [
        "conversion_action.id",
        "conversion_action.name",
        "conversion_action.category",
        "conversion_action.origin",
        "conversion_action.primary_for_goal",
        "conversion_action.include_in_conversions_metric",
        "conversion_action.status",
    ]
    for field in required_fields:
        assert field in q


def test_build_conversion_action_query_filters_enabled_status():
    q = build_conversion_action_query()
    assert "WHERE conversion_action.status = 'ENABLED'" in q
    assert "FROM conversion_action" in q


def test_build_customer_conversion_goal_query_shape():
    q = build_customer_conversion_goal_query()
    assert "customer_conversion_goal.category" in q
    assert "customer_conversion_goal.origin" in q
    assert "customer_conversion_goal.biddable" in q
    assert "FROM customer_conversion_goal" in q


def test_build_customer_conversion_goal_query_no_filter():
    """customer_conversion_goal query não tem WHERE — retorna todos goals."""
    q = build_customer_conversion_goal_query()
    assert "WHERE" not in q


# === Boundary parser tests (4) ===


def test_dict_to_conversion_action_row_handles_missing_status():
    d: dict = {"id": "1", "name": "Test"}
    row = dict_to_conversion_action_row(d)
    assert row.id == "1"
    assert row.name == "Test"
    assert row.status == ""
    assert row.primary_for_goal is False  # bool(None) = False, but bool({}) for missing key uses default


def test_dict_to_conversion_action_row_bool_coercion_for_primary_for_goal():
    """primary_for_goal True/False preserved via bool()."""
    d_true = {"primary_for_goal": True}
    d_false = {"primary_for_goal": False}
    assert dict_to_conversion_action_row(d_true).primary_for_goal is True
    assert dict_to_conversion_action_row(d_false).primary_for_goal is False


def test_dict_to_customer_conversion_goal_row_handles_missing_biddable():
    d: dict = {"category": "CONTACT", "origin": "WEBSITE"}
    row = dict_to_customer_conversion_goal_row(d)
    assert row.category == "CONTACT"
    assert row.origin == "WEBSITE"
    assert row.biddable is False  # default


def test_dict_to_customer_conversion_goal_row_full_dict():
    d = {"category": "PURCHASE", "origin": "APP", "biddable": True}
    row = dict_to_customer_conversion_goal_row(d)
    assert row.category == "PURCHASE"
    assert row.origin == "APP"
    assert row.biddable is True
```

- [ ] **Step 3: Run tests — expect 8/8 PASS**

```bash
python -m pytest tests/unit/test_audit_goal_attribution_queries.py -v
```

Expected: 8 passed.

- [ ] **Step 4: Run ruff + mypy**

```bash
python -m ruff check src/google_ads/queries/audit_goal_attribution.py tests/unit/test_audit_goal_attribution_queries.py
python -m mypy src/google_ads/queries/audit_goal_attribution.py
```

Expected: All checks PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/queries/audit_goal_attribution.py tests/unit/test_audit_goal_attribution_queries.py
git commit -m "feat(queries): audit_goal_attribution GAQL builders + parsers (Sprint 3b.35 A2)"
```

---

## Task A3: Tool wrapper + 3 integration tests + schema

**Files:**
- Create: `src/mcp/tools/audit_goal_attribution.py`
- Create: `tests/integration/test_audit_goal_attribution.py`
- Modify: `tests/unit/test_tools_schemas.py`

**Depende de A1 + A2** (importa dataclasses + função + GAQL builders + parsers).

- [ ] **Step 1: Create `src/mcp/tools/audit_goal_attribution.py`**

```python
"""Tool: audit_goal_attribution — pre-flight check antes de mexer em primary_for_goal.

Sprint 3b.35 — W3 do dogfood 2026-05-21 MO-JP+CAB (ICE 360).
Cruza conversion_action com customer_conversion_goal pra revelar biddable flag
por (category, origin), emitindo warning PT-BR se primary→secondary impacta
Smart Bidding. Resolve falsa premissa "cosmético KPI" descoberta em lição 47.
"""

import asyncio
from typing import Any

from src.google_ads.goal_attribution import (
    audit_goal_attribution as _audit_goal_attribution_pure,
    dict_to_conversion_action_row,
    dict_to_customer_conversion_goal_row,
)
from src.google_ads.queries.audit_goal_attribution import (
    build_conversion_action_query,
    build_customer_conversion_goal_query,
    parse_conversion_action_row,
    parse_customer_conversion_goal_row,
)
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

# Sprint 3b.19A whitelist — 13 V4-focused categorias (após F17/F18/F19 fixes)
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
                "Default sem filtro = retorna todas categories da conta agrupadas "
                "por (category, origin). Whitelist V4 13 valores (mesma de "
                "create_conversion_action 3b.19A — F17/F18/F19-safe)."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="audit_goal_attribution",
    description=(
        "Pre-flight check antes de mexer em ConversionAction.primary_for_goal. "
        "Cruza conversion_action com customer_conversion_goal pra revelar "
        "biddable flag por (category, origin). Output: origin_summary dict com "
        "biddable + warning PT-BR (null se biddable=false) + primary/secondary "
        "actions split. biddable=true significa que promover Secondary→Primary "
        "AFETA Smart Bidding em todas campaigns que usam esta category+origin — "
        "NÃO é cosmético KPI (lição 47 dogfood MO-JP). Filter opcional por "
        "category (whitelist 13 V4 valores). Apenas actions com status=ENABLED. "
        "Sempre auditado."
    ),
    input_schema=_SCHEMA,
)
async def audit_goal_attribution(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    category_filter = args.get("category")

    # 2 queries paralelas via asyncio.gather (padrão Sprint 3b.21 + 3b.31)
    actions_query = build_conversion_action_query()
    goals_query = build_customer_conversion_goal_query()

    actions_raw, goals_raw = await asyncio.gather(
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=actions_query,
            row_formatter=parse_conversion_action_row,
            operation_name="audit_goal_attribution_actions",
            audit_this_call=True,
            params_summary={"category_filter": category_filter, "phase": "actions"},
        ),
        run_report(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            query=goals_query,
            row_formatter=parse_customer_conversion_goal_row,
            operation_name="audit_goal_attribution_goals",
            audit_this_call=True,
            params_summary={"category_filter": category_filter, "phase": "goals"},
        ),
    )

    # Boundary conversion: dict → dataclass
    actions = [dict_to_conversion_action_row(d) for d in actions_raw]
    goals = [dict_to_customer_conversion_goal_row(d) for d in goals_raw]

    # Pure aggregator
    result = _audit_goal_attribution_pure(
        actions,
        goals,
        category_filter=category_filter,
        customer_id=customer_id,
    )

    # Return dict — serialize dataclasses
    return {
        "customer_id": result.customer_id,
        "category_filter": result.category_filter,
        "origin_summary": {
            key: {
                "category": s.category,
                "origin": s.origin,
                "biddable": s.biddable,
                "warning": s.warning,
                "primary_count": s.primary_count,
                "secondary_count": s.secondary_count,
                "primary_actions": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "include_in_conversions_metric": a.include_in_conversions_metric,
                        "status": a.status,
                    }
                    for a in s.primary_actions
                ],
                "secondary_actions": [
                    {
                        "id": a.id,
                        "name": a.name,
                        "include_in_conversions_metric": a.include_in_conversions_metric,
                        "status": a.status,
                    }
                    for a in s.secondary_actions
                ],
            }
            for key, s in result.origin_summary.items()
        },
        "total_actions_audited": result.total_actions_audited,
        "origins_audited": list(result.origins_audited),
        "categories_audited": list(result.categories_audited),
    }
```

- [ ] **Step 2: Create `tests/integration/test_audit_goal_attribution.py` com 3 tests**

```python
"""Integration tests for audit_goal_attribution (Sprint 3b.35)."""

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
async def test_panoramic_no_filter_composite_keys(bound_context):
    """T1 cenário smoke: sem category filter → composite keys."""
    from src.mcp.tools.audit_goal_attribution import audit_goal_attribution

    fake_actions = [
        {
            "id": "1",
            "name": "Whatsapp - JPA",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
        {
            "id": "2",
            "name": "Compra Produto X",
            "category": "PURCHASE",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
    ]
    fake_goals = [
        {"category": "CONTACT", "origin": "WEBSITE", "biddable": True},
        {"category": "PURCHASE", "origin": "WEBSITE", "biddable": True},
    ]

    async def fake_run_report(*args, **kwargs):
        op_name = kwargs.get("operation_name", "")
        if "actions" in op_name:
            return fake_actions
        return fake_goals

    with patch(
        "src.mcp.tools.audit_goal_attribution.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        result = await audit_goal_attribution({"customer_id": "1234567890"})

    assert "CONTACT__WEBSITE" in result["origin_summary"]
    assert "PURCHASE__WEBSITE" in result["origin_summary"]
    assert result["total_actions_audited"] == 2
    assert result["category_filter"] is None


@pytest.mark.asyncio
async def test_category_filter_uses_origin_only_key(bound_context):
    """T2 cenário smoke: com category filter → key = origin simple."""
    from src.mcp.tools.audit_goal_attribution import audit_goal_attribution

    fake_actions = [
        {
            "id": "1",
            "name": "Whatsapp - JPA",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
    ]
    fake_goals = [{"category": "CONTACT", "origin": "WEBSITE", "biddable": True}]

    async def fake_run_report(*args, **kwargs):
        op_name = kwargs.get("operation_name", "")
        if "actions" in op_name:
            return fake_actions
        return fake_goals

    with patch(
        "src.mcp.tools.audit_goal_attribution.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        result = await audit_goal_attribution(
            {"customer_id": "1234567890", "category": "CONTACT"}
        )

    assert "WEBSITE" in result["origin_summary"]
    assert "CONTACT__WEBSITE" not in result["origin_summary"]
    assert result["category_filter"] == "CONTACT"


@pytest.mark.asyncio
async def test_warning_emitted_when_biddable_true(bound_context):
    """T4 cenário smoke: biddable=true → warning PT-BR emitido."""
    from src.mcp.tools.audit_goal_attribution import audit_goal_attribution

    fake_actions = [
        {
            "id": "1",
            "name": "Test Action",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "include_in_conversions_metric": True,
            "status": "ENABLED",
        },
    ]
    fake_goals = [{"category": "CONTACT", "origin": "WEBSITE", "biddable": True}]

    async def fake_run_report(*args, **kwargs):
        op_name = kwargs.get("operation_name", "")
        if "actions" in op_name:
            return fake_actions
        return fake_goals

    with patch(
        "src.mcp.tools.audit_goal_attribution.run_report",
        AsyncMock(side_effect=fake_run_report),
    ):
        result = await audit_goal_attribution(
            {"customer_id": "1234567890", "category": "CONTACT"}
        )

    summary = result["origin_summary"]["WEBSITE"]
    assert summary["biddable"] is True
    assert summary["warning"] is not None
    assert "AFETA Smart Bidding" in summary["warning"]
```

- [ ] **Step 3: Bump tool count em `tests/unit/test_tools_schemas.py`**

Add `"audit_goal_attribution"` ao allowlist em ambos `test_all_phase_2_tools_registered` e `test_no_unexpected_tools` (alphabetically — entre `audit_competitor_keywords` e `audit_quality_score`).

Auto-discovery test usa `len(all_tools()) == file_count` dynamic — não precisa hardcode bump.

- [ ] **Step 4: Run tests + pre-push gate**

```bash
python -m pytest tests/integration/test_audit_goal_attribution.py tests/unit/test_tools_schemas.py -v
python scripts/check_pre_push.py
```

Expected: 3 integration + tool count tests PASS. Pre-push gate 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/tools/audit_goal_attribution.py tests/integration/test_audit_goal_attribution.py tests/unit/test_tools_schemas.py
git commit -m "feat(mcp): audit_goal_attribution tool wrapper + integration tests (Sprint 3b.35 A3)"
```

---

## Task A4: Smoke runbook via subagent

**Files:**
- Create: `docs/operacao/phase-3b-35-bootstrap.md`

**Pode rodar PARALELO ao A3** (geração de runbook não depende do código pronto, só do spec/plan).

- [ ] **Step 1: Dispatch smoke-runbook-generator subagent**

Prompt mínimo:
```
Generate phase-3b-35-bootstrap.md smoke runbook para Sprint 3b.35 (audit_goal_attribution, 55ª tool).
Spec: docs/superpowers/specs/2026-05-21-sprint-3b-35-audit-goal-attribution-design.md
Plan: docs/superpowers/plans/2026-05-21-sprint-3b-35-audit-goal-attribution.md

6 cenários a cobrir (referência spec Section 6):
- T1: Default sem category filter (panorâmico) em MO-JP 7862230676
- T2: Category filter = CONTACT em MO-JP
- T3: Category filter = PURCHASE em ML Antiguidades 7455088726 (best-effort)
- T4: Biddable=true → warning emitido
- T5: Biddable=false → warning null
- T6: Caso real lição 47 MO-JP CONTACT WEBSITE (confirma dogfood numbers)

Production URL: https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app
```

- [ ] **Step 2: Review generated runbook + commit**

```bash
git add docs/operacao/phase-3b-35-bootstrap.md
git commit -m "docs(smoke): phase-3b-35-bootstrap.md runbook (Sprint 3b.35 A4)"
```

---

## Task A5: Pre-push gate + push + smoke + signoff

**Files modificados em signoff:**
- Modify: `docs/operacao/sprint-history.md` (append Sprint 3b.35 entry)
- Modify: `CLAUDE.md` (bump tool count 54→55 + sprint count 34→35 + Last updated)

- [ ] **Step 1: Run full pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS em ~40s.

- [ ] **Step 2: Push origin/main**

```bash
git push origin main
```

Expected: 4 commits pushed (A1 + A2 + A3 + A4).

- [ ] **Step 3: Watch CI + Deploy**

```bash
gh run list --limit 3
gh run watch <deploy-run-id> --exit-status
curl -s -o /dev/null -w "%{http_code}\n" https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: CI green + Deploy green + /health HTTP 200.

- [ ] **Step 4: Execute 6 smoke tests em produção**

Após reload (se necessário pra MCP schema cache), executar T1-T6 do runbook contra contas MO-JP `7862230676` + ML Antiguidades `7455088726`. Preencher result blocks in-place no runbook.

- [ ] **Step 5: Catalog F-findings se houver**

Se algum teste descobriu bug:
- Add entry em `docs/operacao/findings-catalog.md` próximo F##
- Document affected tools + fix candidate

Se zero F-findings, document explicitly: "Zero F-findings novos. Sprint clean."

- [ ] **Step 6: Append Sprint 3b.35 entry em sprint-history.md**

Format consistente com entries anteriores (3b.30/3b.31/3b.33/3b.34). Inclui:
- Production revision
- Tool count 54 → 55
- Smoke X/6 PASS + Y DEFERRED
- F-findings count
- Reference plan + spec + runbook
- Architecture summary
- ICE 360 (W3 dogfood 21/05)

- [ ] **Step 7: Bump CLAUDE.md**

3 edits:
- `Last updated: 2026-05-21` (mantém)
- `Sprint 3b.1 → 3b.34 (34 sprints)` → `3b.1 → 3b.35 (35 sprints)`
- `**Shipped (54 tools** ...)` → `**Shipped (55 tools** ...)`
- Production revision line atualizada
- Pending/future: 3b.35 candidate → 3b.36 (audit_zombie_keywords ICE 315 ou outros)

- [ ] **Step 8: Commit signoff + push**

```bash
git add docs/operacao/sprint-history.md CLAUDE.md docs/operacao/phase-3b-35-bootstrap.md
# Se F-findings:
git add docs/operacao/findings-catalog.md
git commit -m "docs(signoff): Sprint 3b.35 audit_goal_attribution smoke X/6 PASS"
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
| Section 4 Algorithm | A1 Step 1 (audit_goal_attribution function) |
| Section 5 V0 cuts | N/A (cuts documentation only) |
| Section 6 Testing | A1 (18 unit) + A2 (8 unit) + A3 (3 integration) + A4 (runbook) + A5 (smoke execution) |

Todas as 6 sections cobertas.

**2. Placeholder scan:** zero "TBD/TODO" no plano. Cada step tem código concreto ou comando exato.

**3. Type consistency:**
- `ConversionActionRow` definido em A1, importado em A2 (boundary tests) + A3 (wrapper) ✅
- `CustomerConversionGoalRow` definido em A1, importado em A2 + A3 ✅
- `GoalAttributionResult` produzido por `audit_goal_attribution` em A1, consumido em A3 wrapper ✅
- Field names consistentes: `customer_id`, `category_filter`, `origin_summary`, `total_actions_audited`, `origins_audited`, `categories_audited`, `warning`, `biddable`, `primary_count`, `secondary_count`, `primary_actions`, `secondary_actions` aparecem identicamente em spec Section 3 e A3 Step 1 ✅
- GAQL builder names match: `build_conversion_action_query`, `build_customer_conversion_goal_query` ✅
- Parser names match: `parse_conversion_action_row`, `parse_customer_conversion_goal_row` ✅

**4. Out-of-scope confirmed deferred (V0 cuts table na spec):**
- `campaign_attribution` ❌ V0
- `origin` filter ❌ V0
- `include_paused_actions` flag ❌ V0
- `limit` per origin ❌ V0
- Recommendation engine ❌ V0
- Custom goal config lookup ❌ V0

**Estimated total: ~100 min** (A1 ~25 + A2 ~15 + A3 ~25 + A4 ~5 + A5 ~30).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-21-sprint-3b-35-audit-goal-attribution.md`.

**Recomendação:** Subagent-Driven (padrão das últimas 4 sprints 3b.30/3b.31/3b.33/3b.35 tool inteira).
