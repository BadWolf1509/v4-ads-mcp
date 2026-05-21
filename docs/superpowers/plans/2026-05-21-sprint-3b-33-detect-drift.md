# Sprint 3b.33 — `detect_drift` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `detect_drift` (54ª MCP tool) — pure aggregator + wrapper sobre `get_change_history` que detecta mudanças NÃO-autorizadas em conta Google Ads (co-management workflow V4, lição 46 dogfood 2026-05-21).

**Architecture:** Pure aggregator (`src/google_ads/drift_detection.py`) + tool wrapper (`src/mcp/tools/detect_drift.py`) que invoca `get_change_history` internamente, converte dict→dataclass na boundary, agrega via pure function, emite 3 flags (auto_apply_detected, multiple_users_detected, structural_change), trunca via limit. Padrão idêntico ao Sprint 3b.30/3b.31.

**Tech Stack:** Python 3.12 com frozen+slots dataclasses, asyncio (herdado de get_change_history), pytest com AsyncMock+patch, ruff+mypy strict.

**Reference:** [`docs/superpowers/specs/2026-05-21-sprint-3b-33-detect-drift-design.md`](../specs/2026-05-21-sprint-3b-33-detect-drift-design.md)

---

## File Structure

**Create:**
- `src/google_ads/drift_detection.py` — pure module com 5 dataclasses + `detect_drift()` + `dict_to_change_event_row()` parser
- `src/mcp/tools/detect_drift.py` — tool wrapper MCP
- `tests/unit/test_drift_detection.py` — 16 algorithm tests + 3 boundary parser tests
- `tests/integration/test_detect_drift.py` — 3 wire-up tests
- `docs/operacao/phase-3b-33-bootstrap.md` — smoke runbook (gerado via subagent)

**Modify:**
- `tests/unit/test_tools_schemas.py` — bump tool count 53→54 + add `detect_drift` ao allowlist
- `docs/operacao/sprint-history.md` — append entry Sprint 3b.33 (em A5 signoff)
- `CLAUDE.md` — bump tool count + pending/future section (em A5 signoff)

**Reuse (no changes):**
- `src/mcp/tools/get_change_history.py` — chamada interna
- `src/google_ads/queries/_common.py:resolve_date_window` — para resolver date_range/start_date/end_date
- `src/mcp/tools/_registry.py` — auto-discovery picks up novo tool

---

## Task A1: `drift_detection.py` pure module + 19 unit tests

**Files:**
- Create: `src/google_ads/drift_detection.py`
- Create: `tests/unit/test_drift_detection.py`

**Sequencial:** This task is foundational. A2 depende dos dataclasses + função detect_drift definidos aqui.

- [ ] **Step 1: Create `src/google_ads/drift_detection.py` com 5 dataclasses + detect_drift + parser**

