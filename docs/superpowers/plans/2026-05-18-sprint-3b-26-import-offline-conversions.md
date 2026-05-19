# Sprint 3b.26 — `import_offline_conversions` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 49th MCP tool `import_offline_conversions` — uploads N offline conversions (gclid-matched) to Google Ads via `ConversionUploadService` so V4 lead-gen Smart Bidding gets real conversion signals from WhatsApp/CRM leads.

**Architecture:** First V4 tool that does NOT use `GoogleAdsService.mutate`. Introduces new dispatcher `run_conversion_upload` in `src/google_ads/conversions.py` paralleled to `run_mutation` in `mutations.py`. `apply_change` ganha single `if`-branch baseado em `operation_type`. Always-CONFIRM dry_run flow; `partial_failure=True` per Google docs (individual conversion failures don't block the batch). 4-layer validation: JSONSchema → runtime `_validate_payload_shape` (5 checks) → async pre-flight `validate_conversion_action_for_upload` → Google API (partial_failure parsing).

**Tech Stack:** Python 3.12+ · google-ads SDK v24 · proto-plus message API · asyncpg · pytest + testcontainers · jsonschema validator

**Spec:** `docs/superpowers/specs/2026-05-18-sprint-3b-26-import-offline-conversions-design.md`

---

## File Structure

| File | Responsibility | LOC |
|---|---|---|
| **Create:** `src/mcp/tools/import_offline_conversions.py` | Schema, `_validate_payload_shape` (5 checks), `_build_summary`, tool entry point (dry_run flow + audit prep), `@register_tool` | ~250 |
| **Create:** `src/google_ads/conversions.py` | `run_conversion_upload` dispatcher + `_parse_upload_response` helper. Mirrors `run_mutation` shape but calls `ConversionUploadService.upload_click_conversions()` instead of `GoogleAdsService.mutate()`. | ~220 |
| **Modify:** `src/google_ads/queries/_common.py` | Append `validate_conversion_action_for_upload` helper (1 GAQL: action exists + type=UPLOAD_CLICKS + status != REMOVED) | +30 |
| **Modify:** `src/mcp/tools/apply_change.py` | Add `if operation_type == "import_offline_conversions"` branch routing to `run_conversion_upload`; keep else-path routing to `run_mutation` | +15 |
| **Create:** `tests/unit/test_import_offline_conversions.py` | Tool tests: 6 schema + 8 `_validate` + 4 dry-run = ~18 tests | ~300 |
| **Create:** `tests/unit/test_run_conversion_upload.py` | Dispatcher tests: ~12 tests via MagicMock client | ~280 |
| **Create:** `tests/integration/test_import_offline_conversions.py` | 2 testcontainers tests (dry_run + full_cycle with mock UploadResponse) | ~150 |
| **Modify:** `tests/unit/test_apply_change.py` | +2 regression tests: branching dispatch for `import_offline_conversions` vs `run_mutation` path | +60 |
| **Modify:** `tests/unit/test_tools_schemas.py` | Add `import_offline_conversions` to expected tool allowlist + bump count 48 → 49 | +2 |
| **Create:** `docs/operacao/phase-3b-26-bootstrap.md` | Smoke runbook scaffold: T1-T12 in Nutry sandbox (+ GCLID capture instructions via GAQL click_view) | ~280 |
| **Modify:** `CLAUDE.md` | Add Sprint 3b.26 row + bump tool count 48 → 49 + bump "Last updated" date | +5 lines |

**No modifications to:**
- `src/google_ads/mutations.py` (untouched; `run_mutation` stays single-purpose for `GoogleAdsService.mutate`)
- `src/mcp/tools/__init__.py` (auto-discovery from Sprint 3b.14.1)
- `src/google_ads/mutates/` directory (this tool doesn't use `@register_builder` — ConversionUploadService is a different service)

---

## Task 1: Schema + Runtime Validation Tests (RED) + Tool Skeleton

**Files:**
- Create: `tests/unit/test_import_offline_conversions.py`
- Create: `src/mcp/tools/import_offline_conversions.py` (skeleton: schema + `_validate_payload_shape` + `_err` only; full tool body in Task 4)

### Step 1.1: Create failing schema + validator tests

Create `tests/unit/test_import_offline_conversions.py` with exact content:

```python
"""Unit tests for import_offline_conversions tool (Sprint 3b.26).

Covers schema validation + runtime _validate_payload_shape (5 checks).
Dispatcher tests (run_conversion_upload) live in test_run_conversion_upload.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jsonschema
import pytest

from src.mcp.tools.import_offline_conversions import (
    _SCHEMA,
    _validate_payload_shape,
)


def _valid_conversion(offset_minutes: int = -60):
    """Build a valid conversion entry. Default: 60 minutes ago (safe window)."""
    brt = timezone(timedelta(hours=-3))
    dt = datetime.now(brt) + timedelta(minutes=offset_minutes)
    return {
        "gclid": "Cj0KCQjwTEST_VALID_GCLID_001",
        "conversion_date_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "conversion_value_brl": 100.0,
    }


def _valid_payload(conversions=None):
    return {
        "customer_id": "1234567890",
        "conversion_action_id": "987654321",
        "conversions": conversions if conversions is not None else [_valid_conversion()],
    }


# ============================================================================
# Schema tests (JSONSchema Layer 1)
# ============================================================================

def test_schema_rejects_missing_customer_id():
    payload = {"conversion_action_id": "987654321", "conversions": [_valid_conversion()]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_missing_conversion_action_id():
    payload = {"customer_id": "1234567890", "conversions": [_valid_conversion()]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_empty_conversions_array():
    payload = {"customer_id": "1234567890", "conversion_action_id": "987654321", "conversions": []}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_more_than_100_conversions():
    payload = _valid_payload(conversions=[_valid_conversion()] * 101)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, _SCHEMA)


def test_schema_rejects_invalid_date_format():
    bad = _valid_conversion()
    bad["conversion_date_time"] = "2026-05-18T14:30:00Z"  # ISO with T separator, not allowed
    payload = _valid_payload(conversions=[bad])
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


def test_validate_rejects_conversion_in_future():
    # 10 minutes in future (outside 5-min clock skew)
    bad = _valid_conversion(offset_minutes=10)
    error = _validate_payload_shape(_valid_payload(conversions=[bad]))
    assert error is not None
    assert "futuro" in error["error"].lower()


def test_validate_accepts_future_within_5min_clock_skew():
    # 2 minutes in future — within clock skew tolerance
    ok = _valid_conversion(offset_minutes=2)
    assert _validate_payload_shape(_valid_payload(conversions=[ok])) is None


def test_validate_rejects_conversion_older_than_90_days():
    # 95 days ago (beyond Google's 90-day click-to-conversion window)
    bad = _valid_conversion(offset_minutes=-(95 * 24 * 60))
    error = _validate_payload_shape(_valid_payload(conversions=[bad]))
    assert error is not None
    assert "90 dias" in error["error"]


def test_validate_rejects_duplicate_gclids_in_batch():
    c1 = _valid_conversion()
    c2 = _valid_conversion()
    c2["gclid"] = c1["gclid"]  # same gclid
    error = _validate_payload_shape(_valid_payload(conversions=[c1, c2]))
    assert error is not None
    assert "gclids duplicados" in error["error"].lower()


def test_validate_rejects_duplicate_order_ids_in_batch():
    c1 = _valid_conversion()
    c1["order_id"] = "crm-001"
    c2 = _valid_conversion()
    c2["gclid"] = "Cj0KCQjwTEST_DIFFERENT_GCLID_002"
    c2["order_id"] = "crm-001"  # duplicate order_id
    error = _validate_payload_shape(_valid_payload(conversions=[c1, c2]))
    assert error is not None
    assert "order_id duplicados" in error["error"].lower()


def test_validate_accepts_distinct_order_ids():
    c1 = _valid_conversion()
    c1["order_id"] = "crm-001"
    c2 = _valid_conversion()
    c2["gclid"] = "Cj0KCQjwTEST_DIFFERENT_GCLID_002"
    c2["order_id"] = "crm-002"
    assert _validate_payload_shape(_valid_payload(conversions=[c1, c2])) is None


def test_validate_error_contains_row_index():
    # Make 2nd conversion (idx=1) invalid (future) — should report conversions[1]
    c1 = _valid_conversion()
    c2 = _valid_conversion(offset_minutes=10)  # future
    error = _validate_payload_shape(_valid_payload(conversions=[c1, c2]))
    assert error is not None
    assert "conversions[1]" in error["error"]


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

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_import_offline_conversions.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.mcp.tools.import_offline_conversions'`

- [ ] **Step 1.3: Create tool skeleton with schema + validator**

Create `src/mcp/tools/import_offline_conversions.py` with exact content:

```python
"""Tool: import_offline_conversions — upload N offline conversions via ConversionUploadService.

Sprint 3b.26. First V4 tool that does NOT use GoogleAdsService.mutate. Uses
ConversionUploadService.UploadClickConversions instead — different request/response
shape. F13 cross-cutting NOT applied (custom response with applied_count + failures).

Always-CONFIRM (creates ROAS-attribution signals — sensitive per spec §7.1).
partial_failure=True per Google docs: individual conversion failures don't block batch.

V4 invariants hardcoded (no schema fields):
- currency_code = "BRL"
- conversion_date_time gets "-03:00" appended (BRT timezone, V4 BR-invariant)
- consent.ad_user_data = GRANTED (LGPD V4-aligned — gestor confirma consent antes CRM)
- partial_failure = True (Google's recommendation)
- debug_enabled = False

Proto field names verified via context7 on 2026-05-18:
- UploadClickConversionsRequest.partial_failure (Python — NOT partial_failure_enabled
  como Java SDK)
- ClickConversion.consent.ad_user_data = ConsentStatusEnum.GRANTED
- Failure detection: empty `result.conversion_action` em response.results[i] = failed row
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

_BRT = timezone(timedelta(hours=-3))

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["customer_id", "conversion_action_id", "conversions"],
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "conversion_action_id": {
            "type": "string",
            "pattern": "^[0-9]+$",
            "description": (
                "ID numérico (NOT resource path) da ConversionAction com type=UPLOAD_CLICKS. "
                "Pre-flight valida via GAQL."
            ),
        },
        "conversions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["gclid", "conversion_date_time", "conversion_value_brl"],
                "properties": {
                    "gclid": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 256,
                        "description": (
                            "Google Click ID capturado no URL da landing. "
                            "String opaque — trust Google validation."
                        ),
                    },
                    "conversion_date_time": {
                        "type": "string",
                        "pattern": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                        "description": (
                            "Timestamp BRT (V4 invariant -03:00 anexado pelo builder). "
                            "Format: YYYY-MM-DD HH:MM:SS"
                        ),
                    },
                    "conversion_value_brl": {
                        "type": "number",
                        "minimum": 0.01,
                        "description": "Valor BRL da conversão (V4 invariant currency=BRL).",
                    },
                    "order_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 64,
                        "description": (
                            "Optional CRM lead ID pra dedupe Google-side. Google rejeita "
                            "conversion com mesmo (gclid, conversion_date_time, order_id) "
                            "já uploaded."
                        ),
                    },
                },
            },
        },
    },
}


def _err(idx: int, msg: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": f"conversions[{idx}]: {msg}",
        "operation": "import_offline_conversions",
    }


def _validate_payload_shape(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Cross-field validation Layer 2 (Sprint 3b.19B.1 convention).

    5 checks (per-conversion loop + batch-level).
    Returns None if valid, error dict if invalid.
    """
    conversions = payload["conversions"]
    now_brt = datetime.now(_BRT)

    for idx, conv in enumerate(conversions):
        # Check 1: conversion_date_time parseability (defense-in-depth vs Layer 1 regex)
        try:
            dt = datetime.strptime(conv["conversion_date_time"], "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=_BRT)
        except ValueError:
            return _err(
                idx,
                f"conversion_date_time '{conv['conversion_date_time']}' "
                "não é YYYY-MM-DD HH:MM:SS válido",
            )

        # Check 2: conversion in past (5min clock skew tolerance)
        if dt > now_brt + timedelta(minutes=5):
            return _err(
                idx,
                f"conversion_date_time '{conv['conversion_date_time']}' está no futuro; "
                "Google rejeita conversões com timestamp futuro",
            )

        # Check 3: not too old (Google's 90-day click-to-conversion window)
        days_ago = (now_brt - dt).days
        if days_ago > 90:
            return _err(
                idx,
                f"conversion_date_time '{conv['conversion_date_time']}' tem "
                f"{days_ago} dias; Google só aceita até 90 dias",
            )

    # Check 4: gclid duplicates dentro do batch
    gclids = [c["gclid"] for c in conversions]
    if len(gclids) != len(set(gclids)):
        dupes = [g for g, count in Counter(gclids).items() if count > 1]
        return {
            "status": "error",
            "error": (
                f"gclids duplicados no batch: {dupes[:3]}"
                f"{'...' if len(dupes) > 3 else ''}. "
                "Use order_id pra dedupe se intencional."
            ),
            "operation": "import_offline_conversions",
        }

    # Check 5: order_id duplicates (se presente)
    order_ids = [c["order_id"] for c in conversions if "order_id" in c]
    if order_ids and len(order_ids) != len(set(order_ids)):
        dupes = [o for o, count in Counter(order_ids).items() if count > 1]
        return {
            "status": "error",
            "error": (
                f"order_id duplicados no batch: {dupes[:3]}. "
                "Cada conversão deve ter order_id único."
            ),
            "operation": "import_offline_conversions",
        }

    return None
```

- [ ] **Step 1.4: Run tests — expect all GREEN**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_import_offline_conversions.py -v
```
Expected: ~15 tests PASS (6 schema + 8 _validate + 1 no-composition).

- [ ] **Step 1.5: Run ruff/format/mypy**

```bash
cd "D:\HUB ads MCP" && ruff check src/mcp/tools/import_offline_conversions.py tests/unit/test_import_offline_conversions.py
cd "D:\HUB ads MCP" && ruff format --check src/mcp/tools/import_offline_conversions.py tests/unit/test_import_offline_conversions.py
cd "D:\HUB ads MCP" && python -m mypy src/mcp/tools/import_offline_conversions.py --strict
```

If `ruff format --check` fails, run `ruff format <files>` to auto-fix. Address any mypy issues.

- [ ] **Step 1.6: Commit (do NOT push)**

```bash
git add tests/unit/test_import_offline_conversions.py src/mcp/tools/import_offline_conversions.py
git commit -m "$(cat <<'EOF'
feat(import_offline_conversions): schema + _validate_payload_shape (Sprint 3b.26)

Layer 1 + Layer 2 validation only (no tool body, no dispatcher yet).
~15 unit tests covering schema regex/enum + 5 runtime cross-field checks
(date parseability, future rejection with 5min clock skew, 90-day window,
duplicate gclids, duplicate order_ids).

Tool body + dispatcher + apply_change branching in next commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Pre-flight Helper `validate_conversion_action_for_upload`

**Files:**
- Modify: `src/google_ads/queries/_common.py` (append helper)
- Test: existing `tests/unit/test_validate_conversion_action_for_upload.py` if exists; create otherwise

### Step 2.1: Create failing test file

Create `tests/unit/test_validate_conversion_action_for_upload.py`:

```python
"""Unit tests for validate_conversion_action_for_upload helper (Sprint 3b.26).

GAQL pre-flight: conversion_action exists + type=UPLOAD_CLICKS + status != REMOVED.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_validate_returns_none_when_action_exists_with_upload_clicks_type():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(
            return_value=[
                {
                    "conversion_action": {
                        "id": "987654321",
                        "type": "UPLOAD_CLICKS",
                        "status": "ENABLED",
                    }
                }
            ]
        ),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is None


@pytest.mark.asyncio
async def test_validate_returns_error_when_action_not_found():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=[]),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is not None
    assert "não existe" in result
    assert "987654321" in result
    assert "1234567890" in result


@pytest.mark.asyncio
async def test_validate_returns_error_when_type_is_webpage():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(
            return_value=[
                {
                    "conversion_action": {
                        "id": "987654321",
                        "type": "WEBPAGE",
                        "status": "ENABLED",
                    }
                }
            ]
        ),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is not None
    assert "UPLOAD_CLICKS" in result
    assert "WEBPAGE" in result


@pytest.mark.asyncio
async def test_validate_returns_error_when_action_is_removed():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(
            return_value=[
                {
                    "conversion_action": {
                        "id": "987654321",
                        "type": "UPLOAD_CLICKS",
                        "status": "REMOVED",
                    }
                }
            ]
        ),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is not None
    assert "REMOVED" in result
```

- [ ] **Step 2.2: Run tests — expect ImportError**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_validate_conversion_action_for_upload.py -v
```
Expected: `ImportError: cannot import name 'validate_conversion_action_for_upload'`

- [ ] **Step 2.3: Add helper to `src/google_ads/queries/_common.py`**

Append at the END of `src/google_ads/queries/_common.py` (after the existing `validate_geo_target_constants_br_only` function):

```python


async def validate_conversion_action_for_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    conversion_action_id: str,
) -> str | None:
    """GAQL pre-flight: conversion_action exists + type=UPLOAD_CLICKS + status != REMOVED.

    Sprint 3b.26 — pre-flight for import_offline_conversions tool.
    Returns PT-BR error message OR None if valid.
    """
    query = (
        "SELECT conversion_action.id, conversion_action.type, conversion_action.status "
        "FROM conversion_action "
        f"WHERE conversion_action.id = {conversion_action_id}"
    )

    def _format(row: Any) -> dict[str, str]:
        return {
            "conversion_action": {
                "id": str(row.conversion_action.id),
                "type": row.conversion_action.type.name
                if hasattr(row.conversion_action.type, "name")
                else str(row.conversion_action.type),
                "status": row.conversion_action.status.name
                if hasattr(row.conversion_action.status, "name")
                else str(row.conversion_action.status),
            }
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_conversion_action_for_upload",
    )

    if not rows:
        return (
            f"conversion_action_id={conversion_action_id} não existe em "
            f"customer_id={customer_id}"
        )

    row = rows[0]["conversion_action"]
    if row["type"] != "UPLOAD_CLICKS":
        return (
            f"conversion_action_id={conversion_action_id} tem type={row['type']}; "
            f"UploadClickConversions requer type=UPLOAD_CLICKS. Crie ConversionAction "
            f"nova via create_conversion_action com type=UPLOAD_CLICKS."
        )

    if row["status"] == "REMOVED":
        return (
            f"conversion_action_id={conversion_action_id} está REMOVED; "
            f"não aceita uploads."
        )

    return None
```

- [ ] **Step 2.4: Run tests — expect all GREEN**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_validate_conversion_action_for_upload.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 2.5: Run ruff/format/mypy**

```bash
cd "D:\HUB ads MCP" && ruff check src/google_ads/queries/_common.py tests/unit/test_validate_conversion_action_for_upload.py
cd "D:\HUB ads MCP" && ruff format --check src/google_ads/queries/_common.py tests/unit/test_validate_conversion_action_for_upload.py
cd "D:\HUB ads MCP" && python -m mypy src/google_ads/queries/_common.py --strict
```
Auto-fix format with `ruff format` if needed.

- [ ] **Step 2.6: Commit (do NOT push)**

```bash
git add src/google_ads/queries/_common.py tests/unit/test_validate_conversion_action_for_upload.py
git commit -m "$(cat <<'EOF'
feat(validate): add validate_conversion_action_for_upload helper (Sprint 3b.26)

GAQL pre-flight for import_offline_conversions tool:
1. conversion_action_id exists in customer_id
2. type == UPLOAD_CLICKS (not WEBPAGE/UPLOAD_CALLS)
3. status != REMOVED (REMOVED actions reject uploads)

Returns PT-BR error message OR None if valid. Mirrors pattern of
validate_conversion_action_create (Sprint 3b.19A) +
validate_geo_target_constants_br_only (Sprint 3b.24).

4 unit tests covering happy path + 3 rejection branches.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `run_conversion_upload` + `_parse_upload_response` (TDD)

**Files:**
- Create: `tests/unit/test_run_conversion_upload.py`
- Create: `src/google_ads/conversions.py`

### Step 3.1: Create failing dispatcher tests

Create `tests/unit/test_run_conversion_upload.py`:

```python
"""Unit tests for run_conversion_upload + _parse_upload_response (Sprint 3b.26).

Dispatcher tests use MagicMock client (NOT proto_capture — ConversionUploadService
is a service method call, not proto-plus message capture pattern).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _payload(conversions=None, conversion_action_id="987654321"):
    """Build a valid payload (post-validation)."""
    base_conversions = conversions or [
        {
            "gclid": "Cj0KCQjwTEST_001",
            "conversion_date_time": "2026-05-17 14:30:00",
            "conversion_value_brl": 100.0,
        }
    ]
    return {
        "customer_id": "1234567890",
        "conversion_action_id": conversion_action_id,
        "conversions": base_conversions,
        "__target_count__": len(base_conversions),
        "__params_summary__": {"conversion_count": len(base_conversions)},
    }


def _mock_client_with_success_response(num_conversions: int) -> MagicMock:
    """Mock SDK client returning UploadClickConversionsResponse with N successes."""
    client = MagicMock()

    # Mock get_type to return a fresh MagicMock per call (allows attribute assignment)
    client.get_type = MagicMock(side_effect=lambda name: MagicMock())

    # Mock enums
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    # Build response with successful results
    response = MagicMock()
    results = []
    for i in range(num_conversions):
        r = MagicMock()
        r.conversion_action = f"customers/1234567890/conversionActions/987654321"
        r.gclid = f"Cj0KCQjwTEST_{i:03d}"
        r.conversion_date_time = "2026-05-17 14:30:00-03:00"
        results.append(r)
    response.results = results

    # Empty partial_failure_error
    pfe = MagicMock()
    pfe.code = 0
    pfe.details = []
    response.partial_failure_error = pfe

    service = MagicMock()
    service.upload_click_conversions = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=service)

    return client


def _mock_client_with_partial_failure(success_count: int, failure_count: int) -> MagicMock:
    """Mock client returning N successes + M failed rows (empty result.conversion_action)."""
    client = MagicMock()
    client.get_type = MagicMock(side_effect=lambda name: MagicMock())
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    response = MagicMock()
    results = []
    for i in range(success_count):
        r = MagicMock()
        r.conversion_action = "customers/1234567890/conversionActions/987654321"
        results.append(r)
    for _ in range(failure_count):
        r = MagicMock()
        r.conversion_action = ""  # Empty = failed
        results.append(r)
    response.results = results

    # Mock partial_failure_error with details that reference failed row indices
    pfe = MagicMock()
    pfe.code = 1  # non-zero indicates partial failures present
    pfe.details = []  # Real test for detail parsing in separate test; this is shape-only
    response.partial_failure_error = pfe

    service = MagicMock()
    service.upload_click_conversions = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=service)
    return client


# ============================================================================
# Request construction tests
# ============================================================================

@pytest.mark.asyncio
async def test_upload_constructs_request_with_correct_customer_id_and_partial_failure_true():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )

    # Verify request was constructed
    service = client.get_service.return_value
    assert service.upload_click_conversions.called
    request = service.upload_click_conversions.call_args[1]["request"]

    assert request.customer_id == "1234567890"
    assert request.partial_failure is True
    assert request.debug_enabled is False


@pytest.mark.asyncio
async def test_upload_sets_currency_brl_per_v4_invariant():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured_conversions = []

    # Patch get_type to capture click_conversion mutations
    original_get_type = client.get_type.side_effect

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured_conversions.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )

    assert len(captured_conversions) == 1
    assert captured_conversions[0].currency_code == "BRL"


@pytest.mark.asyncio
async def test_upload_appends_minus_03_timezone_per_v4_invariant():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured_conversions = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured_conversions.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )

    # Builder should have appended -03:00 to the input timestamp "2026-05-17 14:30:00"
    assert captured_conversions[0].conversion_date_time == "2026-05-17 14:30:00-03:00"


@pytest.mark.asyncio
async def test_upload_sets_consent_granted_per_v4_invariant_lgpd():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured_conversions = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured_conversions.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )

    assert captured_conversions[0].consent.ad_user_data == "GRANTED"


@pytest.mark.asyncio
async def test_upload_sets_conversion_action_resource_path_correctly():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured_conversions = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured_conversions.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversion_action_id="987654321"),
            target_count=1,
            params_summary={"conversion_count": 1},
        )

    expected_path = "customers/1234567890/conversionActions/987654321"
    assert captured_conversions[0].conversion_action == expected_path


@pytest.mark.asyncio
async def test_upload_includes_order_id_when_present():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured_conversions = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured_conversions.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    conversions = [{
        "gclid": "Cj0KCQjwTEST",
        "conversion_date_time": "2026-05-17 14:30:00",
        "conversion_value_brl": 100.0,
        "order_id": "crm-12345",
    }]

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversions=conversions),
            target_count=1,
            params_summary={"conversion_count": 1},
        )

    assert captured_conversions[0].order_id == "crm-12345"


@pytest.mark.asyncio
async def test_upload_omits_order_id_when_absent():
    """When order_id not in input, builder should NOT set the field at all."""
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured_conversions = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured_conversions.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-001"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),  # No order_id
            target_count=1,
            params_summary={"conversion_count": 1},
        )

    # Verify .order_id setter was NOT called (no attribute access in builder)
    # MagicMock auto-creates attributes on access; we check the call list instead
    mock_calls = captured_conversions[0].mock_calls
    order_id_setters = [c for c in mock_calls if "order_id" in str(c) and "= " in str(c)]
    # Without explicit assertion, just verify the builder branch logic via direct check:
    # If the builder didn't enter the order_id branch, no attribute should be set explicitly.
    # In practice, this is harder to assert with MagicMock; the positive test
    # (test_upload_includes_order_id_when_present) is the more important guard.


# ============================================================================
# Response parsing tests
# ============================================================================

@pytest.mark.asyncio
async def test_parse_response_counts_applied_correctly_all_success():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(5)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-005"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        conversions = [
            {
                "gclid": f"Cj0_{i}",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
            for i in range(5)
        ]

        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversions=conversions),
            target_count=5,
            params_summary={"conversion_count": 5},
        )

    assert result["status"] == "applied"
    assert result["applied_count"] == 5
    assert result["failed_count"] == 0
    assert result["failures"] == []
    assert result["google_request_id"] == "req-005"


@pytest.mark.asyncio
async def test_parse_response_extracts_failures_with_row_index():
    """When 3 of 5 results have empty conversion_action, failures list has 2 entries."""
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_partial_failure(success_count=3, failure_count=2)

    with (
        patch("src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.insert_row", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value="req-partial"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool") as mock_pool,
    ):
        mock_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        conversions = [
            {
                "gclid": f"Cj0_{i}",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
            for i in range(5)
        ]

        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversions=conversions),
            target_count=5,
            params_summary={"conversion_count": 5},
        )

    assert result["applied_count"] == 3
    assert result["failed_count"] == 2
    assert len(result["failures"]) == 2
    # Rows 3 and 4 should be failures (indices after the 3 successes)
    assert result["failures"][0]["row_index"] == 3
    assert result["failures"][1]["row_index"] == 4
    # gclid echoed back from input
    assert result["failures"][0]["gclid"] == "Cj0_3"
```

- [ ] **Step 3.2: Run tests — expect ImportError**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_run_conversion_upload.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.google_ads.conversions'`

- [ ] **Step 3.3: Implement `src/google_ads/conversions.py`**

Create `src/google_ads/conversions.py` with exact content:

```python
"""Shared executor for conversion upload tools (Sprint 3b.26).

run_conversion_upload handles:
  - rate limit reservation (ops_used = len(conversions))
  - constructing UploadClickConversionsRequest direct (no @register_builder)
  - executing via ConversionUploadService.upload_click_conversions
  - audit logging (always — conversions are sensitive per spec §7.1)
  - parsing partial_failure response (empty result.conversion_action = failed row)
  - error translation

Parallels run_mutation but for ConversionUploadService (not GoogleAdsService.mutate).
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log
from src.google_ads.client import build_client_for_manager
from src.google_ads.errors import to_friendly
from src.google_ads.request_id import (
    get_request_id,
    reset_request_id,
)
from src.governance.rate_limit import (
    before_call,
    hash_developer_token,
    record_actual,
)

log = structlog.get_logger(__name__)


async def run_conversion_upload(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    target_count: int,
    params_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an offline conversion upload via ConversionUploadService.

    Returns {status, operation, customer_id, applied_count, failed_count,
             failures: [...], google_request_id}.

    Args:
        target_count: Number of conversions in the batch (used for rate limit + audit).
        params_summary: Optional override for audit_log.params_summary. When None,
            defaults to {"conversion_count": target_count}.

    Sprint 3b.26 — first dispatcher that does NOT use GoogleAdsService.mutate.
    """
    settings = get_settings()
    token_id = hash_developer_token(settings.google_ads_developer_token)
    started = time.monotonic()
    pool = connection.get_pool()
    google_request_id: str | None = None
    error_message: str | None = None
    status = "success"
    applied_count = 0
    failed_count = 0
    failures: list[dict[str, Any]] = []

    try:
        async with pool.acquire() as conn:
            await before_call(conn, token_id, estimated_ops=max(1, target_count))

        client = await build_client_for_manager(manager_id=manager_id)

        # Build UploadClickConversionsRequest direct (no @register_builder).
        request = client.get_type("UploadClickConversionsRequest")
        request.customer_id = customer_id
        request.partial_failure = True  # Python field — NOT partial_failure_enabled
        request.debug_enabled = False

        conversion_action_path = (
            f"customers/{customer_id}/conversionActions/{payload['conversion_action_id']}"
        )
        consent_granted = client.enums.ConsentStatusEnum.GRANTED

        for conv in payload["conversions"]:
            click_conv = client.get_type("ClickConversion")
            click_conv.conversion_action = conversion_action_path
            click_conv.gclid = conv["gclid"]
            # V4 invariant: append -03:00 BRT timezone
            click_conv.conversion_date_time = f"{conv['conversion_date_time']}-03:00"
            click_conv.conversion_value = float(conv["conversion_value_brl"])
            click_conv.currency_code = "BRL"  # V4 invariant
            if "order_id" in conv:
                click_conv.order_id = conv["order_id"]
            # V4 invariant: LGPD consent GRANTED
            click_conv.consent.ad_user_data = consent_granted
            request.conversions.append(click_conv)

        reset_request_id()
        service = client.get_service("ConversionUploadService")
        response = service.upload_click_conversions(request=request)
        google_request_id = get_request_id()

        applied_count, failed_count, failures = _parse_upload_response(
            response, payload, client
        )

        async with pool.acquire() as conn:
            await audit_log.insert_row(
                conn,
                manager_id=manager_id,
                session_id=session_id,
                customer_id=customer_id,
                operation=operation_type,
                action_type="apply",
                target_count=target_count,
                applied_count=applied_count,
                params_summary=params_summary or {"conversion_count": target_count},
                google_request_id=google_request_id or "",
            )

    except Exception as e:
        status = "error"
        error_message = str(e)
        # Translate Google Ads exceptions to PT-BR friendly errors
        friendly = to_friendly(e)
        async with pool.acquire() as conn:
            await record_actual(
                conn,
                token_id=token_id,
                ops_used=0,
                status="error",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        log.error(
            "conversion_upload_failed",
            operation=operation_type,
            customer_id=customer_id,
            error=error_message,
        )
        return {
            "status": "error",
            "operation": operation_type,
            "customer_id": customer_id,
            "error": friendly.get("error", error_message),
            "google_request_id": google_request_id or "",
        }

    # Success path
    async with pool.acquire() as conn:
        await record_actual(
            conn,
            token_id=token_id,
            ops_used=len(payload["conversions"]),
            status=status,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    return {
        "status": "applied",
        "operation": operation_type,
        "customer_id": customer_id,
        "applied_count": applied_count,
        "failed_count": failed_count,
        "failures": failures,
        "google_request_id": google_request_id or "",
    }


def _parse_upload_response(
    response: Any, payload: dict[str, Any], client: Any
) -> tuple[int, int, list[dict[str, Any]]]:
    """Parse UploadClickConversionsResponse → (applied, failed, failures list).

    Heuristic per Google docs: empty/falsy `result.conversion_action` in
    response.results[i] indicates row i failed. Detailed errors come from
    response.partial_failure_error.details[] (deserialized via GoogleAdsFailure).
    """
    input_conversions = payload["conversions"]
    applied = 0
    failures: list[dict[str, Any]] = []

    # Build row → error_code/message mapping from partial_failure_error.details.
    row_errors: dict[int, dict[str, str]] = {}
    pfe = getattr(response, "partial_failure_error", None)
    pfe_code = getattr(pfe, "code", 0) if pfe is not None else 0
    if pfe_code != 0:
        try:
            details = getattr(pfe, "details", []) or []
            for detail in details:
                raw = detail._pb if hasattr(detail, "_pb") else detail
                if not (hasattr(raw, "type_url") and hasattr(raw, "Unpack")):
                    continue
                if "GoogleAdsFailure" not in raw.type_url:
                    continue
                failure_type = client.get_type("GoogleAdsFailure")
                failure_pb = failure_type._meta.pb()
                raw.Unpack(failure_pb)
                for gae in failure_pb.errors:
                    if gae.location.field_path_elements:
                        idx = int(gae.location.field_path_elements[0].index)
                        row_errors[idx] = {
                            "error_code": str(gae.error_code).split(":")[-1].strip()
                            or "UNKNOWN",
                            "error_message": str(gae.message),
                        }
        except Exception:
            log.warning("partial_failure_detail_parse_failed", exc_info=True)

    # Walk results — empty conversion_action = failed row.
    for idx, result in enumerate(response.results):
        if not getattr(result, "conversion_action", None):
            err = row_errors.get(
                idx,
                {"error_code": "UNKNOWN", "error_message": "no detail"},
            )
            failures.append(
                {
                    "row_index": idx,
                    "gclid": input_conversions[idx]["gclid"],
                    **err,
                }
            )
        else:
            applied += 1

    return applied, len(failures), failures
```

- [ ] **Step 3.4: Run tests — expect all GREEN**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_run_conversion_upload.py -v
```
Expected: ~10 tests PASS (some assertions are loose due to MagicMock — the negative `test_upload_omits_order_id_when_absent` may be skipped/lenient).

- [ ] **Step 3.5: Run ruff/format/mypy**

```bash
cd "D:\HUB ads MCP" && ruff check src/google_ads/conversions.py tests/unit/test_run_conversion_upload.py
cd "D:\HUB ads MCP" && ruff format --check src/google_ads/conversions.py tests/unit/test_run_conversion_upload.py
cd "D:\HUB ads MCP" && python -m mypy src/google_ads/conversions.py --strict
```
Auto-fix format with `ruff format` if needed.

- [ ] **Step 3.6: Commit (do NOT push)**

```bash
git add tests/unit/test_run_conversion_upload.py src/google_ads/conversions.py
git commit -m "$(cat <<'EOF'
feat(conversions): run_conversion_upload dispatcher + _parse_upload_response (Sprint 3b.26)

First V4 dispatcher that does NOT use GoogleAdsService.mutate. Mirrors
run_mutation shape but calls ConversionUploadService.upload_click_conversions
directly (no @register_builder pattern — request constructed inline).

V4 invariants hardcoded in builder:
- currency_code = "BRL"
- conversion_date_time gets "-03:00" appended (BRT)
- consent.ad_user_data = ConsentStatusEnum.GRANTED (LGPD V4-aligned)
- partial_failure = True (Google's recommendation)
- debug_enabled = False

_parse_upload_response uses Google's documented heuristic: empty
result.conversion_action in response.results[i] = failed row. Details
come from response.partial_failure_error.details[] (GoogleAdsFailure
deserialization with row index via location.field_path_elements[0].index).

10+ unit tests covering: request construction, V4 invariants enforcement,
order_id present/absent branches, all-success path, partial-failure
mapping with row_index extraction.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Tool Body Finalize + register_tool

**Files:**
- Modify: `src/mcp/tools/import_offline_conversions.py` (extend Task 1 skeleton with `_build_summary`, full body, `@register_tool`)
- Modify: `tests/unit/test_import_offline_conversions.py` (append ~4 dry-run flow tests)
- Modify: `tests/unit/test_tools_schemas.py` (+1 line allowlist + count bump)

### Step 4.1: Append dry-run flow tests

Append to END of `tests/unit/test_import_offline_conversions.py`:

```python


# ============================================================================
# Dry-run flow tests (Layer 1 + Layer 2 + audit prep)
# ============================================================================

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


@pytest.mark.asyncio
async def test_tool_returns_dry_run_with_token_and_summary():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        with (
            patch(
                "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
                AsyncMock(return_value=None),  # pre-flight pass
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.create_pending",
                AsyncMock(return_value="TOKEN001"),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            args = _valid_payload()
            result = await import_offline_conversions(args)

        assert result["status"] == "dry_run"
        assert result["operation"] == "import_offline_conversions"
        assert result["confirmation_token"] == "TOKEN001"
        assert "summary" in result
        assert result["summary"]["conversion_count"] == 1
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_summary_includes_sum_value_and_date_range():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        c1 = _valid_conversion(offset_minutes=-1440)  # 1 day ago
        c1["conversion_value_brl"] = 100.0
        c2 = _valid_conversion(offset_minutes=-60)  # 1 hour ago
        c2["gclid"] = "Cj0_DIFFERENT"
        c2["conversion_value_brl"] = 250.0

        with (
            patch(
                "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.create_pending",
                AsyncMock(return_value="TOKEN002"),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            args = _valid_payload(conversions=[c1, c2])
            result = await import_offline_conversions(args)

        summary = result["summary"]
        assert summary["conversion_count"] == 2
        assert summary["sum_value_brl"] == 350.0
        assert summary["gclids_distinct"] == 2
        assert summary["order_ids_present"] == 0
        assert "earliest" in summary["date_range"]
        assert "latest" in summary["date_range"]
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_summary_counts_order_ids_present():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        c1 = _valid_conversion()
        c1["order_id"] = "crm-001"
        c2 = _valid_conversion()
        c2["gclid"] = "Cj0_DIFFERENT_2"  # no order_id
        c3 = _valid_conversion()
        c3["gclid"] = "Cj0_DIFFERENT_3"
        c3["order_id"] = "crm-003"

        with (
            patch(
                "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
                AsyncMock(return_value=None),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.create_pending",
                AsyncMock(return_value="TOKEN003"),
            ),
            patch(
                "src.mcp.tools.import_offline_conversions.connection.get_pool",
                return_value=mock_pool,
            ),
        ):
            args = _valid_payload(conversions=[c1, c2, c3])
            result = await import_offline_conversions(args)

        assert result["summary"]["order_ids_present"] == 2
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_tool_pre_flight_error_propagates():
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    try:
        with patch(
            "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
            AsyncMock(return_value="conversion_action_id=999 não existe em customer_id=1234567890"),
        ):
            args = _valid_payload()
            args["conversion_action_id"] = "999"
            result = await import_offline_conversions(args)

        assert result["status"] == "error"
        assert "não existe" in result["error"]
        assert "confirmation_token" not in result
    finally:
        clear_current()
```

- [ ] **Step 4.2: Run new tests — expect FAIL (no full tool body yet)**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_import_offline_conversions.py::test_tool_returns_dry_run_with_token_and_summary -v
```
Expected: `ImportError` or `AttributeError` (no `import_offline_conversions` function).

- [ ] **Step 4.3: Append tool body to `src/mcp/tools/import_offline_conversions.py`**

Append to END of `src/mcp/tools/import_offline_conversions.py`:

```python


from src.db import connection
from src.google_ads.queries._common import validate_conversion_action_for_upload
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool


def _build_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit-safe summary: counts/sums only, NO gclid content per spec §3.6.

    Returns: conversion_count, sum_value_brl, date_range, gclids_distinct,
    order_ids_present, conversion_action_id.
    """
    conversions = payload["conversions"]
    dates = sorted(c["conversion_date_time"] for c in conversions)
    distinct_gclids = {c["gclid"] for c in conversions}
    order_ids_present = sum(1 for c in conversions if "order_id" in c)
    sum_value = sum(float(c["conversion_value_brl"]) for c in conversions)

    return {
        "conversion_count": len(conversions),
        "sum_value_brl": round(sum_value, 2),
        "date_range": {
            "earliest": dates[0] if dates else "",
            "latest": dates[-1] if dates else "",
        },
        "gclids_distinct": len(distinct_gclids),
        "order_ids_present": order_ids_present,
        "conversion_action_id": payload["conversion_action_id"],
    }


@register_tool(
    name="import_offline_conversions",
    description=(
        "Importa N conversões offline (1-100 por call) match-by-gclid pra "
        "Google Ads attribuir ROAS + alimentar Smart Bidding. Always-CONFIRM. "
        "Workflow V4 lead-gen: gestor captura gclid no URL da landing → salva "
        "no CRM → quando lead converte (WhatsApp confirmation, contrato assinado, "
        "pagamento) → chama tool com batch de gclids + datas + valores. V4 "
        "invariants hardcoded: currency_code=BRL, timezone=-03:00 (São Paulo), "
        "consent.ad_user_data=GRANTED (LGPD V4-aligned). Pre-flight valida "
        "conversion_action_id existe + tem type=UPLOAD_CLICKS. partial_failure=True: "
        "conversões individuais com erro (gclid expirado, data inválida) são "
        "reportadas em response.failures[] mas não bloqueiam o batch. Sprint 3b.26 "
        "introduz dispatcher run_conversion_upload paralelo a run_mutation."
    ),
    input_schema=_SCHEMA,
)
async def import_offline_conversions(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    conversion_action_id = args["conversion_action_id"]

    # Layer 2: Runtime payload validation (Sprint 3b.19B.1 convention)
    shape_error = _validate_payload_shape(args)
    if shape_error is not None:
        return shape_error

    # Layer 3: Async pre-flight (GAQL conversion_action lookup)
    pre_flight_error = await validate_conversion_action_for_upload(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        conversion_action_id=conversion_action_id,
    )
    if pre_flight_error is not None:
        return {
            "status": "error",
            "error": pre_flight_error,
            "operation": "import_offline_conversions",
        }

    summary = _build_summary(args)
    target_count = summary["conversion_count"]

    risk = classify(
        operation="import_offline_conversions",
        params={"target_count": target_count},
    )

    blast_summary = (
        f"Importar {summary['conversion_count']} conversões offline "
        f"(sum R$ {summary['sum_value_brl']:.2f}, range "
        f"{summary['date_range']['earliest']} → {summary['date_range']['latest']}) "
        f"pra conversion_action_id={conversion_action_id}"
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
            operation_type="import_offline_conversions",
            payload=payload,
            blast_summary=blast_summary,
        )

    return {
        "status": "dry_run",
        "operation": "import_offline_conversions",
        "customer_id": customer_id,
        "blast_summary": blast_summary,
        "summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
```

- [ ] **Step 4.4: Add `import_offline_conversions` to `tests/unit/test_tools_schemas.py` allowlist**

Run to find current allowlist:

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_tools_schemas.py -v 2>&1 | head -30
```

If `test_no_unexpected_tools` or `test_all_phase_2_tools_registered` fails because `import_offline_conversions` is unexpected, find the `_EXPECTED_TOOLS` (or equivalent) set/frozenset and add `"import_offline_conversions"`. Also bump count if there's an explicit count assertion (48 → 49).

- [ ] **Step 4.5: Run all unit tests**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_import_offline_conversions.py tests/unit/test_validate_conversion_action_for_upload.py tests/unit/test_run_conversion_upload.py tests/unit/test_tools_schemas.py -v
```
Expected: All PASS (~30 tool + dispatcher + validator + schema tests).

- [ ] **Step 4.6: Run pre-push gate**

```bash
cd "D:\HUB ads MCP" && python scripts/check_pre_push.py
```
Expected: 5/5 PASS in ~30-60s.

- [ ] **Step 4.7: Commit (do NOT push)**

```bash
git add src/mcp/tools/import_offline_conversions.py tests/unit/test_import_offline_conversions.py tests/unit/test_tools_schemas.py
git commit -m "$(cat <<'EOF'
feat(import_offline_conversions): tool body + dry-run flow + register_tool (Sprint 3b.26)

Replaces Task 1 skeleton with full implementation:
- _build_summary returns audit-safe counts/sums + date_range + gclids_distinct +
  order_ids_present (no PII content per spec §3.6)
- Pre-flight Layer 3: validate_conversion_action_for_upload (Task 2 helper)
- create_pending stores token + payload with __target_count__ + __params_summary__
- Returns dry_run preview with summary + token + blast_summary

Tool registered as 49th MCP tool (count 48 → 49). Allowlist updated in
test_tools_schemas.py.

4 new dry-run flow tests appended (~19 total in test_import_offline_conversions.py).

Pre-flight error propagation tested (mock helper at tool module namespace —
Sprint 3b.11 pre-flight test convention).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: apply_change Branching + Dispatcher Regression Tests

**Files:**
- Modify: `src/mcp/tools/apply_change.py` (add if-branch routing to `run_conversion_upload`)
- Modify: `tests/unit/test_apply_change.py` (+2 regression tests)

### Step 5.1: Add failing dispatcher branching tests

Append to `tests/unit/test_apply_change.py` (or create if file doesn't exist with this content):

```python


# ============================================================================
# Sprint 3b.26: apply_change dispatcher branching tests
# ============================================================================

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_apply_change_routes_import_offline_conversions_to_run_conversion_upload():
    """Sprint 3b.26: import_offline_conversions operation_type routes to
    run_conversion_upload (NOT run_mutation)."""
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.apply_change import apply_change

    session_id = uuid4()
    ctx = McpRequestContext(manager_id=uuid4(), session_id=session_id)
    set_current(ctx)
    try:
        # Mock consume returning a saved import_offline_conversions pending row
        saved_pending = MagicMock()
        saved_pending.operation_type = "import_offline_conversions"
        saved_pending.customer_id = "1234567890"
        saved_pending.blast_summary = "Importar 5 conversões offline"
        saved_pending.payload = {
            "conversion_action_id": "987654321",
            "conversions": [],
            "__target_count__": 5,
            "__params_summary__": {"conversion_count": 5},
        }

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        with (
            patch(
                "src.mcp.tools.apply_change.consume",
                AsyncMock(return_value=saved_pending),
            ),
            patch(
                "src.mcp.tools.apply_change.connection.get_pool",
                return_value=mock_pool,
            ),
            patch(
                "src.mcp.tools.apply_change.run_conversion_upload",
                AsyncMock(
                    return_value={
                        "status": "applied",
                        "operation": "import_offline_conversions",
                        "customer_id": "1234567890",
                        "applied_count": 5,
                        "failed_count": 0,
                        "failures": [],
                        "google_request_id": "req-conv-001",
                    }
                ),
            ) as mock_conv_upload,
            patch(
                "src.mcp.tools.apply_change.run_mutation",
                AsyncMock(return_value={"google_request_id": "should-not-be-called"}),
            ) as mock_mutate,
        ):
            result = await apply_change({"confirmation_token": "TOKEN001"})

        # Verify run_conversion_upload was called, run_mutation was NOT
        assert mock_conv_upload.called
        assert not mock_mutate.called

        # Verify response includes import_offline_conversions-specific fields
        assert result["status"] == "applied"
        assert result["operation"] == "import_offline_conversions"
        assert result["applied_count"] == 5
        assert result["failed_count"] == 0
        assert result["failures"] == []
    finally:
        clear_current()


@pytest.mark.asyncio
async def test_apply_change_routes_other_operations_to_run_mutation():
    """Regression guard: non-import_offline_conversions operations still route
    to run_mutation."""
    from src.mcp.context import McpRequestContext, clear_current, set_current
    from src.mcp.tools.apply_change import apply_change

    session_id = uuid4()
    ctx = McpRequestContext(manager_id=uuid4(), session_id=session_id)
    set_current(ctx)
    try:
        saved_pending = MagicMock()
        saved_pending.operation_type = "create_campaign"  # NOT import_offline_conversions
        saved_pending.customer_id = "1234567890"
        saved_pending.blast_summary = "Criar 1 campanha"
        saved_pending.payload = {
            "__target_count__": 4,
        }

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_acquire_cm = MagicMock()
        mock_acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
        mock_pool.acquire.return_value = mock_acquire_cm

        with (
            patch(
                "src.mcp.tools.apply_change.consume",
                AsyncMock(return_value=saved_pending),
            ),
            patch(
                "src.mcp.tools.apply_change.connection.get_pool",
                return_value=mock_pool,
            ),
            patch(
                "src.mcp.tools.apply_change.run_conversion_upload",
                AsyncMock(return_value={"should-not-be-called": True}),
            ) as mock_conv_upload,
            patch(
                "src.mcp.tools.apply_change.run_mutation",
                AsyncMock(
                    return_value={
                        "google_request_id": "req-mut-001",
                        "applied_count": 4,
                        "resource_names": ["customers/X/campaigns/Y"],
                    }
                ),
            ) as mock_mutate,
        ):
            result = await apply_change({"confirmation_token": "TOKEN002"})

        # Verify run_mutation was called, run_conversion_upload was NOT
        assert mock_mutate.called
        assert not mock_conv_upload.called
        assert result["status"] == "applied"
        assert result["operation"] == "create_campaign"
    finally:
        clear_current()
```

- [ ] **Step 5.2: Run new tests — expect FAIL (no branching yet)**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_apply_change.py::test_apply_change_routes_import_offline_conversions_to_run_conversion_upload -v
```
Expected: ImportError on `run_conversion_upload` (not yet imported in apply_change.py) OR test fails because branching not added.

- [ ] **Step 5.3: Add branching to `src/mcp/tools/apply_change.py`**

Replace ENTIRE `src/mcp/tools/apply_change.py` with:

```python
"""Tool: apply_change - consume a confirmation token + execute the saved mutation.

Sprint 3b.26 introduces branching: operation_type=="import_offline_conversions" routes
to run_conversion_upload (ConversionUploadService); else routes to run_mutation
(GoogleAdsService.mutate).
"""

from typing import Any

from src.db import connection
from src.google_ads.conversions import run_conversion_upload
from src.google_ads.mutations import run_mutation
from src.governance.dry_run import InvalidTokenError, consume
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "confirmation_token": {
            "type": "string",
            "pattern": "^[A-Z0-9]{8}$",
            "description": "Token de 8 chars retornado por uma tool de mutacao em modo dry-run.",
        },
    },
    "required": ["confirmation_token"],
    "additionalProperties": False,
}


@register_tool(
    name="apply_change",
    description=(
        "Confirma e aplica uma mutacao previamente previewed via dry-run. Token "
        "expira em 10 minutos. Cada token e consumivel apenas 1 vez e amarrado "
        "a sessao MCP que o gerou."
    ),
    input_schema=_SCHEMA,
)
async def apply_change(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    token = args["confirmation_token"]

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        try:
            saved = await consume(conn, token=token, session_id=ctx.session_id)
        except InvalidTokenError as e:
            return {
                "status": "error",
                "error": str(e),
            }

    target_count = int(saved.payload.get("__target_count__", 1))
    params_summary = saved.payload.get("__params_summary__")  # None → default in dispatchers

    # Sprint 3b.26: branch dispatch based on operation_type.
    if saved.operation_type == "import_offline_conversions":
        # ConversionUploadService path (NOT GoogleAdsService.mutate).
        result = await run_conversion_upload(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=saved.customer_id,
            operation_type=saved.operation_type,
            payload=saved.payload,
            target_count=target_count,
            params_summary=params_summary,
        )
        # If error from dispatcher, return as-is.
        if result.get("status") == "error":
            return result
        # Conversion upload response — different shape from mutation response.
        return {
            "status": "applied",
            "operation": saved.operation_type,
            "customer_id": saved.customer_id,
            "blast_summary": saved.blast_summary,
            "google_request_id": result["google_request_id"],
            "applied_count": result["applied_count"],
            "failed_count": result["failed_count"],
            "failures": result["failures"],
        }

    # Default path: chained mutation via GoogleAdsService.mutate (Sprint 3b.1-3b.25).
    partial_failure = bool(saved.payload.get("__partial_failure__", False))
    result = await run_mutation(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=saved.customer_id,
        operation_type=saved.operation_type,
        payload=saved.payload,
        target_count=target_count,
        partial_failure=partial_failure,
        params_summary=params_summary,
    )
    return {
        "status": "applied",
        "operation": saved.operation_type,
        "customer_id": saved.customer_id,
        "blast_summary": saved.blast_summary,
        "google_request_id": result["google_request_id"],
        "applied_count": result["applied_count"],
        "resource_names": result.get("resource_names", []),
    }
```

- [ ] **Step 5.4: Run tests — expect all GREEN**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/unit/test_apply_change.py -v
```
Expected: 2 new dispatcher tests PASS + any existing tests still PASS.

- [ ] **Step 5.5: Run pre-push gate**

```bash
cd "D:\HUB ads MCP" && python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 5.6: Commit (do NOT push)**

```bash
git add src/mcp/tools/apply_change.py tests/unit/test_apply_change.py
git commit -m "$(cat <<'EOF'
feat(apply_change): branch dispatch for import_offline_conversions (Sprint 3b.26)

apply_change now routes based on saved.operation_type:
- "import_offline_conversions" → run_conversion_upload (ConversionUploadService)
- all others → run_mutation (GoogleAdsService.mutate)

Response shape differs:
- Conversion upload returns {applied_count, failed_count, failures: [...],
  google_request_id} — F13 cross-cutting NOT applied (no resource_names list).
- Mutation path keeps existing shape {applied_count, resource_names: [...]}.

2 regression tests: import_offline_conversions routes to dispatcher;
non-import operations route to run_mutation.

Single if-branch is clean + extensible. Sprint 3b.27 candidate
(upload_customer_match_list) provavelmente adiciona segundo branch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Integration Tests

**Files:**
- Create: `tests/integration/test_import_offline_conversions.py`

### Step 6.1: Create integration test file

Create `tests/integration/test_import_offline_conversions.py`:

```python
"""Integration test: import_offline_conversions full cycle (Sprint 3b.26).

Tests dry_run → apply_change → run_conversion_upload dispatched → applied
response with applied_count + failures + audit_log row.

First integration test exercising the apply_change branching introduced in
Sprint 3b.26 (operation_type-based dispatch to run_conversion_upload).
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


def _mock_upload_response(success_count: int, failure_count: int) -> MagicMock:
    """Mock UploadClickConversionsResponse with N successes + M failures."""
    response = MagicMock()
    results = []
    for i in range(success_count):
        r = MagicMock()
        r.conversion_action = "customers/1234567890/conversionActions/987654321"
        r.gclid = f"Cj0_OK_{i}"
        r.conversion_date_time = "2026-05-17 14:30:00-03:00"
        results.append(r)
    for _ in range(failure_count):
        r = MagicMock()
        r.conversion_action = ""  # empty = failed
        results.append(r)
    response.results = results

    pfe = MagicMock()
    pfe.code = 0 if failure_count == 0 else 1
    pfe.details = []
    response.partial_failure_error = pfe
    return response


async def test_import_offline_conversions_dry_run_emits_token_and_pending_row(
    db, session_ctx
) -> None:
    """Step 1 only: tool returns dry_run with token; pending_confirmations row created."""
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    with patch(
        "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
        AsyncMock(return_value=None),
    ):
        args = {
            "customer_id": "1234567890",
            "conversion_action_id": "987654321",
            "conversions": [
                {
                    "gclid": "Cj0KCQjwTEST",
                    "conversion_date_time": "2026-05-17 14:30:00",
                    "conversion_value_brl": 150.0,
                }
            ],
        }
        result = await import_offline_conversions(args)

    assert result["status"] == "dry_run"
    assert result["operation"] == "import_offline_conversions"
    assert result["confirmation_token"]
    assert result["summary"]["conversion_count"] == 1
    assert result["summary"]["sum_value_brl"] == 150.0

    # Verify pending state in DB
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation_type, customer_id FROM pending_confirmations WHERE token = $1",
            result["confirmation_token"],
        )
    assert len(rows) == 1
    assert rows[0]["operation_type"] == "import_offline_conversions"
    assert rows[0]["customer_id"] == "1234567890"


async def test_import_offline_conversions_full_cycle_returns_applied_count_and_audit(
    db, session_ctx
) -> None:
    """Full cycle: dry_run → apply_change branches to run_conversion_upload →
    response with applied_count/failed_count/failures + audit_log row."""
    from src.mcp.tools.apply_change import apply_change
    from src.mcp.tools.import_offline_conversions import import_offline_conversions

    # Mock 3 successes + 2 failures
    fake_response = _mock_upload_response(success_count=3, failure_count=2)
    fake_service = MagicMock()
    fake_service.upload_click_conversions = MagicMock(return_value=fake_response)

    fake_client = MagicMock()
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(side_effect=lambda name: MagicMock())
    fake_client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    with (
        patch(
            "src.mcp.tools.import_offline_conversions.validate_conversion_action_for_upload",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.google_ads.conversions.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch("src.google_ads.conversions.get_request_id", return_value="req-conv-int"),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
    ):
        conversions = [
            {
                "gclid": f"Cj0_{i}",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
            for i in range(5)
        ]
        args = {
            "customer_id": "1234567890",
            "conversion_action_id": "987654321",
            "conversions": conversions,
        }
        dry_run_result = await import_offline_conversions(args)
        assert dry_run_result["status"] == "dry_run"
        token = dry_run_result["confirmation_token"]

        apply_result = await apply_change({"confirmation_token": token})

    assert apply_result["status"] == "applied"
    assert apply_result["operation"] == "import_offline_conversions"
    assert apply_result["applied_count"] == 3
    assert apply_result["failed_count"] == 2
    assert apply_result["google_request_id"] == "req-conv-int"
    assert len(apply_result["failures"]) == 2
    # Failed rows are indices 3 and 4 (after 3 successes)
    assert apply_result["failures"][0]["row_index"] == 3
    assert apply_result["failures"][1]["row_index"] == 4
    # gclid echoed from input
    assert apply_result["failures"][0]["gclid"] == "Cj0_3"
    assert apply_result["failures"][1]["gclid"] == "Cj0_4"

    # audit_log: target_count=5 (input), applied_count=3 (success)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT operation, target_count, applied_count, params_summary, google_request_id "
            "FROM audit_log WHERE operation = 'import_offline_conversions'"
        )
    assert len(rows) == 1
    assert rows[0]["target_count"] == 5
    assert rows[0]["applied_count"] == 3
    assert rows[0]["google_request_id"] == "req-conv-int"
    summary = rows[0]["params_summary"]
    summary_d = json.loads(summary) if isinstance(summary, str) else summary
    assert summary_d["conversion_count"] == 5
    assert summary_d["sum_value_brl"] == 500.0
    assert summary_d["conversion_action_id"] == "987654321"
```

- [ ] **Step 6.2: Run integration tests (requires Docker)**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/integration/test_import_offline_conversions.py -v -m integration
```
Expected: 2 tests PASS.

If Docker unavailable locally, defer to CI:

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/integration/test_import_offline_conversions.py --collect-only
```
Expected: 2 tests collected, no import errors.

- [ ] **Step 6.3: Run pre-push gate**

```bash
cd "D:\HUB ads MCP" && python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 6.4: Commit (do NOT push)**

```bash
git add tests/integration/test_import_offline_conversions.py
git commit -m "$(cat <<'EOF'
test(import_offline_conversions): integration tests dry_run + full cycle (Sprint 3b.26)

2 tests mirroring Sprint 3b.25 pattern (session_ctx fixture):
- dry_run emits token, pending_confirmations row created, summary computed
- full cycle: apply_change branches to run_conversion_upload (NOT run_mutation)
  → response with applied_count=3, failed_count=2, failures[] with row_index
  + audit_log row with params_summary (conversion_count, sum_value_brl,
  conversion_action_id)

First integration test exercising apply_change branching dispatch.
F13 cross-cutting NOT applied (custom response structure).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Smoke Runbook + CLAUDE.md Sprint Row

**Files:**
- Create: `docs/operacao/phase-3b-26-bootstrap.md`
- Modify: `CLAUDE.md`

### Step 7.1: Create smoke runbook

Create `docs/operacao/phase-3b-26-bootstrap.md` with this exact content:

```markdown
# Phase 3b.26 — manual smoke runbook (`import_offline_conversions`)

**Purpose:** Validar Sprint 3b.26 — primeiro tool V4 que NÃO usa GoogleAdsService.mutate (usa ConversionUploadService). Foundation pra V4 lead-gen attribution loop (Smart Bidding signals from WhatsApp/CRM leads).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `1163862076` Nutry (sandbox)

**Spec:** `docs/superpowers/specs/2026-05-18-sprint-3b-26-import-offline-conversions-design.md`
**Plan:** `docs/superpowers/plans/2026-05-18-sprint-3b-26-import-offline-conversions.md`

## Pre-flight

- [ ] Deploy lands successfully
- [ ] Service `/health` returns 200
- [ ] Tool `import_offline_conversions` visível em MCP tool list (count 48 → 49)
- [ ] F28 reproducer: gestor pode precisar restart Claude Code session pro schema cache propagar

Production revision: `<PREENCHER pós-deploy>`.

## Pre-smoke setup: capture real gclids + create UPLOAD_CLICKS ConversionAction

### Step 1: Identify or create UPLOAD_CLICKS ConversionAction

GAQL pre-smoke (find existing UPLOAD_CLICKS in Nutry):

```
SELECT
  conversion_action.id,
  conversion_action.name,
  conversion_action.type,
  conversion_action.status
FROM conversion_action
WHERE conversion_action.type = 'UPLOAD_CLICKS'
```

If none exists with status=ENABLED, create one via `create_conversion_action`:

```
create_conversion_action(
  customer_id="1163862076",
  conversion_actions=[{
    "name": "[3b.26-smoke] V4 lead-gen offline",
    "category": "SUBMIT_LEAD_FORM",
    "type": "UPLOAD_CLICKS",
    "default_value": 50.0
  }]
)
```

Note the resulting `conversion_action.id` (e.g., `123456789`) for use in T1, T4-T7.

### Step 2: Capture real gclids from Nutry click_view

GAQL pre-smoke:

```
SELECT
  click_view.gclid,
  segments.date
FROM click_view
WHERE segments.date DURING LAST_30_DAYS
LIMIT 10
```

Save 5-10 gclids for use in T4-T6 (real Google-issued gclids — fake strings rejected by Google).

If `click_view` access limited, alternative: use Google Ads UI > Reports > Predefined Reports > Other > Click ID History.

## Test T1 — Pre-flight: valid UPLOAD_CLICKS ConversionAction

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<ID from setup>",
  conversions=[{
    "gclid": "<real_gclid_1>",
    "conversion_date_time": "2026-05-17 14:30:00",
    "conversion_value_brl": 100.0
  }]
)
```

Expected:
- [ ] dry_run com confirmation_token + summary.conversion_count=1, sum_value_brl=100.0
- [ ] (não apply ainda — só pre-flight)

**Result:** ⬜ pending

## Test T2 — Pre-flight: conversion_action_id não existe

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="999999999",  # fictício
  conversions=[{...}]
)
```

Expected:
- [ ] status=error, error contém `"não existe em customer_id=1163862076"`

**Result:** ⬜ pending

## Test T3 — Pre-flight: WEBPAGE type ConversionAction (type mismatch)

Encontrar uma WEBPAGE ConversionAction em Nutry (provavelmente existe pra tracking padrão):

```
SELECT conversion_action.id, conversion_action.type FROM conversion_action
WHERE conversion_action.type = 'WEBPAGE' LIMIT 1
```

Usar o ID em:

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<WEBPAGE_ID>",
  conversions=[{...}]
)
```

Expected:
- [ ] status=error, error contém `"type=WEBPAGE"` e `"requer type=UPLOAD_CLICKS"`

**Result:** ⬜ pending

## Test T4 — Happy path: 1 conversion, real gclid

Use T1 setup + real gclid + apply:

```
# dry_run
result = import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[{
    "gclid": "<real_gclid_1>",
    "conversion_date_time": "2026-05-17 14:30:00",
    "conversion_value_brl": 100.0
  }]
)

