# Sprint 3b.24 — `create_campaign` SEARCH v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship o quinto create-pattern do MCP V4 (`create_campaign` SEARCH-only), foundation pra onboarding completo via Claude/Codex.

**Architecture:** Chained mutation pattern (Sprint 3b.19B established): N+M+2 ops em single MutateGoogleAdsRequest — 1 budget + 1 campaign + N geo criterions + 1 PT language criterion. Reuses existing helper `validate_geo_target_constants_for_value_rule` (renamed to generic `validate_geo_target_constants_br_only`) para pre-flight V4 BR-invariant. Runtime payload validation via private `_validate_payload_shape` (Sprint 3b.19B.1 pattern: no JSON Schema composition keywords).

**Tech Stack:** Python 3.13, google-ads SDK v23+, pytest + ProtoFieldCapture fixture, asyncpg, jsonschema Draft 2020-12.

---

## File Structure

**Files to create:**
- `src/google_ads/mutates/campaigns.py` — builder `build_create_campaign`
- `src/mcp/tools/create_campaign.py` — tool with @register_tool
- `tests/unit/test_create_campaign.py` — tool tests (schema + runtime validation + pre-flight integration)
- `tests/unit/test_create_campaign_builder.py` — builder tests using ProtoFieldCapture
- `tests/integration/test_create_campaign.py` — e2e mocked SDK test
- `docs/operacao/phase-3b-24-bootstrap.md` — smoke runbook

**Files to modify:**
- `src/google_ads/queries/_common.py` — rename `validate_geo_target_constants_for_value_rule` → `validate_geo_target_constants_br_only`
- `src/mcp/tools/create_conversion_value_rule_set.py` — update import + callsite
- `tests/unit/test_create_conversion_value_rule_set.py` — update patch targets (`.validate_geo_target_constants_for_value_rule` → `.validate_geo_target_constants_br_only`)
- `tests/integration/test_create_conversion_value_rule_set.py` — same patch target update
- `tests/unit/test_validate_conversion_value_rule_set.py` — update direct import + test function names if any
- `tests/unit/test_tools_schemas.py` — add `create_campaign` to expected tools allowlist (test_all_phase_2_tools_registered + test_no_unexpected_tools)
- `tests/unit/fixtures/proto_capture.py` — extend mocks for `CampaignService.campaign_path`, `CampaignBudgetService.campaign_budget_path` if not already present
- `CLAUDE.md` — add Sprint 3b.24 row to "Shipped + in production" table

---

## Task 1: Rename helper `validate_geo_target_constants_for_value_rule` → `validate_geo_target_constants_br_only` (cross-tool reuse refactor)

**Files:**
- Modify: `src/google_ads/queries/_common.py` (line ~628 function definition)
- Modify: `src/mcp/tools/create_conversion_value_rule_set.py` (import + callsite)
- Modify: `tests/unit/test_create_conversion_value_rule_set.py` (3 patch sites)
- Modify: `tests/integration/test_create_conversion_value_rule_set.py` (patch sites)
- Modify: `tests/unit/test_validate_conversion_value_rule_set.py` (direct import + test name if any)

- [ ] **Step 1: Rename function in `_common.py`**

In `src/google_ads/queries/_common.py`, find `async def validate_geo_target_constants_for_value_rule(` and replace with `async def validate_geo_target_constants_br_only(`. Update the docstring to be generic:

```python
async def validate_geo_target_constants_br_only(
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    geo_paths: list[str],
) -> str | None:
    """Returns PT-BR error string if any geo target is non-BR; else None.

    Validates each geo_target_constant resource_name:
    1. Exists in Google Ads (queryable via GAQL)
    2. country_code == "BR" (V4 invariant — all V4 accounts in Brazil)

    Performs 1 GAQL batch lookup. Returns first-offender error in INPUT order.

    Sprint 3b.19B (initial) + 3b.24 (renamed generic) — pre-flight for any
    create_* tool that accepts BR-only geo_target_constant paths.
    """
```

Rest of function body unchanged.

- [ ] **Step 2: Update import + callsite in `create_conversion_value_rule_set.py`**

Replace:
```python
from src.google_ads.queries._common import (
    validate_campaign_for_value_rule_set,
    validate_geo_target_constants_for_value_rule,
)
```

With:
```python
from src.google_ads.queries._common import (
    validate_campaign_for_value_rule_set,
    validate_geo_target_constants_br_only,
)
```

And replace the callsite:
```python
error = await validate_geo_target_constants_for_value_rule(
```

With:
```python
error = await validate_geo_target_constants_br_only(
```

- [ ] **Step 3: Update patch targets in tests**

In `tests/unit/test_create_conversion_value_rule_set.py`, replace ALL occurrences:
- `src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_for_value_rule` → `src.mcp.tools.create_conversion_value_rule_set.validate_geo_target_constants_br_only`

In `tests/integration/test_create_conversion_value_rule_set.py`, same replacement.

In `tests/unit/test_validate_conversion_value_rule_set.py`, update direct import:
- `from src.google_ads.queries._common import validate_geo_target_constants_for_value_rule` → `from src.google_ads.queries._common import validate_geo_target_constants_br_only`
- Update any test function references to the old name.

Run grep to confirm zero references remain:
```bash
grep -rn "validate_geo_target_constants_for_value_rule" src/ tests/
```
Expected: zero matches in `src/` and `tests/` (matches in `docs/` are historical and OK).