```python
"""Pure client-side drift detection for change_event rows (Sprint 3b.33).

3 flags V0:
- auto_apply_detected (severity low): any drift row com client_type=GOOGLE_ADS_RECOMMENDATIONS
- multiple_users_detected (severity medium): >1 distinct non-auto-apply user em drift set
- structural_change (severity high): any REMOVE em CAMPAIGN/AD_GROUP/CONVERSION_ACTION

Pure function, zero Google SDK imports — testable standalone.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

Severity = Literal["low", "medium", "high"]

# Structural-change family: REMOVE em qualquer destes resource types é high-impact
_STRUCTURAL_RESOURCE_TYPES = frozenset({"CAMPAIGN", "AD_GROUP", "CONVERSION_ACTION"})

# Auto-apply detection: client_type sentinel (already used em get_change_history)
_AUTO_APPLY_CLIENT_TYPE = "GOOGLE_ADS_RECOMMENDATIONS"
_AUTO_APPLY_USER_BUCKET = "auto-apply"


@dataclass(frozen=True, slots=True)
class ChangeEventRow:
    """Boundary input — dict de get_change_history converte pra cá."""

    change_date_time: str
    user_email: str
    client_type: str
    resource_type: str
    resource_id: str
    resource_name: str
    operation: str
    changed_fields: tuple[str, ...]
    campaign_id: str | None
    ad_group_id: str | None


@dataclass(frozen=True, slots=True)
class DriftChange:
    """Output row — mesma shape de ChangeEventRow."""

    change_date_time: str
    user_email: str
    client_type: str
    resource_type: str
    resource_id: str
    resource_name: str
    operation: str
    changed_fields: tuple[str, ...]
    campaign_id: str | None
    ad_group_id: str | None


@dataclass(frozen=True, slots=True)
class DriftFlag:
    code: str
    severity: Severity
    message_pt: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DriftSummary:
    total_drift_changes: int
    total_changes_in_window: int
    by_user: dict[str, int]
    by_resource_type: dict[str, int]
    by_operation: dict[str, int]


@dataclass(frozen=True, slots=True)
class DriftResult:
    summary: DriftSummary
    flags: tuple[DriftFlag, ...]
    drift_changes: tuple[DriftChange, ...]
    truncated: bool


def dict_to_change_event_row(d: dict[str, Any]) -> ChangeEventRow:
    """Convert get_change_history row dict to ChangeEventRow dataclass.

    Defensive: missing fields default to "" or None; changed_fields list → tuple.
    """
    return ChangeEventRow(
        change_date_time=str(d.get("change_date_time", "")),
        user_email=str(d.get("user_email", "")),
        client_type=str(d.get("client_type", "")),
        resource_type=str(d.get("resource_type", "")),
        resource_id=str(d.get("resource_id", "")),
        resource_name=str(d.get("resource_name", "")),
        operation=str(d.get("operation", "")),
        changed_fields=tuple(d.get("changed_fields", [])),
        campaign_id=d.get("campaign_id"),
        ad_group_id=d.get("ad_group_id"),
    )


def detect_drift(
    rows: list[ChangeEventRow],
    *,
    responsible_user_emails: list[str],
    limit: int,
) -> DriftResult:
    """Detect drift changes given a list of change_event rows.

    Algorithm:
    1. Normalize responsible_user_emails (lowercase + strip).
    2. Partition rows: authorized (user_email in normalized set) vs drift.
       Auto-apply (client_type=GOOGLE_ADS_RECOMMENDATIONS) ALWAYS goes to drift.
    3. Aggregate drift rows: by_user (auto-apply collapsed), by_resource_type, by_operation.
    4. Detect 3 flags in order: auto_apply / multiple_users / structural_change.
    5. Stable sort drift rows DESC by change_date_time.
    6. Truncate to limit. truncated = True se len(drift_rows) > limit.

    Pure function — zero IO, zero Google SDK, fully testable.
    """
    # 1. Normalize authorized emails
    authorized: set[str] = {e.strip().lower() for e in responsible_user_emails}

    # 2. Partition
    drift_rows: list[ChangeEventRow] = []
    for row in rows:
        is_auto_apply = row.client_type == _AUTO_APPLY_CLIENT_TYPE
        is_authorized = row.user_email.strip().lower() in authorized and not is_auto_apply
        if not is_authorized:
            drift_rows.append(row)

    # 3. Aggregate
    by_user: Counter[str] = Counter()
    by_resource_type: Counter[str] = Counter()
    by_operation: Counter[str] = Counter()
    for row in drift_rows:
        if row.client_type == _AUTO_APPLY_CLIENT_TYPE:
            by_user[_AUTO_APPLY_USER_BUCKET] += 1
        else:
            by_user[row.user_email] += 1
        by_resource_type[row.resource_type] += 1
        by_operation[row.operation] += 1

    # 4. Flags
    flags: list[DriftFlag] = []

    auto_apply_count = sum(1 for r in drift_rows if r.client_type == _AUTO_APPLY_CLIENT_TYPE)
    if auto_apply_count > 0:
        flags.append(
            DriftFlag(
                code="auto_apply_detected",
                severity="low",
                message_pt=(
                    f"{auto_apply_count} change(s) aplicadas via Google Auto-Apply "
                    f"Recommendations. Revise se intencional."
                ),
                evidence={"auto_apply_count": auto_apply_count},
            )
        )

    non_auto_users = sorted(k for k in by_user if k != _AUTO_APPLY_USER_BUCKET)
    if len(non_auto_users) > 1:
        flags.append(
            DriftFlag(
                code="multiple_users_detected",
                severity="medium",
                message_pt=(
                    f"{len(non_auto_users)} usuários não-autorizados realizaram changes: "
                    f"{', '.join(non_auto_users)}."
                ),
                evidence={"unauthorized_users": non_auto_users},
            )
        )

    structural_rows = [
        r
        for r in drift_rows
        if r.operation == "REMOVE" and r.resource_type in _STRUCTURAL_RESOURCE_TYPES
    ]
    if structural_rows:
        flags.append(
            DriftFlag(
                code="structural_change",
                severity="high",
                message_pt=(
                    f"{len(structural_rows)} REMOVE(s) em recursos estruturais "
                    f"(CAMPAIGN/AD_GROUP/CONVERSION_ACTION). Investigação obrigatória."
                ),
                evidence={
                    "removed_resources": [
                        {"resource_type": r.resource_type, "resource_id": r.resource_id}
                        for r in structural_rows
                    ]
                },
            )
        )

    # 5. Sort DESC by change_date_time (Python sorted é stable)
    sorted_drift = sorted(drift_rows, key=lambda r: r.change_date_time, reverse=True)

    # 6. Truncate
    truncated = len(sorted_drift) > limit
    truncated_drift = sorted_drift[:limit]

    # Convert to DriftChange (same shape, just different type for output clarity)
    drift_changes = tuple(
        DriftChange(
            change_date_time=r.change_date_time,
            user_email=r.user_email,
            client_type=r.client_type,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            resource_name=r.resource_name,
            operation=r.operation,
            changed_fields=r.changed_fields,
            campaign_id=r.campaign_id,
            ad_group_id=r.ad_group_id,
        )
        for r in truncated_drift
    )

    summary = DriftSummary(
        total_drift_changes=len(drift_rows),
        total_changes_in_window=len(rows),
        by_user=dict(by_user),
        by_resource_type=dict(by_resource_type),
        by_operation=dict(by_operation),
    )

    return DriftResult(
        summary=summary,
        flags=tuple(flags),
        drift_changes=drift_changes,
        truncated=truncated,
    )
```