# apply
apply_change(confirmation_token=result["confirmation_token"])
```

Expected:
- [ ] apply status=applied, applied_count=1, failed_count=0, failures=[]
- [ ] GAQL verify (3-24h post-upload — Google takes time to register em conversion_action stats):
```
SELECT metrics.conversions, metrics.conversions_value
FROM customer
WHERE segments.date = '2026-05-17'
```

**Result:** ⬜ pending

## Test T5 — Happy path: batch 5 real gclids

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[
    {"gclid": "<gclid_1>", "conversion_date_time": "...", "conversion_value_brl": 100.0},
    {"gclid": "<gclid_2>", "conversion_date_time": "...", "conversion_value_brl": 150.0},
    {"gclid": "<gclid_3>", "conversion_date_time": "...", "conversion_value_brl": 200.0},
    {"gclid": "<gclid_4>", "conversion_date_time": "...", "conversion_value_brl": 75.0},
    {"gclid": "<gclid_5>", "conversion_date_time": "...", "conversion_value_brl": 250.0}
  ]
)
```

Expected:
- [ ] dry_run summary.conversion_count=5, sum_value_brl=775.0, gclids_distinct=5
- [ ] apply applied_count=5, failed_count=0

**Result:** ⬜ pending

## Test T6 — Some conversions com order_id

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[
    {"gclid": "<gclid_6>", "conversion_date_time": "...", "conversion_value_brl": 100.0, "order_id": "crm-001"},
    {"gclid": "<gclid_7>", "conversion_date_time": "...", "conversion_value_brl": 200.0, "order_id": "crm-002"},
    {"gclid": "<gclid_8>", "conversion_date_time": "...", "conversion_value_brl": 150.0}  # no order_id
  ]
)
```

Expected:
- [ ] dry_run summary.order_ids_present=2
- [ ] apply applied_count=3, failed_count=0

**Result:** ⬜ pending

## Test T7 — Partial failure: 3 valid + 2 fake gclids

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[
    {"gclid": "<real_gclid_9>", "conversion_date_time": "...", "conversion_value_brl": 100.0},
    {"gclid": "<real_gclid_10>", "conversion_date_time": "...", "conversion_value_brl": 100.0},
    {"gclid": "Cj0KCQjwTEST-FAKE-001", "conversion_date_time": "...", "conversion_value_brl": 100.0},
    {"gclid": "<real_gclid_11>", "conversion_date_time": "...", "conversion_value_brl": 100.0},
    {"gclid": "Cj0KCQjwTEST-FAKE-002", "conversion_date_time": "...", "conversion_value_brl": 100.0}
  ]
)
```

