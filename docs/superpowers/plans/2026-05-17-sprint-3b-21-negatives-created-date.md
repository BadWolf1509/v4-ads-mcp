# Sprint 3b.21 — `get_negative_keywords_audit` created_date enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `get_negative_keywords_audit` response com `created_date` + `added_by_email` por critério + bloco `additions_summary` no root, fechando o último finding aberto do relatório 2026-05-17 (§1.3).

**Architecture:** Parallel 2-query JOIN via `asyncio.gather` — Query A (existente `negative_keywords_audit_query`) + Query B (novo `negative_criterion_creations_query` para `change_event` resource, last 30 days). Client-side merge usa novo helper público `parse_resource_path` em `_common.py` (extraído de `get_change_history.py` + renomeado de `_parse_resource_path` pra consistência com outros helpers públicos). Computa `additions_summary` iterando enriched data.

**Tech Stack:** Python 3.12, asyncio, google-ads SDK, pytest + freezegun (data-sensitive tests), testcontainers (integration tests).

---

## File Structure

**Files to create:**
- `tests/integration/test_get_negative_keywords_audit.py` — end-to-end integration test
- `tests/unit/test_get_negative_keywords_audit.py` — unit tests para enrichment + summary logic
- `docs/operacao/phase-3b-21-bootstrap.md` — smoke runbook

**Files to modify:**
- `src/google_ads/queries/_common.py` — adicionar `parse_resource_path` (extraído de `get_change_history.py`)
- `src/google_ads/queries/change_history.py` — adicionar `negative_criterion_creations_query`
- `src/mcp/tools/get_change_history.py` — remover `_parse_resource_path`, importar `parse_resource_path` de `_common.py` + atualizar 2 call sites internos
- `src/mcp/tools/get_negative_keywords_audit.py` — refactor body: 2 parallel queries + merge + summary
- `tests/unit/test_query_helpers.py` — adicionar tests para `parse_resource_path` (post-extraction)
- `tests/unit/test_change_history_query.py` — adicionar tests para `negative_criterion_creations_query`
- `CLAUDE.md` — adicionar row Sprint 3b.21 na tabela "Shipped + in production"

---

## Task 1: Extract `parse_resource_path` — failing test (TDD red)

**Files:**
- Modify: `tests/unit/test_query_helpers.py` (append at end)

- [ ] **Step 1: Append tests for `parse_resource_path`**

Append to `tests/unit/test_query_helpers.py`:

```python
# ---------- parse_resource_path (Sprint 3b.21, extracted from get_change_history) ----------

from src.google_ads.queries._common import parse_resource_path


def test_parse_resource_path_campaign() -> None:
    rtype, rid = parse_resource_path("customers/7862230676/campaigns/21359547724")
    assert rtype == "campaign"
    assert rid == "21359547724"


def test_parse_resource_path_campaign_criterion_compound() -> None:
    """campaign_criterion uses compound id {campaign_id}~{criterion_id} — Sprint 3b.6 A5."""
    rtype, rid = parse_resource_path(
        "customers/7862230676/campaignCriteria/21359547724~1234567890"
    )
    assert rtype == "campaign_criterion"
    assert rid == "21359547724~1234567890"


def test_parse_resource_path_ad_group_criterion_compound() -> None:
    rtype, rid = parse_resource_path(
        "customers/7862230676/adGroupCriteria/164805426684~9876543210"
    )
    assert rtype == "ad_group_criterion"
    assert rid == "164805426684~9876543210"


def test_parse_resource_path_unknown_plural_returns_none() -> None:
    rtype, rid = parse_resource_path("customers/123/fooBars/456")
    assert rtype is None
    assert rid == "456"  # current behavior: id parsed even when type unknown


def test_parse_resource_path_malformed_returns_nones() -> None:
    rtype, rid = parse_resource_path("not/a/valid/path")
    assert rtype is None
    assert rid is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_helpers.py -v -k parse_resource_path`
Expected: ImportError on `parse_resource_path` (não existe em `_common.py` ainda).

- [ ] **Step 3: Commit (red)**

```bash
git add tests/unit/test_query_helpers.py
git commit -m "test(common): add failing tests for parse_resource_path helper (Sprint 3b.21)"
```

---

## Task 2: Extract `parse_resource_path` to `_common.py` (TDD green)

**Files:**
- Modify: `src/google_ads/queries/_common.py` (add function)
- Modify: `src/mcp/tools/get_change_history.py` (remove function + update imports + update 2 call sites)

- [ ] **Step 1: Add `parse_resource_path` to `_common.py`**

Append to `src/google_ads/queries/_common.py` (after `gaql_date_clause` around line 110):

