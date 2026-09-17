"""`/audit` e `/audit/export.csv` do gestor (não-admin) + detalhe de um evento."""

from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.db import connection
from src.db.repositories import manager_account_access
from src.web.deps import CurrentUser, current_manager
from src.web.routes._shared import templates

router = APIRouter(tags=["web"])


@router.get("/audit", response_class=HTMLResponse)
async def audit(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    action_type: str = "all",
    customer_id: str | None = None,
    status: str = "all",
    days: int = 7,
    page: int = 1,
) -> HTMLResponse:
    page_size = 50
    offset = (page - 1) * page_size

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)

        # Build dynamic WHERE
        where = ["al.manager_id = $1", "al.occurred_at > now() - ($2 || ' days')::interval"]
        params: list[Any] = [user.id, str(days)]
        idx = 3
        if action_type != "all":
            where.append(f"al.action_type = ${idx}")
            params.append(action_type)
            idx += 1
        if customer_id:
            where.append(f"al.customer_id = ${idx}")
            params.append(customer_id)
            idx += 1
        if status != "all":
            where.append(f"al.status = ${idx}")
            params.append(status)
            idx += 1

        count_sql = f"SELECT count(*) FROM audit_log al WHERE {' AND '.join(where)}"
        total = await conn.fetchval(count_sql, *params) or 0
        total_pages = max(1, (total + page_size - 1) // page_size)

        rows_sql = f"""SELECT al.*, a.descriptive_name AS account_name
                       FROM audit_log al LEFT JOIN google_ads_accounts a
                         ON a.customer_id = al.customer_id
                       WHERE {" AND ".join(where)}
                       ORDER BY al.occurred_at DESC, al.id DESC LIMIT ${idx} OFFSET ${idx + 1}"""
        params_with_pagination = params + [page_size, offset]
        rows = await conn.fetch(rows_sql, *params_with_pagination)

    # Group by day for sticky day headers
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    today = datetime.now(UTC).date()
    for r in rows:
        d = r["occurred_at"].date()
        if d == today:
            label = "Hoje"
        elif d == today - timedelta(days=1):
            label = "Ontem"
        else:
            label = d.strftime("%d/%m/%Y")
        grouped.setdefault(label, []).append(dict(r))

    # Preserve query string for CSV export link
    qparts = []
    if action_type != "all":
        qparts.append(f"action_type={action_type}")
    if customer_id:
        qparts.append(f"customer_id={customer_id}")
    if status != "all":
        qparts.append(f"status={status}")
    qparts.append(f"days={days}")
    query_string = "&".join(qparts)

    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "current_user": user,
            "grouped": grouped,
            "accessible_accounts": accounts,
            "filter_action_type": action_type,
            "filter_customer_id": customer_id,
            "filter_status": status,
            "filter_days": days,
            "current_page": page,
            "total_pages": total_pages,
            "query_string": query_string,
        },
    )


@router.get("/audit/export.csv", response_model=None)
async def audit_export_csv(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    action_type: str = "all",
    customer_id: str | None = None,
    status: str = "all",
    days: int = 7,
) -> StreamingResponse:
    """Stream CSV export of the gestor's audit log with current filters applied."""
    pool = connection.get_pool()

    async def stream() -> AsyncIterator[bytes]:
        async with pool.acquire() as conn:
            from src.db.repositories import audit_log

            async for line in audit_log.export_csv_rows(
                conn,
                manager_id=user.id,
                customer_id=customer_id,
                action_type=action_type if action_type != "all" else None,
                status=status if status != "all" else None,
                days=days,
            ):
                yield line.encode("utf-8")

    filename = f"audit-{datetime.now(UTC).strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit/{audit_id}", response_class=HTMLResponse)
async def audit_detail(
    request: Request,
    audit_id: int,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Audit event detail. audit_log.id is BIGSERIAL (int), not UUID."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import audit_log

        # Gestores see only their own; admins see any
        scope_id = None if user.is_admin else user.id
        event = await audit_log.get_by_id(conn, audit_id=audit_id, manager_id=scope_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found or out of scope")
    return templates.TemplateResponse(
        request,
        "audit_detail.html",
        {"current_user": user, "event": event},
    )
