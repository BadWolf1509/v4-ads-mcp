"""Contas visíveis ao gestor (não-admin): conexões OAuth Google + contas Google/Meta."""

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from src.db import connection
from src.db.repositories import (
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
)
from src.web.deps import CurrentUser, current_manager
from src.web.routes._shared import resposta_hx, templates

router = APIRouter(tags=["web"])


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """List Google OAuth connections + accessible Google Ads accounts."""

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(conn: asyncpg.Connection) -> tuple[list[asyncpg.Record], list[Any], list[Any]]:
        # All connections (including revoked, sorted most-recent first)
        all_conns = await google_oauth_connections.list_for_manager(conn, user.id)
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)
        meta_accounts = await manager_meta_account_access.list_accounts_for_manager(conn, user.id)
        return all_conns, accounts, meta_accounts

    all_conns, accounts, meta_accounts = await connection.run_with_reconnect(_load)

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
        owner = await google_oauth_connections.get_owner(conn, connection_id)
        if owner != user.id:
            raise HTTPException(status_code=404, detail="Conexão não encontrada")
        await google_oauth_connections.revoke(conn, connection_id)

    # F96 — o XHR do htmx SEGUE o 303; `resposta_hx` devolve 204 + HX-Refresh,
    # e o refresh re-renderiza a lista de conexões (e o badge) de graça.
    return resposta_hx(request, destino="/accounts")
