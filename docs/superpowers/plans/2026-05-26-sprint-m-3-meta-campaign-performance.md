# Sprint M.3 — Meta Performance Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 3 Meta Ads MCP tools (campaign + ad_set + ad performance) com paridade direta Google `get_*_performance`, contribuindo +3-6 calls/dia ao Caminho B+ Meta volume (500 calls/15d threshold pra Full Access re-submit).

**Architecture:** Approach C — shared `src/meta_ads/insights.py` pure module (~150 LOC) + 3 thin tool handlers (~30 LOC cada) reusando `run_meta_graph_get` + `resolve_meta_date_window` + `meta_ad_accounts.get_by_id`. Bucket: campaign=always, ad_set+ad=defer. Tool count 59 → 62.

**Tech Stack:** Python 3.12, MCP `>=1.2.0`, facebook-business `>=21.0.0`, asyncpg raw SQL, pytest + respx + testcontainers, register_tool decorator com `bucket` kwarg (Sprint 3b.39).

**Reference spec:** [`docs/superpowers/specs/2026-05-26-sprint-m-3-meta-campaign-performance-design.md`](../specs/2026-05-26-sprint-m-3-meta-campaign-performance-design.md)

---

## File Structure

**Create:**
- `src/meta_ads/insights.py` — shared pure module (build_insights_call, parse_insights_row, helpers, field constants)
- `src/mcp/tools/meta_get_campaign_performance.py` — tool handler (bucket=always)
- `src/mcp/tools/meta_get_ad_set_performance.py` — tool handler (bucket=defer)
- `src/mcp/tools/meta_get_ad_performance.py` — tool handler (bucket=defer)
- `tests/unit/test_meta_insights.py` — ~15 pure-module unit tests
- `tests/integration/test_meta_get_campaign_performance.py` — ~6 integration tests
- `tests/integration/test_meta_get_ad_set_performance.py` — ~4 integration tests
- `tests/integration/test_meta_get_ad_performance.py` — ~4 integration tests
- `docs/operacao/phase-M-3-bootstrap.md` — smoke runbook (10 tests)

**Modify:**
- `src/mcp/tools/_meta_common.py` — adicionar `META_EFFECTIVE_STATUS_LABELS` constant
- `CLAUDE.md` — Current state (59→62 tools) + Last updated stamp
- `docs/operacao/sprint-history.md` — add Sprint M.3 row

**Why split insights.py from tool files:**
- 3 tools compartilham 90% lógica (build call, parse row). Single module = DRY.
- Pure module (zero IO) = unit-testable standalone (mirror `account_overview.py` pattern Sprint M.2b).
- Tool files ficam thin (~30 LOC handlers) = boundary entre MCP context + business logic clara.

---

## Task 1: Add META_EFFECTIVE_STATUS_LABELS constant

**Files:**
- Modify: `src/mcp/tools/_meta_common.py`

- [ ] **Step 1: Add new constant after existing META_ACCOUNT_STATUS_LABELS**

Edit `src/mcp/tools/_meta_common.py`. After line 12 (closing of `META_ACCOUNT_STATUS_LABELS`), add:

```python


META_EFFECTIVE_STATUS_LABELS: dict[str, str] = {
    "ACTIVE": "ATIVO",
    "PAUSED": "PAUSADO",
    "ARCHIVED": "ARQUIVADO",
    "DELETED": "REMOVIDO",
    "PENDING_REVIEW": "EM_REVISÃO",
    "DISAPPROVED": "REPROVADO",
    "PREAPPROVED": "PRÉ_APROVADO",
    "PENDING_BILLING_INFO": "COBRANÇA_PENDENTE",
    "CAMPAIGN_PAUSED": "CAMPANHA_PAUSADA",
    "ADSET_PAUSED": "ADSET_PAUSADO",
}
```

- [ ] **Step 2: Verify no other imports broke**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS (constants-only addition; nothing else touches enum).

- [ ] **Step 3: Commit**

```bash
git add src/mcp/tools/_meta_common.py
git commit -m "$(cat <<'EOF'
feat(meta_ads): add META_EFFECTIVE_STATUS_LABELS constant (Sprint M.3 Task 1)

10 Meta effective_status enum values → PT-BR labels (ALL_CAPS_UNDERSCORE
convention, paralelo a META_ACCOUNT_STATUS_LABELS).

Pre-requisite pra parse_insights_row em src/meta_ads/insights.py (Task 2).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Create insights.py shared module (TDD, ~15 unit tests)

**Files:**
- Create: `src/meta_ads/insights.py`
- Create: `tests/unit/test_meta_insights.py`

**Note:** Follow TDD strictly. Each function gets failing test → implementation → passing test → commit. Group all 15 tests + final module in single commit at end (atomic).

- [ ] **Step 1: Write failing tests file**

Create `tests/unit/test_meta_insights.py`:

```python
"""Unit tests for src/meta_ads/insights.py (Sprint M.3 Task 2).

Pure module — zero IO, zero SDK. ~50ms total.
"""

from datetime import date

import pytest

from src.meta_ads.insights import (
    INSIGHTS_FIELDS_AD,
    INSIGHTS_FIELDS_ADSET,
    INSIGHTS_FIELDS_CAMPAIGN,
    _extract_action_value,
    _extract_purchase_roas,
    build_insights_call,
    parse_insights_row,
)


# ============================================================================
# build_insights_call
# ============================================================================


def test_build_insights_call_campaign_level() -> None:
    edge, params = build_insights_call(
        level="campaign",
        ad_account_id="act_123",
        start=date(2026, 5, 1),
        end=date(2026, 5, 7),
        effective_status="ACTIVE",
        limit=100,
    )
    assert edge == "/act_123/insights"
    assert params["level"] == "campaign"
    assert "spend" in params["fields"]
    assert "campaign_id" in params["fields"]
    assert "objective" in params["fields"]
    assert params["time_range"] == '{"since":"2026-05-01","until":"2026-05-07"}'
    assert params["limit"] == 100
    assert params["ad_account_id"] == "act_123"
    assert "filtering" in params  # ACTIVE != ALL → filtering injected


def test_build_insights_call_adset_level() -> None:
    _, params = build_insights_call(
        level="adset",
        ad_account_id="act_456",
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        effective_status="PAUSED",
        limit=50,
    )
    assert params["level"] == "adset"
    assert "adset_id" in params["fields"]
    assert "optimization_goal" in params["fields"]
    assert "daily_budget" in params["fields"]


def test_build_insights_call_ad_level() -> None:
    _, params = build_insights_call(
        level="ad",
        ad_account_id="act_789",
        start=date(2026, 5, 25),
        end=date(2026, 5, 25),
        effective_status="ACTIVE",
        limit=500,
    )
    assert params["level"] == "ad"
    assert "ad_id" in params["fields"]
    assert "creative_id" in params["fields"]
    assert params["limit"] == 500


def test_build_insights_call_status_all_omits_filtering() -> None:
    _, params = build_insights_call(
        level="campaign",
        ad_account_id="act_1",
        start=date(2026, 5, 1),
        end=date(2026, 5, 1),
        effective_status="ALL",
        limit=10,
    )
    assert "filtering" not in params


def test_build_insights_call_status_active_injects_filtering() -> None:
    _, params = build_insights_call(
        level="campaign",
        ad_account_id="act_1",
        start=date(2026, 5, 1),
        end=date(2026, 5, 1),
        effective_status="ACTIVE",
        limit=10,
    )
    assert "filtering" in params
    assert "ACTIVE" in params["filtering"]
    assert "effective_status" in params["filtering"]