```python
# Plural-form keys in sync with resource types Google Ads emits via change_event.
# Compound IDs (e.g., {campaign_id}~{criterion_id}) returned as-is — caller splits if needed.
# Sprint 3b.21: extracted from get_change_history.py for cross-tool reuse.
_RESOURCE_PLURAL_TO_TYPE: dict[str, str] = {
    "campaigns": "campaign",
    "adGroups": "ad_group",
    "adGroupAds": "ad_group_ad",
    "adGroupCriteria": "ad_group_criterion",
    "campaignCriteria": "campaign_criterion",
    "campaignBudgets": "campaign_budget",
    "biddingStrategies": "bidding_strategy",
    "conversionActions": "conversion_action",
    "customerNegativeCriteria": "customer_negative_criterion",
    "assets": "asset",
    "campaignAssets": "campaign_asset",
    "adGroupAssets": "ad_group_asset",
}


def parse_resource_path(path: str) -> tuple[str | None, str | None]:
    """Parse 'customers/{cid}/{resource_plural}/{id}[...]' into (resource_type, id).

    Returns:
      (resource_type, id) when path matches known pattern.
      (None, id) when plural is unknown but id is parseable.
      (None, None) when path is malformed.

    Adding a new resource type? Update `_RESOURCE_PLURAL_TO_TYPE` above.
    """
    parts = path.split("/")
    if len(parts) < 4 or parts[0] != "customers":
        return None, None
    resource_plural = parts[2]
    resource_id = parts[3] if len(parts) > 3 else None
    return _RESOURCE_PLURAL_TO_TYPE.get(resource_plural), resource_id
```

- [ ] **Step 2: Remove old `_parse_resource_path` from `get_change_history.py` + update imports**

In `src/mcp/tools/get_change_history.py`:

Find (around lines 107-134):
```python
def _parse_resource_path(path: str) -> tuple[str | None, str | None]:
    """Parse 'customers/123/campaigns/456' -> ('campaign', '456').
    ...
    """
    parts = path.split("/")
    # path is "customers/{cid}/{resource_plural}/{id}[...]"
    if len(parts) < 4 or parts[0] != "customers":
        return None, None
    resource_plural = parts[2]
    # ... full body ...
    return plural_to_type.get(resource_plural), parts[3] if len(parts) > 3 else None
```

Delete the entire function definition (lines 107-134 inclusive).

In the existing import block (top of file), add:
```python
from src.google_ads.queries._common import parse_resource_path
```

Then update the 2 call sites inside `_row_formatter` (currently around lines 140 and 147):

Find:
```python
_rtype, rid = _parse_resource_path(resource_path)
```
Replace:
```python
_rtype, rid = parse_resource_path(resource_path)
```

Find:
```python
_, campaign_id = _parse_resource_path(campaign_path) if campaign_path else (None, None)
_, ad_group_id = _parse_resource_path(ad_group_path) if ad_group_path else (None, None)
```
Replace:
```python
_, campaign_id = parse_resource_path(campaign_path) if campaign_path else (None, None)
_, ad_group_id = parse_resource_path(ad_group_path) if ad_group_path else (None, None)
```

- [ ] **Step 3: Run tests to verify all pass**

Run: `pytest tests/unit/test_query_helpers.py tests/unit/test_change_history_query.py -v`
Expected: 5 new tests PASS + all existing PASS.

- [ ] **Step 4: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 5: Commit (green)**

```bash
git add src/google_ads/queries/_common.py src/mcp/tools/get_change_history.py
git commit -m "refactor(common): extract parse_resource_path for cross-tool reuse (Sprint 3b.21)"
```

---

## Task 3: New GAQL builder `negative_criterion_creations_query` — failing test

**Files:**
- Modify: `tests/unit/test_change_history_query.py` (append at end)

- [ ] **Step 1: Append tests for new GAQL builder**

Append to `tests/unit/test_change_history_query.py`:

```python
# ---------- negative_criterion_creations_query (Sprint 3b.21) ----------

from src.google_ads.queries.change_history import (
    RangeTooWideError,
    negative_criterion_creations_query,
)


def test_negative_criterion_creations_query_format():
    q = negative_criterion_creations_query(start=date(2026, 4, 17), end=date(2026, 5, 17))
    # Selects only the 3 fields we need
    assert "change_event.change_resource_name" in q
    assert "change_event.change_date_time" in q
    assert "change_event.user_email" in q
    # Filters
    assert "FROM change_event" in q
    assert "change_event.change_date_time BETWEEN '2026-04-17' AND '2026-05-17'" in q
    assert "change_event.change_resource_type = 'CAMPAIGN_CRITERION'" in q
    assert "change_event.resource_change_operation = 'CREATE'" in q
    # Ordering + limit
    assert "ORDER BY change_event.change_date_time DESC" in q
    assert "LIMIT 10000" in q


def test_negative_criterion_creations_query_rejects_over_30d():
    with pytest.raises(RangeTooWideError, match="30 dias"):
        negative_criterion_creations_query(start=date(2026, 4, 1), end=date(2026, 5, 17))


def test_negative_criterion_creations_query_at_exactly_30d_ok():
    # 30-day boundary: start+29 days inclusive = 30 days total
    q = negative_criterion_creations_query(start=date(2026, 4, 18), end=date(2026, 5, 17))
    assert "FROM change_event" in q
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_change_history_query.py -v -k negative_criterion_creations`
Expected: ImportError on `negative_criterion_creations_query`.

