# Sprint M.2b — Meta Get Account Overview + App Review Prep — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `meta_get_account_overview` (1ª Graph API real call) + completar pré-requisitos Meta App Review (data-deletion callback + refresh endpoint + UI polish + A5 fix), seguido de smoke real e submit App Review.

**Architecture:** Pure module `account_overview.py` (zero-IO date math + parsing + warnings) consumed by MCP tool orchestrator que delega Graph calls a `run_meta_graph_get` (M.2a executor, audit + BUC counter internos). 2 endpoints novos OAuth (data-deletion-callback HMAC-validated + refresh-accounts sync) + admin UI extensions (revoke modal + refresh button via vanilla `<dialog>` + form POST).

**Tech Stack:** Python 3.12, FastAPI + Jinja2 + HTMX 2 (CDN), facebook-business v21 SDK, asyncpg (raw SQL), pytest + respx, structlog. Mantém zero build step + zero JS framework convention V4.

**Spec:** [docs/superpowers/specs/2026-05-25-sprint-m2b-meta-get-account-overview-design.md](../specs/2026-05-25-sprint-m2b-meta-get-account-overview-design.md)

**Estimativa:** ~3-4 dias úteis. 7 tasks A-G implementáveis + 3 tasks H-J de smoke/deploy/App Review.

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `src/meta_ads/account_overview.py` | Pure module: date math (resolve_meta_date_window, shift_to_previous_period), parsing (parse_insights_response), deltas (compute_deltas), warnings (build_warnings) |
| `src/mcp/tools/meta_get_account_overview.py` | MCP tool orchestrator: classify() + meta_get_account_overview() async — wraps Graph 2 calls + pure helpers |
| `src/web/templates/legal/data_deletion_status.html` | Public status page Jinja2 — minimal text "Solicitação recebida, processamento manual em até 30 dias" |
| `tests/unit/test_meta_account_overview.py` | ~20 unit tests pure module |
| `tests/unit/test_meta_signed_request.py` | ~8 unit tests HMAC validation |
| `tests/unit/test_get_my_audit_log_platform.py` | ~2 unit tests platform field regression |
| `tests/integration/test_meta_get_account_overview.py` | 4 integration tests (happy + 3 edges) |
| `tests/integration/test_meta_data_deletion_callback.py` | 2 integration tests (valid sig + invalid sig) |
| `tests/integration/test_meta_refresh_accounts.py` | 2 integration tests (happy + token expired) |
| `scripts/test_meta_deletion_callback.py` | Helper local pra gerar signed_request HMAC-valid pra smoke T6 |
| `docs/operacao/phase-M-2b-bootstrap.md` | Smoke runbook 8 tests Wellington manual |

### Modified files

| Path | Lines | Change |
|---|---|---|
| `src/auth/meta_oauth.py` | append ~120 | Adicionar 2 endpoints (data-deletion-callback + refresh-accounts) + helper `_verify_meta_signed_request` |
| `src/db/repositories/audit_log.py` | ~1 | `list_for_manager` SQL SELECT: append `platform` column |
| `src/mcp/apply_change.py` | +3 | Branch novo `meta_get_account_overview` |
| `src/mcp/tools/__init__.py` | +1 | Register meta_get_account_overview na lista |
| `src/web/routes.py` | +1 handler | `data_deletion_status(code)` view function + flash message `?meta_refreshed=1` |
| `src/web/templates/admin/index.html` | +30 | Botões "Atualizar lista" + "Revogar conexão" + modal + warning banner |
| `src/web/templates/_components.html` | (nenhuma) | reuse existing button macros |

### Out of scope (deferred)

- Migration nova — ZERO (coluna `audit_log.platform` já existe em M.2a migration 003/004)
- `pyproject.toml` dependencies — ZERO (facebook-business v21 já adicionado M.1)
- `.github/workflows/deploy.yml` — ZERO (META_APP_ID + META_APP_SECRET já configurados M.1)

---

## Task ordering rationale

Topological order (independent → dependent):

1. **Task A — A5 fix** (independent, ~30 min) — quick win, paralela com todas
2. **Task B — Pure module** (independent, ~1h) — no IO, fast unit cycle
3. **Task C — Tool orchestrator** (depends B) — consumes account_overview helpers + run_meta_graph_get
4. **Task D — data-deletion-callback endpoint + helper** (independent) — _verify_meta_signed_request reusable
5. **Task E — refresh-accounts endpoint + flash message** (independent) — usa existing meta_oauth_connections + httpx pattern
6. **Task F — Admin UI buttons + modal** (depends D + E shipped) — wires UI to endpoints
7. **Task G — Smoke runbook + helper script** (depends A-F shipped) — depende endpoints existirem
8. **Task H — Pre-push gate + push deploy** (depends A-G done)
9. **Task I — Smoke real Wellington manual** (depends H deploy verde) — out-of-scope agentic execution
10. **Task J — Meta App Review submit Wellington manual** (depends I PASS) — out-of-scope agentic execution

Paralelização: A + B + D + E pode dispatchar paralelos (arquivos não-overlap). C + F + G serializados.

---

## Task A — A5 fix: get_my_audit_log return platform field

**Files:**
- Modify: `src/db/repositories/audit_log.py` (single line in SELECT)
- Test: `tests/unit/test_get_my_audit_log_platform.py` (new file)

**Subagent model recommendation:** haiku (mechanical isolated fix)

### A.1 Write failing unit test

- [ ] **Step 1: Create test file**

Create `tests/unit/test_get_my_audit_log_platform.py`:

```python
"""Regression test A5: get_my_audit_log returns platform field per row."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def db_with_rows(pg, db):
    """Insert 1 google + 1 meta audit_log row pra mesmo manager."""
    from src.db.repositories import audit_log, managers

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )
        # Google row (default platform)
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id=None,
            action_type="read",
            operation="list_my_accounts",
            status="success",
            # platform=google by default
        )
        # Meta row (explicit platform)
        await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="act_123",
            action_type="read",
            operation="meta_list_my_ad_accounts",
            status="success",
            platform="meta",
        )
    return mid


@pytest.mark.integration
async def test_list_for_manager_returns_platform_field(db_with_rows, db):
    """list_for_manager rows MUST contain 'platform' field."""
    from src.db.repositories import audit_log

    async with db.acquire() as conn:
        rows = await audit_log.list_for_manager(
            conn, manager_id=db_with_rows, days=7, limit=10
        )
    assert len(rows) == 2
    assert all("platform" in r for r in rows), f"missing platform field in rows: {rows}"
    platforms = {r["platform"] for r in rows}
    assert platforms == {"google", "meta"}, f"unexpected platforms: {platforms}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/unit/test_get_my_audit_log_platform.py -v
```

Expected: FAIL with `KeyError: 'platform'` or `AssertionError: missing platform field`.

### A.2 Modify audit_log.list_for_manager SQL

- [ ] **Step 3: Edit SQL SELECT statement**

Locate `src/db/repositories/audit_log.py`, function `list_for_manager`. Append `platform` à lista de columns:

```python
# BEFORE (current M.2a):
sql = f"""SELECT id, occurred_at, operation, customer_id, action_type,
                 target_count, status, duration_ms, provider_request_id,
                 error_message
          FROM audit_log
          WHERE {" AND ".join(where)}
          ORDER BY occurred_at DESC
          LIMIT ${idx}"""

# AFTER:
sql = f"""SELECT id, occurred_at, operation, customer_id, action_type,
                 target_count, status, duration_ms, provider_request_id,
                 error_message, platform
          FROM audit_log
          WHERE {" AND ".join(where)}
          ORDER BY occurred_at DESC
          LIMIT ${idx}"""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/unit/test_get_my_audit_log_platform.py -v
```

Expected: PASS (2 platforms found: google + meta).

### A.3 Verify get_my_audit_log tool surfaces field

- [ ] **Step 5: Quick read tool implementation**

Check `src/mcp/tools/get_my_audit_log.py` — return statement deve já incluir todos os campos via `dict(r)` ou similar. Se sim, sem mudanças. Se return constrói dict manualmente, append `"platform": row["platform"]`.

- [ ] **Step 6: Commit**

```bash
git add src/db/repositories/audit_log.py tests/unit/test_get_my_audit_log_platform.py
git commit -m "fix(audit): get_my_audit_log return inclui platform field (A5 fix M.2b)

audit_log.list_for_manager SQL SELECT estava omitindo platform column
(adicionada em M.2a migration 003). Tool retorna agora platform field
em cada row, permitindo filtrar histórico google vs meta cross-platform.

Catalog: A5 OPEN → closed em M.2b Task A.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task B — Pure module account_overview.py

**Files:**
- Create: `src/meta_ads/account_overview.py`
- Test: `tests/unit/test_meta_account_overview.py`

**Subagent model recommendation:** haiku (pure functions, isolated)

### B.1 resolve_meta_date_window

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_meta_account_overview.py`:

```python
"""Unit tests pure module src/meta_ads/account_overview.py (Sprint M.2b)."""

from datetime import date

import pytest

from src.meta_ads.account_overview import (
    build_warnings,
    compute_deltas,
    parse_insights_response,
    resolve_meta_date_window,
    shift_to_previous_period,
)


# resolve_meta_date_window
TODAY = date(2026, 5, 25)


def test_resolve_date_window_default_last_7_days():
    start, end = resolve_meta_date_window(None, None, None, TODAY)
    assert start == date(2026, 5, 19)
    assert end == TODAY


def test_resolve_date_window_last_30_days():
    start, end = resolve_meta_date_window("LAST_30_DAYS", None, None, TODAY)
    assert start == date(2026, 4, 26)
    assert end == TODAY


def test_resolve_date_window_today():
    start, end = resolve_meta_date_window("TODAY", None, None, TODAY)
    assert start == TODAY == end


def test_resolve_date_window_yesterday():
    start, end = resolve_meta_date_window("YESTERDAY", None, None, TODAY)
    assert start == date(2026, 5, 24)
    assert end == date(2026, 5, 24)


def test_resolve_date_window_custom_overrides_preset():
    start, end = resolve_meta_date_window(
        "LAST_7_DAYS", "2026-05-01", "2026-05-10", TODAY
    )
    assert start == date(2026, 5, 1)
    assert end == date(2026, 5, 10)


def test_resolve_date_window_partial_custom_raises():
    with pytest.raises(ValueError, match="start_date e end_date devem ser fornecidos juntos"):
        resolve_meta_date_window(None, "2026-05-01", None, TODAY)
    with pytest.raises(ValueError):
        resolve_meta_date_window(None, None, "2026-05-10", TODAY)
```

- [ ] **Step 2: Run tests to verify failures**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k resolve_date
```

Expected: 6 FAILs (ModuleNotFoundError ou ImportError).

- [ ] **Step 3: Create module + implement resolve_meta_date_window**

Create `src/meta_ads/account_overview.py`:

```python
"""Pure module pra meta_get_account_overview tool (Sprint M.2b).

Zero IO. Date math + Graph response parsing + deltas + warnings.
"""

from datetime import date, datetime, timedelta
from typing import Any

# Conversion actions a totalizar (cross-platform pattern com Google)
CONVERSION_ACTION_TYPES = frozenset({
    "purchase",
    "lead",
    "complete_registration",
    "offsite_conversion.fb_pixel_purchase",
    "offsite_conversion.fb_pixel_lead",
    "offsite_conversion.fb_pixel_complete_registration",
})

_PRESET_DAYS: dict[str, int] = {
    "LAST_7_DAYS": 7,
    "LAST_14_DAYS": 14,
    "LAST_30_DAYS": 30,
    "LAST_90_DAYS": 90,
}


def resolve_meta_date_window(
    preset: str | None,
    start_date: str | None,
    end_date: str | None,
    today: date,
) -> tuple[date, date]:
    """Resolve preset OR (start, end) → (start, end) date tuple.

    Custom (start+end) overrides preset. Default LAST_7_DAYS se ambos None.
    Raises ValueError se inconsistent (apenas um de start/end fornecido).
    """
    if start_date and end_date:
        return (date.fromisoformat(start_date), date.fromisoformat(end_date))
    if start_date or end_date:
        raise ValueError("start_date e end_date devem ser fornecidos juntos")
    preset = preset or "LAST_7_DAYS"
    if preset == "TODAY":
        return (today, today)
    if preset == "YESTERDAY":
        y = today - timedelta(days=1)
        return (y, y)
    days = _PRESET_DAYS[preset]
    return (today - timedelta(days=days - 1), today)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k resolve_date
```

Expected: 6 PASS.

### B.2 shift_to_previous_period

- [ ] **Step 5: Append failing tests**

```python
# tests/unit/test_meta_account_overview.py — append

def test_shift_previous_7_day_window():
    # Current: May 19-25 (7 dias)
    # Previous: May 12-18 (7 dias)
    prev_start, prev_end = shift_to_previous_period(date(2026, 5, 19), date(2026, 5, 25))
    assert prev_start == date(2026, 5, 12)
    assert prev_end == date(2026, 5, 18)


def test_shift_previous_single_day():
    # Current: May 25 only
    # Previous: May 24
    prev_start, prev_end = shift_to_previous_period(date(2026, 5, 25), date(2026, 5, 25))
    assert prev_start == date(2026, 5, 24)
    assert prev_end == date(2026, 5, 24)


def test_shift_previous_30_day_window():
    # Current: Apr 26 - May 25 (30 dias)
    # Previous: Mar 27 - Apr 25 (30 dias)
    prev_start, prev_end = shift_to_previous_period(date(2026, 4, 26), date(2026, 5, 25))
    assert prev_start == date(2026, 3, 27)
    assert prev_end == date(2026, 4, 25)
```

- [ ] **Step 6: Run tests to verify failures**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k shift_previous
```

Expected: 3 FAILs (ImportError).

- [ ] **Step 7: Append implementation**

```python
# src/meta_ads/account_overview.py — append

def shift_to_previous_period(start: date, end: date) -> tuple[date, date]:
    """Calculate previous period of same length (e.g., LAST_7_DAYS → 7d before that)."""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return (prev_start, prev_end)
```

- [ ] **Step 8: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k shift_previous
```

Expected: 3 PASS.

### B.3 parse_insights_response

- [ ] **Step 9: Append failing tests**

```python
# tests/unit/test_meta_account_overview.py — append

def test_parse_insights_empty_data():
    result = parse_insights_response({"data": []})
    assert result["spend"] == 0.0
    assert result["impressions"] == 0
    assert result["conversions"] == 0


def test_parse_insights_no_data_key():
    result = parse_insights_response({})
    assert result["spend"] == 0.0


def test_parse_insights_full_row():
    data = {
        "data": [{
            "spend": "1234.56",
            "impressions": "45000",
            "clicks": "1200",
            "ctr": "2.67",
            "cpc": "1.03",
            "reach": "23000",
            "frequency": "1.95",
            "actions": [
                {"action_type": "purchase", "value": "35"},
                {"action_type": "link_click", "value": "1200"},  # NOT counted
                {"action_type": "lead", "value": "5"},
            ],
            "action_values": [
                {"action_type": "purchase", "value": "8400.0"},
                {"action_type": "link_click", "value": "0"},  # NOT counted
            ],
            "purchase_roas": [{"action_type": "omni_purchase", "value": "6.8"}],
        }]
    }
    result = parse_insights_response(data)
    assert result["spend"] == 1234.56
    assert result["impressions"] == 45000
    assert result["clicks"] == 1200
    assert result["ctr"] == 2.67
    assert result["cpc"] == 1.03
    assert result["reach"] == 23000
    assert result["frequency"] == 1.95
    assert result["conversions"] == 40  # 35 purchase + 5 lead
    assert result["conversion_value"] == 8400.0
    assert result["purchase_roas"] == 6.8


def test_parse_insights_fb_pixel_action_types_counted():
    """offsite_conversion.fb_pixel_* MUST be counted (Meta tracking)."""
    data = {
        "data": [{
            "spend": "100",
            "actions": [
                {"action_type": "offsite_conversion.fb_pixel_purchase", "value": "10"},
                {"action_type": "offsite_conversion.fb_pixel_lead", "value": "3"},
            ],
        }]
    }
    result = parse_insights_response(data)
    assert result["conversions"] == 13


def test_parse_insights_missing_purchase_roas_returns_zero():
    data = {"data": [{"spend": "100"}]}  # no purchase_roas key
    result = parse_insights_response(data)
    assert result["purchase_roas"] == 0.0


def test_parse_insights_null_values_handled():
    """Meta às vezes retorna null pra fields ausentes."""
    data = {"data": [{"spend": None, "impressions": None, "actions": None}]}
    result = parse_insights_response(data)
    assert result["spend"] == 0.0
    assert result["impressions"] == 0
    assert result["conversions"] == 0
```

- [ ] **Step 10: Run tests to verify failures**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k parse_insights
```

Expected: 6 FAILs.

- [ ] **Step 11: Append implementation**

```python
# src/meta_ads/account_overview.py — append

def parse_insights_response(data: dict[str, Any]) -> dict[str, float | int]:
    """Parse Graph /insights response → normalized metrics dict.

    Graph response format:
    {"data": [{"spend": "1234.56", "impressions": "45000",
               "actions": [{"action_type": "purchase", "value": "12"}, ...], ...}]}

    Returns dict with strict types. Empty/missing/null fields → 0.
    """
    rows = data.get("data") or []
    if not rows:
        return _empty_metrics()
    row = rows[0]
    actions = _sum_actions(row.get("actions") or [], CONVERSION_ACTION_TYPES)
    action_values = _sum_actions(row.get("action_values") or [], CONVERSION_ACTION_TYPES)
    return {
        "spend": _to_float(row.get("spend")),
        "impressions": _to_int(row.get("impressions")),
        "clicks": _to_int(row.get("clicks")),
        "ctr": _to_float(row.get("ctr")),
        "cpc": _to_float(row.get("cpc")),
        "reach": _to_int(row.get("reach")),
        "frequency": _to_float(row.get("frequency")),
        "conversions": int(actions),
        "conversion_value": float(action_values),
        "purchase_roas": _extract_purchase_roas(row.get("purchase_roas") or []),
    }


def _sum_actions(actions: list[dict], filter_types: frozenset[str]) -> float:
    """Sum 'value' field across actions matching filter_types."""
    return sum(
        _to_float(a.get("value"))
        for a in actions
        if a.get("action_type") in filter_types
    )


def _extract_purchase_roas(roas_arr: list[dict]) -> float:
    """Graph returns purchase_roas como [{"action_type": "omni_purchase", "value": "6.8"}]."""
    for entry in roas_arr:
        if entry.get("action_type") in ("purchase", "omni_purchase"):
            return _to_float(entry.get("value"))
    return 0.0


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _to_int(v: Any) -> int:
    if v is None:
        return 0
    try:
        return int(float(v))  # Meta returns strings; int(float()) handles "1234.0"
    except (TypeError, ValueError):
        return 0


def _empty_metrics() -> dict[str, float | int]:
    return {
        "spend": 0.0, "impressions": 0, "clicks": 0, "ctr": 0.0, "cpc": 0.0,
        "reach": 0, "frequency": 0.0, "conversions": 0, "conversion_value": 0.0,
        "purchase_roas": 0.0,
    }
```