- [ ] **Step 4: Run pre-push gate to verify no regression**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS. All Sprint 3b.19B tests still pass via renamed helper.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/queries/_common.py src/mcp/tools/create_conversion_value_rule_set.py tests/unit/test_create_conversion_value_rule_set.py tests/integration/test_create_conversion_value_rule_set.py tests/unit/test_validate_conversion_value_rule_set.py
git commit -m "refactor(common): rename validate_geo_target_constants_for_value_rule → _br_only (Sprint 3b.24 cross-tool reuse)"
```

---

## Task 2: TDD red — Schema + runtime validation tests

**Files:**
- Create: `tests/unit/test_create_campaign.py`

- [ ] **Step 1: Write failing tests for schema + runtime validation**

Create `tests/unit/test_create_campaign.py`:

```python
"""Unit tests for create_campaign tool (Sprint 3b.24): schema, runtime validation, pre-flight."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jsonschema
import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture(autouse=True)
def _ctx():
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _valid_payload(**overrides):
    """Build a valid minimal payload, with optional overrides."""
    base = {
        "customer_id": "1234567890",
        "name": "[3b.24 smoke test] T1",
        "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
        "daily_budget_brl": 10.0,
        "geo_targets": ["geoTargetConstants/2076"],
    }
    base.update(overrides)
    return base


# ---------- Schema validation ----------


def test_schema_requires_core_fields():
    from src.mcp.tools.create_campaign import _SCHEMA

    # Missing customer_id
    invalid = {k: v for k, v in _valid_payload().items() if k != "customer_id"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing name
    invalid = {k: v for k, v in _valid_payload().items() if k != "name"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing bidding_strategy
    invalid = {k: v for k, v in _valid_payload().items() if k != "bidding_strategy"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing daily_budget_brl
    invalid = {k: v for k, v in _valid_payload().items() if k != "daily_budget_brl"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # Missing geo_targets
    invalid = {k: v for k, v in _valid_payload().items() if k != "geo_targets"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_schema_rejects_additional_properties():
    from src.mcp.tools.create_campaign import _SCHEMA

    # advertising_channel_type is hardcoded internally, NOT in schema
    invalid = _valid_payload(advertising_channel_type="SEARCH")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)

    # status is hardcoded PAUSED, NOT in schema
    invalid = _valid_payload(status="ENABLED")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_schema_rejects_unknown_bidding_strategy():
    from src.mcp.tools.create_campaign import _SCHEMA

    invalid = _valid_payload(bidding_strategy={"type": "PORTFOLIO_TARGET_CPA"})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)


def test_schema_accepts_all_6_bidding_strategies():
    from src.mcp.tools.create_campaign import _SCHEMA

    for strategy in [
        "MAXIMIZE_CONVERSIONS",
        "MAXIMIZE_CONVERSION_VALUE",
        "TARGET_CPA",
        "TARGET_ROAS",
        "MANUAL_CPC",
        "MAXIMIZE_CLICKS",
    ]:
        # Build minimal-valid per strategy
        bs = {"type": strategy}
        if strategy == "TARGET_CPA":
            bs["target_cpa_brl"] = 25.0
        elif strategy == "TARGET_ROAS":
            bs["target_roas"] = 4.0
        payload = _valid_payload(bidding_strategy=bs)
        # Should NOT raise
        jsonschema.validate(payload, _SCHEMA)


# ---------- Runtime _validate_payload_shape ----------


def test_runtime_target_cpa_requires_target_cpa_brl():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(bidding_strategy={"type": "TARGET_CPA"})
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "TARGET_CPA" in error
    assert "target_cpa_brl" in error


def test_runtime_target_roas_requires_target_roas():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(bidding_strategy={"type": "TARGET_ROAS"})
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "TARGET_ROAS" in error
    assert "target_roas" in error


def test_runtime_enhanced_cpc_only_with_manual_cpc():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # MAX_CONVERSIONS + enhanced_cpc is invalid
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CONVERSIONS", "enhanced_cpc": True}
    )
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "enhanced_cpc" in error

    # MANUAL_CPC + enhanced_cpc is OK
    payload = _valid_payload(
        bidding_strategy={"type": "MANUAL_CPC", "enhanced_cpc": True}
    )
    assert _validate_payload_shape(payload) is None


def test_runtime_cpc_bid_ceiling_only_with_maximize_clicks():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(
        bidding_strategy={"type": "MANUAL_CPC", "cpc_bid_ceiling_brl": 1.5}
    )
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "cpc_bid_ceiling_brl" in error
    assert "MAXIMIZE_CLICKS" in error

    # MAX_CLICKS + ceiling is OK
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CLICKS", "cpc_bid_ceiling_brl": 1.5}
    )
    assert _validate_payload_shape(payload) is None


def test_runtime_target_cpa_brl_invalid_with_wrong_strategy():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # TARGET_ROAS + target_cpa_brl is invalid
    payload = _valid_payload(
        bidding_strategy={"type": "TARGET_ROAS", "target_roas": 4.0, "target_cpa_brl": 50.0}
    )
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "target_cpa_brl" in error


def test_runtime_target_roas_invalid_with_wrong_strategy():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # MAX_CONVERSIONS + target_roas is invalid
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CONVERSIONS", "target_roas": 4.0}
    )
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "target_roas" in error


def test_runtime_max_conv_optional_target_cpa_brl_ok():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # MAX_CONVERSIONS + target_cpa_brl is eCPC mode — valid
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CONVERSIONS", "target_cpa_brl": 30.0}
    )
    assert _validate_payload_shape(payload) is None


def test_runtime_max_conv_value_optional_target_roas_ok():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    # MAX_CONVERSION_VALUE + target_roas is valid (target roi mode)
    payload = _valid_payload(
        bidding_strategy={"type": "MAXIMIZE_CONVERSION_VALUE", "target_roas": 3.5}
    )
    assert _validate_payload_shape(payload) is None


def test_runtime_inverted_dates_rejected():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    payload = _valid_payload(start_date="2026-12-31", end_date="2026-05-01")
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "start_date" in error
    assert "end_date" in error


def test_runtime_valid_payload_returns_none():
    from src.mcp.tools.create_campaign import _validate_payload_shape

    assert _validate_payload_shape(_valid_payload()) is None


# ---------- Pre-flight geo BR validation integration ----------


@pytest.mark.asyncio
async def test_pre_flight_geo_rejection_propagates():
    from src.mcp.tools.create_campaign import create_campaign

    with (
        patch(
            "src.mcp.tools.create_campaign.validate_geo_target_constants_br_only",
            AsyncMock(return_value="Geo target 'Canada' (geoTargetConstants/...) tem country_code 'CA', esperado 'BR'."),
        ),
    ):
        result = await create_campaign(
            _valid_payload(geo_targets=["geoTargetConstants/2124"])
        )

    assert result["status"] == "error"
    assert "BR" in result["error"]
    assert result["operation"] == "create_campaign"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_create_campaign.py -v`
Expected: ALL fail with ImportError (`create_campaign` module doesn't exist) or AttributeError (`_SCHEMA` / `_validate_payload_shape` / `create_campaign` not defined).

- [ ] **Step 3: Commit (red)**

```bash
git add tests/unit/test_create_campaign.py
git commit -m "test(create_campaign): add failing tests for schema + runtime validation (Sprint 3b.24)"
```

---

## Task 3: TDD green — Implement `_SCHEMA` + `_validate_payload_shape`

**Files:**
- Create: `src/mcp/tools/create_campaign.py` (partial — schema + validation helper only; tool body in Task 7)

- [ ] **Step 1: Create the tool file with schema + helper**

Create `src/mcp/tools/create_campaign.py`:

```python
"""Tool: create_campaign — create 1 SEARCH campaign with budget + geo + PT language.

Always-CONFIRM (creates campaign — sensitive per spec §7.1). Chained mutation
pattern (Sprint 3b.19B established): N+M+2 ops em single MutateGoogleAdsRequest:
- 1 campaign_budget_operation
- 1 campaign_operation (references temp budget path)
- N campaign_criterion_operations (locations, references temp campaign path)
- 1 campaign_criterion_operation (PT language, references temp campaign path)

V4 invariants hardcoded (no schema fields):
- status = PAUSED on create
- advertising_channel_type = SEARCH (v0 only)
- network: Search Partners OFF, Display Network OFF
- currency = BRL (account-level inherit)
- language = Portuguese (`languageConstants/1014`) auto-added as criterion

