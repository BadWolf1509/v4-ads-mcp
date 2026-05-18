# Sprint 3b.25 — `create_and_link_assets` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 48th MCP tool `create_and_link_assets` — atomically creates N text-extension assets (SITELINK/CALLOUT/STRUCTURED_SNIPPET/CALL/PROMOTION) and links them to CUSTOMER/CAMPAIGN/AD_GROUP scope in a single chained mutation. Foundation for full campaign onboarding via Claude/Codex (closes loop opened by Sprint 3b.24 `create_campaign`).

**Architecture:** 1 fused MCP tool dispatches a chained mutation via `run_mutation` (Sprint 3b.19B pattern). Builder emits 2N ops: N CreateAssetOp + N Create{Customer|Campaign|AdGroup}AssetOp linked via temp resource names `customers/{cid}/assets/-{i}`. V4 invariants hardcoded in builder (`country_code="BR"`, `language_code="pt"`, `currency_code="BRL"`). 3-layer validation: JSONSchema → runtime `_validate_payload_shape` (6 cross-field checks) → Google API runtime (trust errors per Sprint 3b.19A.1 F14 lesson).

**Tech Stack:** Python 3.12+ · google-ads SDK v24 · proto-plus message API · asyncpg · pytest + testcontainers · jsonschema validator

**Spec:** `docs/superpowers/specs/2026-05-18-sprint-3b-25-create-and-link-assets-design.md`

---

## File Structure

| File | Responsibility | LOC |
|---|---|---|
| **Create:** `src/mcp/tools/create_and_link_assets.py` | Schema, `_validate_payload_shape`, tool entry point (dry_run flow + audit_log params), `@register_tool` | ~250 |
| **Create:** `src/google_ads/mutates/assets.py` | `build_create_and_link_assets` builder; per-type proto assignment; chained mutation ops | ~200 |
| **Create:** `tests/unit/test_create_and_link_assets.py` | Tool tests: 5 schema + 8 `_validate` + 2 dry-run = ~15 tests | ~250 |
| **Create:** `tests/unit/test_create_and_link_assets_builder.py` | Builder tests via `make_capture_client`: 5 per-type + 3 PROMOTION + 3 attachment + 4 chained + 3 V4-invariant = ~18 tests | ~350 |
| **Create:** `tests/integration/test_create_and_link_assets.py` | 2 tests: dry_run emits token + full cycle returns 2N resource_names + audit_log applied | ~120 |
| **Create:** `docs/operacao/phase-3b-25-bootstrap.md` | Smoke runbook scaffold: T1-T15 in Nutry sandbox | ~200 |
| **Modify:** `tests/unit/test_tools_schemas.py` | Add `create_and_link_assets` to expected tool allowlist | +1 line |
| **Modify:** `CLAUDE.md` | Add Sprint 3b.25 row to "Current state" table; bump tool count 47→48; bump "Last updated" date | +5 lines |

**No modifications to:**
- `src/google_ads/mutations.py` (builder auto-registered via `@register_builder` + `import_all_builders()` discovery)
- `src/mcp/tools/__init__.py` (auto-discovery from Sprint 3b.14.1)
- `src/mcp/tools/_registry.py` (existing helpers handle new tool)

---

## Task 1: Schema + Runtime Validation Tests (RED) + Tool Skeleton

**Files:**
- Create: `tests/unit/test_create_and_link_assets.py`
- Create: `src/mcp/tools/create_and_link_assets.py` (skeleton only; full body in Task 3)

### Step 1.1: Create failing schema validation tests

Create `tests/unit/test_create_and_link_assets.py` with these tests:

```python
"""Unit tests for create_and_link_assets tool (Sprint 3b.25).

Covers schema validation + runtime _validate_payload_shape.
Builder tests live in test_create_and_link_assets_builder.py (separate file).
"""

from __future__ import annotations

import pytest

from src.mcp.tools.create_and_link_assets import (
    _SCHEMA,
    _validate_payload_shape,
)

import jsonschema


def _valid_sitelink_asset():
    return {
        "type": "SITELINK",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "link_text": "Sobre nós",
        "final_urls": ["https://example.com/sobre"],
    }


def _valid_payload(assets=None):
    return {
        "customer_id": "1234567890",
        "assets": assets if assets is not None else [_valid_sitelink_asset()],
    }


# ============================================================================
# Schema tests (JSONSchema layer — Layer 1)
# ============================================================================

def test_schema_rejects_missing_customer_id():
    payload = {"assets": [_valid_sitelink_asset()]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_empty_assets_array():
    payload = {"customer_id": "1234567890", "assets": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_more_than_20_assets():
    payload = _valid_payload(assets=[_valid_sitelink_asset()] * 21)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_invalid_phone_number_with_letters():
    asset = {
        "type": "CALL",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "phone_number": "abc-not-a-number",
    }
    payload = _valid_payload(assets=[asset])
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_accepts_minimal_valid_payload():
    # Should NOT raise
    jsonschema.validate(_valid_payload(), _SCHEMA)


# ============================================================================
# Runtime _validate_payload_shape tests (Layer 2)
# ============================================================================

def test_validate_accepts_minimal_valid_payload():
    assert _validate_payload_shape(_valid_payload()) is None


def test_validate_rejects_sitelink_with_callout_text():
    asset = _valid_sitelink_asset()
    asset["callout_text"] = "Atendimento 24h"
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "callout_text" in error["error"]
    assert error["operation"] == "create_and_link_assets"


def test_validate_rejects_promotion_with_both_discounts():
    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "percent_off": 20.0,
        "money_amount_off_brl": 50.0,
        "final_urls": ["https://example.com/promo"],
    }
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "exatamente um" in error["error"].lower()


def test_validate_rejects_promotion_without_any_discount():
    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "final_urls": ["https://example.com/promo"],
    }
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "exatamente um" in error["error"].lower()


def test_validate_rejects_sitelink_with_only_description1():
    asset = _valid_sitelink_asset()
    asset["description1"] = "Apenas linha 1"
    # Missing description2
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "ambos" in error["error"].lower()


def test_validate_rejects_customer_level_with_non_matching_id():
    asset = _valid_sitelink_asset()
    asset["attachment_level"] = "CUSTOMER"
    asset["attachment_id"] = "9999999999"  # different customer
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "customer_id" in error["error"]


def test_validate_rejects_campaign_level_with_invalid_resource_path():
    asset = _valid_sitelink_asset()
    asset["attachment_id"] = "99999"  # raw id, not resource path
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "resource path" in error["error"].lower() or "customers/" in error["error"]


def test_validate_rejects_promotion_end_date_before_start():
    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
        "start_date": "2026-06-01",
        "end_date": "2026-05-01",
    }
    error = _validate_payload_shape(_valid_payload(assets=[asset]))
    assert error is not None
    assert "end_date" in error["error"]
    assert "start_date" in error["error"]


def test_validate_error_contains_asset_index():
    """Errors must identify which asset in the list failed."""
    bad_asset = _valid_sitelink_asset()
    bad_asset["callout_text"] = "wrong"
    payload = _valid_payload(assets=[_valid_sitelink_asset(), bad_asset])
    error = _validate_payload_shape(payload)
    assert error is not None
    assert "assets[1]" in error["error"]


# ============================================================================
# No-composition-keywords regression guard (Sprint 3b.19B.1 convention)
# ============================================================================

def test_schema_has_no_composition_keywords():
    """Anthropic API rejects oneOf/allOf/anyOf at any nesting level."""
    import json

    schema_json = json.dumps(_SCHEMA)
    assert '"oneOf"' not in schema_json
    assert '"allOf"' not in schema_json
    assert '"anyOf"' not in schema_json
```

- [ ] **Step 1.2: Run tests — expect ImportError**

Run: `python -m pytest tests/unit/test_create_and_link_assets.py -v`
Expected: `ModuleNotFoundError: No module named 'src.mcp.tools.create_and_link_assets'`

- [ ] **Step 1.3: Create minimal tool skeleton with schema + validator**

Create `src/mcp/tools/create_and_link_assets.py`:

