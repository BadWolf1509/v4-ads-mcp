"""Matriz de acesso a contas Google e Meta: visão geral, toggles e bulk grant/copy."""

from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    manager_account_access,
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
)
from src.web.deps import CurrentUser, current_manager, pending_invites_count
from src.web.routes._acesso import PLATAFORMAS, aplicar_toggle, conceder_em_massa, copiar_acessos
from src.web.routes._shared import (
    _admin_flash,
    _require_admin,
    _toggle_acesso_response,
    templates,
)

router = APIRouter(tags=["web"])


@router.get("/admin/access", response_class=HTMLResponse)
async def admin_access(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[
        list[asyncpg.Record], list[google_ads_accounts.GoogleAdsAccount], list[asyncpg.Record]
    ]:
        managers_rows = await managers.list_active(conn)
        accs = await google_ads_accounts.list_all(conn)
        # Task 3 (achado extra): revogação virou soft, então a linha do grant
        # revogado FICA — sem o filtro, a célula continuaria marcada mesmo
        # depois do admin revogar (espelha o gêmeo Meta, admin_access_meta).
        access_rows = await manager_account_access.list_live_grants(conn)
        return managers_rows, accs, access_rows

    managers_rows, accs, access_rows = await connection.run_with_reconnect(_load)
    # Build set of (manager_id, customer_id) for quick lookup
    access_set = {(str(r["manager_id"]), r["customer_id"]) for r in access_rows}
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access.html",
        {
            "current_user": user,
            "plataforma": PLATAFORMAS["google"],
            "managers_list": [dict(r) for r in managers_rows],
            "accounts": accs,
            "access_set": access_set,
            "pending_invites_count": pending,
            "flash": _admin_flash(request),
        },
    )


@router.get("/admin/access/meta", response_class=HTMLResponse)
async def admin_access_meta(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[list[asyncpg.Record], list[meta_ad_accounts.MetaAdAccount], list[asyncpg.Record]]:
        managers_rows = await managers.list_active(conn)
        accounts = await meta_ad_accounts.list_all(conn)
        access_rows = await manager_meta_account_access.list_live_grants(conn)
        return managers_rows, accounts, access_rows

    managers_rows, accounts, access_rows = await connection.run_with_reconnect(_load)
    access_set = {(str(r["manager_id"]), r["ad_account_id"]) for r in access_rows}
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access.html",
        {
            "current_user": user,
            "plataforma": PLATAFORMAS["meta"],
            "managers_list": [dict(r) for r in managers_rows],
            "accounts": accounts,
            "access_set": access_set,
            "pending_invites_count": pending,
            "flash": _admin_flash(request),
        },
    )


@router.post("/admin/access/meta/toggle", response_class=HTMLResponse)
async def admin_access_meta_toggle(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: UUID = Form(...),  # noqa: B008
    ad_account_id: str = Form(...),
    desejado: Literal["grant", "revoke"] = Form(...),
) -> HTMLResponse:
    _require_admin(user)
    plataforma = PLATAFORMAS["meta"]
    async with connection.get_pool().acquire() as conn:
        mudou = await aplicar_toggle(
            conn,
            plataforma,
            admin=user,
            manager_id=manager_id,
            conta=ad_account_id,
            desejado=desejado == "grant",
        )
    return _toggle_acesso_response(
        post_url=f"{plataforma.prefixo_url}/toggle",
        manager_id=str(manager_id),
        account_id=ad_account_id,
        account_field=plataforma.coluna_conta,
        granted=desejado == "grant",
        mudou=mudou,
    )