- [ ] **Step 2: Create `tests/unit/test_drift_detection.py` with 19 tests**

```python
"""Unit tests for drift_detection pure module (Sprint 3b.33)."""

import pytest

from src.google_ads.drift_detection import (
    ChangeEventRow,
    detect_drift,
    dict_to_change_event_row,
)


def _make_row(
    *,
    user_email: str = "pedro.vytor@v4company.com",
    client_type: str = "GOOGLE_ADS_WEB_CLIENT",
    resource_type: str = "CAMPAIGN",
    operation: str = "UPDATE",
    change_date_time: str = "2026-05-20 10:13:00",
    resource_id: str = "22169885957",
    resource_name: str = "CAB - Geral",
    changed_fields: tuple[str, ...] = ("campaign.ai_max_setting.enable_ai_max",),
    campaign_id: str | None = "22169885957",
    ad_group_id: str | None = None,
) -> ChangeEventRow:
    return ChangeEventRow(
        change_date_time=change_date_time,
        user_email=user_email,
        client_type=client_type,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        operation=operation,
        changed_fields=changed_fields,
        campaign_id=campaign_id,
        ad_group_id=ad_group_id,
    )


# === Algorithm tests (16) ===


def test_empty_responsible_list_all_drift():
    """Incident mode default: lista vazia → todos changes são drift."""
    rows = [_make_row(user_email="anyone@v4.com")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    assert result.summary.total_drift_changes == 1
    assert result.summary.total_changes_in_window == 1


def test_single_email_match_no_drift():
    """Happy path co-management: user autorizado → zero drift."""
    rows = [_make_row(user_email="wellinton@v4company.com")]
    result = detect_drift(
        rows, responsible_user_emails=["wellinton@v4company.com"], limit=100
    )
    assert result.summary.total_drift_changes == 0
    assert result.summary.total_changes_in_window == 1
    assert result.drift_changes == ()


def test_multi_email_match_partial_drift():
    """V4 multi-gestor: 2 emails autorizados, 1 não-autorizado."""
    rows = [
        _make_row(user_email="wellinton@v4company.com"),
        _make_row(user_email="lucas@v4company.com"),
        _make_row(user_email="intruso@external.com"),
    ]
    result = detect_drift(
        rows,
        responsible_user_emails=["wellinton@v4company.com", "lucas@v4company.com"],
        limit=100,
    )
    assert result.summary.total_drift_changes == 1
    assert result.drift_changes[0].user_email == "intruso@external.com"


def test_auto_apply_always_drift_even_with_full_authorization():
    """Auto-apply ALWAYS goes to drift, mesmo se user_email autorizado."""
    rows = [
        _make_row(
            user_email="wellinton@v4company.com",
            client_type="GOOGLE_ADS_RECOMMENDATIONS",
        )
    ]
    result = detect_drift(
        rows, responsible_user_emails=["wellinton@v4company.com"], limit=100
    )
    assert result.summary.total_drift_changes == 1


def test_case_insensitive_email_matching():
    """Email matching é case-insensitive."""
    rows = [_make_row(user_email="Pedro@V4Company.com")]
    result = detect_drift(
        rows, responsible_user_emails=["PEDRO@v4company.com"], limit=100
    )
    assert result.summary.total_drift_changes == 0


def test_flag_auto_apply_detected_positive():
    """Flag emitida quando há GOOGLE_ADS_RECOMMENDATIONS."""
    rows = [_make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email="")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "auto_apply_detected" in flag_codes


def test_flag_auto_apply_detected_negative():
    """Sem GOOGLE_ADS_RECOMMENDATIONS → flag ausente."""
    rows = [_make_row(client_type="GOOGLE_ADS_WEB_CLIENT")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "auto_apply_detected" not in flag_codes


def test_flag_multiple_users_detected_positive():
    """2+ users não-autorizados → flag emitida."""
    rows = [
        _make_row(user_email="pedro@v4company.com"),
        _make_row(user_email="lucas@v4company.com"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "multiple_users_detected" in flag_codes


def test_flag_multiple_users_detected_negative():
    """Apenas 1 user não-autorizado → flag ausente."""
    rows = [
        _make_row(user_email="pedro@v4company.com"),
        _make_row(user_email="pedro@v4company.com"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "multiple_users_detected" not in flag_codes


def test_flag_multiple_users_ignores_auto_apply_bucket():
    """Auto-apply não conta como user adicional pra multiple_users flag."""
    rows = [
        _make_row(user_email="pedro@v4company.com"),
        _make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email=""),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "multiple_users_detected" not in flag_codes
    assert "auto_apply_detected" in flag_codes


def test_flag_structural_change_positive():
    """REMOVE em CAMPAIGN → flag emitida."""
    rows = [_make_row(operation="REMOVE", resource_type="CAMPAIGN")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "structural_change" in flag_codes


def test_flag_structural_change_negative():
    """UPDATE em CAMPAIGN não trigger structural_change."""
    rows = [_make_row(operation="UPDATE", resource_type="CAMPAIGN")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "structural_change" not in flag_codes


def test_aggregation_by_user_with_auto_apply_collapse():
    """Auto-apply rows aggregam em bucket sintético 'auto-apply'."""
    rows = [
        _make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email=""),
        _make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email=""),
        _make_row(user_email="pedro@v4company.com"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    assert result.summary.by_user["auto-apply"] == 2
    assert result.summary.by_user["pedro@v4company.com"] == 1


def test_aggregation_by_resource_type_counter():
    """by_resource_type conta corretamente."""
    rows = [
        _make_row(resource_type="CAMPAIGN"),
        _make_row(resource_type="CAMPAIGN"),
        _make_row(resource_type="AD_GROUP"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    assert result.summary.by_resource_type["CAMPAIGN"] == 2
    assert result.summary.by_resource_type["AD_GROUP"] == 1


def test_truncation_limit_exceeded():
    """50 rows + limit=10 → truncated=True, returned 10."""
    rows = [
        _make_row(change_date_time=f"2026-05-20 10:{i:02d}:00", resource_id=str(i))
        for i in range(50)
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=10)
    assert result.truncated is True
    assert len(result.drift_changes) == 10
    assert result.summary.total_drift_changes == 50


def test_total_drift_vs_total_in_window_invariant():
    """total_in_window >= total_drift_changes sempre."""
    rows = [
        _make_row(user_email="wellinton@v4company.com"),
        _make_row(user_email="pedro@v4company.com"),
    ]
    result = detect_drift(
        rows, responsible_user_emails=["wellinton@v4company.com"], limit=100
    )
    assert result.summary.total_changes_in_window >= result.summary.total_drift_changes
    assert result.summary.total_changes_in_window == 2
    assert result.summary.total_drift_changes == 1


# === Boundary parser tests (3) ===


def test_dict_to_change_event_row_minimum():
    """Parser handles minimum dict (missing fields → defaults)."""
    d: dict = {"change_date_time": "2026-05-20 10:13:00", "user_email": "p@v4.com"}
    row = dict_to_change_event_row(d)
    assert row.change_date_time == "2026-05-20 10:13:00"
    assert row.user_email == "p@v4.com"
    assert row.changed_fields == ()
    assert row.campaign_id is None
    assert row.ad_group_id is None


def test_dict_to_change_event_row_changed_fields_list_to_tuple():
    """changed_fields list converte pra tuple (frozen dataclass requirement)."""
    d = {"changed_fields": ["a.b", "c.d"]}
    row = dict_to_change_event_row(d)
    assert row.changed_fields == ("a.b", "c.d")
    assert isinstance(row.changed_fields, tuple)


def test_dict_to_change_event_row_preserves_optional_ids():
    """campaign_id/ad_group_id preservados quando presentes."""
    d = {"campaign_id": "123", "ad_group_id": "456"}
    row = dict_to_change_event_row(d)
    assert row.campaign_id == "123"
    assert row.ad_group_id == "456"
```