```python
"""Tool: create_and_link_assets — create N text-assets + link to scope in chained mutation.

Always-CONFIRM (creates assets — sensitive per spec §7.1). Chained mutation
pattern (Sprint 3b.19B established): 2N ops em single MutateGoogleAdsRequest:
- N asset_operation.create
- N {customer|campaign|ad_group}_asset_operation.create (refs temp asset paths)

V4 invariants hardcoded (no schema fields):
- country_code = "BR" (CALL)
- language_code = "pt" (PROMOTION)
- currency_code = "BRL" (PROMOTION.money_amount_off)

Sprint 3b.25.
"""

from __future__ import annotations

from typing import Any

_ASSET_TYPES = ["SITELINK", "CALLOUT", "STRUCTURED_SNIPPET", "CALL", "PROMOTION"]
_ATTACHMENT_LEVELS = ["CUSTOMER", "CAMPAIGN", "AD_GROUP"]
_STRUCTURED_SNIPPET_HEADERS = [
    "AMENITIES", "BRANDS", "COURSES", "DEGREE_PROGRAMS", "DESTINATIONS",
    "FEATURED_HOTELS", "INSURANCE_COVERAGE", "MODELS", "NEIGHBORHOODS",
    "SERVICE_CATALOG", "SHOWS", "STYLES", "TYPES",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["customer_id", "assets"],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "assets": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "attachment_level", "attachment_id"],
                "properties": {
                    "type": {"type": "string", "enum": _ASSET_TYPES},
                    "attachment_level": {"type": "string", "enum": _ATTACHMENT_LEVELS},
                    "attachment_id": {"type": "string"},
                    "link_text": {"type": "string", "minLength": 1, "maxLength": 25},
                    "final_urls": {
                        "type": "array",
                        "items": {"type": "string", "format": "uri"},
                        "minItems": 1,
                        "maxItems": 5,
                    },
                    "description1": {"type": "string", "minLength": 1, "maxLength": 35},
                    "description2": {"type": "string", "minLength": 1, "maxLength": 35},
                    "callout_text": {"type": "string", "minLength": 1, "maxLength": 25},
                    "header": {"type": "string", "enum": _STRUCTURED_SNIPPET_HEADERS},
                    "values": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1, "maxLength": 25},
                        "minItems": 3,
                        "maxItems": 10,
                    },
                    "phone_number": {
                        "type": "string",
                        "pattern": r"^[\d\s\(\)\-]{10,20}$",
                    },
                    "promotion_target": {"type": "string", "minLength": 1, "maxLength": 20},
                    "discount_modifier": {"type": "string", "enum": ["NONE", "UP_TO"]},
                    "percent_off": {"type": "number", "minimum": 0.01, "maximum": 100.0},
                    "money_amount_off_brl": {"type": "number", "minimum": 0.01},
                    "start_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                    "end_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
                },
            },
        },
    },
}


_PER_TYPE_REQUIRED = {
    "SITELINK": ["link_text", "final_urls"],
    "CALLOUT": ["callout_text"],
    "STRUCTURED_SNIPPET": ["header", "values"],
    "CALL": ["phone_number"],
    "PROMOTION": ["promotion_target", "discount_modifier", "final_urls"],
}

_PER_TYPE_ALLOWED = {
    "SITELINK": {"link_text", "final_urls", "description1", "description2"},
    "CALLOUT": {"callout_text"},
    "STRUCTURED_SNIPPET": {"header", "values"},
    "CALL": {"phone_number"},
    "PROMOTION": {
        "promotion_target", "discount_modifier", "percent_off",
        "money_amount_off_brl", "final_urls", "start_date", "end_date",
    },
}

_COMMON_KEYS = {"type", "attachment_level", "attachment_id"}


def _err(idx: int, msg: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": f"assets[{idx}]: {msg}",
        "operation": "create_and_link_assets",
    }


def _validate_payload_shape(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Cross-field validation that JSONSchema cannot express (Sprint 3b.19B.1 convention).

    Returns None if valid, error dict if invalid.
    """
    customer_id = payload["customer_id"]

    for idx, a in enumerate(payload["assets"]):
        atype = a["type"]
        alevel = a["attachment_level"]
        aid = a["attachment_id"]

        # Check 1: attachment_id consistency with attachment_level
        if alevel == "CUSTOMER":
            if aid != customer_id:
                return _err(
                    idx,
                    f"attachment_id deve igualar customer_id ('{customer_id}') "
                    f"quando attachment_level=CUSTOMER",
                )
        elif alevel == "CAMPAIGN":
            expected_prefix = f"customers/{customer_id}/campaigns/"
            if not aid.startswith(expected_prefix):
                return _err(
                    idx,
                    f"attachment_id deve ser resource path '{expected_prefix}<id>' "
                    f"quando attachment_level=CAMPAIGN",
                )
        elif alevel == "AD_GROUP":
            expected_prefix = f"customers/{customer_id}/adGroups/"
            if not aid.startswith(expected_prefix):
                return _err(
                    idx,
                    f"attachment_id deve ser resource path '{expected_prefix}<id>' "
                    f"quando attachment_level=AD_GROUP",
                )

        # Check 2: per-type required fields
        for f in _PER_TYPE_REQUIRED[atype]:
            if f not in a:
                return _err(idx, f"campo '{f}' obrigatório quando type={atype}")

        # Check 3: per-type forbidden fields (defense-in-depth)
        for f in set(a.keys()) - _COMMON_KEYS:
            if f not in _PER_TYPE_ALLOWED[atype]:
                return _err(idx, f"campo '{f}' não aplicável a type={atype}")

        # Check 4: SITELINK description1/description2 paired
        if atype == "SITELINK":
            d1 = "description1" in a
            d2 = "description2" in a
            if d1 != d2:
                return _err(
                    idx,
                    "description1 e description2 devem ser ambos presentes ou ambos ausentes",
                )

        # Check 5: PROMOTION discount XOR
        if atype == "PROMOTION":
            has_pct = "percent_off" in a
            has_amt = "money_amount_off_brl" in a
            if has_pct == has_amt:
                return _err(
                    idx,
                    "PROMOTION requer exatamente um de 'percent_off' OU "
                    "'money_amount_off_brl'",
                )

            # Check 6: PROMOTION dates ordering
            if "start_date" in a and "end_date" in a:
                if a["end_date"] < a["start_date"]:
                    return _err(
                        idx,
                        f"end_date ({a['end_date']}) deve ser >= "
                        f"start_date ({a['start_date']})",
                    )

    return None
```

- [ ] **Step 1.4: Run tests — expect all GREEN**

Run: `python -m pytest tests/unit/test_create_and_link_assets.py -v`
Expected: 13 tests PASS

- [ ] **Step 1.5: Commit**

```bash
git add tests/unit/test_create_and_link_assets.py src/mcp/tools/create_and_link_assets.py
git commit -m "feat(create_and_link_assets): schema + _validate_payload_shape (Sprint 3b.25)

Layer 1 + Layer 2 validation only (no tool body yet). 13 unit tests
covering schema + runtime cross-field checks (attachment_id consistency,
per-type required/forbidden fields, SITELINK description pair, PROMOTION
discount XOR, date ordering).

Builder + tool body in next commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Builder Tests (RED) + Implementation

**Files:**
- Create: `tests/unit/test_create_and_link_assets_builder.py`
- Create: `src/google_ads/mutates/assets.py`

### Step 2.1: Create failing builder tests using `make_capture_client`

Create `tests/unit/test_create_and_link_assets_builder.py`:

```python
"""Unit tests for build_create_and_link_assets (Sprint 3b.25).

Builder tests use ProtoFieldCapture (post-Sprint 3b.5 convention) to verify
proto field assignments. MagicMock would mask bugs like A4 (Google override
of negative=True) — see findings-catalog §A4.
"""

from __future__ import annotations

from tests.unit.fixtures.proto_capture import CapturedOp, make_capture_client


def _payload_with_assets(assets):
    return {"customer_id": "1234567890", "assets": assets}


def _sitelink_minimal():
    return {
        "type": "SITELINK",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "link_text": "Sobre",
        "final_urls": ["https://example.com/sobre"],
    }


# ============================================================================
# Per-type happy path (5 tests)
# ============================================================================