- [ ] **Step 3: Commit (red)**

```bash
git add tests/unit/test_change_history_query.py
git commit -m "test(change_history): add failing tests for negative_criterion_creations_query"
```

---

## Task 4: Implement `negative_criterion_creations_query` (TDD green)

**Files:**
- Modify: `src/google_ads/queries/change_history.py` (append at end)

- [ ] **Step 1: Add the GAQL builder function**

Append to `src/google_ads/queries/change_history.py` (after `change_history_query` function):

```python
def negative_criterion_creations_query(*, start: date, end: date) -> str:
    """Build GAQL for fetching campaign_criterion CREATE events.

    Used by get_negative_keywords_audit to enrich each negative keyword with
    its created_date + added_by_email. Filters to CAMPAIGN_CRITERION resource
    type + CREATE operation. Sprint 3b.21.

    Raises RangeTooWideError if (end - start) > 30 days (change_event API limit).
    """
    range_days = (end - start).days + 1
    if range_days > _MAX_DAYS:
        raise RangeTooWideError(
            f"Janela maxima de {_MAX_DAYS} dias para historico de mudancas — "
            f"recebido {range_days} dias. Limite da API do Google Ads."
        )

    return f"""
        SELECT
          change_event.change_resource_name,
          change_event.change_date_time,
          change_event.user_email
        FROM change_event
        WHERE change_event.change_date_time BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
          AND change_event.change_resource_type = 'CAMPAIGN_CRITERION'
          AND change_event.resource_change_operation = 'CREATE'
        ORDER BY change_event.change_date_time DESC
        LIMIT 10000
    """.strip()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/unit/test_change_history_query.py -v -k negative_criterion_creations`
Expected: 3 PASS.

- [ ] **Step 3: Commit (green)**

```bash
git add src/google_ads/queries/change_history.py
git commit -m "feat(change_history): add negative_criterion_creations_query GAQL builder (Sprint 3b.21)"
```

---

## Task 5: Enrichment logic + summary — failing tests (TDD red)

**Files:**
- Create: `tests/unit/test_get_negative_keywords_audit.py`

- [ ] **Step 1: Create unit test file with all enrichment scenarios**

Create `tests/unit/test_get_negative_keywords_audit.py`:

```python
"""Unit tests for get_negative_keywords_audit enrichment + summary logic (Sprint 3b.21)."""

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from freezegun import freeze_time

from src.mcp.context import ManagerContext, get_current, set_current
from src.mcp.tools.get_negative_keywords_audit import get_negative_keywords_audit


def _negative_row(criterion_id: str, campaign_id: str = "1001", campaign_name: str = "Camp A"):
    """Build a fake row matching `_row_formatter` shape for the negative query."""
    return {
        "criterion_id": criterion_id,
        "keyword_text": f"negativa-{criterion_id}",
        "match_type": "BROAD",
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
    }


def _create_event(criterion_id: str, when: str, email: str, campaign_id: str = "1001"):
    """Build a fake row matching the change_event CREATE event shape."""
    return {
        "change_resource_name": f"customers/9999999999/campaignCriteria/{campaign_id}~{criterion_id}",
        "change_date_time": when,
        "user_email": email,
    }


@pytest.fixture(autouse=True)
def _ctx():
    """Bind a dummy manager context (handler reads ctx.manager_id + ctx.session_id)."""
    from uuid import uuid4
    token = set_current(
        ManagerContext(manager_id=uuid4(), session_id=uuid4(), manager_email="test@v4company.com")
    )
    yield
    set_current(None)
    _ = token  # silence unused


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_enriches_per_criterion_when_match_exists():
    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            # Query A — negatives
            [_negative_row("111"), _negative_row("222")],
            # Query B — CREATE events (only criterion 111 has a recent CREATE)
            [_create_event("111", "2026-05-10 14:30:00+00:00", "wellinton.ribeiro@v4company.com")],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    by_campaign = result["by_campaign"]
    assert len(by_campaign) == 1
    negatives = {n["criterion_id"]: n for n in by_campaign[0]["negatives"]}
    assert negatives["111"]["created_date"] == "2026-05-10"
    assert negatives["111"]["added_by_email"] == "wellinton.ribeiro@v4company.com"
    assert negatives["222"]["created_date"] is None
    assert negatives["222"]["added_by_email"] is None


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_summary_counts_three_buckets():
    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            # 5 negatives
            [_negative_row(str(i)) for i in range(1, 6)],
            # CREATEs: 1 last_7_days (criterion 1), 1 between 7-30d (criterion 2), 3 not in change_event
            [
                _create_event("1", "2026-05-15 10:00:00+00:00", "user@v4.com"),  # 2 days ago = last_7
                _create_event("2", "2026-04-25 10:00:00+00:00", "user@v4.com"),  # 22 days ago = last_30 only
            ],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    s = result["additions_summary"]
    assert s["last_7_days"] == 1
    assert s["last_30_days"] == 2
    assert s["pre_30_days_or_unknown"] == 3
    # Invariant
    assert s["last_30_days"] + s["pre_30_days_or_unknown"] == result["total_negatives"]
    assert s["last_7_days"] <= s["last_30_days"]


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_picks_most_recent_create_when_duplicates():
    """If change_event has 2 CREATE events for same criterion_id, pick the most recent."""
    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            [_negative_row("777")],
            [
                _create_event("777", "2026-05-01 10:00:00+00:00", "older@v4.com"),
                _create_event("777", "2026-05-14 10:00:00+00:00", "newer@v4.com"),
            ],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    neg = result["by_campaign"][0]["negatives"][0]
    assert neg["created_date"] == "2026-05-14"
    assert neg["added_by_email"] == "newer@v4.com"


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_handles_empty_change_event_result():
    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            [_negative_row("111"), _negative_row("222")],
            [],  # No CREATEs in last 30d
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    s = result["additions_summary"]
    assert s["last_7_days"] == 0
    assert s["last_30_days"] == 0
    assert s["pre_30_days_or_unknown"] == 2
    for camp in result["by_campaign"]:
        for n in camp["negatives"]:
            assert n["created_date"] is None
            assert n["added_by_email"] is None


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_handles_empty_negatives_result():
    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [[], []]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    assert result["total_negatives"] == 0
    assert result["by_campaign"] == []
    assert result["additions_summary"] == {
        "last_7_days": 0,
        "last_30_days": 0,
        "pre_30_days_or_unknown": 0,
    }


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_audit_ignores_create_events_for_criteria_not_in_current_state():
    """change_event may have CREATEs for criteria that were later REMOVED — those
    don't appear in Query A's current state. Tool must not surface them."""
    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = [
            [_negative_row("111")],
            [
                _create_event("111", "2026-05-15 10:00:00+00:00", "user@v4.com"),
                _create_event("999", "2026-05-15 10:00:00+00:00", "user@v4.com"),  # orphan
            ],
        ]
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    assert result["total_negatives"] == 1
    assert len(result["by_campaign"][0]["negatives"]) == 1
    assert result["additions_summary"]["last_7_days"] == 1  # criterion 999 doesn't count
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_get_negative_keywords_audit.py -v`
Expected: All 6 FAIL (current impl doesn't have enrichment fields or summary block).

- [ ] **Step 3: Commit (red)**

```bash
git add tests/unit/test_get_negative_keywords_audit.py
git commit -m "test(audit): add failing tests for negatives enrichment + summary (Sprint 3b.21)"
```

---

## Task 6: Refactor tool body — parallel queries + merge + summary (TDD green)

**Files:**
- Modify: `src/mcp/tools/get_negative_keywords_audit.py`

- [ ] **Step 1: Rewrite tool body**

Replace the entire content of `src/mcp/tools/get_negative_keywords_audit.py` with:

```python
"""Tool: get_negative_keywords_audit - campaign-level negative keywords with created_date enrichment."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.google_ads.queries._common import parse_resource_path
from src.google_ads.queries.change_history import negative_criterion_creations_query
from src.google_ads.queries.tactical import negative_keywords_audit_query
from src.google_ads.reports import run_report
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _row_formatter_negatives(row: Any) -> dict[str, Any]:
    return {
        "criterion_id": str(row.campaign_criterion.criterion_id),
        "keyword_text": row.campaign_criterion.keyword.text,
        "match_type": row.campaign_criterion.keyword.match_type.name,
        "campaign_id": str(row.campaign.id),
        "campaign_name": row.campaign.name,
    }


def _row_formatter_creates(row: Any) -> dict[str, Any]:
    return {
        "change_resource_name": str(row.change_event.change_resource_name),
        "change_date_time": str(row.change_event.change_date_time),
        "user_email": str(row.change_event.user_email),
    }


def _build_creations_index(create_rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Map criterion_id -> {created_date, added_by_email} from change_event CREATE rows.

    When multiple CREATE events exist for same criterion_id, picks the MOST RECENT
    (rows arrive ORDER BY change_date_time DESC, so first wins).
    """
    index: dict[str, dict[str, str]] = {}
    for r in create_rows:
        _, compound_id = parse_resource_path(r["change_resource_name"])
        if compound_id is None or "~" not in compound_id:
            continue
        criterion_id = compound_id.split("~", 1)[1]
        if criterion_id in index:
            continue  # most recent already captured (DESC ordering)
        # change_date_time is "YYYY-MM-DD HH:MM:SS+TZ" — take date part
        date_part = r["change_date_time"][:10]
        index[criterion_id] = {
            "created_date": date_part,
            "added_by_email": r["user_email"],
        }
    return index


def _compute_summary(
    negatives_with_dates: list[dict[str, Any]], today: date
) -> dict[str, int]:
    last_7_cutoff = today - timedelta(days=7)
    last_30_cutoff = today - timedelta(days=30)
    last_7 = 0
    last_30 = 0
    unknown = 0
    for n in negatives_with_dates:
        cd = n["created_date"]
        if cd is None:
            unknown += 1
            continue
        cd_parsed = date.fromisoformat(cd)
        if cd_parsed >= last_7_cutoff:
            last_7 += 1
        if cd_parsed >= last_30_cutoff:
            last_30 += 1
    return {
        "last_7_days": last_7,
        "last_30_days": last_30,
        "pre_30_days_or_unknown": unknown,
    }


@register_tool(
    name="get_negative_keywords_audit",
    description=(
        "Lista palavras-chave negativas aplicadas em nivel de campanha, com data "
        "de criacao e usuario que adicionou (quando rastreavel via change_event, "
        "retention ~30 dias). Util pra auditoria de cobertura de negativas, "
        "identificar duplicacoes ou gaps, e narrar 'X negativas adicionadas no "
        "periodo' em report semanal. Bloco additions_summary no root agrega "
        "counts por janela (7d / 30d / pre-30d-ou-desconhecido)."
    ),
    input_schema=_SCHEMA,
)
async def get_negative_keywords_audit(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    today = datetime.now(UTC).date()
    creates_start = today - timedelta(days=30)
    creates_end = today

    # Parallel: full state of negatives + recent CREATE events for enrichment
    negatives_task = run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=negative_keywords_audit_query(),
        row_formatter=_row_formatter_negatives,
        operation_name="get_negative_keywords_audit",
    )
    creates_task = run_report(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        query=negative_criterion_creations_query(start=creates_start, end=creates_end),
        row_formatter=_row_formatter_creates,
        operation_name="get_negative_keywords_audit_creations",
    )
    negatives, creates = await asyncio.gather(negatives_task, creates_task)

    creations_index = _build_creations_index(creates)

    enriched: list[dict[str, Any]] = []
    for n in negatives:
        creation = creations_index.get(n["criterion_id"])
        enriched.append(
            {
                **n,
                "created_date": creation["created_date"] if creation else None,
                "added_by_email": creation["added_by_email"] if creation else None,
            }
        )

    # Group by campaign — same as before, but with enriched fields per negative
    by_campaign: dict[str, dict[str, Any]] = {}
    for n in enriched:
        cid = n["campaign_id"]
        if cid not in by_campaign:
            by_campaign[cid] = {
                "campaign_id": cid,
                "campaign_name": n["campaign_name"],
                "negatives": [],
            }
        by_campaign[cid]["negatives"].append(
            {
                "criterion_id": n["criterion_id"],
                "keyword_text": n["keyword_text"],
                "match_type": n["match_type"],
                "created_date": n["created_date"],
                "added_by_email": n["added_by_email"],
            }
        )

    return {
        "customer_id": customer_id,
        "total_negatives": len(enriched),
        "additions_summary": _compute_summary(enriched, today),
        "by_campaign": list(by_campaign.values()),
    }
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/unit/test_get_negative_keywords_audit.py -v`
Expected: 6 PASS.

- [ ] **Step 3: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS (the regression guards from prior sprints + new tests + linting).

- [ ] **Step 4: Commit (green)**

```bash
git add src/mcp/tools/get_negative_keywords_audit.py
git commit -m "feat(audit): enrich negatives with created_date + additions_summary (Sprint 3b.21)"
```

---

## Task 7: Integration test

**Files:**
- Create: `tests/integration/test_get_negative_keywords_audit.py`

- [ ] **Step 1: Create integration test file**

Create `tests/integration/test_get_negative_keywords_audit.py`:

```python
"""Integration: get_negative_keywords_audit end-to-end with mocked Google Ads SDK responses."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from freezegun import freeze_time
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.mcp.context import ManagerContext, set_current
from src.mcp.tools.get_negative_keywords_audit import get_negative_keywords_audit

pytestmark = pytest.mark.integration


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


def _proto_negative(criterion_id: str, kw_text: str, campaign_id: str = "1001"):
    """Build a SimpleNamespace mimicking the Google Ads SDK row shape (campaign_criterion)."""
    return SimpleNamespace(
        campaign_criterion=SimpleNamespace(
            criterion_id=criterion_id,
            keyword=SimpleNamespace(
                text=kw_text,
                match_type=SimpleNamespace(name="BROAD"),
            ),
        ),
        campaign=SimpleNamespace(id=campaign_id, name="Camp"),
    )


def _proto_create_event(criterion_id: str, when: str, email: str, campaign_id: str = "1001"):
    """Build a SimpleNamespace mimicking the Google Ads SDK row shape (change_event)."""
    return SimpleNamespace(
        change_event=SimpleNamespace(
            change_resource_name=f"customers/9999999999/campaignCriteria/{campaign_id}~{criterion_id}",
            change_date_time=when,
            user_email=email,
        )
    )


@freeze_time("2026-05-17")
@pytest.mark.asyncio
async def test_end_to_end_enrichment_and_summary(db):
    """Full handler path with mocked Google Ads SDK: 3 negatives, 2 enriched."""
    set_current(
        ManagerContext(manager_id=uuid4(), session_id=uuid4(), manager_email="test@v4.com")
    )

    # Mock run_report to bypass actual Google Ads SDK + return SDK-shaped rows.
    async def fake_run_report(*, query: str, row_formatter, **kwargs):
        if "campaign_criterion" in query and "negative = true" in query:
            return [row_formatter(_proto_negative(str(i), f"neg-{i}")) for i in (1, 2, 3)]
        if "change_event" in query and "CREATE" in query:
            return [
                row_formatter(_proto_create_event("1", "2026-05-16 10:00:00+00:00", "u@v4.com")),
                row_formatter(_proto_create_event("2", "2026-04-30 10:00:00+00:00", "u@v4.com")),
            ]
        return []

    with patch("src.mcp.tools.get_negative_keywords_audit.run_report", side_effect=fake_run_report):
        result = await get_negative_keywords_audit({"customer_id": "9999999999"})

    assert result["total_negatives"] == 3
    assert result["additions_summary"] == {
        "last_7_days": 1,  # criterion 1 (yesterday)
        "last_30_days": 2,  # criteria 1 + 2
        "pre_30_days_or_unknown": 1,  # criterion 3
    }
```

- [ ] **Step 2: Run integration test**

If Docker available locally:
```bash
pytest tests/integration/test_get_negative_keywords_audit.py -v -m integration
```
Expected: 1 PASS.

If Docker not running, rely on CI to validate.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_get_negative_keywords_audit.py
git commit -m "test(audit): integration test for created_date enrichment (Sprint 3b.21)"
```

---

## Task 8: Documentation — CLAUDE.md row + close finding #3

**Files:**
- Modify: `CLAUDE.md` (add Shipped row + update Pending/future)

- [ ] **Step 1: Add Sprint 3b.21 row to "Shipped + in production" table**

In `CLAUDE.md`, find the last row in the "Shipped + in production" table (Sprint 3b.20). Append immediately after it:

```markdown
| Sprint 3b.21 — `get_negative_keywords_audit` created_date enrichment | ✅ 2026-05-17 | <N> commits; smoke runbook scaffolded ([`phase-3b-21-bootstrap.md`](docs/operacao/phase-3b-21-bootstrap.md)) — production revision `<rev>` (pending Wellington smoke em MO-JP). Zero new MCP tools (count stays 46); closes relatorio 2026-05-17 finding #3 (último finding aberto). **Enrichment:** per-criterion `created_date` (YYYY-MM-DD) + `added_by_email` (null se >30d via change_event retention) + bloco `additions_summary` no root com counts `last_7_days` / `last_30_days` / `pre_30_days_or_unknown`. **Architecture:** parallel 2-query JOIN via `asyncio.gather` (Query A negatives full state + Query B `change_event` last 30d CREATE), client-side merge keyed por criterion_id (via novo helper público `parse_resource_path` em `_common.py`, extraído de `get_change_history.py` para cross-tool reuse). **6 novos unit tests** (enrichment scenarios + summary invariant) + 1 integration + 5 helper tests + 3 GAQL builder tests. ~+150 LOC source / ~+250 LOC tests. |
```

Update "Last updated":
```markdown
**Last updated:** 2026-05-17
```

- [ ] **Step 2: Update "Pending / future" — close finding #3**

In `CLAUDE.md`, find the long "Phase 3b restante" bullet (line ~77). Find:
```
Finding #3 (negative_keywords_audit sem created_date) deferred to Sprint 3b.21 — requires investigation into change_event JOIN since campaign_criterion resource doesn't expose creation_time directly.
```
Replace with:
```
Finding #3 (negative_keywords_audit sem created_date) shipado em Sprint 3b.21 (created_date + added_by_email per criterion + additions_summary block, parallel 2-query JOIN via change_event last 30d).
```

Also find:
```
**Sprints 3b.21+** candidatos (...): finding #3 do relatório (P2, prioritário pelo dogfood pain), `create_campaign`,
```
Replace with:
```
**Sprints 3b.22+** candidatos (...): `create_campaign`,
```

(Remove the `finding #3 do relatório (P2, prioritário pelo dogfood pain),` clause since it's now done.)

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): Sprint 3b.21 row + closes relatorio finding #3"
```

---

## Task 9: Smoke runbook scaffold

**Files:**
- Create: `docs/operacao/phase-3b-21-bootstrap.md`

- [ ] **Step 1: Create the smoke runbook**

Create `docs/operacao/phase-3b-21-bootstrap.md`:

```markdown
# Phase 3b.21 — manual smoke runbook (negative_keywords_audit enrichment)

