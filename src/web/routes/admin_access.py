"""Matriz de acesso a contas Google e Meta: visão geral, toggles e bulk grant/copy."""

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    manager_account_access,
    manager_meta_account_access,
    meta_ad_accounts,
)
from src.web.deps import CurrentUser, current_manager, pending_invites_count
from src.web.routes._shared import (
    _admin_flash,
    _audit_admin,
    _require_admin,
    _toggle_checkbox_fragment,
    templates,
)

router = APIRouter(tags=["web"])


@router.get("/admin/access", response_class=HTMLResponse)
async def admin_access(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_rows = await conn.fetch(
            "SELECT id, email, full_name, role FROM managers WHERE is_active = true ORDER BY email"
        )
        accs = await google_ads_accounts.list_all(conn)
        # Task 3 (achado extra): revogação virou soft, então a linha do grant
        # revogado FICA — sem o filtro, a célula continuaria marcada mesmo
        # depois do admin revogar (espelha o gêmeo Meta, admin_access_meta).
        access_rows = await conn.fetch(
            "SELECT manager_id, customer_id FROM manager_account_access WHERE revoked_at IS NULL"
        )
    # Build set of (manager_id, customer_id) for quick lookup
    access_set = {(str(r["manager_id"]), r["customer_id"]) for r in access_rows}
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access.html",
        {
            "current_user": user,
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
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_rows = await conn.fetch(
            "SELECT id, email, full_name, role FROM managers WHERE is_active = true ORDER BY email"
        )
        accounts = await meta_ad_accounts.list_all(conn)
        access_rows = await conn.fetch(
            "SELECT manager_id, ad_account_id FROM manager_meta_account_access "
            "WHERE revoked_at IS NULL"
        )
    access_set = {(str(r["manager_id"]), r["ad_account_id"]) for r in access_rows}
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_meta.html",
        {
            "current_user": user,
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
    manager_id: str = Form(...),
    ad_account_id: str = Form(...),
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    target_mid = UUID(manager_id)
    async with pool.acquire() as conn:
        # revoked_at IS NULL: linha revogada não conta como "tem acesso" — senão
        # o clique num checkbox desmarcado (grant revogado) chamaria revoke() de
        # novo em vez de restaurar, e o toggle ficaria preso sem nunca marcar.
        exists = await conn.fetchval(
            "SELECT 1 FROM manager_meta_account_access "
            "WHERE manager_id=$1 AND ad_account_id=$2 AND revoked_at IS NULL",
            target_mid,
            ad_account_id,
        )
        if exists:
            await manager_meta_account_access.revoke(
                conn, manager_id=target_mid, ad_account_id=ad_account_id
            )
            granted = False
        else:
            await manager_meta_account_access.grant(
                conn,
                manager_id=target_mid,
                ad_account_id=ad_account_id,
                access_level="write",
                granted_by=user.id,
            )
            granted = True
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_access_grant" if granted else "admin_access_revoke",
            customer_id=ad_account_id,
            platform="meta",
            target_manager_id=manager_id,
            granted=granted,
        )
    return HTMLResponse(
        _toggle_checkbox_fragment(
            post_url="/admin/access/meta/toggle",
            manager_id=manager_id,
            account_id=ad_account_id,
            account_field="ad_account_id",
            checked=granted,
        )
    )


@router.post("/admin/access/meta/bulk-grant", response_class=HTMLResponse, response_model=None)
async def admin_access_meta_bulk_grant(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str = Form(...),  # noqa: B008
    ad_account_ids: list[str] = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_meta_account_access.bulk_grant(
            conn,
            manager_id=UUID(manager_id),
            ad_account_ids=ad_account_ids,
            granted_by=user.id,
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_access_bulk_grant",
            platform="meta",
            target_manager_id=manager_id,
            count=len(ad_account_ids),
            ids=ad_account_ids[:20],
        )
    return RedirectResponse(url="/admin/access/meta", status_code=303)


@router.post("/admin/access/meta/bulk-copy", response_class=HTMLResponse, response_model=None)
async def admin_access_meta_bulk_copy(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    from_manager_id: str = Form(...),
    to_manager_id: str = Form(...),
) -> RedirectResponse:
    _require_admin(user)
    if from_manager_id == to_manager_id:
        return RedirectResponse(url="/admin/access/meta?error=same_manager", status_code=303)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_meta_account_access.copy_access(
            conn,
            from_manager_id=UUID(from_manager_id),
            to_manager_id=UUID(to_manager_id),
            granted_by=user.id,
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_access_bulk_copy",
            platform="meta",
            from_manager_id=from_manager_id,
            to_manager_id=to_manager_id,
        )
    return RedirectResponse(url="/admin/access/meta", status_code=303)


# IMPORTANT: keep /by-manager BEFORE /{manager_id} (literal must match before the path param).
@router.get("/admin/access/meta/by-manager", response_class=HTMLResponse)
async def admin_access_meta_by_manager(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # I1 (fix round 1): revoked_at entra na CONDICAO do LEFT JOIN, nao no
        # WHERE — WHERE excluiria o gestor inteiro (LEFT vira INNER na pratica)
        # quando todos os grants dele estao revogados, e ele tem que continuar
        # aparecendo com "0 / total". Sem este filtro a contagem incluia grant
        # revogado e contradizia a pagina de detalhe (que ja filtra).
        managers_with_counts = await conn.fetch(
            """SELECT m.id, m.email, m.full_name,
                      count(mmaa.ad_account_id) AS access_count
               FROM managers m
               LEFT JOIN manager_meta_account_access mmaa
                      ON mmaa.manager_id = m.id AND mmaa.revoked_at IS NULL
               WHERE m.is_active = true
               GROUP BY m.id ORDER BY m.email"""
        )
        # M8 (revisao de branch): so conta ATIVA. A pagina de detalhe monta a
        # matriz por `list_all`, que ja filtra `is_active` — sem o filtro aqui o
        # denominador crescia com cada conta desativada pelo offboarding
        # automatico e as duas telas voltavam a discordar, que e exatamente a
        # divergencia que o I1 da Task 5 fechou no numerador.
        total_accounts = (
            await conn.fetchval("SELECT count(*) FROM meta_ad_accounts WHERE is_active = true") or 0
        )
    # F92: FORA do `async with` — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_by_manager_meta.html",
        {
            "current_user": user,
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
        raise HTTPException(status_code=404, detail="Gestor not found") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mgr_row = await conn.fetchrow(
            "SELECT id, email, full_name FROM managers WHERE id = $1", parsed_manager_id
        )
        if mgr_row is None:
            raise HTTPException(status_code=404, detail="Gestor not found")
        accs = await meta_ad_accounts.list_all(conn)
        access_rows = await conn.fetch(
            "SELECT ad_account_id FROM manager_meta_account_access "
            "WHERE manager_id = $1 AND revoked_at IS NULL",
            parsed_manager_id,
        )
        access_set = {r["ad_account_id"] for r in access_rows}
    # F92: FORA do `async with` — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_manager_detail_meta.html",
        {
            "current_user": user,
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
    manager_id: str = Form(...),  # noqa: B008
    customer_ids: list[str] = Form(...),  # noqa: B008
) -> RedirectResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_account_access.bulk_grant(
            conn,
            manager_id=UUID(manager_id),
            customer_ids=customer_ids,
            granted_by=user.id,
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_access_bulk_grant",
            target_manager_id=manager_id,
            count=len(customer_ids),
            ids=customer_ids[:20],
        )
    return RedirectResponse(url="/admin/access", status_code=303)


@router.post("/admin/access/bulk-copy", response_class=HTMLResponse, response_model=None)
async def admin_access_bulk_copy(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    from_manager_id: str = Form(...),
    to_manager_id: str = Form(...),
) -> RedirectResponse:
    _require_admin(user)
    if from_manager_id == to_manager_id:
        return RedirectResponse(url="/admin/access?error=same_manager", status_code=303)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_account_access.copy_access(
            conn,
            from_manager_id=UUID(from_manager_id),
            to_manager_id=UUID(to_manager_id),
            granted_by=user.id,
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_access_bulk_copy",
            from_manager_id=from_manager_id,
            to_manager_id=to_manager_id,
        )
    return RedirectResponse(url="/admin/access", status_code=303)


@router.get("/admin/access/by-manager", response_class=HTMLResponse)
async def admin_access_by_manager(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Revisão final (item 1): numerador e denominador tem que viver no
        # MESMO universo. O I4 abaixo corrigiu só o denominador — o numerador
        # cru (`count(maa.customer_id)`) continuava contando grant vivo em
        # conta que já saiu do MCC (is_active=false, nunca revogada), e a
        # tela chegou a mostrar razão impossível (2/1, numerador > denominador
        # — medido em container). O segundo LEFT JOIN faz o mesmo que o
        # denominador faz sozinho: só conta grant vivo cuja conta AINDA está
        # em `google_ads_accounts.is_active = true`. É LEFT (não JOIN puro)
        # de propósito — um gestor cujos únicos grants apontam pra conta
        # inativa tem que continuar aparecendo com "0 / total", não sumir da
        # lista.
        managers_with_counts = await conn.fetch(
            """SELECT m.id, m.email, m.full_name,
                      count(a.customer_id) AS access_count
               FROM managers m
               LEFT JOIN manager_account_access maa
                      ON maa.manager_id = m.id AND maa.revoked_at IS NULL
               LEFT JOIN google_ads_accounts a
                      ON a.customer_id = maa.customer_id AND a.is_active = true
               WHERE m.is_active = true
               GROUP BY m.id ORDER BY m.email"""
        )
        # I4 (revisao de branch): so conta ATIVA. A pagina de detalhe monta a
        # matriz por `list_all`, que ja filtra `is_active` — sem o filtro aqui
        # o denominador crescia com cada conta desativada pelo offboarding
        # automatico e as duas telas voltavam a discordar. Mesmo fix do M8
        # (gemeo Meta, routes.py:1274).
        total_accounts = (
            await conn.fetchval("SELECT count(*) FROM google_ads_accounts WHERE is_active = true")
            or 0
        )
    # F92: FORA do `async with` — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_by_manager.html",
        {
            "current_user": user,
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
        raise HTTPException(status_code=404, detail="Gestor not found") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mgr_row = await conn.fetchrow(
            "SELECT id, email, full_name FROM managers WHERE id = $1", parsed_manager_id
        )
        if mgr_row is None:
            raise HTTPException(status_code=404, detail="Gestor not found")
        accs = await google_ads_accounts.list_all(conn)
        # Task 3 (achado extra): mesmo raciocínio do admin_access — grant
        # revogado é soft, a linha fica, então sem o filtro o checkbox
        # continuaria marcado (espelha o gêmeo Meta, admin_access_manager_
        # detail_meta, linha ~1307).
        access_rows = await conn.fetch(
            "SELECT customer_id FROM manager_account_access "
            "WHERE manager_id = $1 AND revoked_at IS NULL",
            parsed_manager_id,
        )
        access_set = {r["customer_id"] for r in access_rows}
    # F92: FORA do `async with` — este helper abre a propria conexao, e
    # segurar uma e esperar por outra trava pra sempre com o pool cheio.
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/access_manager_detail.html",
        {
            "current_user": user,
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
    manager_id: str = Form(...),
    customer_id: str = Form(...),
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    target_mid = UUID(manager_id)
    async with pool.acquire() as conn:
        # Task 3, decisão 1: revogação virou soft — a linha FICA depois do
        # revoke. Sem `revoked_at IS NULL` aqui, `exists` continuaria true numa
        # linha revogada, e o clique seguinte (reconceder) chamaria revoke()
        # de novo em vez de grant() — nunca mais daria pra reconceder pelo
        # painel (espelha o gêmeo Meta, admin_access_meta_toggle).
        exists = await conn.fetchval(
            "SELECT 1 FROM manager_account_access "
            "WHERE manager_id = $1 AND customer_id = $2 AND revoked_at IS NULL",
            target_mid,
            customer_id,
        )
        if exists:
            await manager_account_access.revoke(
                conn,
                manager_id=target_mid,
                customer_id=customer_id,
            )
            granted = False
        else:
            await manager_account_access.grant(
                conn,
                manager_id=target_mid,
                customer_id=customer_id,
                access_level="write",
                granted_by=user.id,
            )
            granted = True

        await _audit_admin(
            conn,
            admin=user,
            operation="admin_access_grant" if granted else "admin_access_revoke",
            customer_id=customer_id,
            target_manager_id=manager_id,
            granted=granted,
        )

    # Return a tiny HTMX-friendly fragment that swaps the cell
    return HTMLResponse(
        _toggle_checkbox_fragment(
            post_url="/admin/access/toggle",
            manager_id=manager_id,
            account_id=customer_id,
            account_field="customer_id",
            checked=granted,
        )
    )