- [ ] **Step 12: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k parse_insights
```

Expected: 6 PASS.

### B.4 compute_deltas

- [ ] **Step 13: Append failing tests**

```python
# tests/unit/test_meta_account_overview.py — append

def test_compute_deltas_growth():
    current = {"spend": 1200.0, "conversions": 40}
    previous = {"spend": 1000.0, "conversions": 30}
    deltas = compute_deltas(current, previous)
    assert deltas["spend_pct"] == 20.0
    assert round(deltas["conversions_pct"], 2) == 33.33


def test_compute_deltas_decline():
    current = {"spend": 800.0, "conversions": 25}
    previous = {"spend": 1000.0, "conversions": 30}
    deltas = compute_deltas(current, previous)
    assert deltas["spend_pct"] == -20.0
    assert round(deltas["conversions_pct"], 2) == -16.67


def test_compute_deltas_previous_zero_returns_none():
    """Division undefined when previous=0 — return None pra Claude interpret as N/A."""
    current = {"spend": 100.0, "conversions": 5}
    previous = {"spend": 0.0, "conversions": 0}
    deltas = compute_deltas(current, previous)
    assert deltas["spend_pct"] is None
    assert deltas["conversions_pct"] is None


def test_compute_deltas_missing_keys_zero():
    """Missing key in current OR previous treated as 0."""
    current = {"spend": 100.0}  # missing conversions
    previous = {"spend": 50.0, "conversions": 10}
    deltas = compute_deltas(current, previous)
    assert deltas["spend_pct"] == 100.0
    assert deltas["conversions_pct"] == -100.0  # 0 vs 10


def test_compute_deltas_returns_all_expected_keys():
    current = {"spend": 100, "impressions": 1000, "clicks": 50, "conversions": 5,
               "conversion_value": 500, "purchase_roas": 5.0}
    previous = {"spend": 100, "impressions": 1000, "clicks": 50, "conversions": 5,
                "conversion_value": 500, "purchase_roas": 5.0}
    deltas = compute_deltas(current, previous)
    expected_keys = {"spend_pct", "impressions_pct", "clicks_pct", "conversions_pct",
                     "conversion_value_pct", "purchase_roas_pct"}
    assert set(deltas.keys()) == expected_keys
```

- [ ] **Step 14: Run tests to verify failures**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k compute_deltas
```

Expected: 5 FAILs.

- [ ] **Step 15: Append implementation**

```python
# src/meta_ads/account_overview.py — append

def compute_deltas(current: dict, previous: dict) -> dict[str, float | None]:
    """Returns dict with `_pct` suffix per metric. None if previous=0."""
    out: dict[str, float | None] = {}
    for key in (
        "spend", "impressions", "clicks", "conversions",
        "conversion_value", "purchase_roas",
    ):
        prev_val = previous.get(key, 0)
        curr_val = current.get(key, 0)
        if prev_val == 0:
            out[f"{key}_pct"] = None
        else:
            out[f"{key}_pct"] = round((curr_val - prev_val) / prev_val * 100, 2)
    return out
```

- [ ] **Step 16: Run tests to verify they pass**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k compute_deltas
```

Expected: 5 PASS.

### B.5 build_warnings

- [ ] **Step 17: Append failing tests**

```python
# tests/unit/test_meta_account_overview.py — append

from datetime import UTC


def test_build_warnings_ativo_token_fresh_returns_empty():
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    token_expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)  # 60d future
    warnings = build_warnings("ATIVO", token_expires, now)
    assert warnings == []


def test_build_warnings_account_pagamento_pendente():
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    token_expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    warnings = build_warnings("PAGAMENTO_PENDENTE", token_expires, now)
    assert len(warnings) == 1
    assert "PAGAMENTO_PENDENTE" in warnings[0]
    assert "billing" in warnings[0].lower() or "métricas" in warnings[0]


def test_build_warnings_account_fechado():
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    token_expires = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    warnings = build_warnings("FECHADO", token_expires, now)
    assert len(warnings) == 1
    assert "FECHADO" in warnings[0]


def test_build_warnings_token_expires_in_5_days():
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    token_expires = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)  # 5d future
    warnings = build_warnings("ATIVO", token_expires, now)
    assert len(warnings) == 1
    assert "5 dias" in warnings[0]
    assert "2026-05-30" in warnings[0]
    assert "Reconectar" in warnings[0]


def test_build_warnings_token_expires_in_6_days_still_warns():
    """Threshold é <7d (strictly less than)."""
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    token_expires = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)  # 6d
    warnings = build_warnings("ATIVO", token_expires, now)
    assert len(warnings) == 1


def test_build_warnings_token_expires_in_7_days_no_warn():
    """7d exactly → não warning ainda."""
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    token_expires = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)  # 7d
    warnings = build_warnings("ATIVO", token_expires, now)
    assert warnings == []


def test_build_warnings_token_none_no_warn():
    """token_expires_at NULL → skip token warning."""
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    warnings = build_warnings("ATIVO", None, now)
    assert warnings == []


def test_build_warnings_both_warnings_present():
    """Account fechado E token expirando — 2 warnings retornadas."""
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    token_expires = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)  # 3d
    warnings = build_warnings("PAGAMENTO_PENDENTE", token_expires, now)
    assert len(warnings) == 2
```

- [ ] **Step 18: Run tests to verify failures**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v -k build_warnings
```

Expected: 8 FAILs.

- [ ] **Step 19: Append implementation**

```python
# src/meta_ads/account_overview.py — append

def build_warnings(
    account_status_label: str,
    token_expires_at: datetime | None,
    now: datetime,
) -> list[str]:
    """Returns lista PT-BR warnings ativos (account_status problema + token <7d)."""
    out: list[str] = []
    if account_status_label != "ATIVO":
        out.append(
            f"account_status={account_status_label} — "
            f"métricas podem estar desatualizadas ou ad serving suspenso. "
            f"Verificar billing/status no Meta Business Suite."
        )
    if token_expires_at is not None:
        days_left = (token_expires_at - now).days
        if days_left < 7:
            iso_date = token_expires_at.date().isoformat()
            out.append(
                f"Token OAuth Meta expira em {days_left} dias ({iso_date}). "
                f"Reconectar via /admin → 'Conectar Meta' pra evitar interrupção das tools."
            )
    return out
```

- [ ] **Step 20: Run all account_overview tests to verify they pass**

```bash
python -m pytest tests/unit/test_meta_account_overview.py -v
```

Expected: 28+ PASS (6 resolve + 3 shift + 6 parse + 5 deltas + 8 warnings).

- [ ] **Step 21: Commit**

