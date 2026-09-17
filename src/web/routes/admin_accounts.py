"""`/admin/accounts` (Google + Meta) e as rotas de restauração de acesso pós-churn."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    manager_account_access,
    manager_meta_account_access,
    meta_ad_accounts,
)
from src.web.deps import CurrentUser, current_manager, pending_invites_count
from src.web.routes._shared import (
    _GOOGLE_ACCOUNTS_FLASH_OK,
    _META_ACCOUNTS_FLASH_OK,
    _admin_flash,
    _audit_admin,
    _require_admin,
    templates,
)

router = APIRouter(tags=["web"])


@router.get("/admin/accounts", response_class=HTMLResponse)
async def admin_accounts(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accs = await google_ads_accounts.list_all(conn)
        # Espelha admin_accounts_meta: as duas filas do lado Google (conta
        # ativa sem gestor delegado, conta que voltou ao MCC com restauração
        # pendente) — ver google_ads_accounts.list_queues.
        queues = await google_ads_accounts.list_queues(conn)
    mccs = sorted({a.mcc_id for a in accs if a.mcc_id})
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/accounts.html",
        {
            "current_user": user,
            "accounts": accs,
            "mccs": mccs,
            "sem_delegacao": queues.sem_delegacao,
            "voltaram_ao_mcc": queues.voltaram_ao_mcc,
            "pending_invites_count": pending,
            "flash": _admin_flash(request, ok_codes=_GOOGLE_ACCOUNTS_FLASH_OK),
        },
    )


@router.post("/admin/accounts/{customer_id}/restore", response_class=HTMLResponse)
async def admin_accounts_google_restore(
    request: Request,
    customer_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    """Reconcede os grants que `revoke_for_inactive_accounts` revogou quando a
    conta saiu do MCC — SÓ esses (filtra `LEFT_MCC_REASON`), não qualquer
    revogação que a conta tenha acumulado por outro motivo. Espelha
    `admin_accounts_meta_restore`.

    Só faz sentido com a conta ATIVA, isto é, depois que ela voltou ao MCC.
    Sobre conta inativa o restore limparia `revoked_at` sem destravar nada (o
    gate exige conta ativa) e, pior, produziria um grant vivo que o painel não
    tem como mostrar de volta — a fila `voltaram_ao_mcc` já exige `is_active =
    true` por construção, então essa conta não reaparece em lugar nenhum até
    a reconciliação reativá-la de verdade. O botão nem é renderizado nesse
    estado; a checagem aqui é pra POST direto ou aba velha reenviada.
    """
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        conta = await google_ads_accounts.get_by_customer_id(conn, customer_id)
        if conta is None or not conta.is_active:
            # Restaurar em conta inativa produz grant que o gate nega —
            # trabalho inútil apresentado como sucesso.
            return RedirectResponse(
                url="/admin/accounts?error=conta_inativa_google", status_code=303
            )
        restaurados = await manager_account_access.restore_for_account(
            conn, customer_id=customer_id
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_accounts_google_restore",
            customer_id=customer_id,
            restored_grants=len(restaurados),
        )
    return RedirectResponse(url="/admin/accounts?ok=restored", status_code=303)


@router.get("/admin/accounts/meta", response_class=HTMLResponse)
async def admin_accounts_meta(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await meta_ad_accounts.list_all(conn)
        # Spec 2026-08-20: substitui a secao unica "Fora do alcance" do F128 (d)
        # por tres filas — sem-delegacao, sem-SU e saiu-da-parceria sao tres
        # ACOES diferentes do admin, e a lista antiga nao distinguia nenhuma
        # delas (nao cruzava grants, nao lia su_reachable).
        queues = await meta_ad_accounts.list_queues(conn)
    pending = await pending_invites_count()
    token_configured = bool(get_settings().meta_system_user_token)
    return templates.TemplateResponse(
        request,
        "admin/accounts_meta.html",
        {
            "current_user": user,
            "accounts": accounts,
            "sem_delegacao": queues.sem_delegacao,
            "sem_su": queues.sem_su,
            "saiu_da_parceria": queues.saiu_da_parceria,
            "token_configured": token_configured,
            "pending_invites_count": pending,
            "flash": _admin_flash(request, ok_codes=_META_ACCOUNTS_FLASH_OK),
        },
    )


@router.post(
    "/admin/accounts/meta/{ad_account_id}/restore",
    response_class=HTMLResponse,
    response_model=None,
)
async def admin_accounts_meta_restore(
    request: Request,
    ad_account_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    """Reconcede os grants que `revoke_for_account` revogou quando a conta saiu
    da parceria — SO esses (filtra `PARTNERSHIP_ENDED_REASON`), nao qualquer
    revogacao que a conta tenha acumulado por outro motivo.

    So faz sentido com a conta ATIVA, isto e, depois que a parceria voltou. Sobre
    conta inativa o restore limparia `revoked_at` sem destravar nada (o gate
    exige conta ativa) e, pior, tiraria a linha da fila 3 — que passou a ser
    keyed em revogacao por churn PENDENTE: a conta sumiria do painel com grants
    vivos e inuteis, e o reconciliador nao os revogaria de novo (conta ja
    inativa nao entra em `to_remove`). O botao nem e renderizado nesse estado; a
    checagem aqui e pra POST direto ou aba velha reenviada.
    """
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        conta = await meta_ad_accounts.get_by_id(conn, ad_account_id)
        if conta is None or not conta.is_active:
            destino = "/admin/accounts/meta?error=conta_inativa"
            if request.headers.get("HX-Request"):
                # HX-Redirect, nao HX-Refresh: o refresh perderia o query param
                # e o admin nao veria por que nada aconteceu.
                return Response(status_code=204, headers={"HX-Redirect": destino})
            return RedirectResponse(url=destino, status_code=303)
        restaurados = await manager_meta_account_access.restore_for_account(
            conn, ad_account_id=ad_account_id
        )
        await _audit_admin(
            conn,
            admin=user,
            operation="admin_accounts_meta_restore",
            customer_id=ad_account_id,
            platform="meta",
            restored_grants=restaurados,
        )
    if request.headers.get("HX-Request"):
        # Mesmo idioma de accounts_revoke_connection/admin_invites_cancel: full
        # refresh do browser reconstroi as tres filas de graca, sem swap manual.
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return RedirectResponse(url="/admin/accounts/meta?ok=restored", status_code=303)