# ============================================================================
# parse_insights_row — campaign level
# ============================================================================


def test_parse_insights_row_campaign_full() -> None:
    row = {
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "objective": "OUTCOME_SALES",
        "effective_status": "ACTIVE",
        "spend": "1234.56",
        "impressions": "50000",
        "clicks": "800",
        "ctr": "1.6",
        "cpc": "1.54",
        "reach": "12345",
        "frequency": "4.05",
        "actions": [
            {"action_type": "purchase", "value": "12"},
            {"action_type": "lead", "value": "3"},
        ],
        "action_values": [{"action_type": "purchase", "value": "5500.00"}],
        "purchase_roas": [{"action_type": "omni_purchase", "value": "4.45"}],
    }
    out = parse_insights_row(row, "campaign")
    assert out["campaign_id"] == "23842"
    assert out["campaign_name"] == "Brand BR"
    assert out["objective"] == "OUTCOME_SALES"
    assert out["effective_status"] == "ACTIVE"
    assert out["effective_status_label"] == "ATIVO"
    assert out["spend_brl"] == 1234.56
    assert out["impressions"] == 50000
    assert out["clicks"] == 800
    assert out["ctr"] == 0.016  # 1.6% → decimal
    assert out["cpc_brl"] == 1.54
    assert out["reach"] == 12345
    assert out["frequency"] == 4.05
    assert out["purchases"] == 12
    assert out["purchases_value_brl"] == 5500.00
    assert out["purchase_roas"] == 4.45
    assert out["leads"] == 3


# ============================================================================
# parse_insights_row — adset level
# ============================================================================


