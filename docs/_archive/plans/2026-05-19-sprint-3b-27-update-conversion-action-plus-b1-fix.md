# Sprint 3b.27 — update_conversion_action + B1/F43 fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shippar combo Sprint 3b.27 até 22/05: nova tool MCP `update_conversion_action` (3 fields V0: name + primary_for_goal + include_in_conversions_metric) + fix B1/F43 (pre-flight async em `update_keyword_status` que separa positive vs negative criterion_ids). Atende prazo MO 23/05.

**Architecture:** Pattern unificado pre-flight async via GAQL. Tool nova segue template `update_keyword_bid` (Sprint 3b.8): Layer 1 schema + Layer 2 sync validation + Layer 3 async GAQL pre-flight + classify() + run_mutation. Fix B1 adiciona Layer 3 pre-flight em tool existente com hard-reject + listas positive_safe/negative_blocked.

**Tech Stack:** Python 3.12, mcp>=1.2.0, google-ads>=27.0.0 (v24 proto), asyncpg, pydantic, pytest + testcontainers + proto_capture fixture, ruff + mypy strict. Cloud Run deploy via GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix-design.md`](../specs/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix-design.md)

---

## File structure

### Phase A: `update_conversion_action` tool

| Arquivo | Action | Responsabilidade |
|---|---|---|
| `src/google_ads/queries/_common.py` | Modify (append) | Adicionar helper `validate_conversion_actions_exist` (Layer 3 pre-flight) |
| `src/mcp/tools/update_conversion_action.py` | Create | Tool MCP nova (Layer 1 schema + Layer 2 sync validation + router pra Layer 3 + classify + run_mutation/create_pending) |
| `src/google_ads/mutates/conversion_actions.py` | Modify (append) | Builder `build_update_conversion_action` via `@register_builder` |
| `src/governance/blast_radius.py` | Modify | Adicionar entry `update_conversion_action` em `classify()` |
| `tests/unit/test_update_conversion_action.py` | Create | Unit tests: schema regression + Layer 2 + builder (com proto_capture) + classify |
| `tests/unit/test_validate_conversion_actions_exist.py` | Create | Unit tests do helper (mock run_report) |
| `tests/integration/test_update_conversion_action.py` | Create | Integration test (mock helper no namespace da tool — convention pós-3b.5/3b.8) |

### Phase B: fix B1/F43

| Arquivo | Action | Responsabilidade |
|---|---|---|
| `src/google_ads/queries/_common.py` | Modify (append) | Helper `validate_keyword_criterion_types` (Layer 3 pre-flight) |
| `src/mcp/tools/update_keyword_status.py` | Modify | Adicionar chamada ao novo helper ANTES do classify; retornar error com listas separadas se reject |
| `tests/unit/test_validate_keyword_criterion_types.py` | Create | Unit tests do helper (mock run_report) |
| `tests/integration/test_keyword_mutations.py` | Modify | Adicionar 3 cases pro fix (mock helper no namespace de `update_keyword_status`) |

### Phase C: smoke + signoff

| Arquivo | Action | Responsabilidade |
|---|---|---|
| `docs/operacao/phase-3b-27-bootstrap.md` | Create (via subagent) | Smoke runbook 12 tests |
| `docs/operacao/findings-catalog.md` | Modify | F43 row open → Fixed Sprint 3b.27; summary Open 2→1 |
| `CLAUDE.md` | Modify | Sprint 3b.27 row shipped + tool count 49→50 |

---

# PHASE A — `update_conversion_action`

## Task A1: Helper `validate_conversion_actions_exist`

**Files:**
- Modify: `src/google_ads/queries/_common.py` (append at end of file)
- Test: `tests/unit/test_validate_conversion_actions_exist.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_validate_conversion_actions_exist.py`:

```python
"""Unit tests for validate_conversion_actions_exist helper (Sprint 3b.27)."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "1163862076"}


@pytest.mark.asyncio
async def test_all_actions_exist_and_enabled_returns_none(fake_ctx):
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [
        {"conversion_action": {"id": "123", "status": "ENABLED"}},
        {"conversion_action": {"id": "456", "status": "PAUSED"}},
    ]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "456"],
        )
    assert result is None


@pytest.mark.asyncio
async def test_missing_id_returns_missing_ids_dict(fake_ctx):
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [{"conversion_action": {"id": "123", "status": "ENABLED"}}]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "999"],
        )
    assert result is not None
    assert "missing_ids" in result
    assert result["missing_ids"] == ["999"]
    assert "não existe" in result["error"]


@pytest.mark.asyncio
async def test_removed_id_returns_removed_ids_dict(fake_ctx):
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [
        {"conversion_action": {"id": "123", "status": "ENABLED"}},
        {"conversion_action": {"id": "456", "status": "REMOVED"}},
    ]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "456"],
        )
    assert result is not None
    assert "removed_ids" in result
    assert result["removed_ids"] == ["456"]
    assert "REMOVED" in result["error"]


@pytest.mark.asyncio
async def test_missing_short_circuits_before_removed_check(fake_ctx):
    """If both missing and removed exist, missing takes priority (short-circuit)."""
    from src.google_ads.queries._common import validate_conversion_actions_exist

    rows = [{"conversion_action": {"id": "123", "status": "REMOVED"}}]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_conversion_actions_exist(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            conversion_action_ids=["123", "999"],  # 999 missing, 123 removed
        )
    assert "missing_ids" in result
    assert "removed_ids" not in result  # short-circuit
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_validate_conversion_actions_exist.py -v`
Expected: 4 FAIL with `ImportError: cannot import name 'validate_conversion_actions_exist'`

- [ ] **Step 3: Implement the helper**

Open `src/google_ads/queries/_common.py` and append at the end (after `validate_conversion_action_for_upload`):

```python
async def validate_conversion_actions_exist(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    conversion_action_ids: list[str],
) -> dict[str, Any] | None:
    """GAQL pre-flight: each ID exists + status != REMOVED.

    Returns:
        None if all valid
        dict with {error, missing_ids} OR {error, removed_ids} if issues.

    Missing IDs short-circuit before REMOVED check (cleaner error UX).

    Sprint 3b.27 — pre-flight for update_conversion_action tool.
    """
    ids_clause = ", ".join(str(int(cid)) for cid in conversion_action_ids)
    query = (
        "SELECT conversion_action.id, conversion_action.status "
        "FROM conversion_action "
        f"WHERE conversion_action.id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "conversion_action": {
                "id": str(row.conversion_action.id),
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
        operation_name="validate_conversion_actions_exist",
    )

    found_ids = {r["conversion_action"]["id"] for r in rows}
    missing = [cid for cid in conversion_action_ids if cid not in found_ids]
    if missing:
        return {
            "error": (
                f"conversion_action_ids não encontrados em customer_id={customer_id}: "
                f"{missing}. Verifique IDs via get_conversion_actions(customer_id='{customer_id}')."
            ),
            "missing_ids": missing,
        }

    removed = [
        r["conversion_action"]["id"]
        for r in rows
        if r["conversion_action"]["status"] == "REMOVED"
    ]
    if removed:
        return {
            "error": (
                f"conversion_action_ids com status=REMOVED não aceitam updates: {removed}. "
                f"Para reativar, use Google Ads UI (sem tool MCP dedicada hoje)."
            ),
            "removed_ids": removed,
        }

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_validate_conversion_actions_exist.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run lint + format + mypy**

Run: `.venv/Scripts/python -m ruff check src/google_ads/queries/_common.py tests/unit/test_validate_conversion_actions_exist.py && .venv/Scripts/python -m ruff format --check src/google_ads/queries/_common.py tests/unit/test_validate_conversion_actions_exist.py && .venv/Scripts/python -m mypy src/google_ads/queries/_common.py`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add src/google_ads/queries/_common.py tests/unit/test_validate_conversion_actions_exist.py
git commit -m "$(cat <<'EOF'
feat(mcp): add validate_conversion_actions_exist helper

Sprint 3b.27 — Layer 3 pre-flight pra update_conversion_action tool nova.
GAQL pre-flight 1 query: SELECT conversion_action.id, status FROM
conversion_action WHERE id IN (...). Returns dict com missing_ids ou
removed_ids se problema; None se OK. Missing IDs curto-circuita antes
do REMOVED check.

4 unit tests cobrem happy path + missing + removed + short-circuit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A2: classify() risk entry for `update_conversion_action`

**Files:**
- Modify: `src/governance/blast_radius.py`
- Test: `tests/unit/test_blast_radius.py` (append cases)

- [ ] **Step 1: Read existing classify() pattern**

Run: `grep -n "elif operation ==" src/governance/blast_radius.py`
Familiarize with the existing pattern for `create_conversion_action` (around line 183).

- [ ] **Step 2: Write the failing tests**

Open `tests/unit/test_blast_radius.py` and append:

```python
class TestUpdateConversionActionClassify:
    def test_single_rename_only_is_auto(self):
        from src.governance.blast_radius import RiskLevel, classify

        result = classify(
            operation="update_conversion_action",
            params={"updates": [{"conversion_action_id": "123", "name": "novo nome"}]},
        )
        assert result.level == RiskLevel.AUTO

    def test_single_disable_primary_for_goal_is_confirm(self):
        from src.governance.blast_radius import RiskLevel, classify

        result = classify(
            operation="update_conversion_action",
            params={"updates": [{"conversion_action_id": "123", "primary_for_goal": False}]},
        )
        assert result.level == RiskLevel.CONFIRM

    def test_single_disable_include_in_metric_is_confirm(self):
        from src.governance.blast_radius import RiskLevel, classify

        result = classify(
            operation="update_conversion_action",
            params={
                "updates": [
                    {"conversion_action_id": "123", "include_in_conversions_metric": False}
                ]
            },
        )
        assert result.level == RiskLevel.CONFIRM

    def test_batch_of_two_is_confirm_even_rename_only(self):
        from src.governance.blast_radius import RiskLevel, classify

        result = classify(
            operation="update_conversion_action",
            params={
                "updates": [
                    {"conversion_action_id": "123", "name": "a"},
                    {"conversion_action_id": "456", "name": "b"},
                ]
            },
        )
        assert result.level == RiskLevel.CONFIRM

    def test_set_primary_for_goal_true_is_auto_for_single(self):
        """Setting True (enable) is safe — only False (disable) needs CONFIRM."""
        from src.governance.blast_radius import RiskLevel, classify

        result = classify(
            operation="update_conversion_action",
            params={"updates": [{"conversion_action_id": "123", "primary_for_goal": True}]},
        )
        assert result.level == RiskLevel.AUTO
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_blast_radius.py::TestUpdateConversionActionClassify -v`
Expected: 5 FAIL with classification falling through to a default that doesn't match.

- [ ] **Step 4: Implement the classify() entry**

Open `src/governance/blast_radius.py`. Find the `classify()` function. After the existing `elif operation == "create_conversion_action":` block, add:

```python
    elif operation == "update_conversion_action":
        updates = params.get("updates", [])
        has_unsafe_disable = any(
            u.get("primary_for_goal") is False
            or u.get("include_in_conversions_metric") is False
            for u in updates
        )
        if len(updates) == 1 and not has_unsafe_disable:
            return RiskClassification(
                level=RiskLevel.AUTO,
                reason="1 ConversionAction sem desligar Smart Bidding signal",
            )
        return RiskClassification(
            level=RiskLevel.CONFIRM,
            reason=f"{len(updates)} ConversionAction(s); requer preview",
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_blast_radius.py::TestUpdateConversionActionClassify -v`
Expected: 5 PASS

- [ ] **Step 6: Run lint + mypy**

Run: `.venv/Scripts/python -m ruff check src/governance/blast_radius.py && .venv/Scripts/python -m mypy src/governance/blast_radius.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/governance/blast_radius.py tests/unit/test_blast_radius.py
git commit -m "$(cat <<'EOF'
feat(governance): classify() entry for update_conversion_action

Sprint 3b.27. AUTO: 1 update sem desligar primary_for_goal/include_in_metric
(rename puro). CONFIRM: batch > 1 OR qualquer field False (desligar signal
Smart Bidding tem efeito alto). 5 unit tests cobrem boundary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A3: Builder `build_update_conversion_action`

**Files:**
- Modify: `src/google_ads/mutates/conversion_actions.py` (append)
- Modify: `src/google_ads/mutates/_common.py` (no change — `@register_builder` runs at import time)
- Test: `tests/unit/test_update_conversion_action_builder.py` (create)

- [ ] **Step 1: Confirm proto_capture fixture exists**

Run: `cat tests/unit/fixtures/proto_capture.py | head -30`
Expected: file exists with `make_capture_client` function.

If file doesn't exist, STOP — convention pós-3b.5 requires it. Notify operator.

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_update_conversion_action_builder.py`:

```python
"""Unit tests for build_update_conversion_action builder (Sprint 3b.27).

