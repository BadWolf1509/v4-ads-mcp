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