def test_parse_insights_row_adset_with_daily_budget() -> None:
    row = {
        "adset_id": "12345",
        "adset_name": "AS 1",
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "billing_event": "IMPRESSIONS",
        "daily_budget": "5000",  # cents = R$50.00
        "effective_status": "ACTIVE",
        "spend": "100",
        "impressions": "1000",
        "clicks": "50",
    }
    out = parse_insights_row(row, "adset")
    assert out["ad_set_id"] == "12345"
    assert out["ad_set_name"] == "AS 1"
    assert out["campaign_id"] == "23842"
    assert out["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert out["billing_event"] == "IMPRESSIONS"
    assert out["daily_budget_brl"] == 50.00


def test_parse_insights_row_adset_no_daily_budget() -> None:
    """CBO campaigns: ad sets sem daily_budget → None."""
    row = {
        "adset_id": "12345",
        "adset_name": "AS 1",
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "effective_status": "PAUSED",
    }
    out = parse_insights_row(row, "adset")
    assert out["daily_budget_brl"] is None


# ============================================================================
# parse_insights_row — ad level
# ============================================================================


def test_parse_insights_row_ad_missing_optional() -> None:
    """Ad sem creative_id → None acceptable, não fatal."""
    row = {
        "ad_id": "99999",
        "ad_name": "Ad 1",
        "adset_id": "12345",
        "adset_name": "AS 1",
        "campaign_id": "23842",
        "campaign_name": "Brand BR",
        "effective_status": "ACTIVE",
        # creative_id absent
    }
    out = parse_insights_row(row, "ad")
    assert out["ad_id"] == "99999"
    assert out["creative_id"] is None
    assert out["effective_status_label"] == "ATIVO"


# ============================================================================
# parse_insights_row — edge cases common
# ============================================================================


def test_parse_insights_row_no_actions() -> None:
    """Row sem actions → purchases=0, leads=0, purchases_value_brl=0."""
    row = {
        "campaign_id": "1",
        "campaign_name": "Test",
        "effective_status": "ACTIVE",
        "spend": "100",
    }
    out = parse_insights_row(row, "campaign")
    assert out["purchases"] == 0
    assert out["purchases_value_brl"] == 0.0
    assert out["leads"] == 0
    assert out["purchase_roas"] == 0.0


def test_parse_insights_row_ctr_normalization() -> None:
    """Meta ctr é percentual (1.6 = 1.6%) → decimal (0.016)."""
    row = {
        "campaign_id": "1",
        "campaign_name": "T",
        "effective_status": "ACTIVE",
        "ctr": "2.5",  # 2.5%
    }
    out = parse_insights_row(row, "campaign")
    assert out["ctr"] == 0.025


def test_parse_insights_row_unknown_effective_status() -> None:
    """Status fora do mapa → label='Desconhecido'."""
    row = {
        "campaign_id": "1",
        "campaign_name": "T",
        "effective_status": "BIZARRE_NEW_STATUS",
    }
    out = parse_insights_row(row, "campaign")
    assert out["effective_status"] == "BIZARRE_NEW_STATUS"
    assert out["effective_status_label"] == "DESCONHECIDO"


# ============================================================================
# _extract_action_value helper
# ============================================================================


def test_extract_action_value_missing_action_type() -> None:
    actions = [{"action_type": "link_click", "value": "100"}]
    assert _extract_action_value(actions, "purchase") == 0.0


def test_extract_action_value_first_match_only() -> None:
    """Se houver múltiplos action_type='purchase', retorna primeiro encontrado."""
    actions = [
        {"action_type": "purchase", "value": "10"},
        {"action_type": "purchase", "value": "20"},
    ]
    assert _extract_action_value(actions, "purchase") == 10.0


def test_extract_action_value_malformed_value() -> None:
    """Value não-numérico → 0 (defensive)."""
    actions = [{"action_type": "purchase", "value": "not_a_number"}]
    assert _extract_action_value(actions, "purchase") == 0.0


def test_extract_action_value_none_or_empty() -> None:
    assert _extract_action_value(None, "purchase") == 0.0
    assert _extract_action_value([], "purchase") == 0.0


# ============================================================================
# _extract_purchase_roas helper
# ============================================================================


def test_extract_purchase_roas_first_only() -> None:
    """purchase_roas é lista; retorna [0].value."""
    roas = [
        {"action_type": "omni_purchase", "value": "4.45"},
        {"action_type": "purchase", "value": "5.00"},  # ignored
    ]
    assert _extract_purchase_roas(roas) == 4.45


def test_extract_purchase_roas_empty_list() -> None:
    assert _extract_purchase_roas([]) == 0.0
    assert _extract_purchase_roas(None) == 0.0
```

- [ ] **Step 2: Run tests to verify ALL fail (no module yet)**

Run: `pytest tests/unit/test_meta_insights.py -v`
Expected: ALL FAIL with `ModuleNotFoundError: No module named 'src.meta_ads.insights'`

- [ ] **Step 3: Create insights.py module**

Create `src/meta_ads/insights.py`:

```python
"""Shared insights helpers for meta_get_*_performance tools (Sprint M.3).

Pure module — zero SDK imports, fully unit-testable.

Reusa META_EFFECTIVE_STATUS_LABELS de src.mcp.tools._meta_common.
"""

from datetime import date
from typing import Any, Literal

from src.mcp.tools._meta_common import META_EFFECTIVE_STATUS_LABELS

Level = Literal["campaign", "adset", "ad"]

# Per-level field lists (Meta Insights API field names)
_COMMON_INSIGHTS_FIELDS = [
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "reach",
    "frequency",
    "actions",
    "action_values",
    "purchase_roas",
]
INSIGHTS_FIELDS_CAMPAIGN = [
    "campaign_id",
    "campaign_name",
    "objective",
    "effective_status",
    *_COMMON_INSIGHTS_FIELDS,
]
INSIGHTS_FIELDS_ADSET = [
    "adset_id",
    "adset_name",
    "campaign_id",
    "campaign_name",
    "optimization_goal",
    "billing_event",
    "daily_budget",
    "effective_status",
    *_COMMON_INSIGHTS_FIELDS,
]
INSIGHTS_FIELDS_AD = [
    "ad_id",
    "ad_name",
    "adset_id",
    "adset_name",
    "campaign_id",
    "campaign_name",
    "creative_id",
    "effective_status",
    *_COMMON_INSIGHTS_FIELDS,
]


def build_insights_call(
    *,
    level: Level,
    ad_account_id: str,
    start: date,
    end: date,
    effective_status: str,
    limit: int,
) -> tuple[str, dict[str, Any]]:
    """Build Graph API edge path + params dict for a /insights call.

    Returns: (edge, params) — caller passes both to run_meta_graph_get.
    """
    fields_by_level = {
        "campaign": INSIGHTS_FIELDS_CAMPAIGN,
        "adset": INSIGHTS_FIELDS_ADSET,
        "ad": INSIGHTS_FIELDS_AD,
    }
    edge = f"/{ad_account_id}/insights"
    params: dict[str, Any] = {
        "level": level,
        "fields": ",".join(fields_by_level[level]),
        "time_range": f'{{"since":"{start.isoformat()}","until":"{end.isoformat()}"}}',
        "limit": limit,
        "ad_account_id": ad_account_id,  # passed thru for BUC counter key
    }
    if effective_status != "ALL":
        params["filtering"] = (
            f'[{{"field":"effective_status","operator":"IN",'
            f'"value":["{effective_status}"]}}]'
        )
    return edge, params


def _extract_action_value(
    actions: list[dict[str, Any]] | None, action_type: str
) -> float:
    """Extract value of FIRST action matching action_type. 0 if absent."""
    if not actions:
        return 0.0
    for a in actions:
        if a.get("action_type") == action_type:
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _extract_purchase_roas(roas_list: list[dict[str, Any]] | None) -> float:
    """purchase_roas é lista: [{'action_type':'omni_purchase','value':'4.45'}]."""
    if not roas_list:
        return 0.0
    try:
        return float(roas_list[0].get("value", 0))
    except (TypeError, ValueError, IndexError):
        return 0.0


def parse_insights_row(row: dict[str, Any], level: Level) -> dict[str, Any]:
    """Parse single Meta Insights row → flat dict for MCP response.

    Level-specific fields prepended (id/name/objective/etc).
    Common metrics + extracted actions follow.
    """
    spend = float(row.get("spend") or 0)
    clicks = int(row.get("clicks") or 0)
    actions = row.get("actions")
    action_values = row.get("action_values")

    effective_status_raw = row.get("effective_status", "UNKNOWN")
    common: dict[str, Any] = {
        "effective_status": effective_status_raw,
        "effective_status_label": META_EFFECTIVE_STATUS_LABELS.get(
            effective_status_raw, "DESCONHECIDO"
        ),
        "spend_brl": round(spend, 2),
        "impressions": int(row.get("impressions") or 0),
        "clicks": clicks,
        "ctr": round(float(row.get("ctr") or 0) / 100, 4),  # Meta % → decimal
        "cpc_brl": round(float(row.get("cpc") or 0), 4),
        "reach": int(row.get("reach") or 0),
        "frequency": round(float(row.get("frequency") or 0), 2),
        "purchases": int(_extract_action_value(actions, "purchase")),
        "purchases_value_brl": round(
            _extract_action_value(action_values, "purchase"), 2
        ),
        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas")),
        "leads": int(_extract_action_value(actions, "lead")),
    }

    if level == "campaign":
        return {
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "objective": row.get("objective"),
            **common,
        }
    if level == "adset":
        daily_budget_raw = row.get("daily_budget")
        daily_budget_brl = (
            round(float(daily_budget_raw) / 100, 2) if daily_budget_raw else None
        )
        return {
            "ad_set_id": row.get("adset_id"),
            "ad_set_name": row.get("adset_name"),
            "campaign_id": row.get("campaign_id"),
            "campaign_name": row.get("campaign_name"),
            "optimization_goal": row.get("optimization_goal"),
            "billing_event": row.get("billing_event"),
            "daily_budget_brl": daily_budget_brl,
            **common,
        }
    # ad
    return {
        "ad_id": row.get("ad_id"),
        "ad_name": row.get("ad_name"),
        "ad_set_id": row.get("adset_id"),
        "ad_set_name": row.get("adset_name"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "creative_id": row.get("creative_id"),
        **common,
    }
```

- [ ] **Step 4: Run tests to verify ALL pass**

Run: `pytest tests/unit/test_meta_insights.py -v`
Expected: 17 PASS (5 build_insights_call + 7 parse_insights_row + 4 _extract_action_value + 2 _extract_purchase_roas).

If FAIL: read the assertion error, fix module, re-run. Don't move on until 17/17 green.

- [ ] **Step 5: Run full pre-push gate to catch regressions**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/meta_ads/insights.py tests/unit/test_meta_insights.py
git commit -m "$(cat <<'EOF'
feat(meta_ads): src/meta_ads/insights.py shared module (Sprint M.3 Task 2)

Pure module reusable por meta_get_*_performance tools:
- build_insights_call(level, ad_account_id, start, end, effective_status, limit)
  → (edge, params) for /act_X/insights Graph API call
- parse_insights_row(row, level) → flat dict (level-specific + common metrics)
- INSIGHTS_FIELDS_CAMPAIGN/ADSET/AD constants
- _extract_action_value(actions, action_type) → float (first match)
- _extract_purchase_roas(roas_list) → float (lista[0].value)

Convention: snake_case ad_set_id (não Meta's adset_id) na response pra
consistency Google. Daily_budget cents → BRL conversion.

17 unit tests cobrem todos níveis + edge cases (missing actions, malformed
values, unknown status, CBO sem daily_budget, ctr normalization, multi-match).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: meta_get_campaign_performance tool (bucket=always)

**Files:**
- Create: `src/mcp/tools/meta_get_campaign_performance.py`
- Create: `tests/integration/test_meta_get_campaign_performance.py`

- [ ] **Step 1: Create tool handler file**

Create `src/mcp/tools/meta_get_campaign_performance.py`:

```python
# bucket: always
"""meta_get_campaign_performance — Performance por campanha Meta (Sprint M.3).

Paridade com Google get_campaign_performance: flat list ordenada por spend DESC.
Bucket=always (Pareto Meta top usage — primeira pergunta gestor V4).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_overview import resolve_meta_date_window
from src.meta_ads.insights import build_insights_call, parse_insights_row
from src.meta_ads.reports import run_meta_graph_get

_DESCRIPTION = (
    "[CORE] Performance por campanha Meta Ads: spend, impressões, clicks, CTR, "
    "CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads. "
    "Ordenado por spend desc. Filtros: effective_status "
    "(ACTIVE|PAUSED|ARCHIVED|ALL), limit (max 500). "
    "Use meta_list_my_ad_accounts pra listar ad_account_ids disponíveis."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": (
                "Meta ad account ID (formato act_<numeric>). "
                "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": [
                "TODAY",
                "YESTERDAY",
                "LAST_7_DAYS",
                "LAST_14_DAYS",
                "LAST_30_DAYS",
                "LAST_90_DAYS",
            ],
            "description": (
                "Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos."
            ),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range start. Sobrescreve preset. Requires end_date.",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range end. Sobrescreve preset. Requires start_date.",
        },
        "effective_status": {
            "type": "string",
            "enum": ["ACTIVE", "PAUSED", "ARCHIVED", "ALL"],
            "default": "ACTIVE",
            "description": "Filter por effective_status. ALL inclui tudo.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Max rows. Meta API cap = 500/page.",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}


async def meta_get_campaign_performance(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    effective_status: str = "ACTIVE",
    limit: int = 100,
) -> dict[str, Any]:
    """Core logic — testable by integration tests."""
    pool = connection.get_pool()
    today = datetime.now(UTC).date()

    try:
        start, end = resolve_meta_date_window(
            date_range or "LAST_30_DAYS", start_date, end_date, today
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Datas inválidas: {e}"}

    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, ad_account_id)
        if account is None:
            return {
                "status": "error",
                "error_message": (
                    f"Ad account {ad_account_id} não encontrada. "
                    f"Use meta_refresh_accounts ou reconnect via /oauth/meta/start."
                ),
            }

    edge, params = build_insights_call(
        level="campaign",
        ad_account_id=ad_account_id,
        start=start,
        end=end,
        effective_status=effective_status,
        limit=limit,
    )

    try:
        resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=edge,
            params=params,
            operation_name="meta_get_campaign_performance",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "level": "campaign",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "effective_status": effective_status,
            },
        )
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    rows = [parse_insights_row(r, "campaign") for r in resp.get("data", [])]
    rows.sort(key=lambda r: r["spend_brl"], reverse=True)

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "ad_account_name": account.account_name,
        "currency": account.currency,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "total_rows": len(rows),
    }


@register_tool(
    name="meta_get_campaign_performance",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="always",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_campaign_performance(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        effective_status=args.get("effective_status", "ACTIVE"),
        limit=args.get("limit", 100),
    )
```

- [ ] **Step 2: Create integration tests**

Create `tests/integration/test_meta_get_campaign_performance.py`:

```python
"""Integration tests Sprint M.3 Task 3: meta_get_campaign_performance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
    meta_oauth_connections,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


async def _seed_manager_with_meta_conn(
    db,
    *,
    token_expires_in_days: int = 60,
    account_status: int = 1,  # ATIVO
):
    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )
        token_expires = datetime.now(UTC) + timedelta(days=token_expires_in_days)
        await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="fb_user_test",
            fb_email="t@v4company.com",
            access_token_enc=b"fake_enc_bytes",
            token_expires_at=token_expires,
            scopes=["ads_read", "ads_management"],
        )
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456",
                    "business_id": "bm_test",
                    "business_name": "Test BM",
                    "account_name": "Test Account",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": account_status,
                }
            ],
        )
        await manager_meta_account_access.grant(
            conn, manager_id=mid, ad_account_id="act_123456"
        )
    return mid


