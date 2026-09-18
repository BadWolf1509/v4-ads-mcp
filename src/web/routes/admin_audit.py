"""`/admin/audit` — log de auditoria global (todos os gestores) + export CSV."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.db import connection
from src.db.repositories import google_ads_accounts
from src.web.deps import CurrentUser, current_manager, pending_invites_count
from src.web.routes._shared import _require_admin, templates

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
    page: int = 1,
) -> HTMLResponse:
    _require_admin(user)

    page_size = 50
    offset = (page - 1) * page_size

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[
        int, list[asyncpg.Record], list[asyncpg.Record], list[google_ads_accounts.GoogleAdsAccount]
    ]:
        where = ["al.occurred_at > now() - ($1 || ' days')::interval"]
        params: list[Any] = [str(days)]
        idx = 2
        if manager_id:
            where.append(f"al.manager_id = ${idx}")
            params.append(UUID(manager_id))
            idx += 1
        if customer_id:
            where.append(f"al.customer_id = ${idx}")
            params.append(customer_id)
            idx += 1
        if action_type != "all":
            where.append(f"al.action_type = ${idx}")
            params.append(action_type)
            idx += 1
        if status != "all":
            where.append(f"al.status = ${idx}")
            params.append(status)
            idx += 1

        count_sql = f"SELECT count(*) FROM audit_log al WHERE {' AND '.join(where)}"
        total = await conn.fetchval(count_sql, *params) or 0
        total_pages = max(1, (total + page_size - 1) // page_size)

        rows_sql = f"""SELECT al.id, al.occurred_at, al.action_type, al.operation,
                              al.customer_id, al.target_count, al.status, al.duration_ms,
                              m.email AS manager_email,
                              gaa.descriptive_name AS account_name
                       FROM audit_log al
                       LEFT JOIN managers m ON m.id = al.manager_id
                       LEFT JOIN google_ads_accounts gaa ON gaa.customer_id = al.customer_id
                       WHERE {" AND ".join(where)}
                       ORDER BY al.occurred_at DESC, al.id DESC LIMIT ${idx} OFFSET ${idx + 1}"""
        params_with_pagination = params + [page_size, offset]
        rows = await conn.fetch(rows_sql, *params_with_pagination)

        managers_rows = await conn.fetch(
            "SELECT id, email FROM managers WHERE is_active = true ORDER BY email"
        )
        accs = await google_ads_accounts.list_all(conn)
        return total_pages, rows, managers_rows, accs

    total_pages, rows, managers_rows, accs = await connection.run_with_reconnect(_load)

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
            "rows": [dict(r) for r in rows],
            "managers_list": [dict(r) for r in managers_rows],
            "accounts": accs,
            "filter_manager_id": manager_id or "",
            "filter_customer_id": customer_id or "",
            "filter_action_type": action_type,
            "filter_status": status,
            "filter_days": days,
            "current_page": page,
            "total_pages": total_pages,
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
    days: int = 7,
) -> StreamingResponse:
    """Stream CSV export of the global audit log (admin) with current filters applied."""
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