- [ ] **Step 3: Run tests — expect 19/19 PASS**

```bash
python -m pytest tests/unit/test_drift_detection.py -v
```

Expected: 19 passed.

- [ ] **Step 4: Run ruff + mypy**

```bash
python -m ruff check src/google_ads/drift_detection.py tests/unit/test_drift_detection.py
python -m ruff format --check src/google_ads/drift_detection.py tests/unit/test_drift_detection.py
python -m mypy src/google_ads/drift_detection.py
```

Expected: All checks PASS.

- [ ] **Step 5: Commit**

```bash
git add src/google_ads/drift_detection.py tests/unit/test_drift_detection.py
git commit -m "feat(google_ads): drift_detection pure module + 19 unit tests (Sprint 3b.33 A1)"
```

---

## Task A2: `detect_drift.py` tool wrapper + schema + 3 integration tests

**Files:**
- Create: `src/mcp/tools/detect_drift.py`
- Create: `tests/integration/test_detect_drift.py`
- Modify: `tests/unit/test_tools_schemas.py`

**Depende de:** A1 (importa dataclasses + função detect_drift + dict_to_change_event_row).

- [ ] **Step 1: Create `src/mcp/tools/detect_drift.py`**

```python
"""Tool: detect_drift — auditar mudanças NÃO-autorizadas pós-batch V4.

Sprint 3b.33 — W1 do dogfood 2026-05-21 MO-JP+CAB (ICE 486).
Wrapper sobre get_change_history + pure aggregator com 3 flags acionáveis.
Use case primário: co-management (lição 46 dogfood).
"""

from typing import Any

from src.google_ads.drift_detection import detect_drift as _detect_drift_pure
from src.google_ads.drift_detection import dict_to_change_event_row
from src.google_ads.queries._common import resolve_date_window
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool
from src.mcp.tools.get_change_history import get_change_history

_DATE_PRESETS = [
    "LAST_2_DAYS",  # NEW — sane default for D+1/D+2 post-batch audit
    "TODAY",
    "YESTERDAY",
    "LAST_7_DAYS",
    "LAST_14_DAYS",
    "LAST_30_DAYS",
]

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "responsible_user_emails": {
            "type": "array",
            "items": {"type": "string", "format": "email"},
            "maxItems": 20,
            "description": (
                "Emails AUTORIZADOS pra mexer na conta (gestor responsável + "
                "co-gestores V4). Changes com user_email NESSA lista NÃO contam "
                "como drift. Lista vazia = incident mode (todos os changes "
                "contam como drift). Auto-apply "
                "(client_type=GOOGLE_ADS_RECOMMENDATIONS) sempre conta como "
                "drift (não tem user_email)."
            ),
        },
        "date_range": {
            "type": "string",
            "enum": _DATE_PRESETS,
            "default": "LAST_2_DAYS",
            "description": (
                "Periodo via preset. LAST_2_DAYS sane default pra D+1/D+2 "
                "pos-batch. Para periodo custom, use start_date+end_date."
            ),
        },
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": (
                "Data inicial YYYY-MM-DD inclusive. Quando informado junto com "
                "end_date, sobrepoe date_range preset. Obriga end_date."
            ),
        },
        "end_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
            "description": "Data final YYYY-MM-DD inclusive. Obrigatorio se start_date informado.",
        },
        "limit": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 100,
            "description": (
                "Cap em changes[] na response. Summary + flags refletem total bruto."
            ),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


@register_tool(
    name="detect_drift",
    description=(
        "Detecta mudanças NÃO-autorizadas em conta Google Ads (workflow "
        "co-management V4 pós-batch). Compara change_event com lista de "
        "responsible_user_emails: tudo NÃO-listado conta como drift. Auto-apply "
        "Recommendations sempre conta como drift. Output: summary (count + "
        "by_user/resource/operation) + flags[] (auto_apply_detected, "
        "multiple_users_detected, structural_change) + changes[] (até limit, "
        "default 100 max 500). NOTA: change_event tem lag até HORAS — pra "
        "validar estado atual, use run_gaql FROM campaign como leading "
        "indicator. Sempre auditado."
    ),
    input_schema=_SCHEMA,
)
async def detect_drift(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    responsible_user_emails = args.get("responsible_user_emails", [])
    limit = args.get("limit", 100)

    # Resolve date window LOCALLY (LAST_2_DAYS é preset detect_drift-only).
    # Passamos start_date+end_date explícitos pro get_change_history.
    start_date_obj, end_date_obj = resolve_date_window(
        date_range=args.get("date_range", "LAST_2_DAYS"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
    )
    start_date = start_date_obj.isoformat()
    end_date = end_date_obj.isoformat()

    # Internal call to get_change_history (audit_this_call=True herdado).
    # Pass start_date+end_date explicitly to avoid LAST_2_DAYS coupling com schema enum.
    history_result = await get_change_history(
        {
            "customer_id": customer_id,
            "start_date": start_date,
            "end_date": end_date,
            "limit": 500,  # raw cap; drift detection truncates to user's limit
        }
    )

    # Boundary conversion: dict → dataclass
    rows = [dict_to_change_event_row(d) for d in history_result["rows"]]

    # Pure aggregator
    drift_result = _detect_drift_pure(
        rows,
        responsible_user_emails=responsible_user_emails,
        limit=limit,
    )

    days = (end_date_obj - start_date_obj).days + 1

    return {
        "customer_id": customer_id,
        "period": {
            "from": start_date,
            "to": end_date,
            "days": days,
        },
        "responsible_user_emails": responsible_user_emails,
        "summary": {
            "total_drift_changes": drift_result.summary.total_drift_changes,
            "total_changes_in_window": drift_result.summary.total_changes_in_window,
            "by_user": drift_result.summary.by_user,
            "by_resource_type": drift_result.summary.by_resource_type,
            "by_operation": drift_result.summary.by_operation,
        },
        "flags": [
            {
                "code": f.code,
                "severity": f.severity,
                "message_pt": f.message_pt,
                "evidence": f.evidence,
            }
            for f in drift_result.flags
        ],
        "changes": [
            {
                "change_date_time": c.change_date_time,
                "user_email": c.user_email,
                "client_type": c.client_type,
                "resource_type": c.resource_type,
                "resource_id": c.resource_id,
                "resource_name": c.resource_name,
                "operation": c.operation,
                "changed_fields": list(c.changed_fields),
                "campaign_id": c.campaign_id,
                "ad_group_id": c.ad_group_id,
            }
            for c in drift_result.drift_changes
        ],
        "truncated": drift_result.truncated,
        "returned_count": len(drift_result.drift_changes),
    }
```

