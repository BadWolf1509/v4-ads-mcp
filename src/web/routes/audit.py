"""`/audit` e `/audit/export.csv` do gestor (não-admin) + detalhe de um evento."""

from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from src.db import connection
from src.db.repositories import audit_log, manager_account_access
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
    cursor_at: datetime | None = None,
    cursor_id: int | None = None,
) -> HTMLResponse:
    limit = 50
    # Um cursor so faz sentido inteiro — metade dele nao ancora a tupla
    # (WHERE ($1 IS NULL OR (occurred_at, id) < ($1, $2)) com $2 NULL nao
    # bate nenhuma linha, silenciosamente). Normaliza pra "sem cursor" em vez
    # de propagar um estado que o SQL nao consegue expressar.
    if cursor_at is None or cursor_id is None:
        cursor_at = None
        cursor_id = None
    is_first_page = cursor_at is None

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[list[Any], list[dict[str, Any]], tuple[datetime, int] | None]:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)
        rows, next_cursor = await audit_log.list_page_for_manager(
            conn,
            manager_id=user.id,
            days=days,
            customer_id=customer_id,
            action_type=action_type,
            status=status,
            cursor_occurred_at=cursor_at,
            cursor_id=cursor_id,
            limit=limit,
        )
        return accounts, rows, next_cursor

    accounts, rows, next_cursor = await connection.run_with_reconnect(_load)
    next_cursor_at, next_cursor_id = next_cursor if next_cursor else (None, None)

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
        grouped.setdefault(label, []).append(r)

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
            "next_cursor_at": next_cursor_at.isoformat() if next_cursor_at else None,
            "next_cursor_id": next_cursor_id,
            "is_first_page": is_first_page,
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

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(conn: asyncpg.Connection) -> dict[str, Any] | None:
        from src.db.repositories import audit_log

        # Gestores see only their own; admins see any
        scope_id = None if user.is_admin else user.id
        return await audit_log.get_by_id(conn, audit_id=audit_id, manager_id=scope_id)

    event = await connection.run_with_reconnect(_load)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found or out of scope")
    return templates.TemplateResponse(
        request,
        "audit_detail.html",
        {"current_user": user, "event": event},
    )
