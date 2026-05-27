# Sprint 3b.20 — `date_range` clarification + search_terms default

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar o bug crítico do `date_range` object format do relatório 2026-05-17 (Wellington) + reduzir token cap em `get_search_terms_report` default 500→50. Após este sprint, gestor poderá pedir períodos custom via Claude Desktop/Code sem fricção.

**Architecture:** Substituir schema sem `type` (causa root da serialização do dict como string JSON pelo Claude) por (1) `date_range` com `type: "string" + enum` de presets e (2) dois novos params `start_date` + `end_date` separados com `pattern` YYYY-MM-DD. Novo helper `resolve_date_window(date_range, start_date, end_date)` aplica precedência (custom > preset). Defensive JSON parse em `parse_date_range` mantém robustez interna e cobre edge cases legados. 14 tools afetadas (13 read + 1 mutation). Defense-in-depth: novo schema test impede regressão pra schema sem `type` em `date_range`.

**Tech Stack:** Python 3.12, jsonschema (Draft 2020-12), pytest, testcontainers (não exigido pra unit), freezegun (para preset tests), Anthropic Claude API tool-use validator (constraint upstream).

---

## File Structure

**Files to create:**
- `docs/operacao/phase-3b-20-bootstrap.md` — smoke runbook em conta real

**Files to modify (helper + tests):**
- `src/google_ads/queries/_common.py` — adicionar `resolve_date_window` + defensive JSON parse em `parse_date_range`
- `tests/unit/test_query_helpers.py` — adicionar tests para `resolve_date_window` + defensive parse
- `tests/unit/test_tools_schemas.py` — adicionar `test_date_range_schemas_are_explicit` regression guard

**Files to modify (14 tool schemas + bodies):**
- `src/mcp/tools/get_account_overview.py`
- `src/mcp/tools/get_funnel_metrics.py`
- `src/mcp/tools/get_campaign_performance.py`
- `src/mcp/tools/get_ad_group_performance.py`
- `src/mcp/tools/get_ad_performance.py`
- `src/mcp/tools/get_keyword_performance.py`
- `src/mcp/tools/get_search_terms_report.py` (também: `limit` default 500→50)
- `src/mcp/tools/get_top_keywords_creatives.py`
- `src/mcp/tools/get_device_performance.py`
- `src/mcp/tools/get_geo_performance.py`
- `src/mcp/tools/get_hourly_performance.py`
- `src/mcp/tools/get_audience_performance.py`
- `src/mcp/tools/get_change_history.py`
- `src/mcp/tools/bulk_pause_by_query.py`

**Files to modify (docs):**
- `CLAUDE.md` — adicionar subsection "Date range conventions (post-Sprint 3b.20)" na zona de Conventions; adicionar entrada na tabela "Shipped + in production"

---

## Task 1: Helper `resolve_date_window` — failing tests (TDD red)

**Files:**
- Modify: `tests/unit/test_query_helpers.py` (append at end of file)

- [ ] **Step 1: Write tests para `resolve_date_window`**

Append to `tests/unit/test_query_helpers.py`:

```python
# ---------- resolve_date_window (Sprint 3b.20) ----------

from src.google_ads.queries._common import resolve_date_window


@freeze_time("2026-05-15")
def test_resolve_date_window_preset_only() -> None:
    start, end = resolve_date_window(date_range="LAST_7_DAYS", start_date=None, end_date=None)
    assert start == date(2026, 5, 8)
    assert end == date(2026, 5, 14)


def test_resolve_date_window_custom_range() -> None:
    start, end = resolve_date_window(
        date_range="LAST_30_DAYS",  # should be overridden
        start_date="2026-05-08",
        end_date="2026-05-14",
    )
    assert start == date(2026, 5, 8)
    assert end == date(2026, 5, 14)


def test_resolve_date_window_only_start_raises() -> None:
    with pytest.raises(InvalidDateRangeError, match="end_date"):
        resolve_date_window(date_range="LAST_7_DAYS", start_date="2026-05-08", end_date=None)


def test_resolve_date_window_only_end_raises() -> None:
    with pytest.raises(InvalidDateRangeError, match="start_date"):
        resolve_date_window(date_range="LAST_7_DAYS", start_date=None, end_date="2026-05-14")


def test_resolve_date_window_invalid_custom_format_raises() -> None:
    with pytest.raises(InvalidDateRangeError):
        resolve_date_window(date_range="LAST_7_DAYS", start_date="not-a-date", end_date="2026-05-14")


def test_resolve_date_window_inverted_custom_raises() -> None:
    with pytest.raises(InvalidDateRangeError, match="after"):
        resolve_date_window(date_range="LAST_7_DAYS", start_date="2026-05-14", end_date="2026-05-08")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_helpers.py -v -k resolve_date_window`