Sprint 3b.24.
"""

from __future__ import annotations

from typing import Any

_BIDDING_STRATEGY_ENUM = [
    "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE",
    "TARGET_CPA",
    "TARGET_ROAS",
    "MANUAL_CPC",
    "MAXIMIZE_CLICKS",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "customer_id",
        "name",
        "bidding_strategy",
        "daily_budget_brl",
        "geo_targets",
    ],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "name": {"type": "string", "minLength": 1, "maxLength": 256},
        "bidding_strategy": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": _BIDDING_STRATEGY_ENUM},
                "target_cpa_brl": {"type": "number", "minimum": 0.01},
                "target_roas": {"type": "number", "minimum": 0.01},
                "cpc_bid_ceiling_brl": {"type": "number", "minimum": 0.01},
                "enhanced_cpc": {"type": "boolean"},
            },
        },
        "daily_budget_brl": {"type": "number", "minimum": 1.0},
        "geo_targets": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {
                "type": "string",
                "pattern": "^geoTargetConstants/[0-9]+$",
            },
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
    },
}


def _validate_payload_shape(args: dict[str, Any]) -> str | None:
    """Returns PT-BR error if bidding_strategy conditional fields are inconsistent
    OR dates are inverted; else None.

    Sprint 3b.19B.1 convention — runtime validation in lieu of JSON Schema
    composition keywords (oneOf/allOf/anyOf rejected by Anthropic API).
    """
    bs = args["bidding_strategy"]
    bs_type = bs["type"]

    # Required-conditional fields
    if bs_type == "TARGET_CPA" and "target_cpa_brl" not in bs:
        return "TARGET_CPA requer bidding_strategy.target_cpa_brl."
    if bs_type == "TARGET_ROAS" and "target_roas" not in bs:
        return "TARGET_ROAS requer bidding_strategy.target_roas."

    # Strategy-specific optional fields rejected on wrong strategy
    if "enhanced_cpc" in bs and bs_type != "MANUAL_CPC":
        return "enhanced_cpc so e valido com MANUAL_CPC."
    if "cpc_bid_ceiling_brl" in bs and bs_type != "MAXIMIZE_CLICKS":
        return "cpc_bid_ceiling_brl so e valido com MAXIMIZE_CLICKS."
    if "target_cpa_brl" in bs and bs_type not in ("TARGET_CPA", "MAXIMIZE_CONVERSIONS"):
        return (
            "target_cpa_brl valido apenas para TARGET_CPA ou MAXIMIZE_CONVERSIONS "
            "(eCPC mode)."
        )
    if "target_roas" in bs and bs_type not in ("TARGET_ROAS", "MAXIMIZE_CONVERSION_VALUE"):
        return (
            "target_roas valido apenas para TARGET_ROAS ou MAXIMIZE_CONVERSION_VALUE."
        )

    # Schedule validation
    start = args.get("start_date")
    end = args.get("end_date")
    if start and end and start > end:
        return f"start_date ({start}) posterior a end_date ({end})."

    return None
```

- [ ] **Step 2: Run tests to verify schema + runtime tests pass**

Run: `pytest tests/unit/test_create_campaign.py -v -k "schema or runtime"`
Expected: 13 PASS (schema validation tests + runtime validation tests). The `test_pre_flight_geo_rejection_propagates` will still fail (no tool body yet — handled in Task 7).

- [ ] **Step 3: Commit (green for schema + runtime)**

```bash
git add src/mcp/tools/create_campaign.py
git commit -m "feat(create_campaign): add schema + _validate_payload_shape (Sprint 3b.24)"
```

---

## Task 4: TDD red — Builder tests using ProtoFieldCapture

**Files:**
- Create: `tests/unit/test_create_campaign_builder.py`

- [ ] **Step 1: Write failing builder tests**

Create `tests/unit/test_create_campaign_builder.py`:

```python
"""Unit tests for build_create_campaign (Sprint 3b.24)."""

from __future__ import annotations

import pytest

from tests.unit.fixtures.proto_capture import make_capture_client


def _payload(**overrides):
    """Build a minimal valid payload."""
    base = {
        "name": "Test Campaign",
        "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
        "daily_budget_brl": 10.0,
        "geo_targets": ["geoTargetConstants/2076"],  # Brazil
    }
    base.update(overrides)
    return base


def test_builder_happy_path_max_conversions_minimal():
    """MAX_CONVERSIONS + 1 geo → 4 ops total (budget + campaign + 1 geo + 1 language)."""
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    ops = build_create_campaign(client, "1234567890", _payload())

    assert len(ops) == 4  # 1 budget + 1 campaign + 1 geo + 1 language

    # Op 0: budget
    budget_op = ops[0]
    assert "campaignBudgets/-1" in budget_op.field(
        "campaign_budget_operation.create.resource_name"
    )
    assert budget_op.field("campaign_budget_operation.create.amount_micros") == 10_000_000
    assert (
        budget_op.field("campaign_budget_operation.create.delivery_method") == "STANDARD"
    )

    # Op 1: campaign
    campaign_op = ops[1]
    assert "campaigns/-2" in campaign_op.field(
        "campaign_operation.create.resource_name"
    )
    assert campaign_op.field("campaign_operation.create.name") == "Test Campaign"
    assert campaign_op.field("campaign_operation.create.status") == "PAUSED"
    assert (
        campaign_op.field("campaign_operation.create.advertising_channel_type")
        == "SEARCH"
    )
    assert "campaignBudgets/-1" in campaign_op.field(
        "campaign_operation.create.campaign_budget"
    )
    # Network settings V4 defaults
    assert (
        campaign_op.field(
            "campaign_operation.create.network_settings.target_google_search"
        )
        is True
    )
    assert (
        campaign_op.field(
            "campaign_operation.create.network_settings.target_search_network"
        )
        is False
    )
    assert (
        campaign_op.field(
            "campaign_operation.create.network_settings.target_content_network"
        )
        is False
    )

    # Op 2: geo criterion
    geo_op = ops[2]
    assert "campaigns/-2" in geo_op.field(
        "campaign_criterion_operation.create.campaign"
    )
    assert (
        geo_op.field("campaign_criterion_operation.create.location.geo_target_constant")
        == "geoTargetConstants/2076"
    )

    # Op 3: language criterion (PT hardcoded)
    lang_op = ops[3]
    assert "campaigns/-2" in lang_op.field(
        "campaign_criterion_operation.create.campaign"
    )
    assert (
        lang_op.field("campaign_criterion_operation.create.language.language_constant")
        == "languageConstants/1014"
    )


def test_builder_target_cpa_sets_target_cpa_micros():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(
        bidding_strategy={"type": "TARGET_CPA", "target_cpa_brl": 25.0}
    )
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert (
        campaign_op.field("campaign_operation.create.target_cpa.target_cpa_micros")
        == 25_000_000
    )


def test_builder_target_roas_sets_target_roas():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(
        bidding_strategy={"type": "TARGET_ROAS", "target_roas": 4.0}
    )
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert (
        campaign_op.field("campaign_operation.create.target_roas.target_roas") == 4.0
    )


def test_builder_manual_cpc_with_enhanced_cpc_flag():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(
        bidding_strategy={"type": "MANUAL_CPC", "enhanced_cpc": True}
    )
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert (
        campaign_op.field("campaign_operation.create.manual_cpc.enhanced_cpc_enabled")
        is True
    )


def test_builder_maximize_clicks_with_ceiling():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(
        bidding_strategy={
            "type": "MAXIMIZE_CLICKS",
            "cpc_bid_ceiling_brl": 2.5,
        }
    )
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert (
        campaign_op.field(
            "campaign_operation.create.target_spend.cpc_bid_ceiling_micros"
        )
        == 2_500_000
    )


def test_builder_multiple_geo_targets_emit_multiple_criterion_ops():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(
        geo_targets=[
            "geoTargetConstants/2076",  # Brazil
            "geoTargetConstants/20180",  # SP state
            "geoTargetConstants/1031590",  # São Paulo city
        ]
    )
    ops = build_create_campaign(client, "1234567890", payload)

    # 1 budget + 1 campaign + 3 geos + 1 language = 6 ops
    assert len(ops) == 6

    # Geo criterion ops at positions 2, 3, 4
    geo_paths = [
        ops[i].field(
            "campaign_criterion_operation.create.location.geo_target_constant"
        )
        for i in range(2, 5)
    ]
    assert geo_paths == [
        "geoTargetConstants/2076",
        "geoTargetConstants/20180",
        "geoTargetConstants/1031590",
    ]

    # Language op at position 5
    assert "languageConstants/1014" in ops[5].field(
        "campaign_criterion_operation.create.language.language_constant"
    )


def test_builder_schedule_dates_set_when_provided():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    payload = _payload(start_date="2026-05-20", end_date="2026-12-31")
    ops = build_create_campaign(client, "1234567890", payload)

    campaign_op = ops[1]
    assert campaign_op.field("campaign_operation.create.start_date") == "2026-05-20"
    assert campaign_op.field("campaign_operation.create.end_date") == "2026-12-31"


def test_builder_omits_schedule_when_not_provided():
    from src.google_ads.mutates.campaigns import build_create_campaign

    client = make_capture_client()
    ops = build_create_campaign(client, "1234567890", _payload())

    campaign_op = ops[1]
    assert campaign_op.has("campaign_operation.create.start_date") is False
    assert campaign_op.has("campaign_operation.create.end_date") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_create_campaign_builder.py -v`
Expected: ALL fail with ImportError (`src.google_ads.mutates.campaigns` doesn't exist).

- [ ] **Step 3: Commit (red)**

```bash
git add tests/unit/test_create_campaign_builder.py
git commit -m "test(create_campaign): add failing builder tests (Sprint 3b.24)"
```

---

## Task 5: TDD green — Implement `build_create_campaign`

**Files:**
- Create: `src/google_ads/mutates/campaigns.py`

- [ ] **Step 1: Implement the builder**

Create `src/google_ads/mutates/campaigns.py`:

```python
"""Mutate builders for campaign operations.