Uses ProtoFieldCapture (NOT MagicMock) per convention pós-Sprint 3b.5 —
silent attribute accept on MagicMock would mask field-name typos (F16/F42
lesson).
"""

from tests.unit.fixtures.proto_capture import make_capture_client


def test_build_op_sets_only_name_when_only_name_provided():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {"updates": [{"conversion_action_id": "123", "name": "Novo Nome"}]}
    ops = build_update_conversion_action(client, "1163862076", payload)

    assert len(ops) == 1
    op = ops[0]
    assert op.field("conversion_action_operation.update.name") == "Novo Nome"
    assert op.has("conversion_action_operation.update.primary_for_goal") is False
    assert op.has("conversion_action_operation.update.include_in_conversions_metric") is False
    # Field mask should contain only 'name'
    assert list(op.field("conversion_action_operation.update_mask.paths")) == ["name"]


def test_build_op_sets_primary_for_goal_field():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {
        "updates": [{"conversion_action_id": "123", "primary_for_goal": False}]
    }
    ops = build_update_conversion_action(client, "1163862076", payload)

    op = ops[0]
    assert op.field("conversion_action_operation.update.primary_for_goal") is False
    assert list(op.field("conversion_action_operation.update_mask.paths")) == ["primary_for_goal"]


def test_build_op_sets_include_in_conversions_metric_field():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {
        "updates": [{"conversion_action_id": "123", "include_in_conversions_metric": False}]
    }
    ops = build_update_conversion_action(client, "1163862076", payload)

    op = ops[0]
    assert (
        op.field("conversion_action_operation.update.include_in_conversions_metric") is False
    )
    assert list(op.field("conversion_action_operation.update_mask.paths")) == [
        "include_in_conversions_metric"
    ]


def test_build_op_constructs_correct_resource_name():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {"updates": [{"conversion_action_id": "987654321", "name": "x"}]}
    ops = build_update_conversion_action(client, "1163862076", payload)

    op = ops[0]
    assert (
        op.field("conversion_action_operation.update.resource_name")
        == "customers/1163862076/conversionActions/987654321"
    )


def test_build_ops_handles_batch_of_3_different_field_combos():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {
        "updates": [
            {"conversion_action_id": "111", "name": "A"},
            {"conversion_action_id": "222", "primary_for_goal": False},
            {
                "conversion_action_id": "333",
                "name": "C",
                "include_in_conversions_metric": False,
            },
        ]
    }
    ops = build_update_conversion_action(client, "1163862076", payload)

    assert len(ops) == 3
    # Each op has its own field_mask (not shared/leaked between items)
    assert list(ops[0].field("conversion_action_operation.update_mask.paths")) == ["name"]
    assert list(ops[1].field("conversion_action_operation.update_mask.paths")) == [
        "primary_for_goal"
    ]
    assert sorted(list(ops[2].field("conversion_action_operation.update_mask.paths"))) == sorted(
        ["name", "include_in_conversions_metric"]
    )


def test_build_op_all_three_fields_present():
    from src.google_ads.mutates.conversion_actions import build_update_conversion_action

    client = make_capture_client()
    payload = {
        "updates": [
            {
                "conversion_action_id": "555",
                "name": "Tudo",
                "primary_for_goal": True,
                "include_in_conversions_metric": True,
            }
        ]
    }
    ops = build_update_conversion_action(client, "1163862076", payload)

    op = ops[0]
    assert op.field("conversion_action_operation.update.name") == "Tudo"
    assert op.field("conversion_action_operation.update.primary_for_goal") is True
    assert op.field("conversion_action_operation.update.include_in_conversions_metric") is True
    assert sorted(list(op.field("conversion_action_operation.update_mask.paths"))) == sorted(
        ["name", "primary_for_goal", "include_in_conversions_metric"]
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_update_conversion_action_builder.py -v`
Expected: 6 FAIL with `ImportError: cannot import name 'build_update_conversion_action'`

- [ ] **Step 4: Implement the builder**

Open `src/google_ads/mutates/conversion_actions.py` and append at the end:

```python
@register_builder("update_conversion_action")
def build_update_conversion_action(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {updates: [{conversion_action_id, name?, primary_for_goal?, include_in_conversions_metric?}]}

    Builds MutateOperation messages with dynamic field_mask per item.
    Each update item gets its own field_mask listing only the fields present
    in the payload — critical so Google update doesn't override absent
    fields with default values (silent bug).

    Sprint 3b.27 — update tool (3 fields V0).
    """
    operations: list[Any] = []
    for spec in payload["updates"]:
        op = client.get_type("MutateOperation")
        ca_op = op.conversion_action_operation
        ca = ca_op.update
        ca.resource_name = (
            f"customers/{customer_id}/conversionActions/{spec['conversion_action_id']}"
        )

        fields_to_mask: list[str] = []
        if "name" in spec:
            ca.name = spec["name"]
            fields_to_mask.append("name")
        if "primary_for_goal" in spec:
            ca.primary_for_goal = spec["primary_for_goal"]
            fields_to_mask.append("primary_for_goal")
        if "include_in_conversions_metric" in spec:
            ca.include_in_conversions_metric = spec["include_in_conversions_metric"]
            fields_to_mask.append("include_in_conversions_metric")

        ca_op.update_mask.paths.extend(fields_to_mask)
        operations.append(op)

    return operations
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_update_conversion_action_builder.py -v`
Expected: 6 PASS

- [ ] **Step 6: Run lint + mypy**

Run: `.venv/Scripts/python -m ruff check src/google_ads/mutates/conversion_actions.py tests/unit/test_update_conversion_action_builder.py && .venv/Scripts/python -m mypy src/google_ads/mutates/conversion_actions.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/google_ads/mutates/conversion_actions.py tests/unit/test_update_conversion_action_builder.py
git commit -m "$(cat <<'EOF'
feat(mcp): build_update_conversion_action builder

