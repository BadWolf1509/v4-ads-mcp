"""Convites de gestor: listar, criar, cancelar."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.config import get_settings
from src.db import connection
from src.web.deps import CurrentUser, current_manager, pending_invites_count
from src.web.routes._shared import _admin_flash, _audit_admin, _require_admin, templates

router = APIRouter(tags=["web"])


@router.get("/admin/invites", response_class=HTMLResponse)
async def admin_invites(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        invites = await conn.fetch(
            """SELECT m.id, m.email, m.full_name, m.invited_at,
                      inviter.email AS invited_by_email
               FROM managers m
               LEFT JOIN managers inviter ON inviter.id = m.invited_by
               WHERE m.status = 'invited'
               ORDER BY m.invited_at DESC"""
        )
    pending = await pending_invites_count()
    now = datetime.now(UTC)
    invites_with_age = []
    for r in invites:
        inv = dict(r)
        inv["days_pending"] = (now - inv["invited_at"]).days if inv["invited_at"] else 0
        invites_with_age.append(inv)
    return templates.TemplateResponse(
        request,
        "admin/invites.html",
        {
            "current_user": user,
            "invites": invites_with_age,
            "pending_invites_count": pending,
            "panel_url": get_settings().public_base_url,
            "flash": _admin_flash(request, ok_message="Convite criado."),
        },
    )


@router.post("/admin/invites/new", response_class=HTMLResponse, response_model=None)
async def admin_invites_new(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    email: str = Form(...),
    full_name: str = Form(""),
) -> RedirectResponse:
    _require_admin(user)
    email = email.strip().lower()
    if not email.endswith("@v4company.com"):
        return RedirectResponse(url="/admin/invites?error=bad_domain", status_code=303)

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Idempotency: if email already exists in any status, don't double-invite
        existing = await conn.fetchval("SELECT 1 FROM managers WHERE email = $1", email)
        if existing:
            return RedirectResponse(url="/admin/invites?error=exists", status_code=303)

        from src.db.repositories import managers as managers_repo

        # Task 5: criação do convite e audit na mesma transação — se
        # _audit_admin falhar depois do INSERT já commitado, o convite existe
        # sem registro de quem convidou (F91: isto é transação, não retry).
        async with conn.transaction():
            await managers_repo.create_invited(
                conn,
                email=email,
                invited_by=user.id,
                full_name=(full_name or None),
            )
            await _audit_admin(
                conn,
                admin=user,
                operation="admin_invite_new",
                email=email,
            )
    return RedirectResponse(url="/admin/invites?ok=1", status_code=303)


@router.post("/admin/invites/{invite_id}/cancel", response_class=HTMLResponse, response_model=None)
async def admin_invites_cancel(
    request: Request,
    invite_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    _require_admin(user)
    try:
        parsed_invite_id = UUID(invite_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Não encontrado") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import managers as managers_repo

        email = await conn.fetchval("SELECT email FROM managers WHERE id = $1", parsed_invite_id)
        # Task 5: cancelamento do convite e audit na mesma transação (ver
        # admin_invites_new).
        async with conn.transaction():
            await managers_repo.delete_invite(conn, manager_id=parsed_invite_id)
            await _audit_admin(
                conn,
                admin=user,
                operation="admin_invite_cancel",
                email=email,
            )
    if request.headers.get("HX-Request"):
        # Full-page refresh (browser reload) picks up the updated pending
        # count + subnav badge for free — cheaper than hand-updating both.
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return RedirectResponse(url="/admin/invites", status_code=303)