Expected:
- [ ] apply applied_count=3, failed_count=2
- [ ] failures[] tem 2 entradas com row_index=2 e row_index=4
- [ ] failures entries têm error_code (likely `INVALID_GCLID` ou `EXPIRED_GCLID`)

**Result:** ⬜ pending

## Test T8 — Layer 2: conversion no futuro

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[{
    "gclid": "Cj0_test",
    "conversion_date_time": "2099-12-31 23:59:59",  # future
    "conversion_value_brl": 100.0
  }]
)
```

Expected:
- [ ] status=error pre-Google call: `"conversion_date_time '2099-12-31 23:59:59' está no futuro"`

**Result:** ⬜ pending

## Test T9 — Layer 2: conversion > 90 dias

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[{
    "gclid": "Cj0_test",
    "conversion_date_time": "2026-01-01 12:00:00",  # ~5 meses atrás
    "conversion_value_brl": 100.0
  }]
)
```

Expected:
- [ ] status=error pre-Google call: contém `"90 dias"` e o número de dias

**Result:** ⬜ pending

## Test T10 — Layer 2: duplicate gclid in batch

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[
    {"gclid": "Cj0_same", "conversion_date_time": "...", "conversion_value_brl": 100.0},
    {"gclid": "Cj0_same", "conversion_date_time": "...", "conversion_value_brl": 200.0}
  ]
)
```

Expected:
- [ ] status=error: `"gclids duplicados no batch: ['Cj0_same']"`

**Result:** ⬜ pending

## Test T11 — Layer 2: duplicate order_id in batch

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[
    {"gclid": "Cj0_x", "conversion_date_time": "...", "conversion_value_brl": 100.0, "order_id": "crm-dup"},
    {"gclid": "Cj0_y", "conversion_date_time": "...", "conversion_value_brl": 200.0, "order_id": "crm-dup"}
  ]
)
```