def test_builder_sitelink_minimal_sets_link_text_and_final_urls():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([_sitelink_minimal()]))

    assert len(ops) == 2  # 1 asset + 1 link

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.resource_name") == "customers/1234567890/assets/-1"
    assert asset_op.field("asset_operation.create.sitelink_asset.link_text") == "Sobre"
    assert asset_op.field_count("asset_operation.create.final_urls") == 1


def test_builder_sitelink_with_descriptions_sets_both_lines():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()
    asset["description1"] = "Linha 1"
    asset["description2"] = "Linha 2"

    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.sitelink_asset.description1") == "Linha 1"
    assert asset_op.field("asset_operation.create.sitelink_asset.description2") == "Linha 2"


def test_builder_callout_sets_callout_text():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "CALLOUT",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "callout_text": "Atendimento 24h",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.callout_asset.callout_text") == "Atendimento 24h"


def test_builder_structured_snippet_sets_header_and_values():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "STRUCTURED_SNIPPET",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "header": "SERVICE_CATALOG",
        "values": ["SEO", "Mídia Paga", "Branding"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.structured_snippet_asset.header") == "SERVICE_CATALOG"
    assert asset_op.field_count("asset_operation.create.structured_snippet_asset.values") == 3


def test_builder_call_sets_phone_and_country_code_br():
    """V4 invariant assertion — country_code MUST be hardcoded BR."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "CALL",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "phone_number": "(11) 98765-4321",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.call_asset.phone_number") == "(11) 98765-4321"
    assert asset_op.field("asset_operation.create.call_asset.country_code") == "BR"


# ============================================================================
# PROMOTION variants (3 tests)
# ============================================================================

def test_builder_promotion_percent_off_sets_micros_with_10000_factor():
    """F-class regression: percent_off micros formula is value * 10_000 (1M = 100%)."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "UP_TO",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    # 20.0 percent → 200_000 micros (NOT 20_000_000)
    assert asset_op.field("asset_operation.create.promotion_asset.percent_off") == 200_000


def test_builder_promotion_money_amount_off_sets_amount_micros_and_brl():
    """V4 invariant: currency_code hardcoded BRL."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "money_amount_off_brl": 50.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    # 50.0 BRL → 50_000_000 micros (1 BRL = 1M micros)
    assert asset_op.field(
        "asset_operation.create.promotion_asset.money_amount_off.amount_micros"
    ) == 50_000_000
    assert asset_op.field(
        "asset_operation.create.promotion_asset.money_amount_off.currency_code"
    ) == "BRL"


def test_builder_promotion_with_date_range_sets_both():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
        "start_date": "2026-06-01",
        "end_date": "2026-06-30",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    asset_op = ops[0]
    assert asset_op.field("asset_operation.create.promotion_asset.start_date") == "2026-06-01"
    assert asset_op.field("asset_operation.create.promotion_asset.end_date") == "2026-06-30"


# ============================================================================
# Attachment level branching (3 tests)
# ============================================================================

def test_builder_customer_level_emits_customer_asset_op():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()
    asset["attachment_level"] = "CUSTOMER"
    asset["attachment_id"] = "1234567890"

    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    link_op = ops[1]
    assert link_op.field("customer_asset_operation.create.asset") == "customers/1234567890/assets/-1"
    assert link_op.has("campaign_asset_operation") is False
    assert link_op.has("ad_group_asset_operation") is False


def test_builder_campaign_level_emits_campaign_asset_op_with_campaign_path():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()  # already CAMPAIGN level
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    link_op = ops[1]
    assert link_op.field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-1"
    assert link_op.field("campaign_asset_operation.create.campaign") == "customers/1234567890/campaigns/99999"


def test_builder_ad_group_level_emits_ad_group_asset_op_with_ad_group_path():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = _sitelink_minimal()
    asset["attachment_level"] = "AD_GROUP"
    asset["attachment_id"] = "customers/1234567890/adGroups/77777"

    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))

    link_op = ops[1]
    assert link_op.field("ad_group_asset_operation.create.asset") == "customers/1234567890/assets/-1"
    assert link_op.field("ad_group_asset_operation.create.ad_group") == "customers/1234567890/adGroups/77777"


# ============================================================================
# Chained mutation invariants (4 tests)
# ============================================================================

def test_builder_emits_2N_ops_for_N_assets():
    from src.google_ads.mutates.assets import build_create_and_link_assets

    assets = [_sitelink_minimal() for _ in range(3)]
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets(assets))

    assert len(ops) == 6  # 3 assets × 2 ops each


def test_builder_links_temp_resource_names_correctly():
    """Link op's asset field must match the matching CreateAssetOp's resource_name."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    assets = [_sitelink_minimal() for _ in range(2)]
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets(assets))

    # Asset #1 → ops[0], Link #1 → ops[1]
    assert ops[0].field("asset_operation.create.resource_name") == "customers/1234567890/assets/-1"
    assert ops[1].field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-1"

    # Asset #2 → ops[2], Link #2 → ops[3]
    assert ops[2].field("asset_operation.create.resource_name") == "customers/1234567890/assets/-2"
    assert ops[3].field("campaign_asset_operation.create.asset") == "customers/1234567890/assets/-2"


def test_builder_field_type_set_on_link_op():
    """Each link op carries field_type matching the asset type."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    callout_asset = {
        "type": "CALLOUT",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "callout_text": "Atendimento 24h",
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([callout_asset]))

    link_op = ops[1]
    # _BareEnumDict returns the key as-is — so field_type comes back as "CALLOUT"
    assert link_op.field("campaign_asset_operation.create.field_type") == "CALLOUT"


def test_builder_mixed_types_and_levels_in_single_call():
    """V4 onboarding workflow — mixed types and levels in one batch."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    sitelink_camp = _sitelink_minimal()  # CAMPAIGN
    callout_cust = {
        "type": "CALLOUT",
        "attachment_level": "CUSTOMER",
        "attachment_id": "1234567890",
        "callout_text": "Atendimento 24h",
    }
    call_camp = {
        "type": "CALL",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "phone_number": "(11) 98765-4321",
    }

    client = make_capture_client()
    ops = build_create_and_link_assets(
        client, "1234567890", _payload_with_assets([sitelink_camp, callout_cust, call_camp])
    )

    assert len(ops) == 6
    # Op 1 = SITELINK CAMPAIGN link
    assert ops[1].has("campaign_asset_operation") is True
    # Op 3 = CALLOUT CUSTOMER link
    assert ops[3].has("customer_asset_operation") is True
    # Op 5 = CALL CAMPAIGN link
    assert ops[5].has("campaign_asset_operation") is True


# ============================================================================
# V4 invariant explicit assertions (3 tests)
# ============================================================================

def test_builder_call_always_sets_country_code_br():
    """Regardless of phone format, country_code MUST be BR (V4 invariant)."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    for phone in ["1198765432", "(11) 98765-4321", "11 9 8765 4321"]:
        asset = {
            "type": "CALL",
            "attachment_level": "CAMPAIGN",
            "attachment_id": "customers/1234567890/campaigns/99999",
            "phone_number": phone,
        }
        client = make_capture_client()
        ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))
        assert ops[0].field("asset_operation.create.call_asset.country_code") == "BR"


def test_builder_promotion_always_sets_language_code_pt():
    """V4 invariant: language_code hardcoded pt regardless of payload."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "percent_off": 20.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))
    assert ops[0].field("asset_operation.create.promotion_asset.language_code") == "pt"


def test_builder_promotion_money_amount_off_always_brl():
    """V4 invariant: BRL currency hardcoded."""
    from src.google_ads.mutates.assets import build_create_and_link_assets

    asset = {
        "type": "PROMOTION",
        "attachment_level": "CAMPAIGN",
        "attachment_id": "customers/1234567890/campaigns/99999",
        "promotion_target": "Verão 2026",
        "discount_modifier": "NONE",
        "money_amount_off_brl": 100.0,
        "final_urls": ["https://example.com/promo"],
    }
    client = make_capture_client()
    ops = build_create_and_link_assets(client, "1234567890", _payload_with_assets([asset]))
    assert ops[0].field(
        "asset_operation.create.promotion_asset.money_amount_off.currency_code"
    ) == "BRL"
