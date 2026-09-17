"""Contas visíveis ao gestor (não-admin): conexões OAuth Google + contas Google/Meta."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.db import connection
from src.db.repositories import (
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
)
from src.web.deps import CurrentUser, current_manager
from src.web.routes._shared import templates

router = APIRouter(tags=["web"])


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """List Google OAuth connections + accessible Google Ads accounts."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # All connections (including revoked, sorted most-recent first)
        all_conns = await conn.fetch(
            """
            SELECT id, google_email, scopes, connected_at, revoked_at
            FROM google_oauth_connections
            WHERE manager_id = $1
            ORDER BY connected_at DESC
            """,
            user.id,
        )
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)
        meta_accounts = await manager_meta_account_access.list_accounts_for_manager(conn, user.id)

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "current_user": user,
            "connections": [dict(r) for r in all_conns],
            "accounts": accounts,
            "meta_accounts": meta_accounts,
        },
    )


@router.post("/accounts/{connection_id}/revoke", response_class=HTMLResponse, response_model=None)
async def accounts_revoke_connection(
    request: Request,
    connection_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    """Revoke an OAuth connection (sets revoked_at). Manager can reconnect later."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Verify ownership
        owner = await conn.fetchval(
            "SELECT manager_id FROM google_oauth_connections WHERE id = $1",
            connection_id,
        )
        if owner != user.id:
            raise HTTPException(status_code=404, detail="Connection not found")
        await google_oauth_connections.revoke(conn, connection_id)

    if request.headers.get("HX-Request"):
        # F96 — o XHR do htmx SEGUE o 303, então devolver redirect aqui entregava
        # a página `/accounts` inteira pro swap. Full refresh do browser re-renderiza
        # a lista de conexões (e o badge) de graça, como em `admin_invite_cancel`.
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return RedirectResponse(url="/accounts", status_code=303)
