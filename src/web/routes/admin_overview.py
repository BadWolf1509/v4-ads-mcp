"""`/admin` overview + gestão de gestores (`/admin/managers`, toggles de status/role).

A tabela de dez módulos da Task 2 só nomeia `/admin` pra este módulo; as rotas
de `/admin/managers` não têm responsabilidade própria listada e ficam aqui por
serem administração geral de gestor, no mesmo espírito do overview — ver o
relatório da Task 2 para a decisão.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.db import connection
from src.db.repositories import google_oauth_connections, meta_oauth_connections
from src.web.deps import CurrentUser, current_manager, pending_invites_count
from src.web.routes._shared import _audit_admin, _require_admin, meta_expiry_signals, templates

router = APIRouter(tags=["web"])


@router.get("/admin", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Admin overview: operational metrics, usage sparkline, tops, onboarding."""
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import managers as managers_repo

        pending = await managers_repo.count_invited(conn)
        active_mgrs = (
            await conn.fetchval("SELECT count(*) FROM managers WHERE status = 'active'") or 0
        )
        total_mgrs = await conn.fetchval("SELECT count(*) FROM managers") or 0
        quota_used = (
            await conn.fetchval(
                "SELECT COALESCE(SUM(operations_used), 0) FROM rate_counters WHERE date = current_date"
            )
            or 0
        )
        errors_24h = (
            await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE status='error' AND occurred_at > now() - interval '24 hours'"
            )
            or 0
        )

        # Usage 30d sparkline
        rows_30 = await conn.fetch(
            """SELECT (occurred_at::date) AS d, count(*) AS c
               FROM audit_log
               WHERE occurred_at > now() - interval '30 days'
               GROUP BY 1 ORDER BY 1"""
        )
        usage_30d = [r["c"] for r in rows_30]

        # Top operations 7d
        top_ops = await conn.fetch(
            """SELECT operation, count(*) AS count FROM audit_log
               WHERE occurred_at > now() - interval '7 days'
               GROUP BY operation ORDER BY count DESC LIMIT 5"""
        )
        # Top managers 7d
        top_mgrs = await conn.fetch(
            """SELECT m.email, count(*) AS count
               FROM audit_log al JOIN managers m ON m.id = al.manager_id
               WHERE al.occurred_at > now() - interval '7 days'
               GROUP BY m.email ORDER BY count DESC LIMIT 5"""
        )
        # Recent onboarding (last 10 managers by created_at)
        onboarding = await conn.fetch(
            """SELECT email, status, created_at, invited_at
               FROM managers ORDER BY coalesce(invited_at, created_at) DESC LIMIT 10"""
        )

        # Load OAuth connections
        google_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)
        meta_conn = await meta_oauth_connections.get_active_for_manager(conn, user.id)

    meta_expiry = meta_expiry_signals(meta_conn.token_expires_at if meta_conn else None)

    meta_connected = request.query_params.get("meta_connected") == "1"
    meta_revoked = request.query_params.get("meta_revoked") == "1"
    meta_refreshed = request.query_params.get("meta_refreshed") == "1"

    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "current_user": user,
            "pending_invites": pending,
            "pending_invites_count": pending,
            "active_managers": active_mgrs,
            "total_managers": total_mgrs,
            "quota_used": quota_used,
            "quota_max": 15000,
            "errors_24h": errors_24h,
            "usage_30d": usage_30d,
            "top_operations": [dict(r) for r in top_ops],
            "top_managers": [dict(r) for r in top_mgrs],
            "recent_onboarding": [dict(r) for r in onboarding],
            "google_conn": google_conn,
            "meta_conn": meta_conn,
            "meta_token_expired": meta_expiry.expired,
            "meta_token_expiring_soon": meta_expiry.expiring_soon,
            "meta_days_until_expiry": meta_expiry.days_until,
            "meta_days_since_expiry": meta_expiry.days_since,
            "meta_connected": meta_connected,
            "meta_revoked": meta_revoked,
            "meta_refreshed": meta_refreshed,
        },
    )


@router.get("/admin/managers", response_class=HTMLResponse)
async def admin_managers(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, full_name, role, is_active, status, created_at, last_seen_at FROM managers ORDER BY email"
        )
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/managers.html",
        {
            "current_user": user,
            "managers": [dict(r) for r in rows],
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/managers/{manager_id}/toggle-active", response_class=HTMLResponse)
async def admin_managers_toggle_active(
    request: Request,
    manager_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    _require_admin(user)
    if manager_id == user.id:
        raise HTTPException(status_code=400, detail="Nao pode desativar voce mesmo")
    pool = connection.get_pool()
    # Task 5: UPDATE cru e audit na mesma transação — se _audit_admin falhar
    # depois do UPDATE já commitado, o gestor muda de status sem registro de
    # quem mudou (F91: isto é transação, não retry).
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "UPDATE managers SET is_active = NOT is_active WHERE id = $1 RETURNING email",
            manager_id,
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_manager_toggle_active",
            target_manager_id=str(manager_id),
            target_email=row["email"] if row else None,
        )
    if request.headers.get("HX-Request") == "true":
        return Response(
            status_code=204,
            headers={
                "HX-Redirect": "/admin/managers",
                "HX-Trigger": (
                    '{"toast": {"message": "Status do gestor atualizado.", "kind": "success"}}'
                ),
            },
        )
    return RedirectResponse(url="/admin/managers", status_code=303)


@router.post("/admin/managers/{manager_id}/toggle-role", response_class=HTMLResponse)
async def admin_managers_toggle_role(
    request: Request,
    manager_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    _require_admin(user)
    if manager_id == user.id:
        raise HTTPException(status_code=400, detail="Nao pode mudar seu proprio role")
    pool = connection.get_pool()
    # Task 5: UPDATE cru e audit na mesma transação (ver admin_managers_toggle_active).
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            UPDATE managers SET role =
              CASE WHEN role = 'admin' THEN 'gestor' ELSE 'admin' END
            WHERE id = $1
            RETURNING email
            """,
            manager_id,
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_manager_toggle_role",
            target_manager_id=str(manager_id),
            target_email=row["email"] if row else None,
        )
    if request.headers.get("HX-Request") == "true":
        return Response(
            status_code=204,
            headers={
                "HX-Redirect": "/admin/managers",
                "HX-Trigger": (
                    '{"toast": {"message": "Role do gestor atualizado.", "kind": "success"}}'
                ),
            },
        )
    return RedirectResponse(url="/admin/managers", status_code=303)