@pytest.mark.integration
async def test_happy_path_returns_sorted_rows(db):
    """3 campaigns retornadas → ordenadas por spend_brl DESC."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "campaign_id": "c1",
                "campaign_name": "Low spend",
                "objective": "OUTCOME_TRAFFIC",
                "effective_status": "ACTIVE",
                "spend": "100",
                "impressions": "1000",
                "clicks": "50",
                "ctr": "5.0",
                "cpc": "2.0",
                "actions": [{"action_type": "purchase", "value": "1"}],
                "action_values": [{"action_type": "purchase", "value": "50"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "0.5"}],
            },
            {
                "campaign_id": "c2",
                "campaign_name": "High spend",
                "objective": "OUTCOME_SALES",
                "effective_status": "ACTIVE",
                "spend": "1000",
                "impressions": "10000",
                "clicks": "300",
                "ctr": "3.0",
                "cpc": "3.33",
                "actions": [{"action_type": "purchase", "value": "20"}],
                "action_values": [{"action_type": "purchase", "value": "4000"}],
                "purchase_roas": [{"action_type": "omni_purchase", "value": "4.0"}],
            },
            {
                "campaign_id": "c3",
                "campaign_name": "Mid spend",
                "objective": "OUTCOME_LEADS",
                "effective_status": "ACTIVE",
                "spend": "500",
                "impressions": "5000",
                "clicks": "100",
                "actions": [{"action_type": "lead", "value": "10"}],
            },
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            date_range="LAST_7_DAYS",
        )

    assert result["status"] == "success"
    assert result["ad_account_id"] == "act_123456"
    assert result["ad_account_name"] == "Test Account"
    assert result["currency"] == "BRL"
    assert result["total_rows"] == 3
    # Sorted by spend_brl DESC
    assert result["rows"][0]["campaign_name"] == "High spend"
    assert result["rows"][1]["campaign_name"] == "Mid spend"
    assert result["rows"][2]["campaign_name"] == "Low spend"
    # Top row metrics
    top = result["rows"][0]
    assert top["spend_brl"] == 1000.0
    assert top["purchases"] == 20
    assert top["purchases_value_brl"] == 4000.0
    assert top["purchase_roas"] == 4.0
    assert top["effective_status_label"] == "ATIVO"


@pytest.mark.integration
async def test_effective_status_filter_active_default(db):
    """Default effective_status=ACTIVE → filtering injetado nos params."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert "filtering" in captured_params
    assert "ACTIVE" in captured_params["filtering"]


@pytest.mark.integration
async def test_effective_status_all_omits_filtering(db):
    """effective_status=ALL → NÃO injeta filtering."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            effective_status="ALL",
        )

    assert "filtering" not in captured_params


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    """ad_account_id inexistente → error PT-BR friendly (sem Graph API call)."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )

    result = await meta_get_campaign_performance(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",  # not seeded
    )

    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
    assert "não encontrada" in result["error_message"]


@pytest.mark.integration
async def test_meta_api_error_returns_friendly_pt_br(db):
    """Graph API raise → error PT-BR friendly via to_friendly_meta_error."""
    from src.meta_ads.errors import MetaAdsFriendlyError
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=MetaAdsFriendlyError(
            "Limite Meta atingido. Tente novamente em alguns minutos.",
            retryable=True,
        )),
    ):
        result = await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "error"
    assert "Limite Meta" in result["error_message"]


@pytest.mark.integration
async def test_date_range_custom_overrides_preset(db):
    """start_date+end_date sobrescreve date_range preset → params.time_range custom."""
    from src.mcp.tools.meta_get_campaign_performance import (
        meta_get_campaign_performance,
    )

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_campaign_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_campaign_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            date_range="LAST_7_DAYS",  # should be overridden
            start_date="2026-03-01",
            end_date="2026-03-31",
        )

    assert "2026-03-01" in captured_params["time_range"]
    assert "2026-03-31" in captured_params["time_range"]
