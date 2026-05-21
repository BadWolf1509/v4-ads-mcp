# Sprint 3b.37 — `audit_orphan_smart_actions` Design Doc

**Date:** 2026-05-21
**Sprint:** 3b.37 (57ª MCP tool)
**ICE:** 288 (#12 backlog dogfood 2026-05-19 cleanup massivo MO-JP)
**Author:** Wellington Ribeiro + Claude (brainstorming-driven)

---

## Context

Workflow V4 recurring "cleanup conversion actions": gestor periodicamente identifica ConversionActions ENABLED mas sem activity real (zero conversions em window N days). Tracking pixels obsoletos, ações de campanhas removidas, conversion actions criadas em testes — todas continuam ENABLED, ocupam quota de "Conversions" no dashboard, mas não trackam nada útil.

Workflow manual atual:
1. `get_conversion_actions(customer_id)` lista 43+ actions
2. Pra cada action, query manual `metrics.all_conversions` em window
3. Mental filter por `all_conversions=0`
4. Decisão pause/remove

`audit_orphan_smart_actions` consolida em **1 tool call** retornando lista flagged + agrupada por category/origin.

## Use case primário V0 (cravado em brainstorming)

**Cleanup ConversionActions orphan recurring:** Detectar ENABLED actions com zero conversions (`metrics.all_conversions == 0`) em window LAST_30_DAYS (default). Pre-cleanup decision tool — Wellington decide pause/remove com base no output.

## Design decisions cravadas (brainstorming 2 perguntas)

| Decisão | Escolha |
|---|---|
| **Definição orphan V0** | `metrics.all_conversions == 0.0` em window (semantic simples, pattern análogo audit_zombie_keywords 3b.36) |
| **Output fields** | id, name, category, origin, primary_for_goal, status, all_conversions (echo) |

Decisões assumidas (sem question explícita):
- Architecture: pure aggregator + wrapper sobre conversion_action GAQL com `segments.date` per-action aggregation
- `status=ENABLED` hardcoded server-side via GAQL
- Sort: `category ASC, origin ASC, name ASC` (visual grouping)
- `audit_this_call=True` (sensitive read)
- `limit` default **100** (não 200) — lição 3b.36 (default 200 estoura MCP cap em conta grande). Max 500.

---

## Section 1 — Architecture overview

**Pattern:** Pure aggregator + wrapper (lineage Sprint 3b.30/3b.31/3b.33/3b.35/3b.36).

**Layer stack:**

1. **`src/google_ads/flag_orphan_smart_actions.py` — pure module** (testable standalone, zero Google SDK imports). 2 dataclasses frozen+slots: `ConversionActionRow`, `OrphanAction`. Função `flag_orphan_smart_actions(rows, *, limit) → tuple[list[OrphanAction], int]`.
2. **`src/google_ads/queries/audit_orphan_smart_actions.py`** — GAQL builder + row parser + boundary dict→dataclass.
3. **`src/mcp/tools/audit_orphan_smart_actions.py` — tool wrapper** com `run_report` único. `audit_this_call=True`.

**Data flow:**

```
audit_orphan_smart_actions({customer_id, category?, limit?, date_range?, start?, end?})
  └─> resolve_date_window
  └─> build_audit_orphan_smart_actions_query(start, end, category)
        └─> GAQL conversion_action + metrics.all_conversions + segments.date BETWEEN
            WHERE status=ENABLED + (optional category)
  └─> run_report(query) [audit_this_call=True]
  └─> dict_to_conversion_action_row[] (boundary)
  └─> flag_orphan_smart_actions.flag_orphan_smart_actions(rows, limit)
       └─> filter all_conversions == 0.0
       └─> sort by (category, origin, name)
       └─> truncate to limit
  └─> return result.to_dict()
```

**Reuse benefits:**

- Padrão validado em 5 sprints anteriores
- Boundary parser idêntico (`.name` em enums per 3b.7)
- F46 imune (não usa change_event)
- `resolve_date_window` reusa (Sprint 3b.20)
- Schema com `date_range` preset + start/end custom é convention V4

---

## Section 2 — Schema (input)

```python
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
                "Default 100 (lição 3b.36: limit=200 default estourou MCP cap "
                "em conta com 500+ entries)."
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
```

**Notas:**

- `category` é **optional** (default = todas categories)
- `limit` default **100** (lição 3b.36 — reduce default from 200 to avoid MCP cap overflow)
- **No composition keywords** (3b.19B.1 convention)

---

## Section 3 — Output shape (response)

```python
{
    "customer_id": "7862230676",
    "date_range_resolved": {
        "start": "2026-04-21",
        "end": "2026-05-20",
        "days": 30,
    },
    "filters_applied": {
        "category": None,
        "limit": 100,
    },
    "total_orphans": 12,
    "truncated": False,
    "returned_count": 12,
    "orphans": [
        {
            "conversion_action_id": "6826818917",
            "name": "Whatsapp - Antigo",
            "category": "CONTACT",
            "origin": "WEBSITE",
            "primary_for_goal": True,
            "status": "ENABLED",
            "all_conversions": 0.0,
        },
        # sorted by category ASC, origin ASC, name ASC
    ],
}
```

**Decisões cravadas:**

- `total_orphans` é POST-filter (POST-WHERE GAQL + POST-`all_conversions==0` client-side)
- `returned_count` ≤ `total_orphans` (após truncation)
- `truncated: bool` echoes Sprint 3b.23 F22 pattern
- `orphans[]` flat list sorted by `(category, origin, name)` ASC

---

## Section 4 — Algorithm (pure module logic)

```python
# src/google_ads/flag_orphan_smart_actions.py

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

**Edge cases tratados:**
- Empty `rows` input → `([], 0)`
- `limit=1` em conta com N orphans → returns 1, total=N, truncated=True
- Multiple actions same (category, origin) → all listed
- Float comparison: `r.all_conversions == 0.0` (Google retorna float 0.0 exato)

**GAQL builder** (`src/google_ads/queries/audit_orphan_smart_actions.py`):

```python
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

    Filters: date range via gaql_date_clause (segments.date) + status=ENABLED +
    optional category. Returns one row per (conversion_action, date) aggregated
    no client-side — but conversion_action metrics segments.date works per-action
    over window quando WHERE específica.
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

    Uses `.name` on category/origin/status enums (Sprint 3b.7 lesson: proto-plus
    v20+ regression — `str(enum)` retorna integer, `.name` retorna 'CONTACT'/'ENABLED').
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

---

## Section 5 — V0 cuts (out of scope)

| Item | Por que cortar V0 | V1+ candidato |
|---|---|---|
| **Cross-ref `campaign_conversion_goal`** | Opção B brainstorming — complexity 3x (2-query asyncio.gather + reverse-lookup). Semantic distinct: "no campaign uses this action" vs "zero conversions". | V1 dedicated `audit_unused_conversion_actions` |
| **`origin` filter** | Pós-filter client-side (output flat list scannable) | V1 se demanda |
| **`include_paused_actions` flag** | PAUSED já não-active, redundante com zero-conv signal | YAGNI |
| **Cost / impressions / clicks fields** | `conversion_action` metrics não inclui cost (vive em campaign_view) | N/A architecture |
| **Auto-pause action** | Tool é passive detect | V1 workflow `update_conversion_action(status=PAUSED)` separate |
| **Reverse-lookup "which campaigns tracked this"** | Complex query + UX challenge (multi-campaign per action) | V2+ |
| **Threshold > 0 (e.g., < 5 conversions)** | V0 strict zero. Threshold = "low-performing" diferente concept | V1 com `min_conversions` flag |

---

## Section 6 — Testing strategy + V0 surface metrics

### Test pyramid

| Tipo | Count | Foco |
|---|---|---|
| Unit (pure module) | ~8 | Filter logic (all_conversions==0.0), sort, truncate, edge cases |
| Unit (boundary + GAQL) | ~5 | `parse_conversion_action_row` (`.name` enums + float casting), `dict_to_conversion_action_row` defaults, GAQL builder shape + WHERE clauses |
| Integration (tool wrapper) | ~3 | Wire-up: run_report mock → flag_orphan_smart_actions → response shape |
| Smoke (production) | T1-T6 | Real account MO-JP + ML Antiguidades |

### Unit tests detail (pure module, ~8)

- `test_empty_rows_returns_empty`
- `test_filter_keeps_zero_conversions`
- `test_filter_excludes_positive_conversions` (>0 NÃO é orphan)
- `test_filter_excludes_fractional_conversions` (0.5 NÃO é orphan — Google can return fractional)
- `test_sort_by_category_origin_name`
- `test_truncation_limit_exceeded`
- `test_truncation_limit_not_exceeded`
- `test_total_count_pre_truncate_preserved`

### Boundary + GAQL tests (~5)

- `test_build_query_includes_required_fields` (7 fields SELECT)
- `test_build_query_filters_enabled` (WHERE status='ENABLED')
- `test_build_query_category_filter` (optional category clause)
- `test_parse_conversion_action_row_handles_enums_and_floats` (regression: `.name` em category/origin/status + float casting em all_conversions)
- `test_dict_to_conversion_action_row_handles_missing_fields` (defaults)

### Smoke runbook V0 (6 tests)

| # | Cenário | Conta | Expected |
|---|---|---|---|
| T1 | Default LAST_30_DAYS panorâmico | MO-JP `7862230676` | Lista orphans, sorted by category/origin/name |
| T2 | category=CONTACT filter | MO-JP | Apenas CONTACT actions orphan |
| T3 | Custom date range (start/end) | MO-JP | Window honored |
| T4 | limit truncation (limit=5 em conta com 10+) | MO-JP | truncated=true, returned_count=5 |
| T5 | category=PURCHASE em ML Antiguidades | ML `7455088726` | E-commerce — PURCHASE actions orphan candidates |
| T6 | Caso real cleanup conversion actions MO-JP | MO-JP | Identifica actions ENABLED com 0 conversions em 30d — cleanup candidates |

**Defer conditions:**
- T5 DEFERRED se ML PURCHASE all_conversions>0 (e-commerce ativo, sem orphans)
- T4 DEFERRED se MO-JP <10 orphans (mudar threshold)

### V0 surface metrics

```
- 1 new MCP tool: audit_orphan_smart_actions (tool count 56 → 57)
- 1 new pure module: src/google_ads/flag_orphan_smart_actions.py (~70 LOC)
- 1 new queries file: src/google_ads/queries/audit_orphan_smart_actions.py (~80 LOC)
- 1 new tool wrapper: src/mcp/tools/audit_orphan_smart_actions.py (~100 LOC)
- ~16 testes (8 unit pure + 5 boundary/GAQL + 3 integration)
- 1 smoke runbook (phase-3b-37-bootstrap.md, 6 tests)
```

### Estimated effort

- A1 (haiku — pure module + 8 unit tests): ~20 min
- A2 (haiku — GAQL builder + parsers + 5 tests): ~15 min
- A3 (sonnet — tool wrapper + 3 integration + schema): ~20 min
- A4 (smoke-runbook-generator): ~5 min
- A5 (controller smoke + signoff): ~30 min

**TOTAL:** ~90 min (~1.5h) via subagent-driven (paralelo A1+A2).

---

## Riscos + mitigações

| Risco | Mitigação |
|---|---|
| **MCP cap em conta grande** | `limit` default 100 (lição 3b.36). Max 500. F22 pattern aplicado. |
| **Conversion action sem metrics em window** | GAQL retorna row com `all_conversions=0.0` (não null) — filter funciona. |
| **Fractional conversions** (0.5) | Test explicitly excludes — só zero conta. |
| **Category fora whitelist V4** (custom goal) | Schema restringe INPUT mas algorithm aceita qualquer category em rows (design-correct, mesma pattern 3b.35). |
| **F46 lag concerns** | N/A — tool não usa change_event. |
| **PHONE_CALL_LEAD category** (Sprint 3b.35 finding) | Algorithm aceita, output mostra category bruta vindo do Google. |

---

## References

- Dogfood source: cleanup massivo MO-JP recurring (dogfood 2026-05-19 lição 41+)
- Architecture precedent: Sprint 3b.30 (`audit_quality_score`), 3b.35 (`audit_goal_attribution` — V4 categories whitelist), 3b.36 (`audit_zombie_keywords` — limit default 100 lição)
- F22 limit + truncated pattern: Sprint 3b.23
- F17/F18/F19 category whitelist: Sprint 3b.19A
- No-composition-keywords: Sprint 3b.19B.1
- `.name` on enums: Sprint 3b.7
- F46 fix imune: tool não usa change_event