- [ ] **Step 2: Create `tests/integration/test_detect_drift.py` with 3 tests**

```python
"""Integration tests for detect_drift (Sprint 3b.33)."""

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
async def test_co_management_filter_pedro_drift(bound_context):
    """T2 cenário smoke: 2 changes Wellington autorizado + 4 Pedro Vytor drift."""
    from src.mcp.tools.detect_drift import detect_drift

    fake_history_result = {
        "customer_id": "7862230676",
        "period": {"from": "2026-05-20", "to": "2026-05-21"},
        "rows": [
            {
                "change_date_time": "2026-05-21 14:30:00",
                "user_email": "wellinton.ribeiro@v4company.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB - Geral",
                "operation": "UPDATE",
                "changed_fields": ["campaign.text_guidelines.messaging_restrictions"],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            },
            {
                "change_date_time": "2026-05-20 10:13:00",
                "user_email": "pedro.vytor@v4company.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB - Geral",
                "operation": "UPDATE",
                "changed_fields": ["campaign.ai_max_setting.enable_ai_max"],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            },
            {
                "change_date_time": "2026-05-20 10:12:30",
                "user_email": "pedro.vytor@v4company.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "21359547724",
                "resource_name": "JPA - Geral",
                "operation": "UPDATE",
                "changed_fields": ["campaign.ai_max_setting.enable_ai_max"],
                "campaign_id": "21359547724",
                "ad_group_id": None,
            },
        ],
        "summary": {},
    }
    with patch(
        "src.mcp.tools.detect_drift.get_change_history",
        AsyncMock(return_value=fake_history_result),
    ):
        result = await detect_drift(
            {
                "customer_id": "7862230676",
                "responsible_user_emails": ["wellinton.ribeiro@v4company.com"],
                "date_range": "LAST_2_DAYS",
            }
        )
    assert result["summary"]["total_drift_changes"] == 2
    assert result["summary"]["total_changes_in_window"] == 3
    assert result["summary"]["by_user"] == {"pedro.vytor@v4company.com": 2}
    assert result["returned_count"] == 2


@pytest.mark.asyncio
async def test_incident_mode_empty_responsible_list(bound_context):
    """T1 cenário smoke: lista vazia → todos changes são drift."""
    from src.mcp.tools.detect_drift import detect_drift

    fake_history_result = {
        "customer_id": "7862230676",
        "period": {"from": "2026-05-19", "to": "2026-05-21"},
        "rows": [
            {
                "change_date_time": "2026-05-20 10:13:00",
                "user_email": "anyone@v4.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB",
                "operation": "UPDATE",
                "changed_fields": ["campaign.status"],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            }
        ],
        "summary": {},
    }
    with patch(
        "src.mcp.tools.detect_drift.get_change_history",
        AsyncMock(return_value=fake_history_result),
    ):
        result = await detect_drift({"customer_id": "7862230676"})
    assert result["summary"]["total_drift_changes"] == 1
    assert result["responsible_user_emails"] == []


@pytest.mark.asyncio
async def test_structural_change_flag_emitted(bound_context):
    """T5 cenário smoke: REMOVE em CAMPAIGN → structural_change flag."""
    from src.mcp.tools.detect_drift import detect_drift

    fake_history_result = {
        "customer_id": "7862230676",
        "period": {"from": "2026-05-19", "to": "2026-05-21"},
        "rows": [
            {
                "change_date_time": "2026-05-20 10:13:00",
                "user_email": "intruso@external.com",
                "client_type": "GOOGLE_ADS_WEB_CLIENT",
                "resource_type": "CAMPAIGN",
                "resource_id": "22169885957",
                "resource_name": "CAB",
                "operation": "REMOVE",
                "changed_fields": [],
                "campaign_id": "22169885957",
                "ad_group_id": None,
            }
        ],
        "summary": {},
    }
    with patch(
        "src.mcp.tools.detect_drift.get_change_history",
        AsyncMock(return_value=fake_history_result),
    ):
        result = await detect_drift({"customer_id": "7862230676"})
    flag_codes = [f["code"] for f in result["flags"]]
    assert "structural_change" in flag_codes
    structural_flag = next(f for f in result["flags"] if f["code"] == "structural_change")
    assert structural_flag["severity"] == "high"
```