Sprint 3b.27. Builds MutateOperation.conversion_action_operation.update
with dynamic field_mask per item (each item has its own mask listing only
fields present in payload — critical so Google update doesnt overwrite
absent fields with default values).

6 unit tests via proto_capture (NOT MagicMock — F16/F42 lesson):
- name only / primary_for_goal only / include_in_conversions_metric only
- resource_name path format
- batch of 3 with different field combos (each mask isolated)
- all 3 fields together

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A4: Tool MCP `update_conversion_action.py` (Layer 1 + Layer 2)

**Files:**
- Create: `src/mcp/tools/update_conversion_action.py`
- Test: `tests/unit/test_update_conversion_action.py` (create — schema + Layer 2 only; integration test em A5)

- [ ] **Step 1: Write the failing schema + Layer 2 tests**

Create `tests/unit/test_update_conversion_action.py`:

```python
"""Unit tests for update_conversion_action tool — schema + Layer 2 (Sprint 3b.27).

Integration tests (Layer 3 mocking, dispatcher routing) live em
tests/integration/test_update_conversion_action.py — Task A5.
"""

from src.mcp.tools.update_conversion_action import _SCHEMA, _validate_payload_shape


def test_schema_has_no_composition_keywords():
    """Regression guard: F18/F25 family — Anthropic API rejects oneOf/allOf/anyOf."""
    import json

    schema_str = json.dumps(_SCHEMA)
    assert '"oneOf"' not in schema_str
    assert '"allOf"' not in schema_str
    assert '"anyOf"' not in schema_str


def test_schema_explicit_types():
    """F1 lesson: every property has explicit type."""

    def _walk(obj):
        if isinstance(obj, dict):
            if "properties" in obj:
                for prop_name, prop_schema in obj["properties"].items():
                    assert "type" in prop_schema, f"property '{prop_name}' missing type"
                    _walk(prop_schema)
            elif "items" in obj:
                _walk(obj["items"])
            for v in obj.values():
                _walk(v) if isinstance(v, dict | list) else None
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(_SCHEMA)


def test_validate_payload_shape_accepts_well_formed_input():
    args = {
        "customer_id": "1163862076",
        "updates": [
            {"conversion_action_id": "123", "name": "Novo"},
            {"conversion_action_id": "456", "primary_for_goal": False},
        ],
    }
    assert _validate_payload_shape(args) is None


def test_validate_payload_shape_rejects_item_without_mutable_field():
    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123"}],  # só ID, sem field mutável
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "sem nenhum field mutável" in err
    assert "conversion_action_id=123" in err


def test_validate_payload_shape_rejects_duplicate_conversion_action_id():
    args = {
        "customer_id": "1163862076",
        "updates": [
            {"conversion_action_id": "123", "name": "A"},
            {"conversion_action_id": "456", "name": "B"},
            {"conversion_action_id": "123", "primary_for_goal": False},  # dup
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "duplicados" in err
    assert "123" in err


def test_validate_payload_shape_rejects_multiple_problems_with_first():
    """When multiple items have no mutable, report the first to keep msg concise."""
    args = {
        "customer_id": "1163862076",
        "updates": [
            {"conversion_action_id": "123"},  # no mutable
            {"conversion_action_id": "456"},  # also no mutable
        ],
    }
    err = _validate_payload_shape(args)
    assert err is not None
    assert "conversion_action_id=123" in err  # first one
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_update_conversion_action.py -v`
Expected: 6 FAIL with `ImportError: No module named 'src.mcp.tools.update_conversion_action'`

- [ ] **Step 3: Implement the tool**

Create `src/mcp/tools/update_conversion_action.py`:

```python
"""Tool: update_conversion_action - update name, primary_for_goal, include_in_conversions_metric.

Sprint 3b.27. V0 minimal: 3 fields mutáveis. Field mask dinâmico por item.

Pre-flight async: validate_conversion_actions_exist (each ID exists + not REMOVED).
Layer 2 sync: _validate_payload_shape (item tem ≥1 field mutável; sem duplicate IDs).
"""

from typing import Any

from src.db import connection
from src.google_ads.mutations import run_mutation
from src.google_ads.queries._common import validate_conversion_actions_exist
from src.governance.blast_radius import RiskLevel, classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_MUTABLE_FIELDS = ("name", "primary_for_goal", "include_in_conversions_metric")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "updates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "conversion_action_id": {"type": "string", "pattern": "^[0-9]+$"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "primary_for_goal": {"type": "boolean"},
                    "include_in_conversions_metric": {"type": "boolean"},
                },
                "required": ["conversion_action_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["customer_id", "updates"],
    "additionalProperties": False,
}


def _validate_payload_shape(args: dict[str, Any]) -> str | None:
    """Layer 2: synchronous validation pre-Google call.

    Rejects:
    - Item without any mutable field (just conversion_action_id)
    - Duplicate conversion_action_id in batch
    """
    updates = args["updates"]

    for idx, item in enumerate(updates):
        has_mutable = any(f in item for f in _MUTABLE_FIELDS)
        if not has_mutable:
            return (
                f"update item {idx} (conversion_action_id={item['conversion_action_id']}) "
                f"só tem conversion_action_id sem nenhum field mutável "
                f"({', '.join(_MUTABLE_FIELDS)}). Inclua ao menos 1 field pra atualizar."
            )

    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for item in updates:
        cid = item["conversion_action_id"]
        if cid in seen:
            if cid not in duplicates:
                duplicates.append(cid)
        else:
            seen[cid] = 1

    if duplicates:
        return (
            f"conversion_action_ids duplicados no batch: {duplicates}. "
            f"Cada ID deve aparecer no máximo 1 vez."
        )

    return None


@register_tool(
    name="update_conversion_action",
    description=(
        "Atualiza ConversionAction: name, primary_for_goal (off = action vira "
        "non-biddable em todas as campaigns), include_in_conversions_metric "
        "(off = excluir das metric conversions). 3 fields V0 — todos opcionais "
        "por item (forneça ao menos 1). Single item rename auto-aplica; "
        "qualquer batch > 1 OU qualquer field False retorna preview com token."
    ),
    input_schema=_SCHEMA,
)
async def update_conversion_action(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    updates = args["updates"]

    # Layer 2 sync validation
    shape_error = _validate_payload_shape(args)
    if shape_error:
        return {
            "status": "error",
            "operation": "update_conversion_action",
            "customer_id": customer_id,
            "error": shape_error,
        }

    # Layer 3 async pre-flight
    conversion_action_ids = [u["conversion_action_id"] for u in updates]
    preflight_error = await validate_conversion_actions_exist(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        conversion_action_ids=conversion_action_ids,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "update_conversion_action",
            "customer_id": customer_id,
            **preflight_error,
        }

    target_count = len(updates)
    risk = classify(operation="update_conversion_action", params={"updates": updates})

    payload = {"updates": updates, "__target_count__": target_count}

    changes_preview = [
        {
            "conversion_action_id": u["conversion_action_id"],
            "fields_updated": [f for f in _MUTABLE_FIELDS if f in u],
        }
        for u in updates
    ]
    summary = f"Atualizar {target_count} ConversionAction(s)."

    if risk.level == RiskLevel.AUTO:
        result = await run_mutation(
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_conversion_action",
            payload=payload,
            target_count=target_count,
        )
        return {
            "status": "applied",
            "operation": "update_conversion_action",
            "customer_id": customer_id,
            "blast_summary": summary,
            "changes": changes_preview,
            "applied_count": result["applied_count"],
            "google_request_id": result["google_request_id"],
            "auto_applied_reason": risk.reason,
        }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="update_conversion_action",
            payload=payload,
            blast_summary=summary,
        )
    return {
        "status": "dry_run",
        "operation": "update_conversion_action",
        "customer_id": customer_id,
        "blast_summary": summary,
        "changes": changes_preview,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": "Chame apply_change(confirmation_token=<token>) para aplicar.",
        "confirmation_reason": risk.reason,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_update_conversion_action.py -v`
Expected: 6 PASS

- [ ] **Step 5: Verify cross-cutting schema test still passes**

Run: `.venv/Scripts/python -m pytest tests/unit/test_tools_schemas.py -v -k "no_composition"`
Expected: PASS (now includes update_conversion_action via auto-discovery)

- [ ] **Step 6: Run lint + mypy**

Run: `.venv/Scripts/python -m ruff check src/mcp/tools/update_conversion_action.py tests/unit/test_update_conversion_action.py && .venv/Scripts/python -m mypy src/mcp/tools/update_conversion_action.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/mcp/tools/update_conversion_action.py tests/unit/test_update_conversion_action.py
git commit -m "$(cat <<'EOF'
feat(mcp): update_conversion_action tool — schema + Layer 2

Sprint 3b.27 tool nova V0 minimal:
- 3 fields opt: name, primary_for_goal, include_in_conversions_metric
- maxItems 50 (proteção payload bombing)
- Layer 2 sync: rejeita item sem field mutável; rejeita IDs duplicados
- Integra Layer 3 preflight (validate_conversion_actions_exist) +
  classify (RiskLevel) + run_mutation / create_pending

Auto-discovery do _registry.py pega o arquivo (count visivel 49 -> 50
post-deploy). 6 unit tests cobrem schema regression + Layer 2 happy/error.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A5: Integration test for `update_conversion_action`

**Files:**
- Create: `tests/integration/test_update_conversion_action.py`

- [ ] **Step 1: Write the integration tests**

Create `tests/integration/test_update_conversion_action.py`:

```python
"""Integration tests for update_conversion_action tool (Sprint 3b.27).

Mock helper at TOOL's namespace (not _common's) — convention pós-3b.5/3b.8
(F-class "Pre-flight test mocks").
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers, mcp_sessions
from src.mcp.context import McpRequestContext, clear_current, set_current


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


@pytest.mark.integration
async def test_layer2_rejects_no_mutable_field(db, session_ctx):
    """Layer 2 rejects an item with only conversion_action_id."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123"}],
    }
    result = await update_conversion_action(args)
    assert result["status"] == "error"
    assert "sem nenhum field mutável" in result["error"]


@pytest.mark.integration
async def test_preflight_missing_id_returns_error(db, session_ctx):
    """Mock preflight at TOOL's namespace (convention pós-3b.5/3b.8)."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "999", "name": "x"}],
    }
    with patch(
        "src.mcp.tools.update_conversion_action.validate_conversion_actions_exist",
        AsyncMock(return_value={"error": "999 não existe", "missing_ids": ["999"]}),
    ):
        result = await update_conversion_action(args)
    assert result["status"] == "error"
    assert result["missing_ids"] == ["999"]


@pytest.mark.integration
async def test_single_rename_auto_applies(db, session_ctx):
    """Single rename only is AUTO — calls run_mutation directly."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123", "name": "Renamed"}],
    }
    with (
        patch(
            "src.mcp.tools.update_conversion_action.validate_conversion_actions_exist",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.mcp.tools.update_conversion_action.run_mutation",
            AsyncMock(
                return_value={"applied_count": 1, "google_request_id": "req-abc"}
            ),
        ),
    ):
        result = await update_conversion_action(args)
    assert result["status"] == "applied"
    assert result["applied_count"] == 1
    assert result["google_request_id"] == "req-abc"
    assert result["changes"][0]["fields_updated"] == ["name"]


@pytest.mark.integration
async def test_disable_primary_for_goal_returns_dry_run(db, session_ctx):
    """Setting primary_for_goal=False is CONFIRM — returns confirmation_token."""
    from src.mcp.tools.update_conversion_action import update_conversion_action

    args = {
        "customer_id": "1163862076",
        "updates": [{"conversion_action_id": "123", "primary_for_goal": False}],
    }
    with patch(
        "src.mcp.tools.update_conversion_action.validate_conversion_actions_exist",
        AsyncMock(return_value=None),
    ):
        result = await update_conversion_action(args)
    assert result["status"] == "dry_run"
    assert "confirmation_token" in result
    assert result["changes"][0]["fields_updated"] == ["primary_for_goal"]