Sprint 3b.24 — quinto create-pattern do MCP. Cria SEARCH campaign via
chained mutation:
- 1 campaign_budget_operation (temp_path -1)
- 1 campaign_operation (temp_path -2, refs budget -1)
- N campaign_criterion_operations (locations, ref campaign -2)
- 1 campaign_criterion_operation (PT language, ref campaign -2)

V4 invariants hardcoded:
- status PAUSED on create
- advertising_channel_type SEARCH (v0)
- network: target_google_search=True, target_search_network=False,
  target_content_network=False (V4 defaults)
- language: languageConstants/1014 (Portuguese)
- budget delivery_method STANDARD

Bidding strategy → oneof field mapping (proto-plus):
- MAXIMIZE_CONVERSIONS → campaign.maximize_conversions (optional target_cpa_micros)
- MAXIMIZE_CONVERSION_VALUE → campaign.maximize_conversion_value (optional target_roas)
- TARGET_CPA → campaign.target_cpa.target_cpa_micros
- TARGET_ROAS → campaign.target_roas.target_roas (decimal, e.g., 4.0 = 400%)
- MANUAL_CPC → campaign.manual_cpc.enhanced_cpc_enabled
- MAXIMIZE_CLICKS → campaign.target_spend (optional cpc_bid_ceiling_micros)