**Purpose:** Verify Sprint 3b.21 enrichment em conta real — closes último finding aberto do relatório 2026-05-17 (§1.3: created_date + added_by_email per criterion + additions_summary block).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` "Mestre da Obra - João Pessoa" (467 negativas conforme relatório 15/05 — bulk shape conhecido)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session)

Production revision: `<fill-in>`.

## Test T1 — Basic enrichment + summary block presence

```
get_negative_keywords_audit(customer_id="7862230676")
```

Expected:
- [ ] Response inclui novo bloco `additions_summary` com 3 fields: `last_7_days`, `last_30_days`, `pre_30_days_or_unknown` (all int).
- [ ] Cada negativa em `by_campaign[*].negatives[*]` inclui novos fields `created_date` (string YYYY-MM-DD ou null) + `added_by_email` (string ou null).
- [ ] `total_negatives` mantém shape (provavelmente ~467 para MO-JP, +/- depending de cleanup recente).

**Result:** ⬜ pending

## Test T2 — Retention boundary: ao menos 1 negativa enriquecida

Wellington rodou Sprint 3b.20 smoke em 17/05 — não adicionou negativas. Sprints 3b.6 e antes podem ter adicionado. Cross-reference com `get_change_history`:

```
get_change_history(
  customer_id="7862230676",
  date_range="LAST_30_DAYS",
  resource_types=["CAMPAIGN_CRITERION"],
  operation_types=["CREATE"]
)
```

Compare with `additions_summary.last_30_days` do T1:

Expected:
- [ ] `additions_summary.last_30_days` >= número de CAMPAIGN_CRITERION CREATEs recentes (deve match exato após filtro de keyword negative).
- [ ] Para cada negativa com `created_date != null` em T1, existe evento correspondente em `get_change_history` result.

**Result:** ⬜ pending

## Test T3 — Bulk pre-30d coverage

Expected (sabendo que MO-JP tem ~467 negativas e algumas são antigas):
- [ ] `additions_summary.pre_30_days_or_unknown` é o bulk (provavelmente >400).
- [ ] Maior parte das negativas tem `created_date: null` (esperado — retention ~30d).

**Result:** ⬜ pending

## Test T4 — Invariant check

Expected:
- [ ] `additions_summary.last_30_days + additions_summary.pre_30_days_or_unknown == total_negatives` (exato).
- [ ] `additions_summary.last_7_days <= additions_summary.last_30_days` (inclusion).

**Result:** ⬜ pending

## Test T5 — Cross-account sanity (diferente volume)

Rodar em 1 conta menor (e.g., ML Antiguidades `7455088726` que pegamos em Sprint 3b.7) pra validar shape consistente em low-volume account:

```
get_negative_keywords_audit(customer_id="7455088726")
```

Expected:
- [ ] Response inclui `additions_summary` mesmo se conta tem 0 negativas (summary com zeros).
- [ ] Se 0 negativas, `total_negatives=0`, `by_campaign=[]`.
- [ ] Sem crash ou erro.

**Result:** ⬜ pending

## Findings

Document any new findings here. Se T1-T5 all PASS clean, este será o **11º sprint consecutivo sem novos bugs no smoke** (continua streak 3b.7→3b.18 + 3b.20).

Se finding emerger:
- Add à seção "Findings" com reproducer
- Spawn-task para fix ou aceitar como limitação
- Update CLAUDE.md row do 3b.21 com finding noted
```