```

- [ ] **Step 2: Run integration tests**

Run: `.venv/Scripts/python -m pytest tests/integration/test_update_conversion_action.py -v -m integration`
Expected: 4 PASS (requires Docker for testcontainers).

If Docker is not running, expected: pytest exits 2 with "no testcontainers". This is acceptable — CI will run full sweep.

- [ ] **Step 3: Run lint + mypy**

Run: `.venv/Scripts/python -m ruff check tests/integration/test_update_conversion_action.py && .venv/Scripts/python -m mypy tests/integration/test_update_conversion_action.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_update_conversion_action.py
git commit -m "$(cat <<'EOF'
test(mcp): integration tests for update_conversion_action

Sprint 3b.27. 4 cases:
- Layer 2 rejects item without mutable field
- Preflight missing_id returns error (mock at TOOL namespace —
  convention pós-3b.5/3b.8 evita slipping pre-push gate local)
- Single rename auto_applies via run_mutation (mocked)
- primary_for_goal=False returns dry_run + confirmation_token

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A6: Pre-push gate + push (deploy Phase A)

- [ ] **Step 1: Run full pre-push gate**

Run: `.venv/Scripts/python scripts/check_pre_push.py`
Expected: `5/5 PASS` (ruff + format + mypy + unit + non-DB integration).

If any step fails, fix and re-run.

- [ ] **Step 2: (opt-in, Docker required) Run full sweep with DB integration**

Run: `.venv/Scripts/python scripts/check_pre_push_full.py`
Expected: `6/6 PASS` (adds pytest -m integration via testcontainers).

If Docker is unavailable, this exits 2 with PT-BR hint — skip and rely on CI.

- [ ] **Step 3: Push to main**

Run: `git push origin main`
Expected: GitHub Actions triggers `test` + `deploy` workflows in parallel.

- [ ] **Step 4: Watch CI**

Run: `gh run list --limit 3`
Then: `gh run watch <run-id>` for the latest deploy.
Expected: both `test` and `deploy` PASS within 5-8 min.

- [ ] **Step 5: Verify production**

Run: `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health`
Expected: HTTP 200, JSON `{"ok": true, ...}`.

Run: `gcloud run revisions list --service=v4-ads-mcp --region=southamerica-east1 --limit=3 --format="value(name,active)"`
Expected: New revision `v4-ads-mcp-002XX-yyy` listed as ACTIVE.

- [ ] **Step 6: Verify tool count in MCP**

In a fresh Claude Code session (or use the active `mcp__v4-ads__*` tools list):
Verify that `mcp__v4-ads__update_conversion_action` appears in available tools.
Expected: yes (count was 49, now 50).

If tool absent: check `gcloud logging read` for import errors during startup. Re-deploy if needed.

---

# PHASE B — Fix B1/F43

## Task B1: Helper `validate_keyword_criterion_types`

**Files:**
- Modify: `src/google_ads/queries/_common.py` (append)
- Test: `tests/unit/test_validate_keyword_criterion_types.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_validate_keyword_criterion_types.py`:

```python
"""Unit tests for validate_keyword_criterion_types helper (Sprint 3b.27 — F43 fix)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "7862230676"}


def _make_row(ad_group_id: str, criterion_id: str, negative: bool, type_name: str = "KEYWORD"):
    """Build a dict matching the row_formatter output of the helper."""
    return {
        "ad_group_id": ad_group_id,
        "criterion_id": criterion_id,
        "negative": negative,
        "type": type_name,
    }


@pytest.mark.asyncio
async def test_all_positive_returns_none(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", False), _make_row("1", "12", False)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert result is None


@pytest.mark.asyncio
async def test_all_negative_returns_blocked_list_with_empty_safe(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", True), _make_row("1", "12", True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert result is not None
    assert len(result["negative_ids_blocked"]) == 2
    assert result["positive_ids_safe"] == []
    assert "2/2" in result["error"]


@pytest.mark.asyncio
async def test_mixed_returns_split_response(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [
        _make_row("1", "11", False),  # positive
        _make_row("1", "12", True),  # negative
        _make_row("2", "21", False),  # positive
    ]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12"), ("2", "21")],
        )
    assert result is not None
    assert len(result["negative_ids_blocked"]) == 1
    assert result["negative_ids_blocked"][0]["criterion_id"] == "12"
    assert len(result["positive_ids_safe"]) == 2
    assert "1/3" in result["error"]
    assert "to_retry_with" in result


@pytest.mark.asyncio
async def test_missing_id_returns_missing_dict_curto_circuit(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", False)]  # 12 not returned by GAQL
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert result is not None
    assert "missing_ids" in result
    assert result["missing_ids"][0]["criterion_id"] == "12"
    # Missing curto-circuita — não tem negative_ids_blocked nesse caminho
    assert "negative_ids_blocked" not in result


@pytest.mark.asyncio
async def test_pt_br_messages(fake_ctx):
    """Ensure PT-BR messages match spec literally for downstream UX consistency."""
    from src.google_ads.queries._common import validate_keyword_criterion_types

    # All negative case
    rows = [_make_row("1", "11", True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11")],
        )
    assert "negative=true" in result["error"]
    assert "positive_ids_safe" in result["error"]
    assert "Google Ads UI" in result["error"]


@pytest.mark.asyncio
async def test_to_retry_with_includes_positive_ids(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    rows = [_make_row("1", "11", False), _make_row("1", "12", True)]
    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=rows),
    ):
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[("1", "11"), ("1", "12")],
        )
    assert "positive_ids_safe" in result["to_retry_with"]
    assert "update_keyword_status" in result["to_retry_with"]


@pytest.mark.asyncio
async def test_empty_input_returns_none_without_calling_run_report(fake_ctx):
    from src.google_ads.queries._common import validate_keyword_criterion_types

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=[]),
    ) as mock_run:
        result = await validate_keyword_criterion_types(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            keyword_pairs=[],
        )
    assert result is None
    mock_run.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/unit/test_validate_keyword_criterion_types.py -v`
Expected: 7 FAIL with `ImportError: cannot import name 'validate_keyword_criterion_types'`

- [ ] **Step 3: Implement the helper**

Open `src/google_ads/queries/_common.py` and append at the end:

```python
async def validate_keyword_criterion_types(
    *,
    manager_id: UUID,
    session_id: UUID,
    customer_id: str,
    keyword_pairs: list[tuple[str, str]],
) -> dict[str, Any] | None:
    """GAQL pre-flight: each (ad_group_id, criterion_id) exists + is positive.

    Returns:
        None if all positive valid
        dict with {error, negative_ids_blocked, positive_ids_safe, to_retry_with}
            for negative mixture
        dict with {error, missing_ids} for IDs not found (short-circuit)

    Sprint 3b.27 fix B1/F43 (Silent-acceptance design gap family — F43).

    Discovered via dogfood 2026-05-19 MO-JP cleanup massivo: update_keyword_status
    accepts batches silently when including criterion with negative=true; only
    apply_change fails with Google generic error "Negative ad group criteria are
    not updateable" which doesn't identify problematic IDs.
    """
    if not keyword_pairs:
        return None

    crit_ids = sorted({c for _, c in keyword_pairs})
    ids_clause = ", ".join(str(int(c)) for c in crit_ids)
    query = (
        "SELECT ad_group.id, ad_group_criterion.criterion_id, "
        "ad_group_criterion.negative, ad_group_criterion.type "
        "FROM ad_group_criterion "
        f"WHERE ad_group_criterion.criterion_id IN ({ids_clause})"
    )

    def _format(row: Any) -> dict[str, Any]:
        return {
            "ad_group_id": str(row.ad_group.id),
            "criterion_id": str(row.ad_group_criterion.criterion_id),
            "negative": bool(row.ad_group_criterion.negative),
            "type": row.ad_group_criterion.type.name
            if hasattr(row.ad_group_criterion.type, "name")
            else str(row.ad_group_criterion.type),
        }

    rows = await run_report(
        manager_id=manager_id,
        session_id=session_id,
        customer_id=customer_id,
        query=query,
        row_formatter=_format,
        operation_name="validate_keyword_criterion_types",
    )

    # Key found rows by (ad_group_id, criterion_id) for O(1) lookup
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        key = (r["ad_group_id"], r["criterion_id"])
        found[key] = r

    missing: list[dict[str, str]] = []
    negative_blocked: list[dict[str, str]] = []
    positive_safe: list[dict[str, str]] = []

    for ad_group_id, criterion_id in keyword_pairs:
        key = (ad_group_id, criterion_id)
        if key not in found:
            missing.append({"ad_group_id": ad_group_id, "criterion_id": criterion_id})
            continue
        if found[key]["negative"]:
            negative_blocked.append(
                {"ad_group_id": ad_group_id, "criterion_id": criterion_id}
            )
        else:
            positive_safe.append({"ad_group_id": ad_group_id, "criterion_id": criterion_id})

    # Curto-circuito: missing IDs antes do negative check
    if missing:
        return {
            "error": (
                f"criterion_ids não encontrados em customer_id={customer_id}: "
                f"{[m['criterion_id'] for m in missing]}. Verifique se IDs estão "
                f"corretos (ad_group_id + criterion_id) e se o gestor ainda tem "
                f"acesso à conta."
            ),
            "missing_ids": missing,
        }

    if negative_blocked:
        return {
            "error": (
                f"{len(negative_blocked)}/{len(keyword_pairs)} criterion_ids são "
                f"ad_group_criterion com negative=true. Google API rejeita updates "
                f"em negative criteria (state machine separada). Re-chame "
                f"update_keyword_status apenas com os criterion_ids POSITIVE "
                f"listados em positive_ids_safe. Pra desnegativar uma keyword, "
                f"use Google Ads UI (sem tool MCP dedicada hoje)."
            ),
            "negative_ids_blocked": negative_blocked,
            "positive_ids_safe": positive_safe,
            "to_retry_with": (
                f"update_keyword_status(customer_id='{customer_id}', "
                f"keywords=positive_ids_safe, new_status=<your_status>)"
            ),
        }

    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/unit/test_validate_keyword_criterion_types.py -v`
Expected: 7 PASS

- [ ] **Step 5: Run lint + mypy**

Run: `.venv/Scripts/python -m ruff check src/google_ads/queries/_common.py tests/unit/test_validate_keyword_criterion_types.py && .venv/Scripts/python -m mypy src/google_ads/queries/_common.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/google_ads/queries/_common.py tests/unit/test_validate_keyword_criterion_types.py
git commit -m "$(cat <<'EOF'
feat(mcp): add validate_keyword_criterion_types helper for F43 fix

Sprint 3b.27 — pre-flight pro fix B1/F43 (Silent-acceptance design gap
discovered em dogfood 2026-05-19 MO-JP cleanup).

GAQL pre-flight: SELECT ad_group.id, criterion_id, negative, type FROM
ad_group_criterion WHERE criterion_id IN (...). Splits keyword_pairs em
positive_ids_safe + negative_ids_blocked + missing_ids. Missing IDs curto-
circuita antes do negative check.

Returns dict com error PT-BR + listas separadas + to_retry_with se mistura
positive/negative. None se todos positive valid.

7 unit tests cobrem happy + all-negative + mixed + missing curto-circuito +
PT-BR messages + to_retry_with format + empty input.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task B2: Wire `validate_keyword_criterion_types` into `update_keyword_status`

**Files:**
- Modify: `src/mcp/tools/update_keyword_status.py`
- Modify: `tests/integration/test_keyword_mutations.py` (append cases)

- [ ] **Step 1: Write the failing integration tests**

Open `tests/integration/test_keyword_mutations.py` and append at the end:

```python
@pytest.mark.integration
async def test_update_keyword_status_preflight_rejects_negative(db, session_ctx):
    """F43 fix: pre-flight rejects batch with negative criteria.

    Mock at TOOL namespace (convention pós-3b.5/3b.8 — patches at _common
    would slip pre-push local gate).
    """
    from src.mcp.tools.update_keyword_status import update_keyword_status

    args = {
        "customer_id": "7862230676",
        "keywords": [
            {"ad_group_id": "1", "criterion_id": "11"},
            {"ad_group_id": "1", "criterion_id": "12"},
        ],
        "new_status": "PAUSED",
    }
    mock_response = {
        "error": "1/2 criterion_ids são negative...",
        "negative_ids_blocked": [{"ad_group_id": "1", "criterion_id": "12"}],
        "positive_ids_safe": [{"ad_group_id": "1", "criterion_id": "11"}],
        "to_retry_with": "update_keyword_status(...)",
    }
    with patch(
        "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
        AsyncMock(return_value=mock_response),
    ):
        result = await update_keyword_status(args)

    assert result["status"] == "error"
    assert result["operation"] == "update_keyword_status"
    assert result["customer_id"] == "7862230676"
    assert result["negative_ids_blocked"] == [{"ad_group_id": "1", "criterion_id": "12"}]
    assert result["positive_ids_safe"] == [{"ad_group_id": "1", "criterion_id": "11"}]