F13 (Sprint 3b.15) auto-returns resource_names array post-create.
"""

from __future__ import annotations

from typing import Any

from src.google_ads.mutates._common import register_builder


def _brl_to_micros(brl: float) -> int:
    """Convert BRL to micros (1 BRL = 1_000_000 micros)."""
    return int(brl * 1_000_000)


@register_builder("create_campaign")
def build_create_campaign(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """Build N+M+2 chained operations for create_campaign.

    payload schema (post-_validate_payload_shape):
      name: str
      bidding_strategy: {type: str, target_cpa_brl?: float, target_roas?: float,
                         cpc_bid_ceiling_brl?: float, enhanced_cpc?: bool}
      daily_budget_brl: float
      geo_targets: list[str]  (geoTargetConstants/{id} paths)
      start_date?: str  (YYYY-MM-DD)
      end_date?: str    (YYYY-MM-DD)

    Returns list[MutateOperation] in order: budget, campaign, geo×N, language.
    """
    operations: list[Any] = []

    # Enums needed
    budget_delivery_enum = client.enums.BudgetDeliveryMethodEnum
    channel_enum = client.enums.AdvertisingChannelTypeEnum
    status_enum = client.enums.CampaignStatusEnum

    # Temp resource paths
    budget_temp_path = f"customers/{customer_id}/campaignBudgets/-1"
    campaign_temp_path = f"customers/{customer_id}/campaigns/-2"

    # ----- Op 0: Campaign Budget -----
    budget_op_wrap = client.get_type("MutateOperation")
    budget_op = budget_op_wrap.campaign_budget_operation
    budget = budget_op.create
    budget.resource_name = budget_temp_path
    budget.name = f"{payload['name']} - budget"
    budget.amount_micros = _brl_to_micros(payload["daily_budget_brl"])
    budget.delivery_method = budget_delivery_enum.STANDARD
    operations.append(budget_op_wrap)

    # ----- Op 1: Campaign -----
    campaign_op_wrap = client.get_type("MutateOperation")
    campaign_op = campaign_op_wrap.campaign_operation
    campaign = campaign_op.create
    campaign.resource_name = campaign_temp_path
    campaign.name = payload["name"]
    campaign.status = status_enum.PAUSED  # V4 invariant
    campaign.advertising_channel_type = channel_enum.SEARCH  # v0
    campaign.campaign_budget = budget_temp_path  # temp ref

    # Network settings V4 invariants
    campaign.network_settings.target_google_search = True
    campaign.network_settings.target_search_network = False  # No Search Partners
    campaign.network_settings.target_content_network = False  # No Display

    # Bidding strategy oneof
    bs = payload["bidding_strategy"]
    bs_type = bs["type"]
    if bs_type == "MAXIMIZE_CONVERSIONS":
        campaign.maximize_conversions  # access creates oneof message
        if "target_cpa_brl" in bs:
            campaign.maximize_conversions.target_cpa_micros = _brl_to_micros(
                bs["target_cpa_brl"]
            )
    elif bs_type == "MAXIMIZE_CONVERSION_VALUE":
        campaign.maximize_conversion_value
        if "target_roas" in bs:
            campaign.maximize_conversion_value.target_roas = bs["target_roas"]
    elif bs_type == "TARGET_CPA":
        campaign.target_cpa.target_cpa_micros = _brl_to_micros(bs["target_cpa_brl"])
    elif bs_type == "TARGET_ROAS":
        campaign.target_roas.target_roas = bs["target_roas"]
    elif bs_type == "MANUAL_CPC":
        campaign.manual_cpc.enhanced_cpc_enabled = bs.get("enhanced_cpc", False)
    elif bs_type == "MAXIMIZE_CLICKS":
        # MAXIMIZE_CLICKS uses target_spend message in proto
        campaign.target_spend
        if "cpc_bid_ceiling_brl" in bs:
            campaign.target_spend.cpc_bid_ceiling_micros = _brl_to_micros(
                bs["cpc_bid_ceiling_brl"]
            )

    # Schedule (optional)
    if "start_date" in payload:
        campaign.start_date = payload["start_date"]
    if "end_date" in payload:
        campaign.end_date = payload["end_date"]

    operations.append(campaign_op_wrap)

    # ----- Ops 2..N+1: Geo Criterion ops -----
    for geo_path in payload["geo_targets"]:
        geo_op_wrap = client.get_type("MutateOperation")
        geo_op = geo_op_wrap.campaign_criterion_operation
        geo_crit = geo_op.create
        geo_crit.campaign = campaign_temp_path  # temp ref
        geo_crit.location.geo_target_constant = geo_path
        operations.append(geo_op_wrap)

    # ----- Op N+2: PT Language Criterion -----
    lang_op_wrap = client.get_type("MutateOperation")
    lang_op = lang_op_wrap.campaign_criterion_operation
    lang_crit = lang_op.create
    lang_crit.campaign = campaign_temp_path  # temp ref
    lang_crit.language.language_constant = "languageConstants/1014"  # PT (V4)
    operations.append(lang_op_wrap)

    return operations
```

- [ ] **Step 2: Run builder tests to verify they pass**

Run: `pytest tests/unit/test_create_campaign_builder.py -v`
Expected: 8 PASS.

If any test fails because ProtoFieldCapture doesn't support the new proto field paths (e.g., `campaign_operation.create.maximize_conversions.target_cpa_micros`), inspect the failure. The ProtoFieldCapture fixture uses dynamic attribute access via `__getattr__` so most nested paths work automatically. If a service method needs explicit mocking, extend `tests/unit/fixtures/proto_capture.py` — but try running first to confirm.

- [ ] **Step 3: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 4: Commit (green)**

```bash
git add src/google_ads/mutates/campaigns.py
git commit -m "feat(mutates): add build_create_campaign with chained mutation (Sprint 3b.24)"
```

---

## Task 6: TDD green — Implement tool body + register_tool

**Files:**
- Modify: `src/mcp/tools/create_campaign.py` (extend Task 3 file with @register_tool decorated handler)

- [ ] **Step 1: Add tool body to `create_campaign.py`**

Open `src/mcp/tools/create_campaign.py` (created in Task 3) and append the following AFTER `_validate_payload_shape` function:

```python
# Tool body imports (placed after schema/validator helpers to keep them dependency-light)
from src.db import connection
from src.google_ads.queries._common import validate_geo_target_constants_br_only
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool


def _build_params_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe: counts only, NO copy text per spec §3.6."""
    bs = payload["bidding_strategy"]
    return {
        "bidding_strategy_type": bs["type"],
        "daily_budget_brl": payload["daily_budget_brl"],
        "geo_count": len(payload["geo_targets"]),
        "has_schedule": ("start_date" in payload) or ("end_date" in payload),
    }