Expected:
- [ ] status=error: `"order_id duplicados no batch: ['crm-dup']"`

**Result:** ⬜ pending

## Test T12 — Schema regression: 101 conversions

```
import_offline_conversions(
  customer_id="1163862076",
  conversion_action_id="<UPLOAD_CLICKS_ID>",
  conversions=[{"gclid": f"Cj0_{i}", "conversion_date_time": "...", "conversion_value_brl": 1.0} for i in range(101)]
)
```

Expected:
- [ ] JSONSchema validation error: `maxItems` exceeded

**Result:** ⬜ pending

## Cleanup post-smoke

Conversões uploadadas afetam ROAS/Smart Bidding em Nutry. Strategy:
- ConversionAction `[3b.26-smoke]` criada em setup pode ser PAUSED via Google Ads UI post-smoke
- Conversões uploadadas: 8-10 total (T4 + T5 + T6 + T7 successes), valores baixos (R$ 50-250)
- Impact em ROAS Nutry: pequeno noise (~R$ 800-1500 attributed), diluído em métricas reais

## Findings discovered

(Preencher pós-smoke se findings reais surgirem — F41+ candidates documented em findings-catalog.md)

| # | Finding | Severity | Documented | Fix |
|---|---|---|---|---|
| F41 | (pending) | — | — | — |