```

- [ ] **Step 2.2: Run tests — expect ImportError**

Run: `python -m pytest tests/unit/test_create_and_link_assets_builder.py -v`
Expected: `ModuleNotFoundError: No module named 'src.google_ads.mutates.assets'`

- [ ] **Step 2.3: Implement builder in `src/google_ads/mutates/assets.py`**

Create `src/google_ads/mutates/assets.py`:

```python
"""Mutate builder for create_and_link_assets (Sprint 3b.25).

Chained mutation pattern (Sprint 3b.19B established + Sprint 3b.24 expanded):
emits 2N ops in single MutateGoogleAdsRequest:
- N asset_operation.create (temp resource names: customers/{cid}/assets/-{i})
- N {customer|campaign|ad_group}_asset_operation.create (refs temp asset paths)

Atomic: all 2N ops succeed or all fail. Google substitutes real IDs at apply
time. F13 (Sprint 3b.15) auto-extracts 2N resource_names from response.

V4 invariants hardcoded (no schema fields):
- CallAsset.country_code = "BR"
- PromotionAsset.language_code = "pt"
- PromotionAsset.money_amount_off.currency_code = "BRL"

Proto field names verified via context7 against /websites/developers_google_google-ads_api
on 2026-05-18:
- SitelinkAsset: link_text, description1, description2 (NOT description_line_1)
- CallAsset: phone_number (raw format), country_code (2-letter ISO)
- CalloutAsset: callout_text
- StructuredSnippetAsset: header (enum), values (3-10 strings)
- PromotionAsset: percent_off in micros (1_000_000 = 100%; multiply by 10_000),
  money_amount_off.{amount_micros, currency_code} (1 BRL = 1_000_000 micros)
- final_urls is Asset-level (parent), NOT inside sub-message
"""

from __future__ import annotations

from typing import Any

from src.google_ads.mutates._common import register_builder