```bash
git add src/meta_ads/account_overview.py tests/unit/test_meta_account_overview.py
git commit -m "feat(meta_ads): account_overview pure module (Sprint M.2b Task B)

src/meta_ads/account_overview.py:
- resolve_meta_date_window(preset|custom, today) → (start, end)
- shift_to_previous_period(start, end) → (prev_start, prev_end)
- parse_insights_response(graph_data) → normalized metrics dict
- compute_deltas(current, previous) → {key_pct: float|None} (None se prev=0)
- build_warnings(account_status, token_expires_at, now) → list[str] PT-BR

CONVERSION_ACTION_TYPES frozenset filtra purchase + lead +
complete_registration + variants fb_pixel pra cross-platform parity.

28 unit tests cobrindo all functions + edge cases.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task C — Tool meta_get_account_overview.py orchestrator

**Files:**
- Create: `src/mcp/tools/meta_get_account_overview.py`
- Modify: `src/mcp/apply_change.py` (+3 lines branch)
- Modify: `src/mcp/tools/__init__.py` (+1 line register)
- Test: `tests/integration/test_meta_get_account_overview.py` (new)

**Subagent model recommendation:** sonnet (orchestrator + integration tests)

### C.1 Write failing integration test (happy path)

- [ ] **Step 1: Create integration test file**

Create `tests/integration/test_meta_get_account_overview.py`:

```python
"""Integration tests Sprint M.2b: meta_get_account_overview tool."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.db.repositories import (
    managers,
    manager_meta_account_access,
    meta_ad_accounts,
    meta_oauth_connections,
)

pytestmark = pytest.mark.asyncio


# Fixtures
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
        await meta_ad_accounts.upsert_many(conn, [{
            "ad_account_id": "act_123456",
            "business_id": "bm_test",
            "business_name": "Test BM",
            "account_name": "Test Account",
            "currency": "BRL",
            "timezone_name": "America/Sao_Paulo",
            "account_status": account_status,
        }])
        await manager_meta_account_access.grant(
            conn, manager_id=mid, ad_account_id="act_123456",
        )
    return mid


@pytest.mark.integration
async def test_meta_get_account_overview_happy_path(db):
    """Happy path: 2 graph calls + parse + deltas + warnings empty + return shape."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = await _seed_manager_with_meta_conn(db)

    current_body = {"data": [{
        "spend": "1200.0", "impressions": "10000", "clicks": "300",
        "ctr": "3.0", "cpc": "4.0", "reach": "8000", "frequency": "1.25",
        "actions": [{"action_type": "purchase", "value": "40"}],
        "action_values": [{"action_type": "purchase", "value": "8000"}],
        "purchase_roas": [{"action_type": "omni_purchase", "value": "6.67"}],
    }]}
    previous_body = {"data": [{
        "spend": "1000.0", "impressions": "8000", "clicks": "240",
        "ctr": "3.0", "cpc": "4.17", "reach": "6500", "frequency": "1.23",
        "actions": [{"action_type": "purchase", "value": "30"}],
        "action_values": [{"action_type": "purchase", "value": "6000"}],
        "purchase_roas": [{"action_type": "omni_purchase", "value": "6.0"}],
    }]}

    with patch(
        "src.mcp.tools.meta_get_account_overview.run_meta_graph_get",
        new=AsyncMock(side_effect=[current_body, previous_body]),
    ):
        result = await meta_get_account_overview(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
            date_range="LAST_7_DAYS",
        )

    assert result["status"] == "success"
    assert result["ad_account_id"] == "act_123456"
    assert result["account_name"] == "Test Account"
    assert result["account_status_label"] == "ATIVO"
    assert result["currency"] == "BRL"
    assert result["current"]["spend"] == 1200.0
    assert result["current"]["conversions"] == 40
    assert result["current"]["purchase_roas"] == 6.67
    assert result["previous"]["spend"] == 1000.0
    assert result["deltas"]["spend_pct"] == 20.0
    assert result["deltas"]["conversions_pct"] == round((40 - 30) / 30 * 100, 2)
    assert result["_warnings"] == []
    assert "date_range" in result
    assert result["date_range"]["start"] is not None
    assert result["date_range"]["end"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/integration/test_meta_get_account_overview.py::test_meta_get_account_overview_happy_path -v
```

Expected: FAIL (ImportError: meta_get_account_overview).

### C.2 Implement orchestrator

- [ ] **Step 3: Create tool file**

Create `src/mcp/tools/meta_get_account_overview.py`:

```python
"""meta_get_account_overview — 1ª tool Meta com Graph API real call (Sprint M.2b).

Single ad_account, fields essenciais, comparativo período anterior,
warnings PT-BR pra account_status problemático + token expiry <7d.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from src.db import connection
from src.db.repositories import meta_ad_accounts, meta_oauth_connections
from src.mcp.tools._meta_common import META_ACCOUNT_STATUS_LABELS
from src.meta_ads.account_overview import (
    build_warnings,
    compute_deltas,
    parse_insights_response,
    resolve_meta_date_window,
    shift_to_previous_period,
)
from src.meta_ads.reports import run_meta_graph_get

log = structlog.get_logger(__name__)


def classify() -> dict[str, Any]:
    return {
        "tool": "meta_get_account_overview",
        "blast_radius": "read_only",
        "platform": "meta",
        "estimated_buc_per_call": 2,
    }


INPUT_SCHEMA: dict[str, Any] = {
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
                "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS",
                "LAST_90_DAYS", "TODAY", "YESTERDAY",
            ],
            "description": "Janela temporal preset. Default LAST_7_DAYS se start_date+end_date não fornecidos.",
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range start (YYYY-MM-DD). Sobrescreve preset. Requires end_date.",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Custom range end (YYYY-MM-DD). Sobrescreve preset. Requires start_date.",
        },
    },
    "required": ["ad_account_id"],
    "additionalProperties": False,
}


async def meta_get_account_overview(
    manager_id: UUID,
    session_id: UUID,
    *,
    ad_account_id: str,
    date_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Account-level overview Meta com comparativo período anterior."""
    pool = connection.get_pool()

    # 1. Resolve date window (cheap, validate antes de hit DB/Graph)
    today = datetime.now(UTC).date()
    try:
        current_start, current_end = resolve_meta_date_window(
            date_range, start_date, end_date, today
        )
    except ValueError as e:
        return {"status": "error", "error_message": f"Parâmetros de data inválidos: {e}"}
    prev_start, prev_end = shift_to_previous_period(current_start, current_end)

    # 2. Get account metadata + oc (pra warnings)
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
        oc = await meta_oauth_connections.get_active_for_manager(conn, manager_id)
        if oc is None:
            return {
                "status": "error",
                "error_message": "Nenhuma conexão Meta ativa. Conectar via /oauth/meta/start.",
            }

    account_status_label = META_ACCOUNT_STATUS_LABELS.get(
        account.account_status or 0, "DESCONHECIDO"
    )

    # 3. Graph API calls (current + previous via shared executor)
    # run_meta_graph_get internally: builds api, records BUC counter,
    # records audit when audit_this_call=True,
    # raises MetaAdsFriendlyError on any failure. Returns parsed dict body.
    fields = (
        "spend,impressions,clicks,ctr,cpc,reach,frequency,"
        "actions,action_values,purchase_roas"
    )

    try:
        current_resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=f"/{ad_account_id}/insights",
            params={
                "fields": fields,
                "time_range": (
                    f'{{"since":"{current_start.isoformat()}",'
                    f'"until":"{current_end.isoformat()}"}}'
                ),
                "level": "account",
                "ad_account_id": ad_account_id,
            },
            operation_name="meta_get_account_overview",
            estimated_calls=1,
            audit_this_call=True,
            params_summary={
                "ad_account_id": ad_account_id,
                "date_range": str(date_range),
                "period": "current",
                "start": current_start.isoformat(),
                "end": current_end.isoformat(),
            },
        )
        previous_resp = await run_meta_graph_get(
            manager_id=manager_id,
            session_id=session_id,
            edge=f"/{ad_account_id}/insights",
            params={
                "fields": fields,
                "time_range": (
                    f'{{"since":"{prev_start.isoformat()}",'
                    f'"until":"{prev_end.isoformat()}"}}'
                ),
                "level": "account",
                "ad_account_id": ad_account_id,
            },
            operation_name="meta_get_account_overview",
            estimated_calls=1,
            audit_this_call=False,
        )
    except Exception as e:
        if hasattr(e, "message"):
            return {"status": "error", "error_message": e.message}
        return {"status": "error", "error_message": str(e)}

    current_metrics = parse_insights_response(current_resp)
    previous_metrics = parse_insights_response(previous_resp)
    deltas = compute_deltas(current_metrics, previous_metrics)
    warnings = build_warnings(account_status_label, oc.token_expires_at, datetime.now(UTC))

    return {
        "status": "success",
        "ad_account_id": ad_account_id,
        "account_name": account.account_name,
        "account_status_label": account_status_label,
        "currency": account.currency,
        "date_range": {
            "start": current_start.isoformat(),
            "end": current_end.isoformat(),
        },
        "current": current_metrics,
        "previous": previous_metrics,
        "deltas": deltas,
        "_warnings": warnings,
    }
```

- [ ] **Step 4: Run happy path test to verify it passes**

```bash
python -m pytest tests/integration/test_meta_get_account_overview.py::test_meta_get_account_overview_happy_path -v
```

Expected: PASS.

### C.3 Edge case integration tests

- [ ] **Step 5: Append account_status_warning test**

```python
# tests/integration/test_meta_get_account_overview.py — append

@pytest.mark.integration
async def test_meta_get_account_overview_account_status_warning(db):
    """account_status=PAGAMENTO_PENDENTE → _warnings list populated."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = await _seed_manager_with_meta_conn(db, account_status=3)  # PAGAMENTO_PENDENTE

    body = {"data": [{"spend": "100"}]}
    with patch(
        "src.mcp.tools.meta_get_account_overview.run_meta_graph_get",
        new=AsyncMock(side_effect=[body, body]),
    ):
        result = await meta_get_account_overview(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert result["account_status_label"] == "PAGAMENTO_PENDENTE"
    assert any("PAGAMENTO_PENDENTE" in w for w in result["_warnings"])
```

- [ ] **Step 6: Append token_expired_warning test**

```python
@pytest.mark.integration
async def test_meta_get_account_overview_token_expiring_warning(db):
    """token_expires_at em 5d → _warnings list populated."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = await _seed_manager_with_meta_conn(db, token_expires_in_days=5)

    body = {"data": [{"spend": "100"}]}
    with patch(
        "src.mcp.tools.meta_get_account_overview.run_meta_graph_get",
        new=AsyncMock(side_effect=[body, body]),
    ):
        result = await meta_get_account_overview(
            manager_id=mid,
            session_id=uuid4(),
            ad_account_id="act_123456",
        )

    assert result["status"] == "success"
    assert any(
        "Token OAuth Meta expira" in w and "dias" in w
        for w in result["_warnings"]
    )
```

- [ ] **Step 7: Append no_oc test**

```python
@pytest.mark.integration
async def test_meta_get_account_overview_no_oc_returns_error(db):
    """Manager sem conexão Meta active → error PT-BR friendly."""
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview

    mid = uuid4()
    async with db.acquire() as conn:
        await managers.create(
            conn, manager_id=mid, email="t@v4company.com", full_name="Tester"
        )
        await meta_ad_accounts.upsert_many(conn, [{
            "ad_account_id": "act_123456",
            "business_id": "bm",
            "business_name": "BM",
            "account_name": "AC",
            "currency": "BRL",
            "timezone_name": "America/Sao_Paulo",
            "account_status": 1,
        }])

    result = await meta_get_account_overview(
        manager_id=mid,
        session_id=uuid4(),
        ad_account_id="act_123456",
    )

    assert result["status"] == "error"
    assert "Nenhuma conexão Meta ativa" in result["error_message"]