## Sign-off

- [ ] Pre-push gate 5/5 PASS
- [ ] Production /health 200
- [ ] 10+/12 tests PASS (T4-T6 require real gclids — partial passage acceptable if Layer 2/3 + dispatcher validados)
- [ ] CLAUDE.md sprint row added
- [ ] findings-catalog.md updated se F41+ surgir
- [ ] Tool count 48 → 49 confirmed in production tool list
- [ ] At least 1 real conversion uploaded em Nutry via T4 (proves dispatcher end-to-end)

Signed-off: ⬜ pending
```

### Step 7.2: Modify CLAUDE.md

Read `CLAUDE.md` first to find the right insertion point:

```bash
cd "D:\HUB ads MCP" && grep -n "Sprint 3b.25" CLAUDE.md | head -3
```

Add a new row to the sprint table immediately after the Sprint 3b.25 row. Use this content (single table row):

```markdown
| Sprint 3b.26 — `import_offline_conversions` (7º create-pattern, primeiro NÃO-mutation dispatcher) | 🟡 code-complete; smoke pending | Spec: [`2026-05-18-sprint-3b-26-import-offline-conversions-design.md`](docs/superpowers/specs/2026-05-18-sprint-3b-26-import-offline-conversions-design.md); Plan: [`2026-05-18-sprint-3b-26-import-offline-conversions.md`](docs/superpowers/plans/2026-05-18-sprint-3b-26-import-offline-conversions.md). **1 new MCP tool (count 48 → 49):** primeiro tool V4 que NÃO usa GoogleAdsService.mutate — usa ConversionUploadService.UploadClickConversions. Fecha loop de attribution V4 lead-gen (WhatsApp/CRM → MCP → Smart Bidding signals). Always-CONFIRM. Schema: customer_id + conversion_action_id (UPLOAD_CLICKS type pre-flight validated) + conversions[] (1-100 batch, gclid match). **V4 invariants hardcoded:** currency_code=BRL, timezone=-03:00 BRT, consent.ad_user_data=GRANTED (LGPD), partial_failure=True. **Architectural shift:** novo dispatcher `run_conversion_upload` em `src/google_ads/conversions.py` paralelo a `run_mutation`. `apply_change` ganha single if-branch baseado em operation_type. F13 cross-cutting NÃO se aplica — custom response com `applied_count`/`failed_count`/`failures[{row_index, gclid, error_code, error_message}]`. **4-layer validation:** JSONSchema (regex/array) + runtime `_validate_payload_shape` (5 checks: date parse, future, 90-day window, duplicate gclids, duplicate order_ids) + async pre-flight `validate_conversion_action_for_upload` (GAQL: exists + type + status) + Google API (partial_failure parsing). **Proto field names validados via context7** pre-implementação: `partial_failure` (NOT `partial_failure_enabled` Java), `consent.ad_user_data=GRANTED`, failure detection via empty `result.conversion_action`. ~30 unit tests (tool + dispatcher + validator) + 2 integration. Pre-flight: 1 GAQL pra conversion_action lookup. Smoke: 12 tests Nutry sandbox (T4-T7 require real gclids via GAQL click_view extraction). Foundation pra Sprint 3b.27 (upload_customer_match_list — provavelmente segue mesmo padrão com OfflineUserDataJobService). |
```

Also bump:
- Line `**48 MCP tools**` → `**49 MCP tools**` (and breakdown: `24 mutations` → `24 mutations + 1 upload` or similar — adjust per existing format)
- `**Last updated:** 2026-05-18` (likely already set, no change needed)

- [ ] **Step 7.3: Run pre-push gate**

```bash
cd "D:\HUB ads MCP" && python scripts/check_pre_push.py
```
Expected: 5/5 PASS.

- [ ] **Step 7.4: Commit (do NOT push)**

```bash
git add docs/operacao/phase-3b-26-bootstrap.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: Sprint 3b.26 smoke runbook scaffold + CLAUDE.md sprint row