- [ ] **Step 3: Bump tool count em `tests/unit/test_tools_schemas.py`**

Locate `test_registered_tool_count_matches_files_on_disk` and `test_all_phase_2_tools_registered`. Bump 53→54 + add `"detect_drift"` ao allowlist.

```bash
grep -n "53" tests/unit/test_tools_schemas.py
```

Replace `53 == 53` with `54 == 54` (count assertion), e adicionar `"detect_drift"` à lista de tool names alphabetically sorted.

- [ ] **Step 4: Run tests — expect all PASS**

```bash
python -m pytest tests/integration/test_detect_drift.py tests/unit/test_tools_schemas.py -v
```

Expected: 3 integration + tool count test PASS.

- [ ] **Step 5: Run ruff + mypy + full pre-push gate-relevant unit tests**

```bash
python -m ruff check src/mcp/tools/detect_drift.py tests/integration/test_detect_drift.py
python -m mypy src/mcp/tools/detect_drift.py
python -m pytest tests/unit/ tests/integration/ -q
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mcp/tools/detect_drift.py tests/integration/test_detect_drift.py tests/unit/test_tools_schemas.py
git commit -m "feat(mcp): detect_drift tool wrapper + integration tests (Sprint 3b.33 A2)"
```

---

## Task A3: Smoke runbook via subagent