```

- [ ] **Step 8: Run all integration tests**

```bash
python -m pytest tests/integration/test_meta_get_account_overview.py -v
```

Expected: 4 PASS (happy + account_status + token_expiring + no_oc).

### C.4 Wire em apply_change router + tools registry

- [ ] **Step 9: Find apply_change router file**

```bash
grep -rn "def apply_change\|def dispatch" "D:/V4 ads MCP/src/mcp/" | head -5
```

Locate router function. Likely `src/mcp/apply_change.py` or `src/mcp/server.py`. Add branch:

```python
# src/mcp/apply_change.py — add branch (mirror existing meta_list_my_ad_accounts pattern)
elif tool_name == "meta_get_account_overview":
    from src.mcp.tools.meta_get_account_overview import meta_get_account_overview
    return await meta_get_account_overview(
        manager_id=manager_id,
        session_id=session_id,
        **kwargs,
    )
```

- [ ] **Step 10: Register tool in __init__.py / tool list**

```bash
grep -rn "meta_list_my_ad_accounts\|TOOL_REGISTRY\|TOOLS = " "D:/V4 ads MCP/src/mcp/" | head -5
```

Mirror registration pattern. Probably append `meta_get_account_overview` ao registry dict.

- [ ] **Step 11: Run integration suite to verify wiring**

```bash
python -m pytest tests/integration/test_meta_get_account_overview.py -v
```

Expected: still 4 PASS.

### C.5 Commit

- [ ] **Step 12: Commit**

```bash
git add src/mcp/tools/meta_get_account_overview.py src/mcp/apply_change.py src/mcp/tools/__init__.py tests/integration/test_meta_get_account_overview.py
git commit -m "feat(mcp): meta_get_account_overview tool — 1ª Graph API real call (M.2b Task C)

src/mcp/tools/meta_get_account_overview.py:
- Single ad_account_id, fields essenciais (spend/imp/clicks/ctr/cpc/conv/
  conv_value/purchase_roas/reach/frequency)
- 2 Graph calls (current + previous via run_meta_graph_get) → compute_deltas
- Warnings PT-BR: account_status problemático (PAGAMENTO_PENDENTE/FECHADO/etc)
  + token_expires_at <7d
- Schema validation: ad_account_id pattern, date_range preset enum,
  start_date+end_date custom override (ZERO oneOf/allOf/anyOf — 3b.19B.1)
- audit_this_call=True na current call → audit_log + BUC counter internos
  via run_meta_graph_get

apply_change router: branch novo pra read-only direct exec.

4 integration tests (happy + account_status_warn + token_expiring_warn + no_oc).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task D — Data deletion callback endpoint + HMAC helper

**Files:**
- Modify: `src/auth/meta_oauth.py` (+1 helper + 1 endpoint, ~80 lines)
- Create: `src/web/templates/legal/data_deletion_status.html`
- Modify: `src/web/routes.py` (+1 handler ~10 lines)
- Test: `tests/unit/test_meta_signed_request.py` (new)
- Test: `tests/integration/test_meta_data_deletion_callback.py` (new)

**Subagent model recommendation:** sonnet (HMAC validation + endpoint integration)

### D.1 _verify_meta_signed_request helper — unit tests

- [ ] **Step 1: Create unit test file**

Create `tests/unit/test_meta_signed_request.py`:

```python
"""Unit tests pra _verify_meta_signed_request HMAC validation (Sprint M.2b)."""

import base64
import hashlib
import hmac
import json

import pytest

from src.auth.meta_oauth import _verify_meta_signed_request


APP_SECRET = "test_app_secret_xyz"


def _make_signed_request(payload: dict, secret: str = APP_SECRET) -> str:
    """Generate signed_request matching Meta spec format."""
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{sig_b64}.{payload_b64}"


def test_verify_signed_request_valid():
    payload = {
        "algorithm": "HMAC-SHA256",
        "user_id": "9999",
        "expires": 1747824000,
        "issued_at": 1747820400,
    }
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is not None
    assert result["user_id"] == "9999"
    assert result["algorithm"] == "HMAC-SHA256"


def test_verify_signed_request_invalid_signature():
    payload = {"algorithm": "HMAC-SHA256", "user_id": "9999"}
    signed_request = _make_signed_request(payload, secret="wrong_secret")
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is None


def test_verify_signed_request_missing_dot():
    result = _verify_meta_signed_request("no_dot_separator", APP_SECRET)
    assert result is None


def test_verify_signed_request_invalid_base64():
    result = _verify_meta_signed_request("!!!.!!!", APP_SECRET)
    assert result is None


def test_verify_signed_request_invalid_json_payload():
    """Payload base64-decodes mas não é JSON válido."""
    bogus_payload = base64.urlsafe_b64encode(b"not json").decode().rstrip("=")
    sig = hmac.new(APP_SECRET.encode(), bogus_payload.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    result = _verify_meta_signed_request(f"{sig_b64}.{bogus_payload}", APP_SECRET)
    assert result is None


def test_verify_signed_request_wrong_algorithm():
    payload = {"algorithm": "RSA-SHA256", "user_id": "9999"}  # not HMAC-SHA256
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is None


def test_verify_signed_request_base64url_padding_variations():
    """Meta base64url tem padding stripped. Helper must handle both."""
    payload = {"algorithm": "HMAC-SHA256", "user_id": "1"}  # short payload → odd length
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is not None


def test_verify_signed_request_empty_payload_missing_algorithm():
    payload = {"user_id": "9999"}  # no algorithm
    signed_request = _make_signed_request(payload)
    result = _verify_meta_signed_request(signed_request, APP_SECRET)
    assert result is None
```

- [ ] **Step 2: Run tests to verify failures**

```bash
python -m pytest tests/unit/test_meta_signed_request.py -v
```

Expected: 8 FAILs (ImportError _verify_meta_signed_request).

### D.2 Implement _verify_meta_signed_request helper

- [ ] **Step 3: Append helper to meta_oauth.py**

In `src/auth/meta_oauth.py`, add helper near top of file (after imports, before routes):

```python
import base64
import hashlib
import hmac
import json


def _verify_meta_signed_request(signed_request: str, app_secret: str) -> dict | None:
    """Validate Meta signed_request HMAC SHA256.

    Format: base64url(signature).base64url(json_payload)
    Returns parsed payload dict, ou None se invalid (wrong sig, malformed, etc).
    """
    try:
        encoded_sig, encoded_payload = signed_request.split(".", 1)
    except ValueError:
        return None

    # base64url padding fix (Meta strips padding)
    try:
        sig = base64.urlsafe_b64decode(encoded_sig + "=" * (-len(encoded_sig) % 4))
        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
    except (ValueError, base64.binascii.Error):
        return None

    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("algorithm") != "HMAC-SHA256":
        return None

    return payload
```

- [ ] **Step 4: Run unit tests to verify they pass**

```bash
python -m pytest tests/unit/test_meta_signed_request.py -v
```

Expected: 8 PASS.

### D.3 Endpoint /oauth/meta/data-deletion-callback

- [ ] **Step 5: Write failing integration test**

Create `tests/integration/test_meta_data_deletion_callback.py`:

```python
"""Integration tests Sprint M.2b: /oauth/meta/data-deletion-callback endpoint."""

import base64
import hashlib
import hmac
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import connection

pytestmark = pytest.mark.asyncio


APP_SECRET = "test_app_secret_xyz"


def _make_signed_request(payload: dict, secret: str = APP_SECRET) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{sig_b64}.{payload_b64}"


@pytest.fixture
async def client(app_with_db, monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.integration
async def test_data_deletion_callback_valid_signature(client):
    """Valid HMAC signed_request → 200 + return {url, confirmation_code} + audit_log row."""
    payload = {
        "algorithm": "HMAC-SHA256",
        "user_id": "fb_user_9999",
        "expires": 1747824000,
        "issued_at": 1747820400,
    }
    signed_request = _make_signed_request(payload)

    resp = await client.post(
        "/oauth/meta/data-deletion-callback",
        data={"signed_request": signed_request},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "url" in body
    assert "confirmation_code" in body
    assert body["url"].endswith(body["confirmation_code"])

    # Verify audit_log row created
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT operation, platform, params_summary FROM audit_log "
            "WHERE operation = 'meta_data_deletion_request' "
            "ORDER BY occurred_at DESC LIMIT 1"
        )
    assert row is not None
    assert row["platform"] == "meta"
    assert row["params_summary"]["meta_user_id"] == "fb_user_9999"
    assert row["params_summary"]["confirmation_code"] == body["confirmation_code"]


@pytest.mark.integration
async def test_data_deletion_callback_invalid_signature(client):
    """Wrong secret → 400 Bad Request."""
    payload = {"algorithm": "HMAC-SHA256", "user_id": "fb_user_9999"}
    signed_request = _make_signed_request(payload, secret="wrong_secret")

    resp = await client.post(
        "/oauth/meta/data-deletion-callback",
        data={"signed_request": signed_request},
    )
    assert resp.status_code == 400


@pytest.mark.integration
async def test_data_deletion_callback_missing_signed_request(client):
    """Empty form body → 400 Bad Request."""
    resp = await client.post("/oauth/meta/data-deletion-callback", data={})
    assert resp.status_code == 400
```

- [ ] **Step 6: Run tests to verify failures**

```bash
python -m pytest tests/integration/test_meta_data_deletion_callback.py -v
```

Expected: 3 FAILs (endpoint not registered).

- [ ] **Step 7: Implement endpoint**

In `src/auth/meta_oauth.py`, append after revoke endpoint:

```python
from uuid import uuid4


@router.post("/data-deletion-callback", response_model=None)
async def meta_data_deletion_callback(request: Request) -> dict[str, str]:
    """V0 callback: log + confirmation_code (NÃO deleta data imediatamente).

    Wellington (admin) processa manualmente em até 30 dias (LGPD/GDPR window).
    Meta App Review requirement.
    """
    settings = get_settings()
    form = await request.form()
    signed_request = str(form.get("signed_request", ""))
    if not signed_request:
        raise HTTPException(status_code=400, detail="signed_request required")

    payload = _verify_meta_signed_request(signed_request, settings.meta_app_secret)
    if payload is None:
        log.warning("meta_data_deletion_invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    meta_user_id = str(payload.get("user_id", ""))
    confirmation_code = str(uuid4())

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=None,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_data_deletion_request",
            params_summary={
                "meta_user_id": meta_user_id,
                "confirmation_code": confirmation_code,
                "expires": payload.get("expires"),
            },
            status="success",
            platform="meta",
        )

    log.info(
        "meta_data_deletion_request_logged",
        meta_user_id=meta_user_id,
        confirmation_code=confirmation_code,
    )

    base_url = "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app"
    return {
        "url": f"{base_url}/legal/data-deletion-status/{confirmation_code}",
        "confirmation_code": confirmation_code,
    }
```

- [ ] **Step 8: Run integration tests to verify pass**

```bash
python -m pytest tests/integration/test_meta_data_deletion_callback.py -v
```

Expected: 3 PASS.

### D.4 Public status page

- [ ] **Step 9: Create template**

Create `src/web/templates/legal/data_deletion_status.html`:

```html
{% extends "_base.html" %}

{% block title %}Solicitação de exclusão de dados — V4 Ads MCP{% endblock %}

{% block content %}
<div class="legal-content" style="max-width: 720px; margin: 64px auto; padding: 0 24px;">
    <h1>Solicitação de exclusão de dados recebida</h1>

    <p><strong>Código de confirmação:</strong> <code>{{ confirmation_code }}</code></p>

    <p>Recebemos sua solicitação de exclusão de dados associados à sua conta Facebook
    no V4 Ads MCP — ferramenta interna da V4 Company (V4 Lima Soares & Co, João Pessoa/PB).</p>

    <h2>Próximos passos</h2>

    <p>O administrador <strong>Wellington Ribeiro</strong> processará sua solicitação
    manualmente em até <strong>30 dias úteis</strong>. Você receberá confirmação por email
    quando os dados forem removidos dos nossos sistemas:</p>

    <ul>
        <li>Tabelas <code>meta_oauth_connections</code> (token OAuth)</li>
        <li>Tabela <code>meta_ad_accounts</code> (cache de ad accounts)</li>
        <li>Tabela <code>manager_meta_account_access</code> (permissões)</li>
        <li>Rows do <code>audit_log</code> associadas à sua interação Meta</li>
    </ul>

    <h2>Contato</h2>

    <p>Dúvidas: <a href="mailto:wellinton.ribeiro@v4company.com">wellinton.ribeiro@v4company.com</a></p>

    <p style="margin-top: 48px; color: #666; font-size: 0.875rem;">
        <a href="/legal/privacy">Política de Privacidade</a> · <a href="/legal/terms">Termos de Uso</a>
    </p>
</div>
{% endblock %}
```

- [ ] **Step 10: Add view handler em src/web/routes.py**

Find `_legal_*` handlers (privacy, terms) and add sibling:

```python
@app.get("/legal/data-deletion-status/{code}", response_class=HTMLResponse)
async def data_deletion_status(request: Request, code: str) -> HTMLResponse:
    return templates.TemplateResponse(
        "legal/data_deletion_status.html",
        {"request": request, "confirmation_code": code},
    )
```

- [ ] **Step 11: Manual smoke locally**

```bash
# Local server pra teste visual (Wellington faz no smoke runbook depois)
python -m uvicorn src.app:create_app --factory --reload --host 0.0.0.0 --port 8000
# Browser: http://localhost:8000/legal/data-deletion-status/test-uuid-1234
```

Expected: page renders sem erro, mostra "Solicitação recebida... código test-uuid-1234".

- [ ] **Step 12: Commit**