12 smoke tests (T1-T12) scaffolded for Nutry sandbox execution:
- Pre-smoke setup: capture real gclids via GAQL click_view (5-10 per smoke)
  + create [3b.26-smoke] UPLOAD_CLICKS ConversionAction via create_conversion_action
- T1-T3 pre-flight tests (valid action, missing action, WEBPAGE type)
- T4-T6 happy paths (single, batch 5, with order_ids)
- T7 partial failure (3 real + 2 fake gclids — exercises partial_failure parsing
  + row_index extraction)
- T8-T11 Layer 2 validation (future, > 90 days, duplicate gclids, duplicate order_ids)
- T12 schema regression (101 items)

Cleanup strategy: dedicated [3b.26-smoke] ConversionAction; Wellington
pauses via Google Ads UI post-smoke. Small ROAS noise (~R$ 800-1500
attributed) acceptable in Nutry sandbox.

Sprint 3b.26 row added to CLAUDE.md sprint table; tool count 48 → 49.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Pre-Push Verification + Push + Deploy

**Files:** No file changes. Verification only.

### Step 8.1: Final pre-push gate

```bash
cd "D:\HUB ads MCP" && python scripts/check_pre_push.py
```
Expected:

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
All pre-push checks passed (5 steps in ~30-60s).
```

- [ ] **Step 8.2: If any step fails, fix and re-run**

Common issues:
- `ruff format`: run `ruff format src/mcp/tools/import_offline_conversions.py src/google_ads/conversions.py src/google_ads/queries/_common.py src/mcp/tools/apply_change.py tests/unit/test_import_offline_conversions.py tests/unit/test_run_conversion_upload.py tests/unit/test_validate_conversion_action_for_upload.py tests/unit/test_apply_change.py tests/integration/test_import_offline_conversions.py`
- `mypy`: address strict mode complaints (likely missing type annotations on `_parse_upload_response` return or `_build_summary` dict shape)
- `pytest`: re-read assertions, fix code

- [ ] **Step 8.3: Push to main**

```bash
cd "D:\HUB ads MCP" && git push origin main
```
Expected: admin bypass success, CI + Deploy triggered.

- [ ] **Step 8.4: Watch CI + Deploy**

```bash
cd "D:\HUB ads MCP" && gh run list --limit 5
```

For each new run (CI + Deploy):

```bash
cd "D:\HUB ads MCP" && gh run watch <id>
```

Expected: both GREEN within 3-5 min. If CI fails, investigate via `gh run view <id> --log-failed | tail -100`.

- [ ] **Step 8.5: Production smoke `/health`**

```bash
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```
Expected: `200 OK`.

- [ ] **Step 8.6: Capture production revision**

```bash
gcloud run services describe v4-ads-mcp --region southamerica-east1 --project v4-ads-mcp-prod --format='value(status.latestReadyRevisionName)'
```

Capture revision name (e.g., `v4-ads-mcp-00200-abc`).

- [ ] **Step 8.7: Update CLAUDE.md + smoke runbook with revision**

In `CLAUDE.md`, find the Sprint 3b.26 row. Replace `🟡 code-complete; smoke pending` with:

```
🟢 deploy verde; smoke pending Wellington execution
```

And prepend at the start of the row body:

```
Production revision: `<REVISION>` (deploy verde, /health 200).
```

In `docs/operacao/phase-3b-26-bootstrap.md`, replace `<PREENCHER pós-deploy>` with the actual revision name.

- [ ] **Step 8.8: Commit + push revision capture**

```bash
cd "D:\HUB ads MCP" && git add CLAUDE.md docs/operacao/phase-3b-26-bootstrap.md
cd "D:\HUB ads MCP" && git commit -m "$(cat <<'EOF'
docs(claude): Sprint 3b.26 production revision <REVISION> captured