@register_tool(
    name="create_campaign",
    description=(
        "Cria 1 SEARCH campaign nova em uma conta V4. Always-CONFIRM. Schema "
        "requer name + bidding_strategy + daily_budget_brl + geo_targets (lista "
        "de geoTargetConstants resource paths, validados como BR via pre-flight "
        "V4). Status sempre PAUSED on create — gestor liga manualmente apos "
        "review. Language defaults Portuguese. Search Partners + Display Network "
        "OFF (V4 defaults). Bidding strategies suportadas v0: MAXIMIZE_CONVERSIONS, "
        "MAXIMIZE_CONVERSION_VALUE, TARGET_CPA (requer target_cpa_brl), "
        "TARGET_ROAS (requer target_roas), MANUAL_CPC (opcional enhanced_cpc), "
        "MAXIMIZE_CLICKS (opcional cpc_bid_ceiling_brl). Conversion goals "
        "inherit account-default (override fica pra v1). Channel SEARCH only v0 "
        "(PMAX/DISPLAY/SHOPPING v1). F13 resource_names auto-retorna paths "
        "criados (budget + campaign + N geo criterions + PT language criterion)."
    ),
    input_schema=_SCHEMA,
)
async def create_campaign(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]

    # Runtime payload validation (Sprint 3b.19B.1 pattern)
    shape_error = _validate_payload_shape(args)
    if shape_error:
        return {
            "status": "error",
            "error": shape_error,
            "operation": "create_campaign",
        }

    # Pre-flight: V4 BR-invariant geo validation
    error = await validate_geo_target_constants_br_only(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        geo_paths=args["geo_targets"],
    )
    if error:
        return {
            "status": "error",
            "error": error,
            "operation": "create_campaign",
        }

    # Compute target_count: 1 budget + 1 campaign + N geos + 1 language
    geo_count = len(args["geo_targets"])
    target_count = 2 + geo_count + 1

    risk = classify(
        operation="create_campaign",
        params={"target_count": target_count},
    )

    params_summary = _build_params_summary(args)
    bs = args["bidding_strategy"]

    summary = (
        f"Criar 1 campanha SEARCH (PAUSED) + budget BRL "
        f"{args['daily_budget_brl']:.2f}/dia + {geo_count} geo target(s) + "
        f"PT language. Bidding: {bs['type']}."
    )

    payload = {
        **args,
        "__target_count__": target_count,
        "__params_summary__": params_summary,
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_campaign",
            payload=payload,
            blast_summary=summary,
        )

    preview = {
        "name": args["name"],
        "bidding_strategy_type": bs["type"],
        "daily_budget_brl": args["daily_budget_brl"],
        "geo_count": geo_count,
        "has_schedule": params_summary["has_schedule"],
    }

    return {
        "status": "dry_run",
        "operation": "create_campaign",
        "customer_id": customer_id,
        "blast_summary": summary,
        "preview": preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
```

- [ ] **Step 2: Run all create_campaign tests**

Run: `pytest tests/unit/test_create_campaign.py tests/unit/test_create_campaign_builder.py -v`
Expected: ALL PASS (schema + runtime + pre-flight integration + 8 builder tests = ~20 tests).

- [ ] **Step 3: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS — including ruff format/lint/mypy on new files, AND test_tools_schemas.py assertion on `create_campaign` being NEW (may fail until Task 8 updates the allowlist; if fails, proceed to Task 8 first).

If `test_tools_schemas.py::test_no_unexpected_tools` fails because `create_campaign` is not in the expected set, that's the trigger for Task 8 — proceed.

- [ ] **Step 4: Commit (green)**

```bash
git add src/mcp/tools/create_campaign.py
git commit -m "feat(mcp): add create_campaign tool body + register_tool (Sprint 3b.24)"
```

---

## Task 7: Integration test

**Files:**
- Create: `tests/integration/test_create_campaign.py`

- [ ] **Step 1: Create integration test**

Create `tests/integration/test_create_campaign.py`:

```python
"""Integration: create_campaign end-to-end with mocked SDK + real DB (testcontainers)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.mcp.context import McpRequestContext, clear_current, set_current

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


@pytest.mark.asyncio
async def test_create_campaign_dry_run_creates_pending_token(db):
    """Tool returns dry_run + token; audit_log row only on apply, not dry_run."""
    from src.mcp.tools.create_campaign import create_campaign

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
        with patch(
            "src.mcp.tools.create_campaign.validate_geo_target_constants_br_only",
            AsyncMock(return_value=None),
        ):
            result = await create_campaign(
                {
                    "customer_id": "1234567890",
                    "name": "[3b.24 integration] Test",
                    "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
                    "daily_budget_brl": 10.0,
                    "geo_targets": ["geoTargetConstants/2076"],
                }
            )

        assert result["status"] == "dry_run"
        assert "confirmation_token" in result
        assert len(result["confirmation_token"]) == 8
        assert result["preview"]["bidding_strategy_type"] == "MAXIMIZE_CONVERSIONS"
        assert result["preview"]["geo_count"] == 1
        assert result["preview"]["has_schedule"] is False
        assert "SEARCH" in result["blast_summary"]
        assert "PAUSED" in result["blast_summary"]
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_create_campaign_pre_flight_geo_rejection(db):
    """Non-BR geo path → tool returns error before creating dry_run token."""
    from src.mcp.tools.create_campaign import create_campaign

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    try:
        with patch(
            "src.mcp.tools.create_campaign.validate_geo_target_constants_br_only",
            AsyncMock(
                return_value="Geo target tem country_code 'CA', esperado 'BR'."
            ),
        ):
            result = await create_campaign(
                {
                    "customer_id": "1234567890",
                    "name": "[3b.24] Bad geo test",
                    "bidding_strategy": {"type": "MAXIMIZE_CONVERSIONS"},
                    "daily_budget_brl": 10.0,
                    "geo_targets": ["geoTargetConstants/2124"],  # Canada
                }
            )

        assert result["status"] == "error"
        assert "BR" in result["error"]
        assert "confirmation_token" not in result
    finally:
        clear_current()
```

- [ ] **Step 2: Run integration test if Docker available**

```bash
pytest tests/integration/test_create_campaign.py -v -m integration
```
Expected: 2 PASS if Docker running; otherwise rely on CI.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_create_campaign.py
git commit -m "test(create_campaign): integration test for dry_run + pre-flight (Sprint 3b.24)"
```

---

## Task 8: Update `test_tools_schemas.py` registry

**Files:**
- Modify: `tests/unit/test_tools_schemas.py` (add `create_campaign` to expected sets)

- [ ] **Step 1: Add `create_campaign` to expected tool allowlists**

In `tests/unit/test_tools_schemas.py`, find `test_all_phase_2_tools_registered` and `test_no_unexpected_tools`. In both `expected` sets, add `"create_campaign"` in the "create patterns" section (consistent with `create_rsa`, `create_conversion_action`, `create_conversion_value_rule_set`):

```python
        # create patterns
        "create_rsa",
        "create_conversion_action",
        "create_conversion_value_rule_set",
        "create_campaign",  # Sprint 3b.24
```

- [ ] **Step 2: Run schema tests**

Run: `pytest tests/unit/test_tools_schemas.py -v`
Expected: ALL PASS, including registry tests.

- [ ] **Step 3: Run full pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_tools_schemas.py
git commit -m "test(schemas): register create_campaign in expected tool allowlists (Sprint 3b.24)"
```

---

## Task 9: Smoke runbook scaffold

**Files:**
- Create: `docs/operacao/phase-3b-24-bootstrap.md`

- [ ] **Step 1: Create smoke runbook**

Create `docs/operacao/phase-3b-24-bootstrap.md`:

```markdown
# Phase 3b.24 — manual smoke runbook (`create_campaign` SEARCH v0)

**Purpose:** Validar Sprint 3b.24 — quinto create-pattern do MCP, foundation pra onboarding completo V4 via Claude/Codex.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox — campaigns serão PAUSED, zero serving impact)

**Spec:** `docs/superpowers/specs/2026-05-17-sprint-3b-24-create-campaign-design.md`
**Plan:** `docs/superpowers/plans/2026-05-17-sprint-3b-24-create-campaign.md`

**Sprint 3b.19A.1 lesson aplicado:** T5 explicit per-strategy empirical probe pra todas 6 bidding strategies.

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session pra schema cache atualizar)
- [ ] Tool `create_campaign` visível em MCP tool list (count 46 → 47)

Production revision: `<fill-in>`.

## Test T1 — Happy path: MAX_CONVERSIONS + 1 geo (Brazil whole)

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T1 - max_conv brazil",
  bidding_strategy={"type": "MAXIMIZE_CONVERSIONS"},
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/2076"]
)
```

Expected:
- [ ] dry_run com confirmation_token
- [ ] blast_summary: "Criar 1 campanha SEARCH (PAUSED) + budget BRL 10.00/dia + 1 geo target(s) + PT language. Bidding: MAXIMIZE_CONVERSIONS."
- [ ] preview com bidding_strategy_type, daily_budget_brl, geo_count=1, has_schedule=false
- [ ] apply → applied_count = 4 (budget + campaign + 1 geo + 1 language)
- [ ] resource_names array com 4 paths
- [ ] GAQL verify:
```
SELECT campaign.id, campaign.name, campaign.status, campaign.advertising_channel_type,
  campaign.bidding_strategy_type, campaign_budget.amount_micros
FROM campaign
WHERE campaign.id = <id from resource_names[1]>
```
Retorna: status=PAUSED, channel=SEARCH, strategy=MAXIMIZE_CONVERSIONS, budget=10_000_000 micros.

**Result:** ⬜ pending

## Test T2 — TARGET_CPA happy path

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T2 - target_cpa 25brl",
  bidding_strategy={"type": "TARGET_CPA", "target_cpa_brl": 25.0},
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/2076"]
)
```

Expected:
- [ ] dry_run + apply
- [ ] GAQL verify: `SELECT campaign.target_cpa.target_cpa_micros FROM campaign WHERE campaign.id = <id>` → 25_000_000

**Result:** ⬜ pending

## Test T3 — Runtime rejection: TARGET_CPA sem target_cpa_brl

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T3 - invalid",
  bidding_strategy={"type": "TARGET_CPA"},  # missing target_cpa_brl
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/2076"]
)
```

Expected:
- [ ] response status=error
- [ ] error message PT-BR: "TARGET_CPA requer bidding_strategy.target_cpa_brl."
- [ ] sem confirmation_token

**Result:** ⬜ pending

## Test T4 — Pre-flight V4 BR rejection (Canada geo)

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T4 - canada geo",
  bidding_strategy={"type": "MAXIMIZE_CONVERSIONS"},
  daily_budget_brl=10.0,
  geo_targets=["geoTargetConstants/20114"]  # British Columbia, Canada
)
```

Expected:
- [ ] response status=error
- [ ] error message PT-BR menciona country_code='CA' esperado 'BR'
- [ ] sem confirmation_token

**Result:** ⬜ pending

## Test T5 — Per-strategy empirical probe (Sprint 3b.19A.1 lesson)

Validate every bidding strategy enum value works end-to-end. Each call creates a campaign with minimal config for that strategy.

T5.1 MAXIMIZE_CONVERSION_VALUE:
```
bidding_strategy={"type": "MAXIMIZE_CONVERSION_VALUE"}
```

T5.2 TARGET_ROAS:
```
bidding_strategy={"type": "TARGET_ROAS", "target_roas": 3.0}
```

T5.3 MANUAL_CPC + enhanced_cpc:
```
bidding_strategy={"type": "MANUAL_CPC", "enhanced_cpc": true}
```

T5.4 MAXIMIZE_CLICKS + ceiling:
```
bidding_strategy={"type": "MAXIMIZE_CLICKS", "cpc_bid_ceiling_brl": 1.5}
```

Expected:
- [ ] All 4 probes APPLY successfully (combined com MAX_CONVERSIONS T1 + TARGET_CPA T2 = 6/6 strategies validated)
- [ ] If any combo fails → F2x finding documentado + remover strategy do schema enum

**Result:** ⬜ pending

## Test T6 — F13 chained mutation verification

Inspect T1 apply response. `resource_names` should be 4-element array:

```
[
  "customers/1163862076/campaignBudgets/<budget_id>",
  "customers/1163862076/campaigns/<campaign_id>",
  "customers/1163862076/campaignCriteria/<campaign_id>~<location_id>",
  "customers/1163862076/campaignCriteria/<campaign_id>~<language_id>"
]
```

Expected:
- [ ] Length = 4
- [ ] Order: budget, campaign, geo criterion, language criterion
- [ ] Each path has correct prefix
- [ ] Campaign criteria use compound `{campaign_id}~{criterion_id}` format (Sprint 3b.6 A5 pattern)

**Result:** ⬜ pending

## Test T7 — Multi-geo + schedule probe

```
create_campaign(
  customer_id="1163862076",
  name="[3b.24 smoke] T7 - multigeo + schedule",
  bidding_strategy={"type": "MAXIMIZE_CONVERSIONS"},
  daily_budget_brl=15.0,
  geo_targets=["geoTargetConstants/2076", "geoTargetConstants/20180"],  # Brasil + SP state
  start_date="2026-05-20",
  end_date="2026-12-31"
)
```

Expected:
- [ ] dry_run + apply, applied_count = 5 (1 budget + 1 campaign + 2 geos + 1 language)
- [ ] resource_names length = 5
- [ ] GAQL verify campaign has start_date=2026-05-20, end_date=2026-12-31
- [ ] GAQL verify 2 location criteria exist for campaign
- [ ] **Validate languageConstants/1014 open question:** GAQL `SELECT campaign_criterion.language.language_constant FROM campaign_criterion WHERE campaign.id = <id> AND campaign_criterion.type = LANGUAGE` retorna "languageConstants/1014" + Google's display = "Portuguese". Se diferente, documentar F2x + ajustar builder hardcoded constant.

**Result:** ⬜ pending

## Cleanup

7 test campaigns serão criadas em Nutry sandbox. Cannot be deleted via API v0 (Sprint 3b.28 vai shipar `remove_campaign`). Aceitar como sandbox junk per spec § Cleanup. All campaigns PAUSED — zero serving impact.

## Sign-off final

- [ ] T1 happy path: F13 chained returns 4 resource_names; GAQL confirms structure
- [ ] T2 TARGET_CPA: applied + GAQL confirms target_cpa_micros
- [ ] T3 runtime rejection: TARGET_CPA sem target_cpa_brl rejected antes do pre-flight
- [ ] T4 V4 BR pre-flight: Canada geo rejected com PT-BR
- [ ] T5 per-strategy probe: 4 remaining strategies (MAX_CONV_VALUE + TARGET_ROAS + MANUAL_CPC + MAX_CLICKS) all applied
- [ ] T6 F13 chained: 4-element resource_names array em ordem correta
- [ ] T7 multi-geo + schedule: 5 ops + dates persisted + languageConstants/1014 validated
- [ ] Production revision verificada
- [ ] CLAUDE.md atualizado: Sprint 3b.24 shipped, tool count 46 → 47

**Date completed:** ____

## Findings (post-execution)

(Inline — surfaceados durante smoke.)
```

- [ ] **Step 2: Commit smoke runbook**

```bash
git add docs/operacao/phase-3b-24-bootstrap.md
git commit -m "docs(ops): scaffold smoke runbook for Sprint 3b.24"
```

---

## Task 10: Add CLAUDE.md row

**Files:**
- Modify: `CLAUDE.md` ("Shipped + in production" table)

- [ ] **Step 1: Add Sprint 3b.24 row**

In `CLAUDE.md`, find the last row in the "Shipped + in production" table (Sprint 3b.23 ending with "F22 resolvido em conta MO-JP..."). Append immediately after:

```markdown
| Sprint 3b.24 — `create_campaign` SEARCH v0 (5º create-pattern) | ✅ 2026-05-17 | <N> commits ([8d7bc5a..main](https://github.com/BadWolf1509/v4-ads-mcp/compare/8d7bc5a..main)); smoke runbook ([`phase-3b-24-bootstrap.md`](docs/operacao/phase-3b-24-bootstrap.md)) — production revision `<rev>` (pending smoke validation). **1 new MCP tool (count 46 → 47):** primeiro campaign create do MCP V4, foundation pra onboarding completo via Claude/Codex (destrava create_ad_group/rsa/add_keywords que ficavam isolados). Always-CONFIRM. Schema: name + bidding_strategy (6 strategies: MAX_CONVERSIONS, MAX_CONVERSION_VALUE, TARGET_CPA, TARGET_ROAS, MANUAL_CPC, MAX_CLICKS) + daily_budget_brl + geo_targets (required, V4 BR-invariant pre-flight) + optional start/end_date. **V4 invariants hardcoded:** status=PAUSED on create, advertising_channel_type=SEARCH (v0), Search Partners OFF, Display Network OFF, language=Portuguese (`languageConstants/1014`) auto-added. **Architecture:** chained mutation pattern (Sprint 3b.19B established), N+M+2 ops em single MutateGoogleAdsRequest — 1 budget + 1 campaign + N geo criterions + 1 PT language criterion. **Helper `validate_geo_target_constants_for_value_rule` renamed to `validate_geo_target_constants_br_only`** em `_common.py` para cross-tool reuse (extension de Sprint 3b.21 parse_resource_path pattern). Runtime payload validation via `_validate_payload_shape` (Sprint 3b.19B.1 pattern: bidding strategy conditional fields + date validation). ~17 unit tests (~10 tool + ~8 builder) + 1 integration. F13 cross-cutting auto-returns resource_names. **Sprint 3b.19A.1 lesson aplicado:** T5 explicit per-strategy probe (6 strategies × minimal config) em smoke runbook. **Foundation pra Sprint 3b.25** (`create_asset` + `link_assets` need campaign existente). |
```

- [ ] **Step 2: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): add Sprint 3b.24 row (create_campaign SEARCH v0)"
```

---

## Task 11: Pre-push final + push + watch deploy + capture revision

- [ ] **Step 1: Final pre-push gate**

```bash
python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 2: Push to main**

```bash
git push origin main
```
Expected: admin bypass accepted (per project convention).

- [ ] **Step 3: Watch Deploy**

```bash
gh run list --limit 3 --json databaseId,name,status,headSha
gh run watch <deploy-id> --exit-status
```
Expected: Deploy green em ~3-5 min.

- [ ] **Step 4: Capture production revision**

```bash
gcloud run services describe v4-ads-mcp --project=v4-ads-mcp-prod --region=southamerica-east1 --format='value(status.latestReadyRevisionName)'
curl -s -o /dev/null -w "%{http_code}" https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```
Expected: revision name `v4-ads-mcp-NNNNN-xxx` + /health 200.

Update `docs/operacao/phase-3b-24-bootstrap.md` Pre-flight section with captured revision. Update CLAUDE.md row `<rev>` placeholder.

- [ ] **Step 5: Commit + push final docs**

```bash
git add docs/operacao/phase-3b-24-bootstrap.md CLAUDE.md
git commit -m "docs(claude): Sprint 3b.24 production revision <rev> captured"
git push origin main
```

---

## Task 12: Smoke execution + signoff

**Note:** This task can be executed inline by the controller (using mcp__v4-ads__create_campaign + apply_change + run_gaql tools available in session) OR handed off to Wellington for manual execution.

- [ ] **Step 1: Reload Claude Code MCP session** (so the schema cache picks up `limit` field; verify tool count = 47 via list_tools)

- [ ] **Step 2: Execute T1-T7 from `docs/operacao/phase-3b-24-bootstrap.md`**

For each test:
1. Call `create_campaign(...)` with the specified payload (dry_run)
2. If T3/T4 — verify error response matches expected PT-BR
3. Otherwise — capture confirmation_token, then call `apply_change(confirmation_token=...)`
4. Inspect response: applied_count, resource_names array, blast_summary
5. For T1/T2/T7 — GAQL verify via `run_gaql`
6. Mark ⬜ → ✅/❌ in the runbook + add details (resource IDs, GAQL output snippet)

- [ ] **Step 3: Document any findings**

If any test fails OR surfaces unexpected behavior:
- Add finding to `## Findings (post-execution)` section
- F-number it (F29, F30, ... continuing from F28 the latest)
- Severity + reproducer + root cause + fix candidate
- Spawn-task if fix needed in follow-up sprint

- [ ] **Step 4: Final signoff commit**

```bash
git add docs/operacao/phase-3b-24-bootstrap.md CLAUDE.md
git commit -m "docs(ops): Sprint 3b.24 smoke signed-off em Nutry — N/7 PASS"
git push origin main
```

---

## Self-Review Notes

**Spec coverage check:**
- ✅ §Goal — Tasks 5-6 implement create_campaign tool + builder
- ✅ §Non-goals (v0) — schema restricts to SEARCH, MAX 6 strategies, no PMAX/DISPLAY/SHOPPING, no batch, no audience targeting, no conversion goals override, no name uniqueness pre-flight
- ✅ §Tool surface > Description — Task 6 description string matches spec language
- ✅ §Input schema — Task 3 implements exact schema (no composition keywords, additionalProperties:false, all required fields)
- ✅ §Runtime payload validation — Task 3 `_validate_payload_shape` covers 7 validation rules (TARGET_CPA requires target_cpa_brl, TARGET_ROAS requires target_roas, enhanced_cpc only MANUAL_CPC, ceiling only MAX_CLICKS, target_cpa_brl wrong strategy, target_roas wrong strategy, inverted dates)
- ✅ §V4 hardcoded invariants — Task 5 builder hardcodes status=PAUSED, channel=SEARCH, target_search_network=False, target_content_network=False, target_google_search=True, language=1014, budget delivery_method=STANDARD
- ✅ §Architecture > Chained mutation — Task 5 builder produces 4-6 ops in correct order (budget, campaign, geo×N, language)
- ✅ §Bidding strategy → proto mapping — Task 5 covers all 6 strategies with correct proto field oneof selection
- ✅ §Pre-flights — Task 1 renames helper to `validate_geo_target_constants_br_only`; Task 6 invokes it in tool body
- ✅ §F13 auto-return — Inherited via run_mutation infrastructure (Sprint 3b.15 cross-cutting), no new code needed
- ✅ §Audit + governance — Task 6 computes target_count, params_summary, blast_summary, create_pending invocation
- ✅ §Testing strategy > Unit tests — Tasks 2/4 cover ~17 tests (schema, runtime, builder, pre-flight integration)
- ✅ §Testing strategy > Integration test — Task 7
- ✅ §Smoke runbook outline — Task 9 with T1-T7 + sign-off

**Placeholder scan:** clean. The smoke runbook has explicit `<fill-in>` for production revision — that's deliberate operator-fill content (matches pattern from prior bootstraps). CLAUDE.md row has `<N> commits` and `<rev>` placeholders filled in Task 11 Step 4 post-deploy capture.

**Type consistency:**
- ✅ `validate_geo_target_constants_br_only` signature `(manager_id, session_id, customer_id, geo_paths) -> str | None` consistent across rename in Task 1 + callsite in Task 6 + test mocks in Task 2 + Task 7
- ✅ `build_create_campaign` signature `(client, customer_id, payload) -> list[MutateOperation]` consistent across Tasks 4-5
- ✅ `_validate_payload_shape` signature `(args: dict) -> str | None` consistent across Tasks 2-3
- ✅ Response shape keys (`status`, `operation`, `customer_id`, `blast_summary`, `preview`, `confirmation_token`, `expires_in_minutes`, `to_apply`, `confirmation_reason`, `error`) consistent across Task 6 implementation + Task 2/7 test assertions
- ✅ params_summary keys (`bidding_strategy_type`, `daily_budget_brl`, `geo_count`, `has_schedule`) consistent across Task 6 `_build_params_summary` + Task 7 audit assertion