- [ ] **Step 2: Commit**

```bash
git add docs/operacao/phase-3b-21-bootstrap.md
git commit -m "docs(ops): scaffold smoke runbook for Sprint 3b.21"
```

---

## Task 10: Final pre-push verification + push

- [ ] **Step 1: Run full pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 2: Run full sweep if Docker available**

```bash
python scripts/check_pre_push_full.py
```
Expected: 6/6 PASS (if Docker on). If Docker off, exit 2 with clear hint — rely on CI.

- [ ] **Step 3: Push to main**

```bash
git push origin main
```
Expected: Admin bypass accepted (per project convention).

- [ ] **Step 4: Watch CI + Deploy**

```bash
gh run list --limit 5 --json databaseId,name,status,conclusion,headSha
gh run watch <deploy-id> --exit-status
```
Expected: Deploy verde (~3-5 min). CI green in parallel.

- [ ] **Step 5: Capture production revision**

```bash
gcloud run services describe v4-ads-mcp --project=v4-ads-mcp-prod --region=southamerica-east1 --format='value(status.latestReadyRevisionName)'
```

Fill into:
- `docs/operacao/phase-3b-21-bootstrap.md` "Pre-flight" section (`Production revision: <captured>`)
- `CLAUDE.md` "Shipped + in production" row (`<rev>` placeholder + `<N> commits` count)