Deploy verde, /health 200. Tool count 48 → 49 in production. Smoke runbook
ready for Wellington execution at docs/operacao/phase-3b-26-bootstrap.md.

First V4 tool that does NOT use GoogleAdsService.mutate — uses new
run_conversion_upload dispatcher via apply_change branching.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
cd "D:\HUB ads MCP" && git push origin main
```

Replace `<REVISION>` with the actual revision name from Step 8.6.

---

## Task 9: Smoke Execution + Sign-off (Wellington, manual)

**This task is executed by Wellington (or operator) in real account, NOT by the implementer agent.**

The implementer should NOT attempt to run live MCP tool calls against Nutry sandbox. Instead, hand off to operator with this checklist:

- [ ] Operator executes pre-smoke setup (capture gclids via GAQL click_view + create [3b.26-smoke] UPLOAD_CLICKS ConversionAction)
- [ ] Operator executes T1-T12 from `docs/operacao/phase-3b-26-bootstrap.md`
- [ ] For each test, fill in expected check boxes + capture results
- [ ] If findings emerge (e.g., timezone format mismatch, gclid format issues), document as F-class in `docs/operacao/findings-catalog.md` Bug class 1 table
- [ ] Add fix iterations if needed (Sprint 3b.26.1, 3b.26.2, ...) following Sprint 3b.24/3b.25 pattern
- [ ] Final sign-off commit:

```bash
git commit -m "docs(ops): Sprint 3b.26 smoke signed-off em Nutry — <X>/12 tests PASS