**Files:**
- Create: `docs/operacao/phase-3b-33-bootstrap.md`

**Pattern:** Dispatch subagent `smoke-runbook-generator` com sprint context. Idêntico a Sprints 3b.30/3b.31.

- [ ] **Step 1: Dispatch smoke-runbook-generator subagent**

Prompt mínimo (exemplo):
```
Generate phase-3b-33-bootstrap.md smoke runbook para Sprint 3b.33 (detect_drift, 54th tool).
Spec: docs/superpowers/specs/2026-05-21-sprint-3b-33-detect-drift-design.md
Plan: docs/superpowers/plans/2026-05-21-sprint-3b-33-detect-drift.md

6 cenários a cobrir (referência spec Section 6):
- T1: Schema default sem responsible_user_emails (incident mode, conta MO-JP 7862230676)
- T2: Co-management responsible_user_emails=[wellinton] + LAST_2_DAYS (reproduzir caso Pedro Vytor 20/05)
- T3: Custom date range start_date=2026-05-20 end_date=2026-05-20 (reproduzir cluster exato)
- T4: Limit truncation limit=2 em conta com 5+ drift
- T5: Flag structural_change — best-effort em conta com REMOVE recente
- T6: Empty drift — ML Antiguidades 7455088726 conta clean

Production URL: https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app
```

- [ ] **Step 2: Review generated runbook + commit**

Check file exists at `docs/operacao/phase-3b-33-bootstrap.md`. Verify 6 cenários presentes + "How to run" + "Expected results" + "Defer conditions" (F41/F45 pattern).

```bash
git add docs/operacao/phase-3b-33-bootstrap.md
git commit -m "docs(smoke): phase-3b-33-bootstrap.md runbook (Sprint 3b.33 A3)"
```

---

## Task A4: Pre-push gate + push deploy

- [ ] **Step 1: Run full pre-push gate**

```bash
python scripts/check_pre_push.py
```

Expected: 5/5 PASS em ~40s. Inclui ruff + format + mypy + pytest unit + non-DB integration.

- [ ] **Step 2: Push origin/main (admin bypass)**

```bash
git push origin main
```

Expected: 3 commits pushed (A1 + A2 + A3).

- [ ] **Step 3: Watch CI + Deploy**

```bash
gh run list --limit 3
gh run watch <ci-run-id> --exit-status
gh run watch <deploy-run-id> --exit-status
```

Expected: CI green + Deploy green em ~5-7 min.

- [ ] **Step 4: Verify /health post-deploy**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: HTTP 200.

---

## Task A5: Smoke execution Wellington manual + signoff