```

- [ ] **Step 3: Run integration tests**

Run: `pytest tests/integration/test_meta_get_campaign_performance.py -v -m integration`
Expected: 6 PASS.

If Docker unavailable: integration tests will skip — that's OK, CI runs them. Run unit-only check instead:

Run: `pytest tests/unit/test_meta_insights.py tests/unit/test_tools_schemas.py -v`
Expected: All PASS (schema regression guards pegam novo tool).

- [ ] **Step 4: Run full pre-push gate**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/tools/meta_get_campaign_performance.py tests/integration/test_meta_get_campaign_performance.py
git commit -m "$(cat <<'EOF'
feat(meta_ads): meta_get_campaign_performance tool (Sprint M.3 Task 3)

Paridade direta com Google get_campaign_performance. Flat list ordenada
por spend_brl DESC. Bucket=always (Pareto Meta top usage).

Schema: ad_account_id required + date_range preset (LAST_30_DAYS default)
+ start_date/end_date custom override + effective_status filter
(ACTIVE/PAUSED/ARCHIVED/ALL, default ACTIVE) + limit max 500.

Response: status + ad_account_id + ad_account_name + currency + date_range
+ rows[] (campaign_id/name/objective + common metrics + purchases/leads
extracted top-level) + total_rows.

Reusa src/meta_ads/insights.py (Task 2) + run_meta_graph_get (M.2b) +
resolve_meta_date_window (M.2b) + meta_ad_accounts.get_by_id (M.2a).

6 integration tests: happy path sorted, status filter active default,
status ALL omits filtering, account not found, Meta API error PT-BR,
custom date range overrides preset.

Tool count: 59 → 60 (22 always + 38 defer).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: meta_get_ad_set_performance tool (bucket=defer)

**Files:**
- Create: `src/mcp/tools/meta_get_ad_set_performance.py`
- Create: `tests/integration/test_meta_get_ad_set_performance.py`

**Note:** Task 3+4+5 can run in parallel via subagent-driven (isolated files, padrão Sprint 3b.28 validado).

- [ ] **Step 1: Create tool handler file**

Create `src/mcp/tools/meta_get_ad_set_performance.py`:

```python
# bucket: defer
"""meta_get_ad_set_performance — Performance por ad set Meta (Sprint M.3).

Paridade com Google get_ad_group_performance. Bucket=defer (granular,
gestor pede após ver campaign-level).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_overview import resolve_meta_date_window
from src.meta_ads.insights import build_insights_call, parse_insights_row
from src.meta_ads.reports import run_meta_graph_get

_DESCRIPTION = (
    "[DEFER] Performance por ad set Meta Ads: spend, impressões, clicks, CTR, "
    "CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, leads. "
    "Inclui campaign_id/name parent + optimization_goal + billing_event + "
    "daily_budget_brl (CBO=None). Ordenado por spend desc. Filtros: "
    "effective_status (ACTIVE|PAUSED|ARCHIVED|ALL), limit (max 500)."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": (
                "Meta ad account ID (formato act_<numeric>). "
                "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": [
                "TODAY",
                "YESTERDAY",
                "LAST_7_DAYS",
                "LAST_14_DAYS",
                "LAST_30_DAYS",
                "LAST_90_DAYS",
            ],
            "description": (
                "Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos."
            ),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range start. Sobrescreve preset. Requires end_date.",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range end. Sobrescreve preset. Requires start_date.",
        },
        "effective_status": {
            "type": "string",
            "enum": ["ACTIVE", "PAUSED", "ARCHIVED", "ALL"],
            "default": "ACTIVE",
            "description": "Filter por effective_status. ALL inclui tudo.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Max rows. Meta API cap = 500/page.",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}


async def meta_get_ad_set_performance(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    effective_status: str = "ACTIVE",
    limit: int = 100,
) -> dict[str, Any]:
    """Core logic — testable by integration tests."""
    pool = connection.get_pool()
    today = datetime.now(UTC).date()

    try:
        start, end = resolve_meta_date_window(
            date_range or "LAST_30_DAYS", start_date, end_date, today
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Datas inválidas: {e}"}

    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, ad_account_id)
        if account is None:
            return {
                "status": "error",
                "error_message": (
                    f"Ad account {ad_account_id} não encontrada. "
                    f"Use meta_refresh_accounts ou reconnect via /oauth/meta/start."
                ),
            }

    edge, params = build_insights_call(
        level="adset",
        ad_account_id=ad_account_id,
        start=start,
        end=end,
        effective_status=effective_status,
        limit=limit,
    )

    try:
        resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=edge,
            params=params,
            operation_name="meta_get_ad_set_performance",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "level": "adset",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "effective_status": effective_status,
            },
        )
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    rows = [parse_insights_row(r, "adset") for r in resp.get("data", [])]
    rows.sort(key=lambda r: r["spend_brl"], reverse=True)

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "ad_account_name": account.account_name,
        "currency": account.currency,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "total_rows": len(rows),
    }


@register_tool(
    name="meta_get_ad_set_performance",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_ad_set_performance(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        effective_status=args.get("effective_status", "ACTIVE"),
        limit=args.get("limit", 100),
    )
```

- [ ] **Step 2: Create integration tests**

Create `tests/integration/test_meta_get_ad_set_performance.py`:

```python
"""Integration tests Sprint M.3 Task 4: meta_get_ad_set_performance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
    meta_oauth_connections,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


async def _seed_manager_with_meta_conn(db):
    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )
        await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="fb_user_test",
            fb_email="t@v4company.com",
            access_token_enc=b"fake_enc_bytes",
            token_expires_at=datetime.now(UTC) + timedelta(days=60),
            scopes=["ads_read", "ads_management"],
        )
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456",
                    "business_id": "bm_test",
                    "business_name": "Test BM",
                    "account_name": "Test Account",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )
        await manager_meta_account_access.grant(
            conn, manager_id=mid, ad_account_id="act_123456"
        )
    return mid


@pytest.mark.integration
async def test_happy_path_returns_adset_rows_sorted(db):
    """2 ad sets retornados → ordenados por spend_brl DESC + daily_budget conversion."""
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "adset_id": "as1",
                "adset_name": "AS Low",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "daily_budget": "5000",  # R$ 50.00
                "effective_status": "ACTIVE",
                "spend": "200",
                "actions": [{"action_type": "purchase", "value": "2"}],
            },
            {
                "adset_id": "as2",
                "adset_name": "AS High",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "daily_budget": "20000",  # R$ 200.00
                "effective_status": "ACTIVE",
                "spend": "1500",
                "actions": [{"action_type": "purchase", "value": "30"}],
            },
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_ad_set_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_set_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["total_rows"] == 2
    assert result["rows"][0]["ad_set_name"] == "AS High"
    assert result["rows"][0]["spend_brl"] == 1500.0
    assert result["rows"][0]["daily_budget_brl"] == 200.00
    assert result["rows"][1]["daily_budget_brl"] == 50.00


@pytest.mark.integration
async def test_cbo_adset_no_daily_budget_returns_none(db):
    """CBO campaign ad sets sem daily_budget → daily_budget_brl=None."""
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "adset_id": "as1",
                "adset_name": "CBO AS",
                "campaign_id": "c1",
                "campaign_name": "CBO Camp",
                "effective_status": "ACTIVE",
                "spend": "100",
                # daily_budget absent (CBO controls at campaign level)
            }
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_ad_set_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_set_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["rows"][0]["daily_budget_brl"] is None


@pytest.mark.integration
async def test_level_adset_in_params(db):
    """Confirma level='adset' passado à Graph API."""
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_ad_set_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_ad_set_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert captured_params["level"] == "adset"
    assert "adset_id" in captured_params["fields"]
    assert "optimization_goal" in captured_params["fields"]


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    """ad_account_id inexistente → error PT-BR."""
    from src.mcp.tools.meta_get_ad_set_performance import meta_get_ad_set_performance

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )

    result = await meta_get_ad_set_performance(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",
    )

    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