Expected: ImportError or AttributeError on `resolve_date_window` (não existe ainda).

- [ ] **Step 3: Commit (red)**

```bash
git add tests/unit/test_query_helpers.py
git commit -m "test(common): add failing tests for resolve_date_window helper (Sprint 3b.20)"
```

---

## Task 2: Helper `resolve_date_window` — implementation (TDD green)

**Files:**
- Modify: `src/google_ads/queries/_common.py:38-95` (extend after `parse_date_range`)

- [ ] **Step 1: Implement `resolve_date_window`**

Insert after the existing `parse_date_range` function (around line 95, before `get_comparison_range`):

```python
def resolve_date_window(
    date_range: str | dict[str, str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[date, date]:
    """Resolve date_range preset OR explicit start_date+end_date pair into (start, end).

    Precedence: if both start_date and end_date are provided, those win over date_range.
    Mismatched pair (only one of start_date/end_date) is rejected.

    Sprint 3b.20: replaces direct parse_date_range calls in tool bodies so that custom
    periods can be expressed via two top-level params (each with explicit `type: "string"`)
    instead of a single composite param without `type`, which caused Claude to serialize
    the dict as a JSON string and break the parser (relatorio 2026-05-17, finding #1).
    """
    if start_date is not None and end_date is None:
        raise InvalidDateRangeError("end_date e obrigatorio quando start_date e informado.")
    if end_date is not None and start_date is None:
        raise InvalidDateRangeError("start_date e obrigatorio quando end_date e informado.")
    if start_date is not None and end_date is not None:
        return parse_date_range({"from": start_date, "to": end_date})
    return parse_date_range(date_range if date_range is not None else "LAST_30_DAYS")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/unit/test_query_helpers.py -v -k resolve_date_window`
Expected: 6 PASS.

- [ ] **Step 3: Commit (green)**

```bash
git add src/google_ads/queries/_common.py
git commit -m "feat(common): add resolve_date_window helper (Sprint 3b.20)"
```

---

## Task 3: Defensive JSON parse em `parse_date_range` — failing test

**Files:**
- Modify: `tests/unit/test_query_helpers.py` (append at end)

- [ ] **Step 1: Write defensive parse tests**

Append:

```python
# ---------- parse_date_range defensive JSON parse (Sprint 3b.20) ----------


def test_parse_date_range_recovers_from_json_string_dict() -> None:
    """Safety net: if Claude serializes dict as JSON string (root cause of relatorio
    finding #1), helper detects and parses it instead of falling through to preset
    uppercase which would corrupt the keys."""
    start, end = parse_date_range('{"from":"2026-05-08","to":"2026-05-14"}')
    assert start == date(2026, 5, 8)
    assert end == date(2026, 5, 14)


def test_parse_date_range_invalid_json_string_falls_through_to_preset_error() -> None:
    """String starting with '{' but invalid JSON should not silently succeed —
    fall through to the preset error path with original (lowercased) input visible."""
    with pytest.raises(InvalidDateRangeError, match="Unknown date_range preset"):
        parse_date_range("{not valid json}")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_query_helpers.py -v -k "recovers_from_json or invalid_json_string"`
Expected: 2 FAIL (first: lookup fails; second: error message includes uppercased garbled input not lowercase).

- [ ] **Step 3: Commit (red)**

```bash
git add tests/unit/test_query_helpers.py
git commit -m "test(common): add failing tests for parse_date_range defensive JSON parse"
```

---

## Task 4: Defensive JSON parse — implementation

**Files:**
- Modify: `src/google_ads/queries/_common.py:38-62` (inside `parse_date_range`)

- [ ] **Step 1: Add `json` import + defensive parse at top of function**

At top of `_common.py`, after the existing imports, add:

```python
import json
```

Modify `parse_date_range` (currently line 38) to add a defensive JSON parse BEFORE the existing isinstance(arg, dict) check:

```python
def parse_date_range(arg: str | dict[str, str]) -> tuple[date, date]:
    """Resolve a date_range param into (start_date, end_date) inclusive.

    Accepts either a preset string (e.g., 'LAST_7_DAYS') or an explicit
    dict {from: ISO_DATE, to: ISO_DATE}.

    Sprint 3b.20 safety net: if `arg` is a string that looks like a JSON object,
    parse it before applying preset matching. This recovers from cases where
    Claude serialized a dict as a JSON string (relatorio 2026-05-17 finding #1).
    """
    if isinstance(arg, str) and arg.strip().startswith("{"):
        try:
            arg = json.loads(arg)
        except (ValueError, json.JSONDecodeError):
            pass  # fall through to preset matching, which will raise a clean error

    if isinstance(arg, dict):
        try:
            start = date.fromisoformat(arg["from"])
            end = date.fromisoformat(arg["to"])
        except (KeyError, ValueError) as e:
            raise InvalidDateRangeError(f"Invalid date dict {arg}: {e}") from e
        if start > end:
            raise InvalidDateRangeError(f"date_range from ({start}) is after to ({end})")
        return start, end

    if not isinstance(arg, str):
        raise InvalidDateRangeError(f"date_range must be string or dict, got {type(arg)}")

    preset = arg.upper()
    if preset not in _PRESETS:
        raise InvalidDateRangeError(
            f"Unknown date_range preset '{preset}'. Valid presets: {', '.join(sorted(_PRESETS))}"
        )

    # ... rest unchanged
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/unit/test_query_helpers.py -v`
Expected: ALL pass (existing + 6 new resolve_date_window + 2 new defensive parse).

- [ ] **Step 3: Commit (green)**

```bash
git add src/google_ads/queries/_common.py
git commit -m "fix(common): defensive JSON parse in parse_date_range (Sprint 3b.20)"
```

---

## Task 5: Retrofit canonical tool — `get_account_overview`

**Files:**
- Modify: `src/mcp/tools/get_account_overview.py`

This is the template — Tasks 6-7 apply the same pattern to other tools.

- [ ] **Step 1: Replace schema `date_range` property + add `start_date`/`end_date`**

In `src/mcp/tools/get_account_overview.py`, replace the existing `_SCHEMA` (lines 16-35) with:

```python
_DATE_PRESETS = [
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
    "LAST_90_DAYS",
    "THIS_MONTH",
    "LAST_MONTH",
    "THIS_WEEK",
    "LAST_WEEK",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {
            "type": "string",
            "description": "ID da conta Google Ads (10 digitos, sem tracos)",
            "pattern": "^[0-9]{10}$",
        },
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_30_DAYS",
            "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
        },
        "start_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
                "sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
            "description": (
                "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}
```

- [ ] **Step 2: Update tool body to call `resolve_date_window`**

Find the existing line:
```python
date_range = args.get("date_range", "LAST_30_DAYS")
start, end = parse_date_range(date_range)
```

Replace with:
```python
start, end = resolve_date_window(
    date_range=args.get("date_range", "LAST_30_DAYS"),
    start_date=args.get("start_date"),
    end_date=args.get("end_date"),
)
```

Update the import line accordingly:
```python
from src.google_ads.queries._common import (
    get_comparison_range,
    micros_to_currency,
    resolve_date_window,
    value_proxy_warning,
)
```