@pytest.mark.integration
async def test_update_keyword_status_preflight_passes_only_positive(db, session_ctx):
    """F43 fix: regression — pre-flight returns None preserves pre-existing behavior."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    args = {
        "customer_id": "7862230676",
        "keywords": [{"ad_group_id": "1", "criterion_id": "11"}],
        "new_status": "PAUSED",
    }
    with (
        patch(
            "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.google_ads.mutations.run_mutation",
            AsyncMock(return_value={"applied_count": 1, "google_request_id": "req-z"}),
        ),
    ):
        result = await update_keyword_status(args)
    # 1 keyword = AUTO per existing classify()
    assert result["status"] == "applied"
    assert result["applied_count"] == 1


@pytest.mark.integration
async def test_update_keyword_status_preflight_missing_id_short_circuits(db, session_ctx):
    """F43 fix: missing IDs return missing_ids without negative_ids_blocked."""
    from src.mcp.tools.update_keyword_status import update_keyword_status

    args = {
        "customer_id": "7862230676",
        "keywords": [{"ad_group_id": "1", "criterion_id": "99"}],
        "new_status": "PAUSED",
    }
    mock_response = {
        "error": "criterion_ids não encontrados: ['99']",
        "missing_ids": [{"ad_group_id": "1", "criterion_id": "99"}],
    }
    with patch(
        "src.mcp.tools.update_keyword_status.validate_keyword_criterion_types",
        AsyncMock(return_value=mock_response),
    ):
        result = await update_keyword_status(args)
    assert result["status"] == "error"
    assert result["missing_ids"] == [{"ad_group_id": "1", "criterion_id": "99"}]
    assert "negative_ids_blocked" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/integration/test_keyword_mutations.py -v -m integration -k "preflight"`
Expected: 3 FAIL — `AttributeError: module 'src.mcp.tools.update_keyword_status' has no attribute 'validate_keyword_criterion_types'`

- [ ] **Step 3: Modify the tool**

Open `src/mcp/tools/update_keyword_status.py`. After the existing imports (line ~10), add:

```python
from src.google_ads.queries._common import validate_keyword_criterion_types
```

Then locate the body of `async def update_keyword_status(args: dict[str, Any]) -> dict[str, Any]:` and find the lines starting with `customer_id = args["customer_id"]`. Add the pre-flight block AFTER the existing context setup and BEFORE `risk = classify(...)`:

```python
    # Sprint 3b.27 fix B1/F43: pre-flight async — Google API rejects negative
    # ad_group_criterion updates with generic error that doesn't identify which
    # IDs were problematic. Splits batch into positive vs negative.
    keyword_pairs = [(k["ad_group_id"], k["criterion_id"]) for k in keywords]
    preflight_error = await validate_keyword_criterion_types(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        keyword_pairs=keyword_pairs,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "update_keyword_status",
            "customer_id": customer_id,
            **preflight_error,
        }
```

The full function should now look like (with the new block inserted between `target_count` line and `risk = classify` line):

```python
async def update_keyword_status(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    keywords = args["keywords"]
    new_status = args["new_status"]
    target_count = len(keywords)

    # Sprint 3b.27 fix B1/F43: pre-flight async ...
    keyword_pairs = [(k["ad_group_id"], k["criterion_id"]) for k in keywords]
    preflight_error = await validate_keyword_criterion_types(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        keyword_pairs=keyword_pairs,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "update_keyword_status",
            "customer_id": customer_id,
            **preflight_error,
        }

    risk = classify(...)  # rest unchanged
    ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/integration/test_keyword_mutations.py -v -m integration -k "preflight"`
Expected: 3 PASS

- [ ] **Step 5: Run regression — all existing keyword_mutation tests still pass**

Run: `.venv/Scripts/python -m pytest tests/integration/test_keyword_mutations.py -v -m integration`
Expected: ALL pass (existing tests + 3 new = 100% PASS).

If existing tests fail because they don't mock `validate_keyword_criterion_types`, add the mock to them (default `AsyncMock(return_value=None)`).

- [ ] **Step 6: Run lint + mypy**

Run: `.venv/Scripts/python -m ruff check src/mcp/tools/update_keyword_status.py tests/integration/test_keyword_mutations.py && .venv/Scripts/python -m mypy src/mcp/tools/update_keyword_status.py`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/mcp/tools/update_keyword_status.py tests/integration/test_keyword_mutations.py
git commit -m "$(cat <<'EOF'
fix(mcp): F43 pre-flight in update_keyword_status

Sprint 3b.27 — Layer 3 pre-flight async pre-classify. Chama
validate_keyword_criterion_types antes do mutate. Se batch mixed
positive+negative, retorna error com listas separadas + to_retry_with.

Mock no namespace da tool (src.mcp.tools.update_keyword_status) — convention
pós-3b.5/3b.8 que F-class "Pre-flight test mocks" documenta. Patches em
_common.py slipariam pre-push gate local.

3 integration tests novos:
- preflight_rejects_negative: response com negative_ids_blocked + positive_ids_safe
- preflight_passes_only_positive: regression (mutate prossegue normal)
- preflight_missing_id_short_circuits: response com missing_ids sem negative

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task B3: Pre-push gate + push (deploy Phase B)

- [ ] **Step 1: Run pre-push gate**

Run: `.venv/Scripts/python scripts/check_pre_push.py`
Expected: `5/5 PASS`.

- [ ] **Step 2: (opt-in) Full sweep with DB integration**

Run: `.venv/Scripts/python scripts/check_pre_push_full.py`
Expected: `6/6 PASS` (Docker required). **MANDATORY** for this push — `update_keyword_status` mod adds pre-flight; integration test gap would slip the fast gate (CLAUDE.md "Pre-flight test convention" section).

If Docker unavailable, run a single targeted: `.venv/Scripts/python -m pytest tests/integration/test_keyword_mutations.py -v -m integration -k "preflight"` and verify 3 PASS. Rely on CI for full sweep.

- [ ] **Step 3: Push**

Run: `git push origin main`

- [ ] **Step 4: Watch CI + verify production**

Run: `gh run list --limit 3` → `gh run watch <run-id>`
Then: `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health`
Expected: HTTP 200.

Run: `gcloud run revisions list --service=v4-ads-mcp --region=southamerica-east1 --limit=3`
Expected: New revision active.

---

# PHASE C — Smoke + signoff

## Task C1: Generate smoke runbook

**Files:**
- Create (via subagent): `docs/operacao/phase-3b-27-bootstrap.md`

- [ ] **Step 1: Dispatch smoke-runbook-generator subagent**

Use the Agent tool with `subagent_type: smoke-runbook-generator`.

Prompt:
```
Gere o runbook docs/operacao/phase-3b-27-bootstrap.md para Sprint 3b.27 combo.

Sprint metadata:
- Sprint number: 3b.27
- Tool nova: update_conversion_action (já implementada, deployed em produção)
- Fix: B1/F43 em update_keyword_status (pre-flight negative check, já deployed)
- Account de smoke: 1163862076 (Nutry sandbox)

Spec: docs/superpowers/specs/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix-design.md
Plan: docs/superpowers/plans/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix.md

Pontos importantes pra gerar test scenarios sensatos:

- Tool count target: 49 → 50 (após Phase A deploy) + 1 fix em existing tool
- Pre-flight setup necessário:
  T0a: GAQL listar 3-5 ConversionActions existentes em Nutry (ENABLED, with primary_for_goal=true)
  T0b: GAQL listar ad_group_criterion misturados positive + negative em Nutry (pelo menos 5 de cada)

- update_conversion_action tests (8):
  T1: dry_run happy path — alterar name em 1 action (preview + token, AUTO=False forçado pra testar dry_run)
  T2: apply T1 → verify GAQL
  T3: pre-flight reject — conversion_action_id 9999999999 não existe
  T4: Layer 2 reject — item sem field mutável (só conversion_action_id)
  T5: Layer 2 reject — duplicate conversion_action_id no batch
  T6: batch dry_run — 3 actions com fields diferentes (rename + primary_for_goal=false + include_in_metric=false)
  T7: apply T6 + verify GAQL — Store visits action vira non-biddable (caso real MO 23/05)
  T8: schema regression — maxItems 51 items rejected

- update_keyword_status F43 fix tests (4):
  T9: regression — só positives (5 keywords PAUSED) ainda funciona
  T10: F43 trigger — 100% negativos → hard reject (apenas 1 negative_id)
  T11: F43 trigger — mistura 3 positives + 2 negatives → split com listas separadas
  T12: missing IDs — criterion_id 999 inexistente → missing_ids curto-circuita

V4 invariants pra Component A (update_conversion_action):
- N/A — campos mutáveis (name, primary_for_goal, include_in_conversions_metric) são neutros geográfica/linguisticamente.

Per-value probe:
- N/A — tool nova não tem enum whitelist (3 fields bool/string).

Pode escrever o arquivo direto em docs/operacao/phase-3b-27-bootstrap.md. Wellington vai executar smoke após deploy ambas as phases.
```

Expected: subagent writes the file with 12 test scenarios + V4 invariants table (N/A note) + per-value probe (N/A note) + sign-off plan.

- [ ] **Step 2: Verify file created**

Run: `ls -la docs/operacao/phase-3b-27-bootstrap.md`
Expected: file exists, 200-350 lines.

- [ ] **Step 3: Commit**

```bash
git add docs/operacao/phase-3b-27-bootstrap.md
git commit -m "$(cat <<'EOF'
docs(runbook): Sprint 3b.27 smoke runbook

Gerado via subagent smoke-runbook-generator. 12 test scenarios:
- 8 update_conversion_action (dry_run + apply + Layer 2 + Layer 3 + schema)
- 4 update_keyword_status F43 fix (regression + trigger + missing)

Pre-flight setup T0a + T0b pra capturar entities em Nutry.

V4 invariants N/A (3 fields neutros). Per-value probe N/A (sem enum
whitelist).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C2: Execute smoke + capture findings

**Operator:** wellinton.ribeiro@v4company.com (manual execution)

- [ ] **Step 1: Pre-smoke setup**

Execute T0a and T0b from the runbook to capture real Nutry entity IDs. Note them in the runbook.

- [ ] **Step 2: Execute T1-T12 in order**

For each test, mark result in the runbook:
- ✅ PASS / ❌ FAIL / ⏸ DEFERRED (with reason)

Capture Google Request IDs for any T2 / T7 apply operations.

- [ ] **Step 3: Document F-findings (if any)**

If any test surfaces a new bug, document inline in runbook §F-findings emerged. For each:
- Severity (CRIT/HIGH/MED/LOW)
- Symptom (1 sentence)
- Root cause (if known)
- Family (Silent-acceptance / Schema / Pre-flight / UX / Runbook typo / Google constraint)

Plan fix iteration (3b.27.1, 3b.27.2, ...) if HIGH severity.

- [ ] **Step 4: Update sign-off section**

In runbook:
- Mark each sign-off checkbox
- Compute final result (e.g. "12/12 PASS" or "11/12 PASS + 1 DEFERRED por X")
- Note production revisions list

- [ ] **Step 5: Mark task A6 + B3 verification complete**

Confirm:
- mcp__v4-ads__update_conversion_action listed in MCP tools ✓
- update_keyword_status with 5 positives still works (T9) ✓
- update_keyword_status with mixed batch returns error ✓

---

## Task C3: Final signoff — update catalog, CLAUDE.md, run quality reviewer

- [ ] **Step 1: Dispatch mcp-tool-quality-reviewer for both deliverables**

Use Agent tool with `subagent_type: mcp-tool-quality-reviewer`.

Prompt:
```
Audite o combo Sprint 3b.27:

1. Tool nova: src/mcp/tools/update_conversion_action.py
2. Fix em tool existente: src/mcp/tools/update_keyword_status.py (post fix B1/F43)

Helpers compartilhados:
- src/google_ads/queries/_common.py (2 helpers novos: validate_conversion_actions_exist + validate_keyword_criterion_types)
- src/google_ads/mutates/conversion_actions.py (builder build_update_conversion_action novo)

Tests:
- tests/unit/test_update_conversion_action.py
- tests/unit/test_update_conversion_action_builder.py
- tests/unit/test_validate_conversion_actions_exist.py
- tests/unit/test_validate_keyword_criterion_types.py
- tests/integration/test_update_conversion_action.py
- tests/integration/test_keyword_mutations.py (modified)

Sprint 3b.27 combo já em produção. Smoke runbook executed: docs/operacao/phase-3b-27-bootstrap.md.

Rode TODOS os checks do seu checklist. Atenção especial:
- Group 2.1 ProtoFieldCapture (F42 lesson) no builder novo
- Group 2.2 Mock no namespace da tool em test_keyword_mutations (convention pós-3b.5/3b.8)
- Group 1.1 zero composition keywords no schema do update_conversion_action

Retorne report estruturado.
```

Expected: report with PASS/FAIL/N/A per check + top-3 fixes if FAIL.

- [ ] **Step 2: Apply top-3 fixes (if any FAIL reported)**

If reviewer reports FAILs:
- Apply fixes inline
- Re-run pre-push gate
- Re-push (sprint becomes 3b.27.x fix iteration)

If only convention-drift FAILs (low impact), document inline and proceed.

- [ ] **Step 3: Update findings-catalog.md — F43 → Fixed**

Open `docs/operacao/findings-catalog.md`. Find the F43 row in Bug class 1.

Change the "Fixed" column from `open (Sprint 3b.27 candidate)` to `3b.27` (or `3b.27.x` if fix iterations happened).

Also update:
- Summary by status: `**Open**` count from 2 → 1
- Total findings tracked: stays at 39 (F43 was already counted)
- Last updated header: `> **Last updated:** 2026-05-22 (Sprint 3b.27 signoff)` (or actual date)

- [ ] **Step 4: Update CLAUDE.md — Sprint 3b.27 shipped**

Open `CLAUDE.md`. Find the "Shipped + in production" table. After the Sprint 3b.26 row, add:

```
| Sprint 3b.27 — combo `update_conversion_action` + B1/F43 pre-flight fix em `update_keyword_status` | ✅ 2026-05-XX | Production revision `v4-ads-mcp-002XX-yyy`. **Tool count 49 → 50.** N/M tests PASS em Nutry sandbox. F43 (HIGH, Silent-acceptance) fechado. Atendeu prazo MO 23/05 Opção C SIMPLIFICADA (Wellington rebaixou Store visits action via tool). Spec: [`2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix-design.md`](docs/superpowers/specs/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix-design.md). Runbook: [`phase-3b-27-bootstrap.md`](docs/operacao/phase-3b-27-bootstrap.md). |
```

Update tool count references in CLAUDE.md header sections (3 places probably):
- "49 MCP tools" → "50 MCP tools"
- Whatever else mentions count

Also update Pending / future section:
- Move "Sprint 3b.27 candidate" → out (it shipped)
- Promote Sprint 3b.28 candidate to next-in-queue

- [ ] **Step 5: Commit signoff**

```bash
git add docs/operacao/findings-catalog.md CLAUDE.md docs/operacao/phase-3b-27-bootstrap.md
git commit -m "$(cat <<'EOF'
docs(signoff): Sprint 3b.27 shipped — update_conversion_action + F43 fix

- findings-catalog: F43 row open → Fixed Sprint 3b.27; Open 2→1
- CLAUDE.md: row Sprint 3b.27 shipped + tool count 49→50; Pending/future
  reordered (3b.28 update_customer_match_list virou next-in-queue)
- phase-3b-27-bootstrap: smoke results documented (N/M PASS, F-findings se
  emergiu)

Atendeu prazo MO 23/05 — Wellington rebaixou Store visits action via tool.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push final**

```bash
git push origin main
```

CI runs full test sweep + deploy (no Python changes, but doc/config push triggers anyway).

---

## Self-review of this plan

Vou conferir contra a spec (checklist mental):

**1. Spec coverage:** Cada seção do spec tem task?
- ✅ Component A schema/Layer 2 → Task A4
- ✅ Component A Layer 3 helper → Task A1
- ✅ Component A builder → Task A3
- ✅ Component A classify() → Task A2
- ✅ Component A integration → Task A5
- ✅ Component B helper → Task B1
- ✅ Component B wire → Task B2
- ✅ Smoke runbook → Task C1
- ✅ Smoke execution → Task C2
- ✅ Sign-off (findings-catalog F43→Fixed, CLAUDE.md, reviewer) → Task C3
- ✅ Pre-push gates → Tasks A6 + B3

**2. Placeholder scan:**
- "002XX-yyy" em C3 step 4 — placeholder esperado (revisão real desconhecida pré-deploy). Aceitável.
- "2026-05-XX" em C3 step 4 — placeholder pra data real do shipped. Aceitável.
- "N/M PASS" em C3 step 5 commit msg — placeholder pra resultado real do smoke. Aceitável.

Sem TBD/TODO/FIXME em código ou test code.

**3. Type consistency:**
- Helper signatures consistentes (`manager_id: UUID, session_id: UUID, customer_id: str, ...`).
- Return types: `dict[str, Any] | None` em ambos helpers.
- Tool function: `async def update_conversion_action(args: dict[str, Any]) -> dict[str, Any]`.
- Builder function: `(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]` (matches MutateBuilder type alias).

Verificações batem ✓.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-sprint-3b-27-update-conversion-action-plus-b1-fix.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