**Files modificados em signoff:**
- Modify: `docs/operacao/sprint-history.md` (append Sprint 3b.33 entry)
- Modify: `CLAUDE.md` (bump tool count 53→54 + Last updated + pending/future)
- Modify: `docs/operacao/phase-3b-33-bootstrap.md` (preencher results em-place)
- Optional: `docs/operacao/findings-catalog.md` (se F-findings novos)

- [ ] **Step 1: Wellington executa 6 testes** em conta MO-JP `7862230676` + ML Antiguidades `7455088726` (T6).

Para cada teste, registrar:
- Input args usados
- Response shape recebida
- PASS/FAIL/DEFERRED
- Observações

- [ ] **Step 2: Update runbook em-place com resultados**

Pattern Sprint 3b.30/3b.31: cada teste ganha bloco "## Result" com PASS/FAIL/DEFERRED + payload real (PII-safe).

- [ ] **Step 3: Catalog F-findings se houver**

Se algum teste descobriu bug:
- Use skill `/findings-add` pra auto-incrementar F##
- Document em `docs/operacao/findings-catalog.md`

Se zero F-findings, document explicitly: "Zero F-findings novos. Sprint clean."

- [ ] **Step 4: Append Sprint 3b.33 entry em sprint-history.md**

Append after Sprint 3b.32 entry, format consistente com entries anteriores (3b.30/3b.31/3b.32). Inclui:
- Production revision
- Tool count 53 → 54
- Smoke X/6 PASS + Y DEFERRED
- F-findings count
- Reference plan + spec + runbook
- Architecture summary
- ICE 486 (W1 dogfood 21/05)

- [ ] **Step 5: Bump CLAUDE.md**

3 edits:
- `Last updated:` 2026-05-21 (mantém data)
- `Sprint 3b.1 → 3b.32 (32 sprints)` → `Sprint 3b.1 → 3b.33 (33 sprints)`
- "Shipped (53 tools)" → "Shipped (54 tools)"
- "Production revision post-Sprint 3b.32" → "post-Sprint 3b.33 — detect_drift 54th tool"
- "Sprint 3b.33 candidate" → "Sprint 3b.34 candidate (next-in-queue):" — W3 audit_goal_attribution ICE 360 ou novos ICE rankings do dogfood

- [ ] **Step 6: Commit signoff + push**

```bash
git add docs/operacao/sprint-history.md CLAUDE.md docs/operacao/phase-3b-33-bootstrap.md
# Se F-findings novos:
git add docs/operacao/findings-catalog.md
git commit -m "docs(signoff): Sprint 3b.33 detect_drift smoke X/6 PASS — signoff"
git push origin main
```

- [ ] **Step 7: Final verification**

```bash
git log --oneline c841c66..HEAD  # ver todos os commits desta sessão
curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health
```

Expected: clean log + HTTP 200.

---

## Self-Review

**1. Spec coverage check:**

| Spec section | Task que implementa |
|---|---|
| Section 1 Architecture | A1 (módulo) + A2 (wrapper) |
| Section 2 Schema | A2 Step 1 |
| Section 3 Output shape | A2 Step 1 (return dict) |
| Section 4 Algorithm | A1 Step 1 (detect_drift function) |
| Section 5 V0 cuts | N/A (cuts documentation only) |
| Section 6 Testing | A1 (19 unit) + A2 (3 integration) + A3 (smoke runbook) + A5 (smoke execution) |

Todas as 6 sections cobertas.

**2. Placeholder scan:** zero "TBD/TODO" no plano. Cada step tem código concreto ou comando exato.

**3. Type consistency:**
- `ChangeEventRow` definido em A1, importado em A2 via `dict_to_change_event_row` ✅
- `DriftResult` produzido por `detect_drift` em A1, consumido em A2 wrapper ✅
- Field names consistentes: `responsible_user_emails`, `total_drift_changes`, `total_changes_in_window`, `truncated`, `returned_count`, `flags`, `changes` aparecem identicamente em spec Section 3 e A2 Step 1 ✅

**4. Out-of-scope confirmed deferred (V0 cuts table na spec):**
- Revert suggestions ❌ V0
- Multi-account aggregation ❌ V0
- Notification ❌ V0
- sensitive_field_modified whitelist ❌ V0
- rapid_cluster flag ❌ V0
- resource_types/operation_types filter ❌ V0

**Estimated total: ~110 min** (A1 ~25, A2 ~25, A3 ~5, A4 ~10, A5 ~30 + 15 = ~110).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-21-sprint-3b-33-detect-drift.md`.

**Recomendação:** Subagent-Driven (padrão das últimas 5 sprints 3b.29-3b.32 onde tool inteira). Mas Inline viável se Wellington prefere ver execução direto (tasks A1+A2 são ~50 min combinados, não exorbitante).