```

- [ ] **Step 3: Run integration tests**

Run: `pytest tests/integration/test_meta_get_ad_set_performance.py -v -m integration`
Expected: 4 PASS.

If Docker unavailable: skip integration, run schema guards:
`pytest tests/unit/test_tools_schemas.py -v` — expected PASS.

- [ ] **Step 4: Pre-push gate**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/tools/meta_get_ad_set_performance.py tests/integration/test_meta_get_ad_set_performance.py
git commit -m "$(cat <<'EOF'
feat(meta_ads): meta_get_ad_set_performance tool (Sprint M.3 Task 4)

Paridade direta com Google get_ad_group_performance. Bucket=defer
(granular, gestor pede após ver campaign-level).

Response inclui campaign_id/name parent + optimization_goal +
billing_event + daily_budget_brl (CBO=None) além de common metrics
+ purchases/leads extracted top-level.

4 integration tests: happy path sorted + daily_budget conversion,
CBO ad set sem daily_budget retorna None, level='adset' in params,
account not found.

Tool count: 60 → 61 (22 always + 39 defer).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: meta_get_ad_performance tool (bucket=defer)

**Files:**
- Create: `src/mcp/tools/meta_get_ad_performance.py`
- Create: `tests/integration/test_meta_get_ad_performance.py`

- [ ] **Step 1: Create tool handler file**

Create `src/mcp/tools/meta_get_ad_performance.py`:

```python
# bucket: defer
"""meta_get_ad_performance — Performance por anúncio (ad) Meta (Sprint M.3).

Paridade com Google get_ad_performance. Bucket=defer (granular, gestor
pede após ver campaign + ad_set levels).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.db import connection
from src.db.repositories import meta_ad_accounts
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.meta_ads.account_overview import resolve_meta_date_window
from src.meta_ads.insights import build_insights_call, parse_insights_row
from src.meta_ads.reports import run_meta_graph_get

_DESCRIPTION = (
    "[DEFER] Performance por anúncio (ad) Meta Ads: spend, impressões, clicks, "
    "CTR, CPC, reach, frequency, purchases, purchases_value_brl, purchase_roas, "
    "leads. Inclui ad_set_id/name + campaign_id/name parents + creative_id. "
    "Ordenado por spend desc. Filtros: effective_status (ACTIVE|PAUSED|"
    "ARCHIVED|ALL), limit (max 500)."
)

_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ad_account_id": {
            "type": "string",
            "pattern": r"^act_\d+$",
            "description": (
                "Meta ad account ID (formato act_<numeric>). "
                "Use meta_list_my_ad_accounts pra descobrir IDs disponíveis."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": [
                "TODAY",
                "YESTERDAY",
                "LAST_7_DAYS",
                "LAST_14_DAYS",
                "LAST_30_DAYS",
                "LAST_90_DAYS",
            ],
            "description": (
                "Preset. Default LAST_30_DAYS se start_date+end_date não fornecidos."
            ),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range start. Sobrescreve preset. Requires end_date.",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range end. Sobrescreve preset. Requires start_date.",
        },
        "effective_status": {
            "type": "string",
            "enum": ["ACTIVE", "PAUSED", "ARCHIVED", "ALL"],
            "default": "ACTIVE",
            "description": "Filter por effective_status. ALL inclui tudo.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": "Max rows. Meta API cap = 500/page.",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}


async def meta_get_ad_performance(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    effective_status: str = "ACTIVE",
    limit: int = 100,
) -> dict[str, Any]:
    """Core logic — testable by integration tests."""
    pool = connection.get_pool()
    today = datetime.now(UTC).date()

    try:
        start, end = resolve_meta_date_window(
            date_range or "LAST_30_DAYS", start_date, end_date, today
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Datas inválidas: {e}"}

    async with pool.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, ad_account_id)
        if account is None:
            return {
                "status": "error",
                "error_message": (
                    f"Ad account {ad_account_id} não encontrada. "
                    f"Use meta_refresh_accounts ou reconnect via /oauth/meta/start."
                ),
            }

    edge, params = build_insights_call(
        level="ad",
        ad_account_id=ad_account_id,
        start=start,
        end=end,
        effective_status=effective_status,
        limit=limit,
    )

    try:
        resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=edge,
            params=params,
            operation_name="meta_get_ad_performance",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "level": "ad",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "effective_status": effective_status,
            },
        )
    except Exception as e:  # noqa: BLE001
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    rows = [parse_insights_row(r, "ad") for r in resp.get("data", [])]
    rows.sort(key=lambda r: r["spend_brl"], reverse=True)

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "ad_account_name": account.account_name,
        "currency": account.currency,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "rows": rows,
        "total_rows": len(rows),
    }


@register_tool(
    name="meta_get_ad_performance",
    description=_DESCRIPTION,
    input_schema=_INPUT_SCHEMA,
    bucket="defer",
)
async def handler(args: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler — pulls context from contextvars, delegates to core."""
    ctx = get_current()
    return await meta_get_ad_performance(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        ad_account_id=args["ad_account_id"],
        date_range=args.get("date_range"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        effective_status=args.get("effective_status", "ACTIVE"),
        limit=args.get("limit", 100),
    )
```

- [ ] **Step 2: Create integration tests**

Create `tests/integration/test_meta_get_ad_performance.py`:

```python
"""Integration tests Sprint M.3 Task 5: meta_get_ad_performance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import (
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
    meta_oauth_connections,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg: PostgresContainer):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


async def _seed_manager_with_meta_conn(db):
    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )
        await meta_oauth_connections.upsert(
            conn,
            manager_id=mid,
            fb_user_id="fb_user_test",
            fb_email="t@v4company.com",
            access_token_enc=b"fake_enc_bytes",
            token_expires_at=datetime.now(UTC) + timedelta(days=60),
            scopes=["ads_read", "ads_management"],
        )
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456",
                    "business_id": "bm_test",
                    "business_name": "Test BM",
                    "account_name": "Test Account",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )
        await manager_meta_account_access.grant(
            conn, manager_id=mid, ad_account_id="act_123456"
        )
    return mid


@pytest.mark.integration
async def test_happy_path_returns_ad_rows_sorted(db):
    """2 ads retornados → ordenados por spend DESC + creative_id presence."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "ad_id": "ad1",
                "ad_name": "Ad Low",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "creative_id": "cr1",
                "effective_status": "ACTIVE",
                "spend": "50",
                "impressions": "500",
                "clicks": "10",
            },
            {
                "ad_id": "ad2",
                "ad_name": "Ad High",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "Camp 1",
                "creative_id": "cr2",
                "effective_status": "ACTIVE",
                "spend": "500",
                "impressions": "5000",
                "clicks": "120",
                "actions": [{"action_type": "purchase", "value": "5"}],
            },
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_ad_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["total_rows"] == 2
    assert result["rows"][0]["ad_name"] == "Ad High"
    assert result["rows"][0]["spend_brl"] == 500.0
    assert result["rows"][0]["creative_id"] == "cr2"
    assert result["rows"][0]["ad_set_id"] == "as1"
    assert result["rows"][0]["campaign_id"] == "c1"