@register_builder("create_and_link_assets")
def build_create_and_link_assets(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """Build 2N chained operations for create_and_link_assets (Sprint 3b.25).

    payload schema (post-_validate_payload_shape):
      assets: list of {type, attachment_level, attachment_id, ...per-type fields}

    Returns list[MutateOperation] in order:
      Op[0]   asset_operation.create     (Asset #1, temp customers/{cid}/assets/-1)
      Op[1]   {C|Camp|AG}_asset_operation.create (Link #1, refs Op[0])
      Op[2]   asset_operation.create     (Asset #2, temp .../assets/-2)
      Op[3]   ...
      ...

    Chained mutation guarantee: atomic. Temp negative IDs replaced by Google.
    """
    operations: list[Any] = []
    field_type_enum = client.enums.AssetFieldTypeEnum
    discount_mod_enum = client.enums.PromotionExtensionDiscountModifierEnum

    for i, a in enumerate(payload["assets"], start=1):
        temp_asset_path = f"customers/{customer_id}/assets/-{i}"

        # ----- Asset create op -----
        asset_op_wrap = client.get_type("MutateOperation")
        asset_op = asset_op_wrap.asset_operation
        asset = asset_op.create
        asset.resource_name = temp_asset_path

        atype = a["type"]
        if atype == "SITELINK":
            asset.sitelink_asset.link_text = a["link_text"]
            if "description1" in a:
                asset.sitelink_asset.description1 = a["description1"]
                asset.sitelink_asset.description2 = a["description2"]
            for url in a["final_urls"]:
                asset.final_urls.append(url)

        elif atype == "CALLOUT":
            asset.callout_asset.callout_text = a["callout_text"]

        elif atype == "STRUCTURED_SNIPPET":
            asset.structured_snippet_asset.header = a["header"]
            for v in a["values"]:
                asset.structured_snippet_asset.values.append(v)

        elif atype == "CALL":
            asset.call_asset.phone_number = a["phone_number"]
            asset.call_asset.country_code = "BR"  # V4 invariant

        elif atype == "PROMOTION":
            promo = asset.promotion_asset
            promo.promotion_target = a["promotion_target"]
            promo.discount_modifier = discount_mod_enum[a["discount_modifier"]]
            if "percent_off" in a:
                # 1_000_000 micros = 100% per Google spec; multiply by 10_000
                promo.percent_off = int(a["percent_off"] * 10_000)
            else:
                # 1 BRL = 1_000_000 micros
                promo.money_amount_off.amount_micros = int(a["money_amount_off_brl"] * 1_000_000)
                promo.money_amount_off.currency_code = "BRL"  # V4 invariant
            promo.language_code = "pt"  # V4 invariant
            for url in a["final_urls"]:
                asset.final_urls.append(url)
            if "start_date" in a:
                promo.start_date = a["start_date"]
            if "end_date" in a:
                promo.end_date = a["end_date"]

        operations.append(asset_op_wrap)

        # ----- Link op (branches on attachment_level) -----
        link_op_wrap = client.get_type("MutateOperation")
        alevel = a["attachment_level"]
        ft = field_type_enum[atype]  # type-to-AssetFieldType is 1:1 v0

        if alevel == "CUSTOMER":
            ca = link_op_wrap.customer_asset_operation.create
            ca.asset = temp_asset_path
            ca.field_type = ft

        elif alevel == "CAMPAIGN":
            cm = link_op_wrap.campaign_asset_operation.create
            cm.asset = temp_asset_path
            cm.campaign = a["attachment_id"]
            cm.field_type = ft

        elif alevel == "AD_GROUP":
            ag = link_op_wrap.ad_group_asset_operation.create
            ag.asset = temp_asset_path
            ag.ad_group = a["attachment_id"]
            ag.field_type = ft

        operations.append(link_op_wrap)

    return operations
```

- [ ] **Step 2.4: Run builder tests — expect all GREEN**

Run: `python -m pytest tests/unit/test_create_and_link_assets_builder.py -v`
Expected: 18 tests PASS

- [ ] **Step 2.5: Commit**

```bash
git add tests/unit/test_create_and_link_assets_builder.py src/google_ads/mutates/assets.py
git commit -m "feat(create_and_link_assets): builder + 18 builder tests (Sprint 3b.25)

Builder emits 2N chained ops (N CreateAssetOp + N {customer|campaign|ad_group}AssetOp).
Per-type proto assignment for 5 asset types × 3 attachment levels = 15 combos.
V4 invariants hardcoded (country=BR, language=pt, currency=BRL).

Proto field names verified via context7 (description1/description2, raw
phone format, percent_off micros formula value * 10_000).

Tests use make_capture_client (post-Sprint 3b.5 convention) — MagicMock
masks bugs like A4. 18 tests covering per-type happy paths, PROMOTION
variants, attachment level branching, chained mutation invariants, and
V4 invariant assertions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Tool Body Finalize (dry_run flow, audit summary, register_tool)

**Files:**
- Modify: `src/mcp/tools/create_and_link_assets.py` (extend skeleton from Task 1)
- Modify: `tests/unit/test_create_and_link_assets.py` (add 2 dry-run tests)
- Modify: `tests/unit/test_tools_schemas.py` (+1 line: allowlist)

### Step 3.1: Add dry-run flow tests

Append to `tests/unit/test_create_and_link_assets.py`:

```python
# ============================================================================
# Dry-run flow tests (Layer 1 + Layer 2 + audit prep)
# ============================================================================

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_tool_returns_dry_run_with_token_and_summary():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        with patch(
            "src.mcp.tools.create_and_link_assets.create_pending",
            AsyncMock(return_value="test-token-123"),
        ), patch(
            "src.mcp.tools.create_and_link_assets.connection.get_pool"
        ) as mock_pool:
            mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
                return_value=AsyncMock()
            )
            mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

            args = {
                "customer_id": "1234567890",
                "assets": [_valid_sitelink_asset()],
            }
            result = await create_and_link_assets(args)

        assert result["status"] == "dry_run"
        assert result["operation"] == "create_and_link_assets"
        assert result["confirmation_token"] == "test-token-123"
        assert "summary" in result
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_summary_includes_counts_by_type_and_level():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        with patch(
            "src.mcp.tools.create_and_link_assets.create_pending",
            AsyncMock(return_value="test-token-456"),
        ), patch(
            "src.mcp.tools.create_and_link_assets.connection.get_pool"
        ) as mock_pool:
            mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
                return_value=AsyncMock()
            )
            mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

            callout_customer = {
                "type": "CALLOUT",
                "attachment_level": "CUSTOMER",
                "attachment_id": "1234567890",
                "callout_text": "Atendimento 24h",
            }
            args = {
                "customer_id": "1234567890",
                "assets": [
                    _valid_sitelink_asset(),
                    _valid_sitelink_asset(),
                    callout_customer,
                ],
            }
            result = await create_and_link_assets(args)

        summary = result["summary"]
        assert summary["asset_count"] == 3
        assert summary["by_type"] == {"SITELINK": 2, "CALLOUT": 1}
        assert summary["by_level"] == {"CAMPAIGN": 2, "CUSTOMER": 1}
    finally:
        clear_current()
```

- [ ] **Step 3.2: Run new tests — expect FAIL (no tool body yet)**

Run: `python -m pytest tests/unit/test_create_and_link_assets.py::test_tool_returns_dry_run_with_token_and_summary -v`
Expected: `AttributeError: module 'src.mcp.tools.create_and_link_assets' has no attribute 'create_and_link_assets'`

- [ ] **Step 3.3: Extend tool body in `src/mcp/tools/create_and_link_assets.py`**

Append to `src/mcp/tools/create_and_link_assets.py` (after `_validate_payload_shape`):

```python
from src.db import connection
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool


def _build_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe summary: counts only, NO copy text per spec §3.6.

    Returns dict with asset_count, by_type, by_level, attachment_ids_distinct,
    total_ops_chained.
    """
    by_type: dict[str, int] = {}
    by_level: dict[str, int] = {}
    distinct_ids: set[str] = set()
    for a in payload["assets"]:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1
        by_level[a["attachment_level"]] = by_level.get(a["attachment_level"], 0) + 1
        distinct_ids.add(a["attachment_id"])
    n = len(payload["assets"])
    return {
        "asset_count": n,
        "by_type": by_type,
        "by_level": by_level,
        "attachment_ids_distinct": len(distinct_ids),
        "total_ops_chained": 2 * n,
    }


@register_tool(
    name="create_and_link_assets",
    description=(
        "Cria N text-assets novos (1-20 por call) e linka cada um ao escopo "
        "solicitado (CUSTOMER/CAMPAIGN/AD_GROUP) em chained mutation atomic. "
        "Always-CONFIRM. Tipos suportados v0: SITELINK, CALLOUT, "
        "STRUCTURED_SNIPPET, CALL, PROMOTION (text-extension family, "
        "SEARCH-relevant). V4 invariants hardcoded: country_code=BR para CALL, "
        "language_code=pt para PROMOTION, currency_code=BRL para "
        "PROMOTION.money_amount_off. Cada item de `assets` carrega type + "
        "attachment_level + attachment_id + payload type-specific. Builder usa "
        "chained mutation (N CreateAssetOp + N Create{Customer,Campaign,"
        "AdGroup}AssetOp em single MutateGoogleAdsRequest com temp resource_names). "
        "F13 auto-retorna 2N resource_names. attachment_id formato: customer_id "
        "(CUSTOMER), 'customers/X/campaigns/Y' (CAMPAIGN), 'customers/X/adGroups/Y' "
        "(AD_GROUP). PROMOTION requer exatamente um de percent_off OU "
        "money_amount_off_brl."
    ),
    input_schema=_SCHEMA,
)
async def create_and_link_assets(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]

    # Runtime payload validation (Sprint 3b.19B.1 pattern)
    shape_error = _validate_payload_shape(args)
    if shape_error is not None:
        return shape_error

    summary = _build_summary(args)
    target_count = summary["total_ops_chained"]

    risk = classify(
        operation="create_and_link_assets",
        params={"target_count": target_count},
    )

    blast_summary = (
        f"Criar {summary['asset_count']} asset(s) text-extension + "
        f"{summary['asset_count']} link(s). Tipos: "
        f"{', '.join(f'{k}:{v}' for k, v in summary['by_type'].items())}. "
        f"Níveis: {', '.join(f'{k}:{v}' for k, v in summary['by_level'].items())}."
    )

    payload = {
        **args,
        "__target_count__": target_count,
        "__params_summary__": summary,
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="create_and_link_assets",
            payload=payload,
            blast_summary=blast_summary,
        )

    return {
        "status": "dry_run",
        "operation": "create_and_link_assets",
        "customer_id": customer_id,
        "blast_summary": blast_summary,
        "summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
```

- [ ] **Step 3.4: Add `create_and_link_assets` to test_tools_schemas allowlist**

Find the expected tool name allowlist in `tests/unit/test_tools_schemas.py` and add `"create_and_link_assets"` to the set.

Run first to find the line:

```bash
python -m pytest tests/unit/test_tools_schemas.py -v 2>&1 | head -30
```

If `test_expected_tools_registered` fails because `create_and_link_assets` is unexpected, find the `_EXPECTED_TOOLS` (or similar) set and add the tool name.

Edit the file to include the new tool in the allowlist set/frozenset.

- [ ] **Step 3.5: Run all unit tests**

Run: `python -m pytest tests/unit/test_create_and_link_assets.py tests/unit/test_create_and_link_assets_builder.py tests/unit/test_tools_schemas.py -v`
Expected: All PASS (15 tool tests + 18 builder tests + tool_schemas regression tests)

- [ ] **Step 3.6: Commit**

```bash
git add src/mcp/tools/create_and_link_assets.py tests/unit/test_create_and_link_assets.py tests/unit/test_tools_schemas.py
git commit -m "feat(create_and_link_assets): tool body + dry-run flow + register_tool (Sprint 3b.25)

Adds full tool body with dry-run flow per Sprint 3b.24 pattern:
- _build_summary returns audit-safe counts (no PII content)
- create_pending stores token + payload with __target_count__ + __params_summary__
- Returns dry_run preview with summary, token, blast_summary

Tool registered as 48th MCP tool. Allowlist updated.

2 new dry-run flow tests (15 → 17 total in test_create_and_link_assets.py).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Integration Tests

**Files:**
- Create: `tests/integration/test_create_and_link_assets.py`

### Step 4.1: Create integration test file

Create `tests/integration/test_create_and_link_assets.py`:

```python
"""Integration test: create_and_link_assets full cycle (Sprint 3b.25).

Tests dry_run → apply_change → builder runs chained mutation → applied
response with 2N resource_names. F13 cross-cutting tested em chained
mutation case (paralleled to Sprint 3b.19B 3-resource test, but 2N here).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
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


@pytest.fixture
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


def _client_with_chained_response_for_n_assets(n: int) -> MagicMock:
    """Mock SDK client returning 2N mutate_operation_responses (N asset + N link)."""
    client = MagicMock()

    op_responses = []
    for i in range(n):
        # Asset result
        asset_resp = MagicMock()
        asset_proto = MagicMock()
        asset_proto.resource_name = f"customers/1234567890/assets/{1000 + i}"
        asset_resp._pb.WhichOneof = MagicMock(return_value="asset_result")
        setattr(asset_resp._pb, "asset_result", asset_proto)
        op_responses.append(asset_resp)

        # Link result (campaign_asset_result for CAMPAIGN-level test)
        link_resp = MagicMock()
        link_proto = MagicMock()
        link_proto.resource_name = (
            f"customers/1234567890/campaignAssets/99999~{1000 + i}~SITELINK"
        )
        link_resp._pb.WhichOneof = MagicMock(return_value="campaign_asset_result")
        setattr(link_resp._pb, "campaign_asset_result", link_proto)
        op_responses.append(link_resp)

    response = MagicMock()
    response.mutate_operation_responses = op_responses
    response.partial_failure_error.code = 0
    response.partial_failure_error.details = []

    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=fake_service)

    failure_type_stub = MagicMock()
    failure_type_stub._meta.pb = lambda: MagicMock(errors=[])

    def get_type(name):
        if name == "GoogleAdsFailure":
            return failure_type_stub
        return MagicMock(
            mutate_operations=[],
            partial_failure_mode=MagicMock(),
        )

    client.get_type = MagicMock(side_effect=get_type)
    client.enums.PartialFailureModeEnum.PARTIAL_FAILURE = "PARTIAL_FAILURE"
    return client


async def test_create_and_link_assets_dry_run_emits_token_and_audit_pending(
    db, session_ctx
) -> None:
    """Step 1 only: tool returns dry_run with token; no apply yet."""
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    args = {
        "customer_id": "1234567890",
        "assets": [
            {
                "type": "SITELINK",
                "attachment_level": "CAMPAIGN",
                "attachment_id": "customers/1234567890/campaigns/99999",
                "link_text": "Sobre",
                "final_urls": ["https://example.com/sobre"],
            },
        ],
    }

    result = await create_and_link_assets(args)

    assert result["status"] == "dry_run"
    assert result["operation"] == "create_and_link_assets"
    assert result["confirmation_token"]
    assert result["summary"]["asset_count"] == 1
    assert result["summary"]["total_ops_chained"] == 2

    # Verify pending state in DB (no audit_log row yet — that's apply step)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation_type, customer_id FROM pending_mutations "
            "WHERE confirmation_token = $1",
            result["confirmation_token"],
        )
    assert len(rows) == 1
    assert rows[0]["operation_type"] == "create_and_link_assets"
    assert rows[0]["customer_id"] == "1234567890"


async def test_create_and_link_assets_full_cycle_returns_2N_resource_names_and_audit_applied(
    db, session_ctx
) -> None:
    """Full cycle: dry_run → apply_change → 2N resource_names + audit_log applied."""
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.create_and_link_assets import create_and_link_assets

    N = 3
    fake_client = _client_with_chained_response_for_n_assets(N)

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock() for _ in range(2 * N)],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-create-assets",
        ),
    ):
        # Step 1: dry_run
        assets = [
            {
                "type": "SITELINK",
                "attachment_level": "CAMPAIGN",
                "attachment_id": "customers/1234567890/campaigns/99999",
                "link_text": f"Page {i}",
                "final_urls": [f"https://example.com/{i}"],
            }
            for i in range(N)
        ]
        dry_run_result = await create_and_link_assets({
            "customer_id": "1234567890",
            "assets": assets,
        })

        assert dry_run_result["status"] == "dry_run"
        token = dry_run_result["confirmation_token"]
        assert token

        # Step 2: apply_change
        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "create_and_link_assets"
    assert apply_result["applied_count"] == 2 * N  # 2N ops
    assert apply_result["google_request_id"] == "req-create-assets"

    # F13 cross-cutting: 2N resource_names, ordering [asset0, link0, asset1, link1, ...]
    assert "resource_names" in apply_result
    assert len(apply_result["resource_names"]) == 2 * N
    for i in range(N):
        assert apply_result["resource_names"][2 * i] == f"customers/1234567890/assets/{1000 + i}"
        assert (
            apply_result["resource_names"][2 * i + 1]
            == f"customers/1234567890/campaignAssets/99999~{1000 + i}~SITELINK"
        )

    # audit_log: target_count = 2N, custom params_summary
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, params_summary, google_request_id "
            "FROM audit_log WHERE operation = 'create_and_link_assets'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 2 * N
    assert rows[0]["google_request_id"] == "req-create-assets"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d["asset_count"] == N
    assert summary_d["by_type"] == {"SITELINK": N}
    assert summary_d["by_level"] == {"CAMPAIGN": N}
    assert summary_d["total_ops_chained"] == 2 * N
```

- [ ] **Step 4.2: Run integration tests (requires Docker)**

Run: `python -m pytest tests/integration/test_create_and_link_assets.py -v -m integration`
Expected: 2 tests PASS (testcontainers spins up Postgres)

If Docker unavailable, defer to CI as catch-all (CLAUDE.md "Don't push without check_pre_push.py first" exception — pre-flight tests can ship and rely on CI integration sweep).

- [ ] **Step 4.3: Commit**

```bash
git add tests/integration/test_create_and_link_assets.py
git commit -m "test(create_and_link_assets): integration tests dry_run + full cycle (Sprint 3b.25)

2 tests mirroring Sprint 3b.24 pattern:
- dry_run emits token, pending_mutations row created, no audit_log yet
- full cycle: apply_change consumes token → run_mutation → 2N resource_names
  extracted via F13 cross-cutting + audit_log row applied with custom
  params_summary (asset_count, by_type, by_level, total_ops_chained)

Verifies F13 resource_names ordering: [asset0, link0, asset1, link1, ...]
matching the 2N mutate_operation_responses ordering (asset_result + N
campaign_asset_result pairs).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Smoke Runbook Scaffold + CLAUDE.md Sprint Row

**Files:**
- Create: `docs/operacao/phase-3b-25-bootstrap.md`
- Modify: `CLAUDE.md`

### Step 5.1: Create smoke runbook scaffold

Create `docs/operacao/phase-3b-25-bootstrap.md`:

````markdown
# Phase 3b.25 — manual smoke runbook (`create_and_link_assets`)

**Purpose:** Validar Sprint 3b.25 — sexto create-pattern do MCP, foundation pra onboarding completo V4 via Claude/Codex (text-extensions).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox — campaigns PAUSED do Sprint 3b.24 anexamos assets sem serving impact)

**Spec:** `docs/superpowers/specs/2026-05-18-sprint-3b-25-create-and-link-assets-design.md`
**Plan:** `docs/superpowers/plans/2026-05-18-sprint-3b-25-create-and-link-assets.md`

**Sprint 3b.19A.1 lesson aplicado:** T3, T6, T7 explicit per-value/per-level empirical probe.

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Tool `create_and_link_assets` visível em MCP tool list (count 47 → 48)
- [ ] F28 reproducer: gestor pode precisar restart Claude Code session pro schema cache propagar

Production revision: `<PREENCHER pós-deploy>`.

## Reference: Nutry sandbox campaigns (from Sprint 3b.24)

Use the 5 PAUSED campaigns criadas no Sprint 3b.24 smoke:
- T1: `customers/1163862076/campaigns/<id_t1>`
- T2: `customers/1163862076/campaigns/<id_t2>`
- T4: `customers/1163862076/campaigns/<id_t4>`
- T5: `customers/1163862076/campaigns/<id_t5>`
- T6: `customers/1163862076/campaigns/<id_t6>`

Confirm via GAQL pré-smoke:

```
SELECT campaign.id, campaign.name, campaign.status FROM campaign
WHERE campaign.name LIKE '[3b.24 smoke]%'
```

Selecionar 1 campaign + 1 ad_group pra T2/T3/T9 (CAMPAIGN/AD_GROUP probes).

## Test T1 — SITELINK CUSTOMER (account-wide)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "SITELINK",
    "attachment_level": "CUSTOMER",
    "attachment_id": "1163862076",
    "link_text": "Sobre nós",
    "final_urls": ["https://nutry.com.br/sobre"]
  }]
)
```

Expected:
- [ ] dry_run com confirmation_token + summary.asset_count=1, by_type={SITELINK:1}, by_level={CUSTOMER:1}
- [ ] apply → applied_count=2, resource_names array com 2 paths (1 asset + 1 customer_asset)
- [ ] GAQL verify: `SELECT asset.id, asset.sitelink_asset.link_text, customer_asset.field_type FROM customer_asset WHERE asset.id = <id from resource_names[0]>`

**Result:** ⬜ pending

## Test T2 — SITELINK CAMPAIGN (most common V4 workflow)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "Serviços", "final_urls": ["https://nutry.com.br/servicos"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "Contato", "final_urls": ["https://nutry.com.br/contato"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "Blog", "final_urls": ["https://nutry.com.br/blog"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T2>",
     "link_text": "FAQ", "final_urls": ["https://nutry.com.br/faq"]}
  ]
)
```

Expected:
- [ ] dry_run summary.asset_count=4, by_type={SITELINK:4}, by_level={CAMPAIGN:4}
- [ ] apply → applied_count=8, resource_names array com 8 paths

**Result:** ⬜ pending

## Test T3 — SITELINK AD_GROUP (rare granular probe)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "SITELINK",
    "attachment_level": "AD_GROUP",
    "attachment_id": "<ad_group T2>",
    "link_text": "Promoção",
    "final_urls": ["https://nutry.com.br/promo"]
  }]
)
```

Expected:
- [ ] Either: apply → applied_count=2 (Google supports AD_GROUP for SITELINK)
- [ ] OR: Google rejects with INVALID_ASSET_LEVEL or similar — **document as F-class finding** if rejected

**Result:** ⬜ pending

## Test T4 — CALLOUT CUSTOMER (brand callouts)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Atendimento 24h"},
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Frete grátis"},
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Entrega 7 dias"}
  ]
)
```

Expected:
- [ ] dry_run summary.by_type={CALLOUT:3}, by_level={CUSTOMER:3}
- [ ] apply → applied_count=6

**Result:** ⬜ pending

## Test T5 — CALLOUT CAMPAIGN

Similar a T4 mas attachment_level=CAMPAIGN. 2 assets.

**Result:** ⬜ pending

## Test T6 — STRUCTURED_SNIPPET CUSTOMER (header=SERVICE_CATALOG)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "STRUCTURED_SNIPPET",
    "attachment_level": "CUSTOMER",
    "attachment_id": "1163862076",
    "header": "SERVICE_CATALOG",
    "values": ["Vitaminas", "Suplementos", "Probióticos"]
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] GAQL verify: `SELECT asset.structured_snippet_asset.header, asset.structured_snippet_asset.values FROM customer_asset WHERE asset.id = <id>`

**Result:** ⬜ pending

## Test T7 — STRUCTURED_SNIPPET CAMPAIGN (header=BRANDS)

Similar a T6 mas header=BRANDS, attachment_level=CAMPAIGN.

**Result:** ⬜ pending

## Test T8 — CALL CAMPAIGN (V4 lead-gen phone)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "CALL",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T4>",
    "phone_number": "(11) 98765-4321"
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] GAQL verify country_code=BR enforced (V4 invariant):
  `SELECT asset.call_asset.country_code, asset.call_asset.phone_number FROM campaign_asset WHERE asset.id = <id>`

**Result:** ⬜ pending

## Test T9 — CALL AD_GROUP (granular probe)

Similar a T8 mas attachment_level=AD_GROUP. Same as T3 — may reject.

**Result:** ⬜ pending

## Test T10 — PROMOTION percent_off=20.0 (critical: micros formula)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "PROMOTION",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T5>",
    "promotion_target": "Verão 2026",
    "discount_modifier": "UP_TO",
    "percent_off": 20.0,
    "final_urls": ["https://nutry.com.br/promo"]
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] **GAQL critical assertion:** `SELECT asset.promotion_asset.percent_off FROM campaign_asset WHERE asset.id = <id>` → **200_000** (NOT 20_000_000 — R6 risk verified)

**Result:** ⬜ pending

## Test T11 — PROMOTION money_amount_off_brl=50.0

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "PROMOTION",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T5>",
    "promotion_target": "Verão 2026",
    "discount_modifier": "NONE",
    "money_amount_off_brl": 50.0,
    "final_urls": ["https://nutry.com.br/promo"]
  }]
)
```

Expected:
- [ ] apply → applied_count=2
- [ ] GAQL: `SELECT asset.promotion_asset.money_amount_off.amount_micros, asset.promotion_asset.money_amount_off.currency_code` → 50_000_000 + BRL

**Result:** ⬜ pending

## Test T12 — Mixed batch (V4 onboarding workflow)

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    # 4 sitelinks CAMPAIGN
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L1", "final_urls": ["https://nutry.com.br/l1"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L2", "final_urls": ["https://nutry.com.br/l2"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L3", "final_urls": ["https://nutry.com.br/l3"]},
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": "L4", "final_urls": ["https://nutry.com.br/l4"]},
    # 2 callouts CUSTOMER
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Atendimento PT-BR"},
    {"type": "CALLOUT", "attachment_level": "CUSTOMER", "attachment_id": "1163862076",
     "callout_text": "Frete BR"},
    # 1 call CAMPAIGN
    {"type": "CALL", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "phone_number": "(11) 98765-4321"}
  ]
)
```

Expected:
- [ ] dry_run summary.asset_count=7, by_type={SITELINK:4, CALLOUT:2, CALL:1}, by_level={CAMPAIGN:5, CUSTOMER:2}
- [ ] apply → applied_count=14, resource_names array com 14 paths
- [ ] Response size < MCP cap (~36k chars projetado, bem abaixo de 100k cap)

**Result:** ⬜ pending

## Test T13 — Schema regression: SITELINK + callout_text rejected

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "SITELINK",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T1>",
    "link_text": "Test",
    "final_urls": ["https://example.com"],
    "callout_text": "BAD — should reject"
  }]
)
```

Expected:
- [ ] Tool returns status=error pre-Google call: "campo 'callout_text' não aplicável a type=SITELINK"

**Result:** ⬜ pending

## Test T14 — Schema regression: PROMOTION sem desconto rejected

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[{
    "type": "PROMOTION",
    "attachment_level": "CAMPAIGN",
    "attachment_id": "<campaign T5>",
    "promotion_target": "Verão",
    "discount_modifier": "NONE",
    "final_urls": ["https://example.com"]
    # Missing percent_off AND money_amount_off_brl
  }]
)
```

Expected:
- [ ] Tool returns status=error: "PROMOTION requer exatamente um de 'percent_off' OU 'money_amount_off_brl'"

**Result:** ⬜ pending

## Test T15 — F22-equivalent: 20 assets em single batch (response cap test)

20 SITELINKs CAMPAIGN attached a 1 campaign. Verify response < MCP cap.

```
create_and_link_assets(
  customer_id="1163862076",
  assets=[
    {"type": "SITELINK", "attachment_level": "CAMPAIGN", "attachment_id": "<campaign T6>",
     "link_text": f"Link {i}", "final_urls": [f"https://nutry.com.br/l{i}"]}
    for i in range(1, 21)
  ]
)
```

Expected:
- [ ] dry_run summary.asset_count=20, by_type={SITELINK:20}
- [ ] apply → applied_count=40, resource_names array com 40 paths
- [ ] Response chars total < 100k (projetado ~36k)

**Result:** ⬜ pending

## Cleanup post-smoke

Assets ficam paused (campaigns Sprint 3b.24 já PAUSED, zero serving impact). Spawn-task pra Sprint 3b.28 (`remove_*` bundle) cleanup.

## Findings discovered

(Preencher pós-smoke se findings reais surgirem — F38+ candidates documented em findings-catalog.md)

| # | Finding | Severity | Documented | Fix |
|---|---|---|---|---|
| F38 | (pending) | — | — | — |

## Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Production /health 200
- [ ] 12+/15 tests PASS (T3/T9 podem ser documentados findings sem blocker)
- [ ] CLAUDE.md sprint row added
- [ ] findings-catalog.md updated se F38+ surgir
- [ ] Tool count 47 → 48 confirmed in production tool list

Signed-off: ⬜ pending
````

- [ ] **Step 5.2: Add Sprint 3b.25 row to CLAUDE.md**

Locate the sprint table in `CLAUDE.md` (in "Current state" → "Shipped + in production" section). After the Sprint 3b.24 row, add:

```markdown
| Sprint 3b.25 — `create_and_link_assets` (sexto create-pattern) | 🟡 code-complete; smoke pending | Spec: [`2026-05-18-sprint-3b-25-create-and-link-assets-design.md`](docs/superpowers/specs/2026-05-18-sprint-3b-25-create-and-link-assets-design.md); Plan: [`2026-05-18-sprint-3b-25-create-and-link-assets.md`](docs/superpowers/plans/2026-05-18-sprint-3b-25-create-and-link-assets.md). **1 new MCP tool (count 47 → 48):** primeiro asset/extension create do MCP V4, fecha loop de onboarding completo (Sprint 3b.24 `create_campaign` foundation). Always-CONFIRM. Schema: lista `assets[]` com 5 types (SITELINK, CALLOUT, STRUCTURED_SNIPPET, CALL, PROMOTION) × 3 attachment levels (CUSTOMER, CAMPAIGN, AD_GROUP) × 1-20 batch. **V4 invariants hardcoded:** country_code=BR (CALL), language_code=pt (PROMOTION), currency_code=BRL (PROMOTION.money_amount_off). **Architecture:** chained mutation 2N ops em single MutateGoogleAdsRequest (1 CreateAsset + 1 {customer|campaign|ad_group}_asset link op per asset). Temp resource_names `customers/{cid}/assets/-{i}`. Runtime payload validation via `_validate_payload_shape` (6 cross-field checks: attachment_id consistency, per-type required/forbidden, description1/2 paired, PROMOTION XOR, date ordering). **Proto field names validados via context7** pre-implementação: `description1`/`description2` (NOT `description_line_1`/`description_line_2`), raw phone format (NOT E.164), `percent_off` micros formula `value * 10_000` (1M = 100%). ~17 unit tests (tool) + ~18 builder tests (proto_capture) + 2 integration. Pre-flight: nenhuma async (trust Google errors, Sprint 3b.19A.1 F14 lesson). Smoke: 15 tests Nutry sandbox (T3/T9 AD_GROUP probes podem ser expected F-finding). |
```

Also bump in same edit:
- **`47 MCP tools`** → **`48 MCP tools`** in summary line (currently after the sprint table)
- **`Last updated:`** value → **`2026-05-18`**

- [ ] **Step 5.3: Commit**

```bash
git add docs/operacao/phase-3b-25-bootstrap.md CLAUDE.md
git commit -m "docs: Sprint 3b.25 smoke runbook scaffold + CLAUDE.md sprint row

15 smoke tests (T1-T15) scaffolded for Nutry sandbox execution:
- T1-T2 SITELINK CUSTOMER/CAMPAIGN (happy paths)
- T3 SITELINK AD_GROUP (rare granular probe — may F-class)
- T4-T5 CALLOUT CUSTOMER/CAMPAIGN
- T6-T7 STRUCTURED_SNIPPET CUSTOMER/CAMPAIGN (2 headers probed)
- T8-T9 CALL CAMPAIGN/AD_GROUP (T9 may F-class)
- T10-T11 PROMOTION percent_off/money_amount_off (T10 critical: assert micros = 200_000 NOT 20_000_000)
- T12 mixed batch (V4 onboarding workflow, 7 assets)
- T13-T14 schema regression guards
- T15 F22-equivalent: 20 assets batch (response cap test)

Sprint 3b.25 row added to CLAUDE.md sprint table; tool count 47 → 48.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Pre-Push Verification + Push

**Files:** No file changes. Verification only.

### Step 6.1: Run pre-push gate

Run: `python scripts/check_pre_push.py`
Expected output:

```
==> [1/5] ruff check
OK: ruff check
==> [2/5] ruff format check
OK: ruff format check
==> [3/5] mypy
OK: mypy
==> [4/5] pytest unit
OK: pytest unit
==> [5/5] pytest non-DB integration
OK: pytest non-DB integration
All pre-push checks passed (5 steps in ~30s).
```

- [ ] **Step 6.2: If any step fails, fix and re-run**

Common issues:
- `ruff format`: run `ruff format src/mcp/tools/create_and_link_assets.py src/google_ads/mutates/assets.py tests/unit/test_create_and_link_assets*.py tests/integration/test_create_and_link_assets.py`
- `mypy`: add missing type annotations (Sprint 3b.24 saw mypy strict mode requires explicit `-> dict[str, Any]` on async tool, `-> dict[str, Any] | None` on validator)
- `pytest unit`: re-read assertions, fix code

- [ ] **Step 6.3: Push to main**

```bash
git push origin main
```

Expected: admin bypass succeeds, CI + Deploy triggered in parallel.

- [ ] **Step 6.4: Watch CI + Deploy**

Run: `gh run list --limit 5`
Then: `gh run watch <id>` for each.

Expected: both green within ~3-5 min. Deploy reaches production with new revision.

- [ ] **Step 6.5: Production smoke `/health`**

```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: `200 OK`.

- [ ] **Step 6.6: Capture production revision in CLAUDE.md**

After deploy succeeds, get revision name:

```bash
gcloud run services describe v4-ads-mcp --region southamerica-east1 --project v4-ads-mcp-prod --format='value(status.latestReadyRevisionName)'
```

Update the Sprint 3b.25 row in `CLAUDE.md` — replace `🟡 code-complete; smoke pending` with `✅ shipped + deploy verde; smoke pending Wellington execution` and add revision name. Commit + push.

```bash
git add CLAUDE.md
git commit -m "docs(claude): Sprint 3b.25 production revision <revision-name> captured

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin main
```

---

## Task 7: Smoke Execution + Sign-off (post-deploy, manual)

**This task is executed by Wellington (or operator) in real account, NOT by the implementer agent.**

The implementer should NOT attempt to run live MCP tool calls against Nutry sandbox. Instead, hand off to operator with this checklist:

- [ ] Operator executes T1-T15 from `docs/operacao/phase-3b-25-bootstrap.md`
- [ ] For each test, fill in expected check boxes + capture resource_names + GAQL verify output
- [ ] If findings emerge (e.g., T3/T9 reject AD_GROUP-level for SITELINK/CALL), document as F-class in `docs/operacao/findings-catalog.md` Bug class 1 table
- [ ] Add fix iterations if needed (Sprint 3b.25.1, 3b.25.2, ...) following Sprint 3b.24 pattern
- [ ] Final sign-off commit:

```bash
git commit -m "docs(ops): Sprint 3b.25 smoke signed-off em Nutry — <X>/15 tests PASS

Highlights:
- <captured results, findings, lessons>

Streak update: <consecutive sprint count without bugs>

Co-Authored-By: Wellington Ribeiro"
```

- [ ] Update Sprint 3b.25 row in CLAUDE.md: `🟡 → ✅ shipped + signed-off em conta real`

---

## Self-Review Checklist (run after writing the plan)

**1. Spec coverage:**
- [x] Schema with 5 asset types × 3 attachment levels → Task 1 (schema) + Task 2 (builder per-type)
- [x] `_validate_payload_shape` 6 checks → Task 1 (validator) + Task 1 tests
- [x] Chained mutation 2N ops → Task 2 (builder)
- [x] V4 invariants hardcoded → Task 2 builder (BR/pt/BRL) + Task 2 tests
- [x] F13 cross-cutting 2N resource_names → Task 4 integration test
- [x] audit_log params_summary (counts only) → Task 3 `_build_summary` + Task 4 integration test
- [x] Smoke runbook with per-value probes → Task 5
- [x] CLAUDE.md sprint row + tool count bump → Task 5

**2. Placeholder scan:**
- All code blocks are complete (no TBD/TODO/placeholder text)
- All file paths are exact
- All commands have expected output
- "PREENCHER pós-deploy" in smoke runbook is intentional (operator fills production revision name post-deploy)

**3. Type consistency:**
- `_validate_payload_shape(payload) -> dict[str, Any] | None` consistent in Task 1 schema test imports + Task 1 implementation + Task 3 tool body invocation
- `build_create_and_link_assets(client, customer_id, payload) -> list[Any]` consistent with `MutateBuilder` signature in `src/google_ads/mutates/_common.py`
- `_build_summary(payload) -> dict[str, Any]` consistent across Task 3 implementation + Task 4 integration test assertions

**4. Spec ↔ Plan alignment:**
- Spec proto fields (description1/description2, percent_off * 10_000, raw phone) → Plan Task 2 code uses identical names + formulas
- Spec smoke matrix T1-T15 → Plan Task 5 includes identical 15 tests
- Spec Risk R6 (percent_off micros) → Plan Task 2 test `test_builder_promotion_percent_off_sets_micros_with_10000_factor` asserts `200_000`
- Spec Layer 3 trust-Google → Plan has no async pre-flight code anywhere

## Done?

**Plan complete and saved to `docs/superpowers/plans/2026-05-18-sprint-3b-25-create-and-link-assets.md`.**

Total: 6 tasks (Task 7 = manual handoff to operator). Sequential dependency chain:

```
Task 1 (schema + validator + 13 tests, RED→GREEN, commit)
   ↓
Task 2 (builder + 18 builder tests, RED→GREEN, commit)
   ↓
Task 3 (tool body + dry-run + 2 tests + allowlist, commit)
   ↓
Task 4 (integration tests, commit)
   ↓
Task 5 (smoke runbook + CLAUDE.md, commit)
   ↓
Task 6 (pre-push + push + revision capture, commit)
   ↓
Task 7 (Wellington manual smoke + sign-off, commit)
```

Each task is self-contained, ends with passing tests + commit. Subagent-driven-development recommended for Tasks 1-6 (fresh subagent per task ≈ 30-60min each, reviewed between).