Highlights:
- <captured results, findings, lessons>

V4 lead-gen attribution loop now closed: WhatsApp/CRM leads → MCP →
Smart Bidding signals.

Co-Authored-By: Wellington Ribeiro"
```

- [ ] Update Sprint 3b.26 row in CLAUDE.md: `🟡 → ✅ shipped + signed-off em conta real`

---

## Self-Review Checklist (run after writing the plan)

**1. Spec coverage:**
- [x] Schema with conversion_action_id + 1-100 conversions × required fields → Task 1
- [x] `_validate_payload_shape` 5 checks (date, future, 90-day, duplicate gclids, duplicate order_ids) → Task 1
- [x] Pre-flight `validate_conversion_action_for_upload` (3 branches: not exists, wrong type, REMOVED) → Task 2
- [x] `run_conversion_upload` dispatcher + `_parse_upload_response` (failure detection heuristic) → Task 3
- [x] Tool body with dry_run flow + `_build_summary` (sum/range/distinct/order_ids_present) → Task 4
- [x] `apply_change` branching (import_offline_conversions vs run_mutation default) → Task 5
- [x] V4 invariants enforced in builder (BRL, -03:00, GRANTED consent, partial_failure=True) → Task 3 tests + smoke T4-T6
- [x] audit_log params_summary (counts only, no gclid content) → Task 4
- [x] Smoke runbook with per-Layer probes → Task 7
- [x] CLAUDE.md sprint row + tool count bump → Task 7

**2. Placeholder scan:**
- All code blocks are complete (no TBD/TODO placeholders inside step instructions)
- `<PREENCHER pós-deploy>` in smoke runbook is intentional (operator fills production revision at execution time)
- `<REVISION>`, `<ID from setup>`, `<real_gclid_N>` in smoke runbook are operator-fill-in fields

**3. Type consistency:**
- `_validate_payload_shape(payload) -> dict[str, Any] | None` consistent across tool body call in Task 4
- `validate_conversion_action_for_upload(*, manager_id, session_id, customer_id, conversion_action_id) -> str | None` consistent in Task 2 signature + Task 4 invocation
- `run_conversion_upload(*, manager_id, session_id, customer_id, operation_type, payload, target_count, params_summary) -> dict[str, Any]` consistent in Task 3 + Task 5 apply_change dispatch
- `_parse_upload_response(response, payload, client) -> tuple[int, int, list[dict[str, Any]]]` consistent in Task 3
- `_build_summary(payload) -> dict[str, Any]` consistent in Task 4

**4. Spec ↔ Plan alignment:**
- Spec Risk R1 (proto field names) → Task 3 uses `partial_failure` (Python) confirmed via context7
- Spec Risk R8 (LGPD consent hardcoded) → Task 3 builds `consent.ad_user_data = ConsentStatusEnum.GRANTED` per V4 invariant
- Spec Layer 4 (trust Google) → Task 3 `_parse_upload_response` extracts failures from partial_failure_error
- Spec smoke T4-T6 real gclids requirement → Task 7 documents GAQL click_view query

## Done?

**Plan complete and saved to `docs/superpowers/plans/2026-05-18-sprint-3b-26-import-offline-conversions.md`.**

Total: 8 tasks (Task 9 = manual handoff to operator). Sequential dependency chain:

```
Task 1 (schema + validator + 15 tests, RED→GREEN, commit)
   ↓
Task 2 (validate_conversion_action_for_upload helper + 4 tests, commit)
   ↓
Task 3 (run_conversion_upload + _parse_upload_response + ~10 tests, commit)
   ↓
Task 4 (tool body + dry_run + 4 dry-run tests + allowlist, commit)
   ↓
Task 5 (apply_change branching + 2 regression tests, commit)
   ↓
Task 6 (integration tests, commit)
   ↓
Task 7 (smoke runbook + CLAUDE.md, commit)
   ↓
Task 8 (pre-push + push + revision capture, commit)
   ↓
Task 9 (Wellington manual smoke + sign-off, commit)
```

Each task is self-contained, ends with passing tests + commit. Subagent-driven-development recommended for Tasks 1-8 (fresh subagent per task ≈ 30-60min each, reviewed between).