- [ ] **Step 6: Final docs commit + push**

```bash
git add docs/operacao/phase-3b-21-bootstrap.md CLAUDE.md
git commit -m "docs(claude): Sprint 3b.21 production revision <captured> + revision in smoke runbook"
git push origin main
```

- [ ] **Step 7: Smoke execution (Wellington-driven, post-deploy)**

Wellington reload Claude Code session + executa T1-T5 do `phase-3b-21-bootstrap.md` em MO-JP `7862230676`. Marca ⬜ → ✅/❌ per test. Final commit `docs(ops): Sprint 3b.21 smoke signed-off`.

---

## Self-Review Notes

**Spec coverage:**
- ✅ §"Goal" — Task 6 enrichment + summary
- ✅ §"Non-goals (v0)" — no toggle/filter param, schema unchanged in Task 6
- ✅ §"Tool surface > Description" — updated in Task 6 `@register_tool` decorator
- ✅ §"Tool surface > Input schema" — Task 6 keeps it unchanged
- ✅ §"Response shape" — Task 6 implements exact shape (3 keys per negative including created_date/added_by_email, additions_summary block at root with 3 counts)
- ✅ §"Implementation overview > Architectural changes" — Tasks 1+2 (extract helper), Tasks 3+4 (new GAQL), Task 6 (parallel + merge)
- ✅ §"Edge cases handled" — covered in Task 5 tests (multiple CREATEs, empty change_event, empty negatives, orphan CREATEs)
- ✅ §"Testing strategy > Unit tests" — Task 1 (parse_resource_path 5 tests), Task 3 (GAQL builder 3 tests), Task 5 (enrichment 6 tests)
- ✅ §"Testing strategy > Integration tests" — Task 7
- ✅ §"Smoke runbook outline" — Task 9 with T1-T5

**Placeholder scan:** clean (no TBD/TODO/vague). The smoke runbook has explicit `<fill-in>` for production revision — that's deliberate template content the operator fills at smoke time (matches pattern from prior bootstraps). CLAUDE.md row has `<N> commits` and `<rev>` placeholders — those get filled in Task 10 Step 5 (post-deploy capture).

**Type consistency:**
- ✅ `parse_resource_path` signature: `(path: str) -> tuple[str | None, str | None]` — consistent in Task 1 tests + Task 2 implementation + Task 6 usage.
- ✅ `negative_criterion_creations_query` signature: `(*, start: date, end: date) -> str` — consistent Task 3 tests + Task 4 impl + Task 6 call.
- ✅ Response shape keys: `total_negatives`, `additions_summary.{last_7_days,last_30_days,pre_30_days_or_unknown}`, `by_campaign[*].negatives[*].{criterion_id,keyword_text,match_type,created_date,added_by_email}` — consistent across Task 5 tests + Task 6 implementation + Task 7 integration + Task 9 smoke.
- ✅ Invariant `last_30_days + pre_30_days_or_unknown == total_negatives` — asserted in Task 5 unit test + Task 9 T4.
