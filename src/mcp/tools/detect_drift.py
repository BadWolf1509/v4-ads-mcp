"""Tool: detect_drift — auditar mudanças NÃO-autorizadas pós-batch V4.

Sprint 3b.33 — W1 do dogfood 2026-05-21 MO-JP+CAB (ICE 486).
Wrapper sobre get_change_history + pure aggregator com 3 flags acionáveis.
Use case primário: co-management (lição 46 dogfood).
"""

from datetime import UTC, date, datetime, timedelta
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
            "description": ("Cap em changes[] na response. Summary + flags refletem total bruto."),
        },
    },
    "required": ["customer_id"],
    "additionalProperties": False,
}


def _resolve_date_window_local(
    date_range: str | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[date, date]:
    """Resolve date window including LAST_2_DAYS preset (not in shared _PRESETS).

    Precedence: explicit start_date+end_date override date_range.
    LAST_2_DAYS = yesterday + day before yesterday (2-day window).
    Delegates all other presets to shared resolve_date_window helper.
    """
    # Explicit dates always win
    if start_date is not None or end_date is not None:
        return resolve_date_window(
            date_range=None,
            start_date=start_date,
            end_date=end_date,
        )

    # Handle LAST_2_DAYS locally (not in shared _PRESETS)
    preset = (date_range or "LAST_2_DAYS").upper()
    if preset == "LAST_2_DAYS":
        today = datetime.now(UTC).date()
        yesterday = today - timedelta(days=1)
        day_before = today - timedelta(days=2)
        return day_before, yesterday

    # Delegate all other presets to shared helper
    return resolve_date_window(
        date_range=date_range,
        start_date=None,
        end_date=None,
    )


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
    get_current()  # ensure context is bound (programmer-error guard)
    customer_id = args["customer_id"]
    responsible_user_emails = args.get("responsible_user_emails", [])
    limit = args.get("limit", 100)

    # Resolve date window LOCALLY (LAST_2_DAYS é preset detect_drift-only).
    # Passamos start_date+end_date explícitos pro get_change_history.
    start_date_obj, end_date_obj = _resolve_date_window_local(
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