```bash
git add src/auth/meta_oauth.py src/web/templates/legal/data_deletion_status.html src/web/routes.py tests/unit/test_meta_signed_request.py tests/integration/test_meta_data_deletion_callback.py
git commit -m "feat(auth): /oauth/meta/data-deletion-callback endpoint + HMAC validation (M.2b Task D)

src/auth/meta_oauth.py:
- _verify_meta_signed_request() helper: base64url decode + HMAC-SHA256
  compare_digest + algorithm whitelist
- POST /oauth/meta/data-deletion-callback endpoint: validate signature,
  log audit_log(operation=meta_data_deletion_request, platform=meta),
  return {url, confirmation_code} required by Meta spec
- V0 NÃO deleta dados imediatamente (manual signoff Wellington, LGPD 30d window)

src/web/templates/legal/data_deletion_status.html + route:
- Public status page com confirmation_code + lista de tabelas a serem
  deletadas + contato

8 unit tests HMAC validation + 3 integration tests endpoint.

Pré-req Meta App Review.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task E — Refresh-accounts endpoint + flash message

**Files:**
- Modify: `src/auth/meta_oauth.py` (+1 endpoint ~70 lines)
- Modify: `src/web/routes.py` (+1 flash branch ~3 lines)
- Test: `tests/integration/test_meta_refresh_accounts.py` (new)

**Subagent model recommendation:** sonnet (httpx + DB upsert + auth flow)

### E.1 Write failing integration test

- [ ] **Step 1: Create test file**

Create `tests/integration/test_meta_refresh_accounts.py`:

```python
"""Integration tests Sprint M.2b: /oauth/meta/refresh-accounts endpoint."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import respx
from httpx import ASGITransport, AsyncClient, Response

from src.db import connection
from src.db.repositories import managers, meta_ad_accounts, meta_oauth_connections

pytestmark = pytest.mark.asyncio


async def _seed_manager_with_meta(db, *, token_expires_days: int = 60):
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
            token_expires_at=datetime.now(UTC) + timedelta(days=token_expires_days),
            scopes=["ads_read", "ads_management"],
        )
    return mid


@pytest.fixture
async def authed_client(app_with_db, db, monkeypatch):
    """Client com session cookie pra manager autenticado."""
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Note: actual auth depends on app session middleware; if cookies
        # required, instantiate Session via login flow first. For now,
        # patch current_manager dependency.
        yield c


@pytest.mark.integration
@respx.mock
async def test_refresh_accounts_happy_path(authed_client, db, monkeypatch):
    """POST /refresh-accounts → respx Graph /me/adaccounts → upsert + grant + redirect."""
    from src.auth.tokens import derive_master_key_from_settings, encrypt_refresh_token
    from src.config import get_settings

    mid = await _seed_manager_with_meta(db)
    # Patch encryption: re-write fake_enc_bytes with valid encrypted token
    settings = get_settings()
    master_key = derive_master_key_from_settings(settings.aes_master_key)
    real_enc = encrypt_refresh_token("fake_long_token", master_key)
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE meta_oauth_connections SET access_token_enc=$1 WHERE manager_id=$2",
            real_enc, mid,
        )

    # Mock Graph /me/adaccounts
    respx.get("https://graph.facebook.com/v22.0/me/adaccounts").mock(
        return_value=Response(
            200,
            json={"data": [
                {
                    "id": "act_777",
                    "name": "Refreshed Client",
                    "business": {"id": "bm_x", "name": "Refreshed BM"},
                    "account_status": 1,
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                }
            ]},
        )
    )

    # Patch dependency current_manager to return our seeded manager
    from src.web import deps
    from src.auth.session import SessionUser
    monkeypatch.setattr(
        deps, "current_manager",
        lambda: SessionUser(id=mid, email="t@v4company.com", role="active"),
    )

    resp = await authed_client.post(
        "/oauth/meta/refresh-accounts",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/admin?meta_refreshed=1" in resp.headers["location"]

    # Verify upsert happened
    async with db.acquire() as conn:
        account = await meta_ad_accounts.get_by_id(conn, "act_777")
    assert account is not None
    assert account.account_name == "Refreshed Client"


@pytest.mark.integration
async def test_refresh_accounts_token_expired_returns_422(authed_client, db, monkeypatch):
    """token_expires_at no passado → 422 PT-BR error."""
    mid = await _seed_manager_with_meta(db, token_expires_days=-1)  # expired

    from src.web import deps
    from src.auth.session import SessionUser
    monkeypatch.setattr(
        deps, "current_manager",
        lambda: SessionUser(id=mid, email="t@v4company.com", role="active"),
    )

    resp = await authed_client.post(
        "/oauth/meta/refresh-accounts",
        follow_redirects=False,
    )
    assert resp.status_code == 422
    assert "Token Meta expirou" in resp.text or "expirou" in resp.text.lower()
```

- [ ] **Step 2: Run tests to verify failures**

```bash
python -m pytest tests/integration/test_meta_refresh_accounts.py -v
```

Expected: 2 FAILs (endpoint not registered).

### E.2 Implement endpoint

- [ ] **Step 3: Append endpoint to meta_oauth.py**

In `src/auth/meta_oauth.py`, append after data-deletion-callback:

```python
from src.auth.tokens import decrypt_refresh_token
from src.db.repositories import manager_meta_account_access


@router.post("/refresh-accounts")
async def meta_oauth_refresh_accounts(
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> RedirectResponse:
    """Re-sync meta_ad_accounts list via Graph /me/adaccounts.

    Útil quando cliente novo entra no BM ou ad account é renomeada.
    Não requer reconnect OAuth (usa long-lived token existente).
    """
    settings = get_settings()
    pool = connection.get_pool()

    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, user.id)
        if oc is None:
            raise HTTPException(status_code=404, detail="No active Meta connection")

        # Check token expiry (proactive)
        if oc.token_expires_at and (oc.token_expires_at - datetime.now(UTC)).days < 0:
            raise HTTPException(
                status_code=422,
                detail="Token Meta expirou. Reconectar via /oauth/meta/start.",
            )

        master_key = derive_master_key_from_settings(settings.aes_master_key)
        access_token = decrypt_refresh_token(oc.access_token_enc, master_key)

    async with httpx.AsyncClient(timeout=30.0) as http:
        adacc_resp = await http.get(
            f"{META_GRAPH_BASE}/me/adaccounts",
            params={
                "fields": "id,name,business,account_status,currency,timezone_name",
                "access_token": access_token,
            },
        )
        ad_accounts_data = (
            adacc_resp.json().get("data", [])
            if adacc_resp.status_code == 200
            else []
        )

    accounts_payload: list[dict[str, Any]] = []
    for a in ad_accounts_data:
        ad_id_raw = a.get("id", "")
        if not ad_id_raw.startswith("act_"):
            ad_id_raw = f"act_{ad_id_raw}"
        business = a.get("business") or {}
        accounts_payload.append({
            "ad_account_id": ad_id_raw,
            "business_id": business.get("id"),
            "business_name": business.get("name"),
            "account_name": a.get("name", ad_id_raw),
            "currency": a.get("currency"),
            "timezone_name": a.get("timezone_name"),
            "account_status": a.get("account_status"),
        })

    async with pool.acquire() as conn:
        if accounts_payload:
            await meta_ad_accounts.upsert_many(conn, accounts_payload)
            for a in accounts_payload:
                await manager_meta_account_access.grant(
                    conn, manager_id=user.id, ad_account_id=a["ad_account_id"],
                )

        await audit_log.record(
            conn,
            manager_id=user.id,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_refresh_accounts",
            target_count=len(accounts_payload),
            status="success",
            platform="meta",
        )

    log.info(
        "meta_accounts_refreshed",
        manager_id=str(user.id),
        count=len(accounts_payload),
    )
    return RedirectResponse("/admin?meta_refreshed=1", status_code=302)
```

- [ ] **Step 4: Run integration tests to verify they pass**

```bash
python -m pytest tests/integration/test_meta_refresh_accounts.py -v
```

Expected: 2 PASS.

### E.3 Admin index handler flash message branch

- [ ] **Step 5: Find admin_index handler**

```bash
grep -n "admin_index\|meta_connected=1\|meta_revoked=1" "D:/V4 ads MCP/src/web/routes.py"
```

Add branch for `?meta_refreshed=1` mirroring existing flash messages logic.

- [ ] **Step 6: Edit handler**

In `src/web/routes.py`, in admin_index handler:

```python
# BEFORE — existing flash branches
meta_connected = request.query_params.get("meta_connected") == "1"
meta_revoked = request.query_params.get("meta_revoked") == "1"

# AFTER — append
meta_connected = request.query_params.get("meta_connected") == "1"
meta_revoked = request.query_params.get("meta_revoked") == "1"
meta_refreshed = request.query_params.get("meta_refreshed") == "1"

# In context dict passed to template:
return templates.TemplateResponse("admin/index.html", {
    "request": request,
    # ... existing keys ...
    "meta_connected": meta_connected,
    "meta_revoked": meta_revoked,
    "meta_refreshed": meta_refreshed,
})
```

(Template rendering of message will be added in Task F.)

- [ ] **Step 7: Commit**

```bash
git add src/auth/meta_oauth.py src/web/routes.py tests/integration/test_meta_refresh_accounts.py
git commit -m "feat(auth): /oauth/meta/refresh-accounts endpoint + flash message (M.2b Task E)

src/auth/meta_oauth.py:
- POST /oauth/meta/refresh-accounts: re-sync meta_ad_accounts via Graph
  /me/adaccounts, upsert + grant_all_active (idempotent), audit_log,
  redirect /admin?meta_refreshed=1
- Token expiry pre-check: 422 PT-BR se token <0 dias

src/web/routes.py: admin_index handler flash branch ?meta_refreshed=1
pra subsequente render no template (Task F).

2 integration tests (happy + token_expired).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task F — Admin UI buttons (Revoke modal + Refresh + warning banner)

**Files:**
- Modify: `src/web/templates/admin/index.html` (+~40 lines no card Meta)

**Subagent model recommendation:** haiku (HTML + form, isolated template change)

### F.1 Add buttons + modal + warning banner

- [ ] **Step 1: Locate Meta connection card in admin/index.html**

```bash
grep -n "meta_conn\|Suas conexões\|meta_token_expiring" "D:/V4 ads MCP/src/web/templates/admin/index.html"
```

Identifica linha onde card Meta connection é renderizada.

- [ ] **Step 2: Append HTML inside `{% if meta_conn %}` block**

Edit `src/web/templates/admin/index.html`. Append após existing meta_conn info (fb_email, scopes, expiry days):

```html
  <!-- M.2b: actions + warning banner + revoke modal -->
  <div class="meta-conn-actions" style="margin-top: 16px; display: flex; gap: 8px;">
    <form method="post" action="/oauth/meta/refresh-accounts" style="margin: 0;">
      <button type="submit" class="btn btn-secondary">
        Atualizar lista
      </button>
    </form>
    <button
      type="button"
      onclick="document.getElementById('meta-revoke-modal').showModal()"
      class="btn btn-danger">
      Revogar conexão
    </button>
  </div>

  {% if meta_token_expiring_soon %}
    <div class="warning-banner" style="margin-top: 12px; padding: 8px 12px; background: #fff3cd; border-left: 4px solid #ffa500; font-size: 0.875rem;">
      ⚠ Token expira em {{ meta_days_until_expiry }} dia(s). Recomendado reconectar via "Conectar Meta" antes da expiração.
    </div>
  {% endif %}

  {% if meta_refreshed %}
    <div class="flash-success" style="margin-top: 12px; padding: 8px 12px; background: #d4edda; border-left: 4px solid #28a745; font-size: 0.875rem;">
      ✓ Lista de ad accounts atualizada via Graph API.
    </div>
  {% endif %}

  <!-- Modal confirm revoke -->
  <dialog id="meta-revoke-modal" style="border: 1px solid #ccc; border-radius: 8px; padding: 24px; max-width: 480px;">
    <h3 style="margin-top: 0;">Revogar conexão Meta</h3>
    <p>Vai desativar todas as tools Meta até reconnect via <strong>/oauth/meta/start</strong>.</p>
    <p><strong>Confirma?</strong></p>
    <form method="post" action="/oauth/meta/revoke" style="display: flex; gap: 8px; justify-content: flex-end; margin: 0;">
      <button type="button" onclick="this.closest('dialog').close()" class="btn btn-secondary">
        Cancelar
      </button>
      <button type="submit" class="btn btn-danger">
        Revogar
      </button>
    </form>
  </dialog>
```

- [ ] **Step 3: Manual visual verification locally**

```bash
python -m uvicorn src.app:create_app --factory --reload --host 0.0.0.0 --port 8000
# Browser: http://localhost:8000/admin (após login OAuth)
```

Verificar:
- Card Meta tem 2 botões "Atualizar lista" + "Revogar conexão"
- Click "Revogar" abre modal — Cancelar fecha, Revogar submete POST
- Warning banner aparece se token <7d (mock via DB UPDATE token_expires_at)
- Flash "✓ Lista atualizada" aparece após ?meta_refreshed=1

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/admin/index.html
git commit -m "feat(web): admin UI buttons Revogar + Atualizar lista Meta (M.2b Task F)

src/web/templates/admin/index.html:
- Botões 'Atualizar lista' + 'Revogar conexão' no card Meta connection
- Modal vanilla <dialog> pra confirm revoke (no JS framework)
- Warning banner se token_expires_at <7d
- Flash success ✓ após ?meta_refreshed=1

Consistent design system V4 (no build step + no Alpine/React).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task G — Helper script + smoke runbook

**Files:**
- Create: `scripts/test_meta_deletion_callback.py`
- Create: `docs/operacao/phase-M-2b-bootstrap.md`

**Subagent model recommendation:** Use `smoke-runbook-generator` subagent pra phase-M-2b-bootstrap.md (saves ~30 min vs manual)

### G.1 Helper script for T6 smoke

- [ ] **Step 1: Create script**

Create `scripts/test_meta_deletion_callback.py`:

```python
"""Gerar signed_request HMAC-valid pra testar /oauth/meta/data-deletion-callback localmente.

Usage:
    python scripts/test_meta_deletion_callback.py [META_APP_SECRET]
    # Se não passar arg, lê via input() interativo (evita exposição em shell history).

Output: signed_request string pronta pra curl POST.

Example end-to-end:
    SIGNED=$(python scripts/test_meta_deletion_callback.py)
    curl -X POST https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/meta/data-deletion-callback \\
      -d "signed_request=$SIGNED"
