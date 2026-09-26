"""`/admin/audit` — log de auditoria global (todos os gestores) + export CSV."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.db import connection
from src.db.repositories import audit_log, google_ads_accounts
from src.web.deps import CurrentUser, current_manager, pending_invites_count
from src.web.routes._shared import _TETO_DIAS_EXPORT_AUDIT, _require_admin, templates

router = APIRouter(tags=["web"])


@router.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str | None = None,
    customer_id: str | None = None,
    action_type: str = "all",
    status: str = "all",
    days: int = 7,
    cursor_at: datetime | None = None,
    cursor_id: int | None = None,
) -> HTMLResponse:
    _require_admin(user)

    limit = 50
    # Um cursor so faz sentido inteiro (ver mesma nota em routes/audit.py) —
    # metade dele nao ancora a tupla, so faz o WHERE nao bater linha nenhuma.
    if cursor_at is None or cursor_id is None:
        cursor_at = None
        cursor_id = None
    is_first_page = cursor_at is None

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[
        list[dict[str, Any]],
        tuple[datetime, int] | None,
        list[asyncpg.Record],
        list[google_ads_accounts.GoogleAdsAccount],
    ]:
        rows, next_cursor = await audit_log.list_page_admin(
            conn,
            days=days,
            manager_id=UUID(manager_id) if manager_id else None,
            customer_id=customer_id,
            action_type=action_type,
            status=status,
            cursor_occurred_at=cursor_at,
            cursor_id=cursor_id,
            limit=limit,
        )

        managers_rows = await conn.fetch(
            "SELECT id, email FROM managers WHERE is_active = true ORDER BY email"
        )
        accs = await google_ads_accounts.list_all(conn)
        return rows, next_cursor, managers_rows, accs

    rows, next_cursor, managers_rows, accs = await connection.run_with_reconnect(_load)
    next_cursor_at, next_cursor_id = next_cursor if next_cursor else (None, None)

    # Build query_string for CSV export link
    qparts = []
    if manager_id:
        qparts.append(f"manager_id={manager_id}")
    if customer_id:
        qparts.append(f"customer_id={customer_id}")
    if action_type != "all":
        qparts.append(f"action_type={action_type}")
    if status != "all":
        qparts.append(f"status={status}")
    qparts.append(f"days={days}")
    query_string = "&".join(qparts)

    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "current_user": user,
            "rows": rows,
            "managers_list": [dict(r) for r in managers_rows],
            "accounts": accs,
            "filter_manager_id": manager_id or "",
            "filter_customer_id": customer_id or "",
            "filter_action_type": action_type,
            "filter_status": status,
            "filter_days": days,
            "next_cursor_at": next_cursor_at.isoformat() if next_cursor_at else None,
            "next_cursor_id": next_cursor_id,
            "is_first_page": is_first_page,
            "query_string": query_string,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/audit/export.csv", response_model=None)
async def admin_audit_export_csv(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str | None = None,
    action_type: str = "all",
    customer_id: str | None = None,
    status: str = "all",
    days: int = Query(7, ge=1, le=_TETO_DIAS_EXPORT_AUDIT),  # noqa: B008
) -> StreamingResponse:
    """Stream CSV export of the global audit log (admin) with current filters applied.

    O arquivo termina com uma linha-sentinela; a AUSENCIA dela significa
    export incompleto (o 200 ja foi enviado quando a primeira linha saiu).
    """
    _require_admin(user)
    pool = connection.get_pool()
    scope_manager_id = UUID(manager_id) if manager_id else None

    async def stream() -> AsyncIterator[bytes]:
        async with pool.acquire() as conn:
            from src.db.repositories import audit_log

            async for line in audit_log.export_csv_rows(
                conn,
                manager_id=scope_manager_id,
                customer_id=customer_id,
                action_type=action_type if action_type != "all" else None,
                status=status if status != "all" else None,
                days=days,
            ):
                yield line.encode("utf-8")

    filename = f"audit-admin-{datetime.now(UTC).strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