@pytest.mark.integration
async def test_ad_missing_creative_id_returns_none(db):
    """Ad sem creative_id (data issue / draft) → creative_id=None acceptable."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = await _seed_manager_with_meta_conn(db)

    body = {
        "data": [
            {
                "ad_id": "ad1",
                "ad_name": "Ad",
                "adset_id": "as1",
                "adset_name": "AS 1",
                "campaign_id": "c1",
                "campaign_name": "C",
                "effective_status": "PAUSED",
                "spend": "0",
                # creative_id absent
            }
        ]
    }

    with patch(
        "src.mcp.tools.meta_get_ad_performance.run_meta_graph_get",
        new=AsyncMock(return_value=body),
    ):
        result = await meta_get_ad_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["rows"][0]["creative_id"] is None
    assert result["rows"][0]["effective_status_label"] == "PAUSADO"


@pytest.mark.integration
async def test_level_ad_in_params(db):
    """Confirma level='ad' passado à Graph API."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = await _seed_manager_with_meta_conn(db)

    captured_params: dict = {}

    async def capture_call(**kwargs):
        captured_params.update(kwargs["params"])
        return {"data": []}

    with patch(
        "src.mcp.tools.meta_get_ad_performance.run_meta_graph_get",
        new=AsyncMock(side_effect=capture_call),
    ):
        await meta_get_ad_performance(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert captured_params["level"] == "ad"
    assert "ad_id" in captured_params["fields"]
    assert "creative_id" in captured_params["fields"]


@pytest.mark.integration
async def test_account_not_found_returns_error(db):
    """ad_account_id inexistente → error PT-BR."""
    from src.mcp.tools.meta_get_ad_performance import meta_get_ad_performance

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )

    result = await meta_get_ad_performance(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_999999",
    )

    assert result["status"] == "error"
    assert "act_999999" in result["error_message"]
```

- [ ] **Step 3: Run integration tests**

Run: `pytest tests/integration/test_meta_get_ad_performance.py -v -m integration`
Expected: 4 PASS.

If Docker unavailable: skip, run schema guards:
`pytest tests/unit/test_tools_schemas.py -v` — expected PASS.

- [ ] **Step 4: Pre-push gate**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/tools/meta_get_ad_performance.py tests/integration/test_meta_get_ad_performance.py
git commit -m "$(cat <<'EOF'
feat(meta_ads): meta_get_ad_performance tool (Sprint M.3 Task 5)

Paridade direta com Google get_ad_performance. Bucket=defer (granular,
gestor pede após campaign + ad_set levels).

Response inclui ad_set_id/name + campaign_id/name parents + creative_id
(None se draft/issue) além de common metrics + purchases/leads extracted
top-level.

4 integration tests: happy path sorted, ad sem creative_id retorna None,
level='ad' in params, account not found.

Tool count: 61 → 62 (22 always + 40 defer = META SPRINT 3 COMPLETO).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Pre-push full sweep + push deploy

**Files:** (no changes — verification only)

- [ ] **Step 1: Run pre-push gate**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS in ~30s.

If FAIL: read output, fix issue (ruff format / mypy error / test failure), re-run.

- [ ] **Step 2: Verify alwaysLoad count regression test still passes**

Run: `pytest tests/unit/test_mcp_server_meta.py -v`
Expected: All PASS — includes `test_list_tools_anthropic_alwaysload_count_matches_always_bucket` which validates 22 tools (was 21, +1 from meta_get_campaign_performance) have `anthropic/alwaysLoad: True`.

If FAIL: bucket kwarg wasn't applied correctly to one of the tools. Re-check Task 3 line `bucket="always"`.

- [ ] **Step 3: Push to main**

```bash
git push origin main
```

Expected: CI + Deploy parallel workflows trigger.

- [ ] **Step 4: Watch CI + Deploy**

Run: `gh run list --limit 3`
Then: `gh run watch <id>` for both CI and Deploy runs.
Expected: Both green in ~3-4min.

- [ ] **Step 5: Verify production /health**

Run: `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health`
Expected: `200 OK`.

- [ ] **Step 6: Verify new tools registered in production**

This validates that bucket=always tools appear in list_tools _meta correctly. Done by Wellington via smoke runbook Task 8 (calling tools real).

---

## Task 7: Smoke runbook generation (subagent)

**Files:**
- Create: `docs/operacao/phase-M-3-bootstrap.md`

- [ ] **Step 1: Dispatch smoke-runbook-generator subagent**

Use Agent tool with `subagent_type=smoke-runbook-generator` and prompt:

```
Generate smoke runbook for Sprint M.3 — 3 Meta Ads performance tools.

Sprint plan: docs/superpowers/plans/2026-05-26-sprint-m-3-meta-campaign-performance.md
Sprint spec: docs/superpowers/specs/2026-05-26-sprint-m-3-meta-campaign-performance-design.md

Tools to test:
1. meta_get_campaign_performance (bucket=always)
2. meta_get_ad_set_performance (bucket=defer)
3. meta_get_ad_performance (bucket=defer)

Required test coverage (10 tests T1-T10):
- T1: meta_get_campaign_performance happy path (conta V4 com Wellington admin)
- T2: meta_get_ad_set_performance happy path
- T3: meta_get_ad_performance happy path
- T4: effective_status="ALL" inclui ARCHIVED rows
- T5: custom date range start_date/end_date override
- T6: per-value probe — cada effective_status enum (ACTIVE/PAUSED/ARCHIVED/ALL)
  → valida 4 valores funcionam OU remove os que falham
- T7: error path — ad_account_id inexistente retorna friendly error
- T8: error path — token expirado retorna PT-BR reconnect message
- T9: BUC tracking — após 5 calls, meta_rate_counters.calls_used incrementa
- T10: audit_log.platform="meta" + provider_request_id populated

Reference style: docs/operacao/phase-M-2b-bootstrap.md (most recent Meta runbook).

Target ad_account_id: Wellington choose from meta_list_my_ad_accounts (precisa
ter spend ativo + pelo menos 1 purchase event configurado pra T1 validar
purchases extraction).

Write file to: docs/operacao/phase-M-3-bootstrap.md
```

Expected output: runbook file created with 10 well-structured test sections, per-value probe table for T6, expected output snippets for assertion validation.

- [ ] **Step 2: Review runbook output**

Run: `cat docs/operacao/phase-M-3-bootstrap.md | head -100`

Verify:
- 10 tests T1-T10 present
- Each test has clear setup + expected output
- T6 has 4 probe rows (ACTIVE/PAUSED/ARCHIVED/ALL)
- T8 mentions token expiry simulation strategy
- T9 includes SQL query to verify meta_rate_counters increment
- T10 includes SQL query to verify audit_log row

If something missing: re-dispatch subagent with specific fix request, or edit inline if minor.

- [ ] **Step 3: Commit runbook**

```bash
git add docs/operacao/phase-M-3-bootstrap.md
git commit -m "$(cat <<'EOF'
docs(meta_ads): smoke runbook Sprint M.3 (Task 7)

10 tests T1-T10 cobrindo:
- T1-T3 happy path 3 tools (campaign + ad_set + ad)
- T4 effective_status ALL inclui ARCHIVED
- T5 custom date range override
- T6 per-value probe 4 effective_status (ACTIVE/PAUSED/ARCHIVED/ALL)
- T7 ad_account inexistente error PT-BR
- T8 token expirado reconnect message
- T9 BUC tracking meta_rate_counters increment
- T10 audit_log.platform='meta' + provider_request_id