"""
import base64
import getpass
import hashlib
import hmac
import json
import sys
import time

if len(sys.argv) > 1:
    APP_SECRET = sys.argv[1]
else:
    APP_SECRET = getpass.getpass("META_APP_SECRET: ")

now = int(time.time())
payload = {
    "algorithm": "HMAC-SHA256",
    "user_id": "9999999999",
    "expires": now + 3600,
    "issued_at": now,
}
payload_json = json.dumps(payload, separators=(",", ":"))
payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
sig = hmac.new(APP_SECRET.encode(), payload_b64.encode(), hashlib.sha256).digest()
sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
print(f"{sig_b64}.{payload_b64}")
```

- [ ] **Step 2: Manual smoke local**

```bash
# Test sem hit endpoint (validate output format)
python scripts/test_meta_deletion_callback.py test_secret
# Expected: "AbCd...XyZ.eyJhbGdv...IjozNjAwfQ" (2 segments split by dot)
```

### G.2 Smoke runbook via subagent

- [ ] **Step 3: Dispatch smoke-runbook-generator subagent**

```
Agent({
    description: "Generate phase-M-2b smoke runbook",
    subagent_type: "smoke-runbook-generator",
    prompt: "Generate phase-M-2b-bootstrap.md smoke runbook for Sprint M.2b. Spec: docs/superpowers/specs/2026-05-25-sprint-m2b-meta-get-account-overview-design.md. Cover 8 tests defined em Section 6 do spec: T1 meta_get_account_overview happy path, T2 per-value probe individual fields, T3 account_status warning, T4 token expiry warning, T5 PT-BR error translation, T6 data-deletion-callback synthetic (use scripts/test_meta_deletion_callback.py), T7 revoke button UX, T8 refresh button UX. Pattern: docs/operacao/phase-M-2a-bootstrap.md (Sprint M.2a precedente). Suggest real ad_account IDs from docs/operacao/dogfood-2026-05-25-meta-first-tool-real-biz-findings.md (ICSER act_1489398022911451 ATIVO + ML Antiguidades act_370008662 PAGAMENTO_PENDENTE)."
})
```

Result: file `docs/operacao/phase-M-2b-bootstrap.md` created.

- [ ] **Step 4: Manual review runbook**

Quick scan pra verificar:
- Cada test tem pre-conditions claras
- Test IDs T1-T8 batem com spec Section 6
- IDs reais ad_account presentes (act_1489398022911451 + act_370008662)
- Restore steps incluem revert mock token_expires_at após T4

- [ ] **Step 5: Commit**

```bash
git add scripts/test_meta_deletion_callback.py docs/operacao/phase-M-2b-bootstrap.md
git commit -m "docs(smoke): phase-M-2b-bootstrap.md runbook + helper script (M.2b Task G)

docs/operacao/phase-M-2b-bootstrap.md (via smoke-runbook-generator subagent):
- 8 tests Wellington manual (~45 min)
- T1 happy path + T2 per-value probe + T3 account_status warn (ML Antiguidades) +
  T4 token expiry warn + T5 PT-BR errors + T6 data-deletion synthetic +
  T7 revoke UX + T8 refresh UX
- Real ad_account IDs sugeridos (ICSER ATIVO + ML Antiguidades PAGAMENTO_PENDENTE)

scripts/test_meta_deletion_callback.py: helper pra gerar signed_request
HMAC-valid local (T6). Usa getpass pra evitar exposure em shell history.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task H — Pre-push gate + push deploy

**Files:** none new

**Subagent model recommendation:** N/A (verification only)

### H.1 Pre-push gate

- [ ] **Step 1: Run base pre-push**

```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS (ruff + format + mypy + unit + non-DB integration). Tempo ~30s.

If FAIL: investigate, fix, re-run.

- [ ] **Step 2: Run full pre-push (Docker required pra testcontainers)**

```bash
python scripts/check_pre_push_full.py
```

Expected: 6/6 PASS (base + integration via testcontainers, ~60-90s). Docker requirement explicit em CLAUDE.md (M.2a lesson).

If Docker not running: skip (CI run integration tests anyway), but flag warning em commit message.

### H.2 Push deploy

- [ ] **Step 3: Push to origin/main**

```bash
git push origin main
```

Expected: triggers CI + Deploy parallel jobs.

- [ ] **Step 4: Watch deploy**

```bash
gh run list --limit 3
gh run watch <id>
```

Expected: green PASS em ~3-5 min.

- [ ] **Step 5: Verify deploy live**

```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: `{"status": "ok"}` ou similar HTTP 200.

```bash
curl -sI https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/data-deletion-status/test
```

Expected: HTTP 200 (template renders).

---

## Task I — Smoke real Wellington manual

**Files:** none — Wellington executes runbook

**Owner:** Wellington Ribeiro (manual, fora agentic execution)

### I.1 Smoke execution

- [ ] **Step 1: Wellington executes 8 tests in `docs/operacao/phase-M-2b-bootstrap.md`**

Estimated time: ~45 min.

Track PASS/FAIL per test em runbook.

### I.2 Findings catalog

- [ ] **Step 2: Se bugs encontrados, document em findings-catalog.md via /findings-add skill**

Each bug:
- ID prefix: F48+ se major (catalog atual termina em F47); A7+ se quality/UX
- Description, repro, root cause, fix (current sprint OR deferred)

### I.3 Signoff

- [ ] **Step 3: Atualizar CLAUDE.md + sprint-history.md**

CLAUDE.md "Shipped" table: append row Sprint M.2b com summary.

sprint-history.md: detail commits + tasks + smoke result.

- [ ] **Step 4: Commit signoff docs**

```bash
git add docs/operacao/findings-catalog.md docs/operacao/sprint-history.md CLAUDE.md
git commit -m "docs(signoff): Sprint M.2b completo — smoke real Wellington manual + signoff"
git push origin main
```

---

## Task J — Meta App Review submit (Wellington manual fora-MCP)

**Files:** none — Wellington faz no Meta App settings dashboard

**Owner:** Wellington Ribeiro (manual, fora agentic execution)

### J.1 Pré-flight check

- [ ] **Step 1: Verify URLs públicos respondem**

```bash
for url in privacy terms; do
  curl -sI https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/$url | head -1
done
curl -sI https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/legal/data-deletion-status/test | head -1
# All HTTP 200
```

### J.2 Meta App Review wizard

- [ ] **Step 2: Wellington abre Meta App settings → App Review tab**

Site: https://developers.facebook.com/apps/<APP_ID>/app-review/

Request advanced permissions:
- `ads_read`: justification em PT-BR/EN (~3-5 sentenças)
- `ads_management`: justification (V0 read-only, M.3+ mutate)
- `business_management`: justification (listar ad accounts BM)

### J.3 Screencast + demo video

- [ ] **Step 3: Record screencast ~3-5 min**

Conteúdo:
1. Login fluxo `/oauth/meta/start` (browser)
2. Granular permissions screen (user consent)
3. Callback redirect `/admin?meta_connected=1`
4. Card OAuth Meta no admin (active connection)
5. Demo `meta_get_account_overview` via Claude Desktop terminal:
   - Comando real ad_account_id query (ICSER `act_1489398022911451` LAST_7_DAYS)
   - Response PT-BR formatted (current+previous+deltas+warnings)

Upload em Meta App settings → Demo Video field.

### J.4 Submit

- [ ] **Step 4: Submit App Review**

Click "Submit for Review". Meta timeline 5-30 dias business.

### J.5 Decision gate pós-Meta review

- [ ] **Step 5: Pós-resposta Meta**

Se APPROVED: tools Meta liberadas publicamente (modo Production), prossegue Sprint M.3+.

Se REJECTED: iterate feedback, re-submit. Dev Mode allow 25 admins enquanto isso — Wellington pode adicionar 3 colaboradores V4 LS&Co como App Admins (deferred M.1 — Meta dashboard manual).

---

## Self-Review

### Spec coverage

| Spec section | Task implementing | Status |
|---|---|---|
| Section 1 Architecture overview | Tasks A-G aggregate | ✓ |
| Section 2 meta_get_account_overview tool | Task B (pure) + Task C (orchestrator) | ✓ |
| Section 3.1 data-deletion-callback endpoint | Task D | ✓ |
| Section 3.2 refresh-accounts endpoint | Task E | ✓ |
| Section 4 UI admin extensions | Task F | ✓ |
| Section 5 A5 fix audit_log platform | Task A | ✓ |
| Section 6 smoke runbook | Task G | ✓ |
| Section 7 Meta App Review submit | Task J (Wellington manual) | ✓ |
| Section 8.1 unit tests | Tasks A, B, D (~30 unit) | ✓ |
| Section 8.2 integration tests | Tasks C, D, E (~6 integration) | ✓ |
| Section 8.3 smoke real | Task I (Wellington manual) | ✓ |
| Section 8.4 verification commands | Task H | ✓ |
| Section 9 risks/decisions | Implicit in implementation pattern | ✓ |

### Placeholder scan

No "TBD", "TODO", "Add appropriate", "implement later", or "similar to" without code.

Every step has actual code OR exact command. All file paths exact.

### Type consistency

- `resolve_meta_date_window` signature consistent Task B → Task C usage
- `parse_insights_response` returns dict consumed by `compute_deltas` → consistent
- `build_warnings(account_status_label, token_expires_at, now)` → Task C calls with `oc.token_expires_at` (datetime|None match)
- `_verify_meta_signed_request(signed_request, app_secret)` → Task D endpoint calls with `settings.meta_app_secret`
- `meta_oauth_connections.get_active_for_manager(conn, user.id)` → matches M.2a signature

All consistent.

### Decomposition sanity

- Tasks A, B, D, E são **independent** (paralelizables se subagent-driven em modo paralelo)
- Tasks C depends B (pure module imports)
- Task F depends D + E shipped (UI wires endpoints)
- Task G depends nothing in code (runbook is doc only), but smoke real I depends H deploy
- Tasks H, I, J serializados

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-25-sprint-m2b-meta-get-account-overview.md`.**

**Two execution options:**

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Suitable for sprint with 7 implementer tasks + 3 verify/manual tasks. Parallel-friendly (A+B+D+E batch).

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Higher context use, slower.

**Recommended:** Subagent-Driven (proven 3b.28+3b.33+3b.35 — same pattern, ~3-4 dias mapped to ~6-8h actual execution with parallel batching).

**Which approach?**