(Remove `parse_date_range` from the import if it's no longer used directly in this file.)

- [ ] **Step 3: Add per-tool unit test verifying schema accepts new shape**

Append to `tests/unit/test_tools_schemas.py`:

```python
def test_get_account_overview_accepts_custom_period():
    """Verify Sprint 3b.20 pattern works on canonical tool."""
    from src.mcp.tools.get_account_overview import _SCHEMA

    valid_custom = {
        "customer_id": "1234567890",
        "start_date": "2026-05-08",
        "end_date": "2026-05-14",
    }
    jsonschema.validate(valid_custom, _SCHEMA)

    valid_preset = {"customer_id": "1234567890", "date_range": "LAST_7_DAYS"}
    jsonschema.validate(valid_preset, _SCHEMA)


def test_get_account_overview_rejects_invalid_date_format():
    from src.mcp.tools.get_account_overview import _SCHEMA

    invalid = {"customer_id": "1234567890", "start_date": "08/05/2026", "end_date": "2026-05-14"}
    with pytest.raises(jsonschema.exceptions.ValidationError):
        jsonschema.validate(invalid, _SCHEMA)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_tools_schemas.py tests/unit/test_query_helpers.py -v`
Expected: all PASS, including the 2 new per-tool tests.

- [ ] **Step 5: Commit**

```bash
git add src/mcp/tools/get_account_overview.py tests/unit/test_tools_schemas.py
git commit -m "feat(mcp): retrofit get_account_overview with start_date/end_date params (Sprint 3b.20)"
```

---

## Task 6: Retrofit 12 read tools (mechanical batch)

**Files (apply the same template as Task 6 to each):**
- `src/mcp/tools/get_funnel_metrics.py`
- `src/mcp/tools/get_campaign_performance.py`
- `src/mcp/tools/get_ad_group_performance.py`
- `src/mcp/tools/get_ad_performance.py`
- `src/mcp/tools/get_keyword_performance.py`
- `src/mcp/tools/get_search_terms_report.py`
- `src/mcp/tools/get_top_keywords_creatives.py`
- `src/mcp/tools/get_device_performance.py`
- `src/mcp/tools/get_geo_performance.py`
- `src/mcp/tools/get_hourly_performance.py`
- `src/mcp/tools/get_audience_performance.py`
- `src/mcp/tools/get_change_history.py`

> NOTE: `get_change_history` uses `LAST_7_DAYS` as default (not 30) — preserve that. Same retrofit otherwise.

For each tool, apply the **same 2-step pattern from Task 5**. Note that some tools have `parse_date_range` on the same line as `args.get(...)`, others split into two lines — both patterns map to the same replacement.

- [ ] **Step 1: Replace the existing `date_range` schema property**

Replace the property:
```python
"date_range": {"default": "LAST_30_DAYS"},
```

With:
```python
"date_range": {
    "type": "string",
    "enum": [
        "TODAY", "YESTERDAY", "LAST_7_DAYS", "LAST_14_DAYS", "LAST_30_DAYS",
        "LAST_90_DAYS", "THIS_MONTH", "LAST_MONTH", "THIS_WEEK", "LAST_WEEK",
    ],
    "default": "LAST_30_DAYS",
    "description": "Periodo via preset. Para periodo custom, use start_date+end_date.",
},
"start_date": {
    "type": "string",
    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
    "description": (
        "Data inicial YYYY-MM-DD inclusive. Quando informado junto com end_date, "
        "sobrepoe date_range preset. Obriga end_date."
    ),
},
"end_date": {
    "type": "string",
    "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
    "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
},
```

For `get_change_history`, change `"default": "LAST_30_DAYS"` to `"default": "LAST_7_DAYS"`.

- [ ] **Step 2: Replace `parse_date_range` call with `resolve_date_window`**

The existing code may appear in one of two forms:

**Form A** (split lines, e.g., `get_account_overview`):
```python
date_range = args.get("date_range", "LAST_30_DAYS")
start, end = parse_date_range(date_range)
```

**Form B** (single line, e.g., `get_funnel_metrics`):
```python
start, end = parse_date_range(args.get("date_range", "LAST_30_DAYS"))
```

Both replace with the same block:
```python
start, end = resolve_date_window(
    date_range=args.get("date_range", "LAST_30_DAYS"),
    start_date=args.get("start_date"),
    end_date=args.get("end_date"),
)
```

(For `get_change_history`, the default in the `args.get(...)` call should be `"LAST_7_DAYS"` to preserve existing behavior.)

Adjust the `from src.google_ads.queries._common import ...` to replace `parse_date_range` with `resolve_date_window`. If other call sites in the same file still use `parse_date_range`, include both — but in practice none do.

For `get_change_history`, also keep the existing `_MAX_DAYS` check downstream (`RangeTooWideError` raised by `change_history_query`) — that flow is preserved since we still receive `(start, end)` dates.

- [ ] **Step 3: Run pre-push gate after each batch**

After each batch of 3-4 retrofits, run:

```bash
python scripts/check_pre_push.py
```

Expected: PASS (5/5 steps).

- [ ] **Step 4: Commit per batch**

Group commits as ~3-4 tools each to keep diffs reviewable:

```bash
git add src/mcp/tools/get_funnel_metrics.py src/mcp/tools/get_campaign_performance.py \
        src/mcp/tools/get_ad_group_performance.py src/mcp/tools/get_ad_performance.py
git commit -m "feat(mcp): retrofit 4 read tools with start_date/end_date (Sprint 3b.20)"

git add src/mcp/tools/get_keyword_performance.py src/mcp/tools/get_search_terms_report.py \
        src/mcp/tools/get_top_keywords_creatives.py src/mcp/tools/get_device_performance.py
git commit -m "feat(mcp): retrofit 4 more read tools with start_date/end_date (Sprint 3b.20)"

git add src/mcp/tools/get_geo_performance.py src/mcp/tools/get_hourly_performance.py \
        src/mcp/tools/get_audience_performance.py src/mcp/tools/get_change_history.py
git commit -m "feat(mcp): retrofit final 4 read tools with start_date/end_date (Sprint 3b.20)"
```

---

## Task 7: Retrofit `bulk_pause_by_query` (mutation tool, special case)

**Files:**
- Modify: `src/mcp/tools/bulk_pause_by_query.py`

`bulk_pause_by_query` is the only mutation that uses `date_range`. It has a try/except wrapping `parse_date_range` to return a friendly PT-BR error. Preserve that pattern.

- [ ] **Step 1: Update schema (same property block as Task 6)**

Replace:
```python
"date_range": {"default": "LAST_30_DAYS"},
```

With the same `date_range` + `start_date` + `end_date` block from Task 6 Step 1.

- [ ] **Step 2: Update body**

Find (around line 169-188):
```python
date_range_arg = args.get("date_range", "LAST_30_DAYS")

# Pre-flight filter validation (raises FilterValidationError → friendly PT-BR)
...

try:
    start, end = parse_date_range(date_range_arg)
except InvalidDateRangeError as e:
    return {
        "status": "error",
        "operation": "bulk_pause_by_query",
        "error": f"date_range invalido: {e}",
    }
```

Replace the date-resolution lines with:
```python
date_range_arg = args.get("date_range", "LAST_30_DAYS")
start_date_arg = args.get("start_date")
end_date_arg = args.get("end_date")

# Pre-flight filter validation (raises FilterValidationError → friendly PT-BR)
...

try:
    start, end = resolve_date_window(
        date_range=date_range_arg,
        start_date=start_date_arg,
        end_date=end_date_arg,
    )
except InvalidDateRangeError as e:
    return {
        "status": "error",
        "operation": "bulk_pause_by_query",
        "error": f"periodo invalido: {e}",
    }
```

Update the import:
```python
from src.google_ads.queries._common import InvalidDateRangeError, resolve_date_window
```

- [ ] **Step 3: Run pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: PASS (5/5 steps).

- [ ] **Step 4: Commit**

```bash
git add src/mcp/tools/bulk_pause_by_query.py
git commit -m "feat(mcp): retrofit bulk_pause_by_query with start_date/end_date (Sprint 3b.20)"
```

---

## Task 8: Regression guard — schema test that rejects loose `date_range`

Now that all 14 tools are retrofitted, add the defense-in-depth schema test
that prevents a future regression to the loose schema shape.

**Files:**
- Modify: `tests/unit/test_tools_schemas.py` (append before `test_every_tool_has_description`)

- [ ] **Step 1: Add `test_date_range_schemas_are_explicit`**

Append:

```python
def test_date_range_schemas_are_explicit():
    """Schemas with `date_range` MUST declare type: "string" + enum of presets.

    Sprint 3b.20: missing `type` field caused Claude to serialize dict-as-string,
    breaking parse_date_range. Defense-in-depth — fails CI if a regression
    reintroduces a loose `date_range` schema.

    For tools that need custom periods, add `start_date` + `end_date` as separate
    string properties with pattern YYYY-MM-DD (see resolve_date_window helper).
    """
    offenders: list[tuple[str, str]] = []

    for tool in all_tools():
        props = tool.input_schema.get("properties", {})
        dr = props.get("date_range")
        if dr is None:
            continue
        if dr.get("type") != "string":
            offenders.append((tool.name, f"date_range.type={dr.get('type')!r}"))
        elif "enum" not in dr:
            offenders.append((tool.name, "date_range missing enum"))

    assert not offenders, (
        "date_range schemas without explicit type+enum (Sprint 3b.20 regression):\n"
        + "\n".join(f"  {name}: {reason}" for name, reason in offenders)
    )
```

- [ ] **Step 2: Run test to verify it passes (all 14 tools already retrofitted)**

Run: `pytest tests/unit/test_tools_schemas.py::test_date_range_schemas_are_explicit -v`
Expected: PASS (zero offenders).

- [ ] **Step 3: Verify the guard catches regressions**

Temporarily revert ONE tool's schema (e.g., `get_account_overview`) back to the
loose form, rerun the test, confirm it fails with that tool listed as offender,
then restore the retrofitted schema. This is a smoke check on the guard itself.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_tools_schemas.py
git commit -m "test(schemas): add regression guard for loose date_range schemas (Sprint 3b.20)"
```

---

## Task 9: Lower `get_search_terms_report` limit default (relatorio finding #2)

**Files:**
- Modify: `src/mcp/tools/get_search_terms_report.py:16`

- [ ] **Step 1: Lower default `limit` from 500 to 50**

In `src/mcp/tools/get_search_terms_report.py`, find:
```python
"limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 500},
```

Replace with:
```python
"limit": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 50},
```

Also update the tool description (find the `description` arg in `@register_tool`) to mention the new default if it references the old number — usually it doesn't, but verify.

- [ ] **Step 2: Update existing test if it hardcodes 500**

Run: `grep -n "default.*500\|limit.*500" tests/unit/test_get_search_terms_report.py tests/integration/*.py`

If any test asserts on the old default, update it to 50.

- [ ] **Step 3: Run unit + integration tests for this tool**

```bash
pytest tests/unit/test_get_search_terms_report.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/mcp/tools/get_search_terms_report.py
git commit -m "fix(mcp): lower get_search_terms_report default limit 500->50 (Sprint 3b.20)"
```

---

## Task 10: Documentation updates

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add new convention subsection**

In `CLAUDE.md`, find the section "## Conventions" and after the "No JSON Schema composition keywords in tool input_schema (post-Sprint 3b.19B.1)" subsection, add:

```markdown
### Date range conventions (post-Sprint 3b.20)

All read tools and `bulk_pause_by_query` accept date windows via two paths:

- **Preset** (default): `date_range: str` — one of `LAST_7_DAYS`, `LAST_30_DAYS`,
  `THIS_MONTH`, `YESTERDAY`, etc. Schema declares `type: "string"` + `enum` of
  presets so Claude generates a clean string (no ambiguity).
- **Custom period**: `start_date: str` + `end_date: str` (both `YYYY-MM-DD`,
  schema `pattern: "^\\d{4}-\\d{2}-\\d{2}$"`). Both required when used.
  Overrides `date_range` preset.

Tool bodies MUST resolve the window via:

```python
from src.google_ads.queries._common import resolve_date_window

start, end = resolve_date_window(
    date_range=args.get("date_range", "LAST_30_DAYS"),
    start_date=args.get("start_date"),
    end_date=args.get("end_date"),
)
```

Why this matters: prior to Sprint 3b.20, the schema declared `date_range` without
a `type` field, intending to accept either a preset string OR a `{from, to}` dict.
Anthropic's tool-use API has no clean way to declare union types (composition
keywords are rejected — see Sprint 3b.19B.1 convention), so Claude silently
serialized the dict as a JSON-string literal. `parse_date_range` then called
`.upper()` on the literal, corrupting keys to `FROM`/`TO`, and lookup failed.
Custom periods were effectively unavailable from real Claude sessions.

Defense-in-depth: `tests/unit/test_tools_schemas.py::test_date_range_schemas_are_explicit`
fails CI if any tool reintroduces a `date_range` schema without `type: "string"` + `enum`.

`parse_date_range` keeps a defensive `json.loads` for any string starting with `{`
as a safety net for callers that bypass the new schema (internal tests, future
agents). This recovers from the original bug pattern even if a regression slips.
```

- [ ] **Step 2: Add the sprint row in "Shipped + in production" table**

In `CLAUDE.md`, find the table under "Shipped + in production" (last row is currently Sprint 3b.19B.1) and append a new row:

```markdown
| Sprint 3b.20 — `date_range` clarification + search_terms default | ✅ 2026-05-17 | <commits>; smoke runbook signed-off em conta real ([`phase-3b-20-bootstrap.md`](docs/operacao/phase-3b-20-bootstrap.md)) — production revision `<rev>`. Zero new MCP tools (count stays 46); closes relatorio 2026-05-17 findings #1 (CRITICO, custom periods unblocked) e #2 (search_terms default 500->50). **Schema change:** 14 tools com `date_range` ganham `type: "string" + enum` explicito + novos params `start_date`/`end_date` (pattern YYYY-MM-DD). Novo helper `resolve_date_window` em `_common.py` aplica precedencia custom > preset. Defensive `json.loads` em `parse_date_range` como safety net (Wellington relatorio root cause: Claude serializa dict como JSON string quando schema nao tem `type`). Regression guard `test_date_range_schemas_are_explicit`. <N> tests totais (6 resolve_date_window + 2 defensive parse + 1 regression guard + 2 per-tool schema). **NN consecutive sprint sem novos bugs no smoke (pending T1-T5 execution).** Resolve dogfood pain identificado pelo Wellington em report 15/05 Mestre da Obra JP+CAB. |
```

Update Last updated:
```markdown
**Last updated:** 2026-05-17
```

- [ ] **Step 3: Update "Pending / future" — close #1 + #2**

In the bullet "Phase 3b restante", update to add `_date_range fix shipped em Sprint 3b.20_` after the existing list and mark #2 as resolved.

- [ ] **Step 4: Commit docs**

```bash
git add CLAUDE.md
git commit -m "docs(claude): document Sprint 3b.20 date_range conventions"
```

---

## Task 11: Smoke runbook scaffold

**Files:**
- Create: `docs/operacao/phase-3b-20-bootstrap.md`

- [ ] **Step 1: Create the smoke runbook file**

Write to `docs/operacao/phase-3b-20-bootstrap.md`:

```markdown
# Phase 3b.20 — manual smoke runbook (date_range clarification + search_terms default)

**Purpose:** Verify Sprint 3b.20 fixes em conta real — re-execute relatorio
2026-05-17 finding #1 (custom periods que falharam em MO-JP) + finding #2
(search_terms cap).

**Operator:** wellinton.ribeiro@v4company.com
**Account:** `7862230676` "Mestre da Obra - João Pessoa" (mesma conta exercida
em report 15/05/2026 onde o bug foi descoberto)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session)

Production revision: `<fill-in>`.

## Test T1 — Regression: preset `LAST_7_DAYS` (must not break)

```
get_account_overview(customer_id="7862230676", date_range="LAST_7_DAYS")
```

Expected:
- [ ] Returns `current` + `previous` blocks com `impressions`, `clicks`,
      `cost_brl`, `conversions`, etc populated
- [ ] `period.from` + `period.to` cover last 7 complete days (ending yesterday)
- [ ] No errors

**Result:** ⬜ pending

## Test T2 — Custom period: o caso que falhou no relatorio

Period que falhou em 15/05 (08-14/05). Para reproduzir hoje sem time-travel,
use os 7 dias completos anteriores a ontem:

```
get_account_overview(
  customer_id="7862230676",
  start_date="<8 days ago YYYY-MM-DD>",
  end_date="<2 days ago YYYY-MM-DD>"
)
```

Expected:
- [ ] Returns `current` block com os dados desse range custom
- [ ] `period.from` + `period.to` match the exact dates passed
- [ ] **NO error** "Unknown date_range preset" (the bug from relatorio finding #1)
- [ ] `previous` block compares against the 7 days BEFORE start_date

**Result:** ⬜ pending

## Test T3 — Schema rejection: only start_date informed

```
get_account_overview(customer_id="7862230676", start_date="2026-05-08")
```

Expected:
- [ ] Erro retornado pelo MCP server: schema validation OR
      `resolve_date_window` raises PT-BR `"end_date e obrigatorio quando
      start_date e informado"`

**Result:** ⬜ pending

## Test T4 — Schema rejection: invalid YYYY-MM-DD format

```
get_account_overview(
  customer_id="7862230676",
  start_date="08/05/2026",
  end_date="14/05/2026"
)
```

Expected:
- [ ] Erro retornado pelo MCP server: schema validation rejects `pattern`
      mismatch (DD/MM/YYYY != YYYY-MM-DD)

**Result:** ⬜ pending

## Test T5 — Precedence: both preset and custom range

```
get_account_overview(
  customer_id="7862230676",
  date_range="LAST_30_DAYS",
  start_date="<3 days ago YYYY-MM-DD>",
  end_date="<2 days ago YYYY-MM-DD>"
)
```

Expected:
- [ ] Custom range WINS (response covers the 2-day range, not 30 days)
- [ ] `period.from` + `period.to` match start_date/end_date exactly
- [ ] No warning/error about conflicting inputs (precedence is intentional)

**Result:** ⬜ pending

## Test T6 — Token cap relief: search_terms default 50

```
get_search_terms_report(customer_id="7862230676", date_range="LAST_7_DAYS")
```

(NO `limit` arg — relies on default.)

Expected:
- [ ] Returns top 50 search terms (was 500 before, would exceed token cap)
- [ ] Response size compact enough to fit in single MCP response (no "saved
      to file" overflow message)
- [ ] Sorted by cost_micros DESC

**Result:** ⬜ pending

## Test T7 — Cross-tool sanity check on 2 other retrofitted tools

Pick 2 read tools at random (eg `get_campaign_performance` + `get_funnel_metrics`)
and run each twice — once with preset, once with custom period:

```
get_campaign_performance(customer_id="7862230676", date_range="LAST_14_DAYS")
get_campaign_performance(
  customer_id="7862230676",
  start_date="<14 days ago>",
  end_date="<1 day ago>"
)
```

Expected:
- [ ] Both calls succeed
- [ ] Both return identical date ranges (or near-identical, ±1 day depending
      on how the preset resolves)
- [ ] No "preset rejected" errors

**Result:** ⬜ pending

## Findings

Document any new findings here. If T1-T7 all pass clean, this is the **10th
consecutive sprint sem novos bugs no smoke** (continues 3b.7→3b.18 streak,
broken only by 3b.19A F17/F18 which were design gaps, not regressions).

If a finding emerges:
- Add to "Findings" section here with reproducer
- Spawn-task for fix or document as accepted limitation
- Update CLAUDE.md "Shipped + in production" row to note the finding
```

- [ ] **Step 2: Commit scaffold**

```bash
git add docs/operacao/phase-3b-20-bootstrap.md
git commit -m "docs(ops): scaffold smoke runbook for Sprint 3b.20"
```

---

## Task 12: Final pre-push verification + deploy

- [ ] **Step 1: Run full fast pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: 5/5 steps PASS (ruff check + format check + mypy + unit tests + non-DB integration).

- [ ] **Step 2: Run full sweep (if Docker available)**

```bash
python scripts/check_pre_push_full.py
```

Expected: 6/6 steps PASS. Per Sprint 3b.5+3b.8 lesson, this is mandatory after
changes that affect read-tool integration paths.

- [ ] **Step 3: Push to main**

```bash
git push origin main
```

- [ ] **Step 4: Watch CI + Deploy**

```bash
gh run list --limit 5
gh run watch <deploy-run-id>
```

Expected: green Deploy, smoke checks pass, production rolls forward.

- [ ] **Step 5: Capture production revision**

```bash
gcloud run services describe v4-ads-mcp --project=v4-ads-mcp-prod --region=southamerica-east1 --format='value(status.latestReadyRevisionName)'
```

Note revision (e.g., `v4-ads-mcp-00161-xxx`) and fill into both:
- `docs/operacao/phase-3b-20-bootstrap.md` "Pre-flight" section
- `CLAUDE.md` "Shipped + in production" row for Sprint 3b.20

- [ ] **Step 6: Reload Claude Code MCP client**

Restart the Claude Code session connected to v4-ads MCP server.

- [ ] **Step 7: Execute T1-T7 smoke tests in real account**

Walk through `docs/operacao/phase-3b-20-bootstrap.md` step by step. Mark
each ⬜ pending as ✅ PASS (or ❌ FAIL — document finding and stop).

- [ ] **Step 8: Commit smoke results**

```bash
git add docs/operacao/phase-3b-20-bootstrap.md CLAUDE.md
git commit -m "docs(ops): Sprint 3b.20 smoke runbook signed-off in Mestre da Obra JP"
git push origin main
```

---

## Self-Review Notes

Coverage of relatorio findings:
- ✅ #1 CRITICO `date_range` object format — Tasks 1-8 (helper + 14 tool retrofit + regression guard)
- ✅ #2 MEDIO `get_search_terms_report` limit 500 — Task 9
- ❌ #3 MEDIO `get_negative_keywords_audit` sem `created_date` — **deferred to Sprint 3b.21** (requires `change_event` JOIN investigation, not 1-line fix as relatorio assumed)
- ❌ Cross-MCP findings (timezone, currency formats) — out of v4-ads scope OR already correct (v4-ads returns number+BRL + Brasil/PB)
- ❌ Meta MCP findings (2.1, 2.2, 2.3, 2.4) — different MCP, not our codebase

Constraints honored:
- ✅ No composition keywords (oneOf/allOf/anyOf) anywhere in new schemas
- ✅ Each property has explicit single `type`
- ✅ Pre-flight test convention (no pre-flight helpers added here — purely schema + body changes)
- ✅ Mock fidelity convention not applicable (read-only, no builder tests)
- ✅ Schema whitelist empirical validation — T1-T6 cover full enum surface via smoke

Type consistency check:
- ✅ `resolve_date_window` signature consistent: `(date_range: str | dict | None, start_date: str | None, end_date: str | None) -> tuple[date, date]`
- ✅ `parse_date_range` signature unchanged externally
- ✅ All tool retrofits use same args.get pattern