Pra Wellington executar manual após Task 6 deploy production.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

---

## Task 8: Smoke execution Wellington manual

**Files:** (no code changes — validation only)

**Owner:** Wellington (não-subagent — precisa Bearer token real + Meta conn ativa)

- [ ] **Step 1: Wellington abre Claude Code com v4-ads MCP conectado**

Pre-reqs:
- Bearer token v4-ads válido em ~/.claude.json (rotacionar via UI se needed)
- Meta OAuth conectado pelo Wellington
- Pelo menos 1 ad_account_id ativo (com spend + purchase event)

- [ ] **Step 2: Execute T1-T10 do runbook**

Wellington segue `docs/operacao/phase-M-3-bootstrap.md` step-by-step.

Esperado: 10/10 PASS.

Edge cases que podem aparecer:
- **T6 effective_status probe:** se algum valor (e.g., ARCHIVED) retornar 400, document como F-finding novo + remover do schema enum.
- **T1 purchases=0:** se conta de teste não tem purchase event configurado, é OK — validar leads ou spend metrics.
- **T8 token expiry:** mock difícil em smoke real. Pode skipar OU usar conta secundária com token expirado de teste.

- [ ] **Step 3: Wellington reporta resultado**

Outcomes:
- **10/10 PASS:** proceed to Task 9 signoff.
- **Algum F-finding novo:** catalog via `/findings-add` skill, fix em sub-sprint M.3.1 se crítico, OU document como known-limitation V0 se non-blocker.
- **Major break:** roll back via `git revert HEAD~5..HEAD` (5 commits do M.3) + investigate.

---

## Task 9: Signoff — docs sync + tool count update

**Files:**
- Modify: `CLAUDE.md` (Current state + tool count 59→62 + Last updated stamp)
- Modify: `docs/operacao/sprint-history.md` (add Sprint M.3 row)

- [ ] **Step 1: Update CLAUDE.md "Last updated" + tool count**

In CLAUDE.md:

Find line `**Last updated:** 2026-05-25 — pós-Sprint 3b.39 F1 D3 fix ship`
Replace with: `**Last updated:** 2026-05-26 — pós-Sprint M.3 ship (3 tools Meta performance: campaign always + ad_set/ad defer)`

Find: `### Shipped — 59 MCP tools (57 Google + 2 Meta)`
Replace with: `### Shipped — 62 MCP tools (57 Google + 5 Meta)`

In the same heading section, find the Meta family row and update:
Look for: `Meta Sprint M.1 + M.1.1 + M.2a + M.2b | ✅ 2026-05-24→25 |`
Append after that row (new row pra M.3):

```markdown
| Meta Sprint M.3 | ✅ 2026-05-26 | 3 tools performance (campaign always + ad_set/ad defer) — paridade Google get_campaign_performance/get_ad_group_performance/get_ad_performance. Shared module `src/meta_ads/insights.py` (~150 LOC) + 3 thin handlers. Caminho B+ Meta volume contribution: +3-6 calls/dia naturais. 17 unit tests + 14 integration tests + 10 smoke tests Wellington manual PASS. Tool count 59→62 (22 always + 40 defer). |
```

- [ ] **Step 2: Update sprint-history.md**

In `docs/operacao/sprint-history.md`, find the most recent Sprint row (Sprint 3b.39 ou M.2b) and append after it:

```markdown
| **M.3** | 2026-05-26 | 3 tools Meta performance (campaign/ad_set/ad) | ✅ shipped | Paridade direta Google get_*_performance. Approach C — shared `src/meta_ads/insights.py` (~150 LOC) + 3 thin handlers (~30 LOC cada) + META_EFFECTIVE_STATUS_LABELS em _meta_common.py. Bucket: campaign=always (Pareto Meta top), ad_set+ad=defer. Caminho B+ contribution: +3-6 calls/dia naturais ao Wellington dogfood (acelera 500 calls/15d threshold pra Full Access re-submit). 17 unit tests + 14 integration tests + 10 smoke tests PASS. Tool count 59→62 (22 always + 40 defer). Spec: `2026-05-26-sprint-m-3-meta-campaign-performance-design.md`. Plan: `2026-05-26-sprint-m-3-meta-campaign-performance.md`. |
```

(Adapt format to match the existing table column structure — check the actual current format in the file when editing.)

- [ ] **Step 3: Pre-push gate**

Run: `python scripts/check_pre_push.py`
Expected: 5/5 PASS.

- [ ] **Step 4: Commit signoff**

```bash
git add CLAUDE.md docs/operacao/sprint-history.md
git commit -m "$(cat <<'EOF'
docs: signoff Sprint M.3 — 3 tools Meta performance (campaign + ad_set + ad)

Updates:
- CLAUDE.md Last updated 2026-05-26
- Tool count 59 → 62 (57 Google + 5 Meta = 22 always + 40 defer)
- Meta family row M.3 add
- sprint-history.md row M.3 add (Approach C + Caminho B+ contribution)

17 unit tests + 14 integration tests + 10 smoke tests PASS Wellington
manual em conta V4 Lima Soares & Co.

Caminho B+ contribution validated: +3-6 calls/dia naturais.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git push origin main
```

- [ ] **Step 5: Final verification**

Run: `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health`
Expected: `200 OK`.

Run: `gh run list --limit 1`
Expected: Latest run green.

Sprint M.3 COMPLETO. ✅

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Section 1 Architecture → Task 2 (insights.py) + Tasks 3/4/5 (3 tool handlers)
- ✅ Section 2 Schema input → Tasks 3/4/5 each defines `_INPUT_SCHEMA`
- ✅ Section 3 Response shape → Task 2 (`parse_insights_row`) + Tasks 3/4/5 (assembly + sort)
- ✅ Section 4 Insights module → Task 2 full implementation
- ✅ Section 5 Testing strategy → Task 2 (15 unit) + Tasks 3/4/5 (14 integration) + Task 7 (10 smoke)
- ✅ Section 6 Risks + Out-of-scope → Schema constraints in Tasks 3/4/5 (limit≤500, effective_status enum 4 valores, date_range LAST_N_DAYS only)
- ✅ Section 7 Sprint timeline → Tasks ordered A1→A7→B1→B2→B3
- ✅ Section 8 Signoff criteria → Task 6 (pre-push + CI green) + Task 8 (smoke) + Task 9 (docs sync)

**Placeholder scan:** Zero TBD/TODO. Each step has exact code or exact command. ✓

**Type consistency:**
- `Level = Literal["campaign", "adset", "ad"]` definida em insights.py Task 2, usada consistente nas 3 tools Tasks 3/4/5.
- `parse_insights_row(row, level)` signature matches across all 3 tools.
- `build_insights_call` kwargs idênticos nas 3 tools (level apenas muda).
- Response shape: `status / ad_account_id / ad_account_name / currency / date_range / rows / total_rows` — idêntico nas 3 tools.
- Schema input shape — idêntico nas 3 tools (effective_status enum + limit + date_range).
- ✓

**File paths:** Exact paths everywhere. ✓

**Commands:** Exact pytest invocations + expected outputs documented. ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-26-sprint-m-3-meta-campaign-performance.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch fresh subagent per task (haiku pra Task 2 pure module, sonnet pra Tasks 3/4/5 + 7), review between tasks via 2-stage review, fast iteration. Tasks 3+4+5 can run in parallel (isolated files).

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