@router.post("/admin/access/meta/bulk-grant", response_class=HTMLResponse, response_model=None)
async def admin_access_meta_bulk_grant(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: UUID = Form(...),  # noqa: B008
    ad_account_ids: list[str] = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    plataforma = PLATAFORMAS["meta"]
    async with connection.get_pool().acquire() as conn:
        await conceder_em_massa(
            conn, plataforma, admin=user, manager_id=manager_id, contas=ad_account_ids
        )
    return RedirectResponse(url=plataforma.prefixo_url, status_code=303)


@router.post("/admin/access/meta/bulk-copy", response_class=HTMLResponse, response_model=None)
async def admin_access_meta_bulk_copy(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    from_manager_id: UUID = Form(...),  # noqa: B008
    to_manager_id: UUID = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    plataforma = PLATAFORMAS["meta"]
    if from_manager_id == to_manager_id:
        return RedirectResponse(url=f"{plataforma.prefixo_url}?error=same_manager", status_code=303)
    async with connection.get_pool().acquire() as conn:
        await copiar_acessos(
            conn,
            plataforma,
            admin=user,
            de_manager_id=from_manager_id,
            para_manager_id=to_manager_id,
        )
    return RedirectResponse(url=plataforma.prefixo_url, status_code=303)


# IMPORTANT: keep /by-manager BEFORE /{manager_id} (literal must match before the path param).
@router.get("/admin/access/meta/by-manager", response_class=HTMLResponse)
async def admin_access_meta_by_manager(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(conn: asyncpg.Connection) -> tuple[list[asyncpg.Record], int]:
        # Os porquês do numerador (revoked_at na condição do LEFT JOIN) e do
        # denominador (só conta ativa) vivem nas docstrings das funções.
        managers_with_counts = await manager_meta_account_access.list_managers_with_counts(conn)
        total_accounts = await manager_meta_account_access.count_active_accounts(conn)
        return managers_with_counts, total_accounts

    managers_with_counts, total_accounts = await connection.run_with_reconnect(_load)
    # F92: fora do bloco de conexão — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_by_manager.html",
        {
            "current_user": user,
            "plataforma": PLATAFORMAS["meta"],
            "managers_with_counts": [dict(r) for r in managers_with_counts],
            "total_accounts": total_accounts,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/access/meta/{manager_id}", response_class=HTMLResponse)
async def admin_access_meta_manager_detail(
    request: Request,
    manager_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    try:
        parsed_manager_id = UUID(manager_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Gestor não encontrado") from None

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    # `HTTPException` (mgr_row ausente) propaga direto: run_with_reconnect só
    # retenta erro de conexão morta, nunca erro de aplicação.
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[asyncpg.Record, list[meta_ad_accounts.MetaAdAccount], set[str]]:
        mgr_row = await managers.get_summary(conn, parsed_manager_id)
        if mgr_row is None:
            raise HTTPException(status_code=404, detail="Gestor não encontrado")
        accs = await meta_ad_accounts.list_all(conn)
        access_rows = await manager_meta_account_access.list_live_grants_for_manager(
            conn, parsed_manager_id
        )
        access_set = {r["ad_account_id"] for r in access_rows}
        return mgr_row, accs, access_set

    mgr_row, accs, access_set = await connection.run_with_reconnect(_load)
    # F92: fora do bloco de conexão — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_manager_detail.html",
        {
            "current_user": user,
            "plataforma": PLATAFORMAS["meta"],
            "manager": dict(mgr_row),
            "accounts": accs,
            "access_set": access_set,
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/access/bulk-grant", response_class=HTMLResponse, response_model=None)
async def admin_access_bulk_grant(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: UUID = Form(...),  # noqa: B008
    customer_ids: list[str] = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    plataforma = PLATAFORMAS["google"]
    async with connection.get_pool().acquire() as conn:
        await conceder_em_massa(
            conn, plataforma, admin=user, manager_id=manager_id, contas=customer_ids
        )
    return RedirectResponse(url=plataforma.prefixo_url, status_code=303)


@router.post("/admin/access/bulk-copy", response_class=HTMLResponse, response_model=None)
async def admin_access_bulk_copy(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    from_manager_id: UUID = Form(...),  # noqa: B008
    to_manager_id: UUID = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    plataforma = PLATAFORMAS["google"]
    if from_manager_id == to_manager_id:
        return RedirectResponse(url=f"{plataforma.prefixo_url}?error=same_manager", status_code=303)
    async with connection.get_pool().acquire() as conn:
        await copiar_acessos(
            conn,
            plataforma,
            admin=user,
            de_manager_id=from_manager_id,
            para_manager_id=to_manager_id,
        )
    return RedirectResponse(url=plataforma.prefixo_url, status_code=303)


@router.get("/admin/access/by-manager", response_class=HTMLResponse)
async def admin_access_by_manager(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    async def _load(conn: asyncpg.Connection) -> tuple[list[asyncpg.Record], int]:
        # Os porquês do numerador (só grant vivo em conta ativa) e do
        # denominador (só conta ativa) vivem nas docstrings das funções.
        managers_with_counts = await manager_account_access.list_managers_with_counts(conn)
        total_accounts = await manager_account_access.count_active_accounts(conn)
        return managers_with_counts, total_accounts

    managers_with_counts, total_accounts = await connection.run_with_reconnect(_load)
    # F92: fora do bloco de conexão — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_by_manager.html",
        {
            "current_user": user,
            "plataforma": PLATAFORMAS["google"],
            "managers_with_counts": [dict(r) for r in managers_with_counts],
            "total_accounts": total_accounts,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/access/{manager_id}", response_class=HTMLResponse)
async def admin_access_manager_detail(
    request: Request,
    manager_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    try:
        parsed_manager_id = UUID(manager_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Gestor não encontrado") from None

    # F76/F77/F91 — leitura idempotente, sobrevive a reconexão (Task 6, PR 5).
    # `HTTPException` (mgr_row ausente) propaga direto: run_with_reconnect só
    # retenta erro de conexão morta, nunca erro de aplicação.
    async def _load(
        conn: asyncpg.Connection,
    ) -> tuple[asyncpg.Record, list[google_ads_accounts.GoogleAdsAccount], set[str]]:
        mgr_row = await managers.get_summary(conn, parsed_manager_id)
        if mgr_row is None:
            raise HTTPException(status_code=404, detail="Gestor não encontrado")
        accs = await google_ads_accounts.list_all(conn)
        access_rows = await manager_account_access.list_live_grants_for_manager(
            conn, parsed_manager_id
        )
        access_set = {r["customer_id"] for r in access_rows}
        return mgr_row, accs, access_set

    mgr_row, accs, access_set = await connection.run_with_reconnect(_load)
    # F92: fora do bloco de conexão — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_manager_detail.html",
        {
            "current_user": user,
            "plataforma": PLATAFORMAS["google"],
            "manager": dict(mgr_row),
            "accounts": accs,
            "access_set": access_set,
            "pending_invites_count": pending,
        },
    )


@router.post("/admin/access/toggle", response_class=HTMLResponse)
async def admin_access_toggle(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: UUID = Form(...),  # noqa: B008
    customer_id: str = Form(...),
    desejado: Literal["grant", "revoke"] = Form(...),
) -> HTMLResponse:
    _require_admin(user)
    plataforma = PLATAFORMAS["google"]
    async with connection.get_pool().acquire() as conn:
        mudou = await aplicar_toggle(
            conn,
            plataforma,
            admin=user,
            manager_id=manager_id,
            conta=customer_id,
            desejado=desejado == "grant",
        )
    return _toggle_acesso_response(
        post_url=f"{plataforma.prefixo_url}/toggle",
        manager_id=str(manager_id),
        account_id=customer_id,
        account_field=plataforma.coluna_conta,
        granted=desejado == "grant",
        mudou=mudou,
    )
