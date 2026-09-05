"""Web panel routes."""

import html
import json
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, NamedTuple
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME
from src.auth.sessions import generate_session_token, hash_session_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
    mcp_sessions,
    meta_ad_accounts,
    meta_oauth_connections,
)
from src.db.repositories.mcp_sessions import DEFAULT_TTL_DAYS
from src.meta_ads.labels import META_ACCOUNT_STATUS_LABELS
from src.web.deps import (
    CurrentUser,
    current_manager,
    optional_current_manager,
    pending_invites_count,
)
from src.web.static_files import asset_version

log = structlog.get_logger(__name__)

router = APIRouter(tags=["web"])


def _require_admin(user: CurrentUser) -> None:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


_ADMIN_FLASH_ERRORS: dict[str, str] = {
    "bad_domain": "Só emails @v4company.com podem ser convidados.",
    "exists": "Esse email já está cadastrado (convite pendente ou conta existente). Nada foi criado.",
    "same_manager": "Gestor de origem e destino são o mesmo — nada foi copiado.",
    "conta_inativa": (
        "Esta conta ainda está fora da parceria — restaurar agora não devolveria "
        "acesso nenhum (o gate exige conta ativa). Espere a reconciliação "
        "reativá-la; a linha volta com o botão."
    ),
}

# Mapa fixo pro `ok=<codigo>` da reconciliacao Meta — distinto do `ok=1` usado
# nas demais paginas admin porque a rota de restaurar precisa de MENSAGEM
# PROPRIA (nao so "sucesso genérico"). Mesma regra: nunca ecoar o param.
_META_ACCOUNTS_FLASH_OK: dict[str, str] = {
    "restored": "Acesso restaurado — os grants revogados pela saída da parceria foram reconcedidos.",
}


def _admin_flash(
    request: Request,
    *,
    ok_message: str | None = None,
    ok_codes: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Flash message via query param. Mapa fixo — NUNCA ecoar o valor do param (XSS)."""
    code = request.query_params.get("error")
    if code:
        message = _ADMIN_FLASH_ERRORS.get(code)
        return {"kind": "error", "message": message} if message else None
    ok = request.query_params.get("ok")
    if ok_codes and ok:
        message = ok_codes.get(ok)
        return {"kind": "success", "message": message} if message else None
    if ok_message and ok == "1":
        return {"kind": "success", "message": ok_message}
    return None


async def _audit_admin(
    conn: Any,
    *,
    admin: CurrentUser,
    operation: str,
    customer_id: str | None = None,
    platform: Literal["google", "meta"] = "google",
    **summary: Any,
) -> None:
    """Record an audit_log row for a sensitive admin-panel mutation.

    Panel actions (access matrix, roles, activation, invites) have no MCP
    session, so session_id is always None; manager_id is the authenticated
    admin performing the action. summary becomes params_summary (target of
    the action — never tokens/secrets).
    """
    await audit_log.record(
        conn,
        manager_id=admin.id,
        session_id=None,
        customer_id=customer_id,
        action_type="mutate",
        operation=operation,
        params_summary=summary or None,
        platform=platform,
    )


def _toggle_checkbox_fragment(
    *,
    post_url: str,
    manager_id: str,
    account_id: str,
    account_field: str,
    checked: bool,
) -> str:
    """Checkbox de reposição servido após o toggle de acesso.

    O comportamento (toast, revert-on-fail) vive num listener delegado em
    v4-panel.js, acionado por `data-v4-access-toggle` — era o F74.

    O NOME ACESSÍVEL segue a mesma regra. Com `aria-label` de texto, a rota
    tinha que reproduzir o que o template escreve, e não reproduzia: todo
    checkbox virava "Alternar acesso" depois do primeiro toggle — e nas views
    por gestor o `aria-label` ainda vencia o `<label>` que embrulha, então o
    texto visível e o nome anunciado passavam a discordar. Agora o nome vem
    por `aria-labelledby`, apontando pro cabeçalho do gestor e pro da conta,
    que ficam FORA do nó trocado. O valor é função pura dos dois ids que já
    chegam no form, então template e fragmento não têm como divergir.
    """
    state = "checked " if checked else ""
    vals = {"manager_id": manager_id, account_field: account_id}
    hx_vals = html.escape(json.dumps(vals), quote=True)
    rotulo = html.escape(f"v4-mgr-{manager_id} v4-acc-{account_id}", quote=True)
    return (
        f'<input type="checkbox" {state}hx-post="{post_url}" '
        f'hx-vals=\'{hx_vals}\' hx-trigger="change" hx-swap="outerHTML" '
        f'data-v4-access-toggle aria-labelledby="{rotulo}">'
    )


_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class MetaExpirySignals(NamedTuple):
    """Sinais de expiração do OAuth pessoal Meta pro painel admin."""

    expired: bool
    expiring_soon: bool
    days_until: int | None
    days_since: int | None


def meta_expiry_signals(
    token_expires_at: datetime | None, *, agora: datetime | None = None
) -> MetaExpirySignals:
    """Traduz a data de expiração nos sinais que o template consome.

    Separado da rota pra ser testável sem DB. O cálculo antigo era
    `max(0, delta.days)`, que achatava vencido em 0 e fazia o painel dizer
    "expira em <data passada> (0 dias)".

    Os dias são contados sempre na direção positiva: `timedelta` negativo
    arredonda pra baixo (`-15,4 dias` vira `.days == -16`), então medir
    `agora - expiração` evita o off-by-one no "há N dias".
    """
    if token_expires_at is None:
        return MetaExpirySignals(False, False, None, None)

    agora = agora or datetime.now(UTC)
    if token_expires_at <= agora:
        return MetaExpirySignals(True, False, None, (agora - token_expires_at).days)

    dias = (token_expires_at - agora).days
    return MetaExpirySignals(False, dias < 7, dias, None)


def meta_status_label(status: int | None) -> str:
    """Jinja filter: resolve Meta account_status int to PT-BR label."""
    return META_ACCOUNT_STATUS_LABELS.get(status or 0, "DESCONHECIDO")


templates.env.filters["meta_status_label"] = meta_status_label

# Cache-busting dos estaticos: muda a cada revisao do Cloud Run, o que torna
# seguro o Cache-Control imutavel de CachedStaticFiles.
templates.env.globals["asset_version"] = asset_version()


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse | RedirectResponse:
    """Render the login page. If already logged in, redirect to dashboard."""
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"current_user": None},
    )


@router.post("/logout")
async def logout() -> RedirectResponse:
    """Clear panel session cookie + redirect to login. POST-only to prevent logout-CSRF."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=PANEL_SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/help", response_class=HTMLResponse)
async def help_page(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Onboarding consolidated. Accessible logged-in or out (login link is included)."""
    # mcp_url injetado no contexto (não hardcoded no template) pra os snippets de
    # conexão nunca driftarem da URL real do serviço — mesmo padrão do /sessions.
    mcp_url = f"{get_settings().public_base_url}/mcp"
    return templates.TemplateResponse(
        request, "help.html", {"current_user": user, "mcp_url": mcp_url}
    )


@router.get("/legal/privacy", response_class=HTMLResponse)
async def legal_privacy(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public Privacy Policy. Required by Meta Marketing API App Settings."""
    return templates.TemplateResponse(request, "legal/privacy.html", {"current_user": user})


@router.get("/legal/terms", response_class=HTMLResponse)
async def legal_terms(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public Terms of Service. Required by Meta Marketing API App Settings."""
    return templates.TemplateResponse(request, "legal/terms.html", {"current_user": user})


@router.get(
    "/legal/data-deletion-status/{code}", response_class=HTMLResponse, name="data_deletion_status"
)
async def data_deletion_status(
    request: Request,
    code: UUID,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Public data deletion confirmation status page. Meta App Review requirement."""
    return templates.TemplateResponse(
        request,
        "legal/data_deletion_status.html",
        {"current_user": user, "confirmation_code": str(code)},
    )


@router.get("/access-denied", response_class=HTMLResponse, response_model=None)
async def access_denied(
    request: Request,
    reason: str = "not_invited",
    email: str | None = None,
    detail: str | None = None,
    missing: str | None = None,
) -> HTMLResponse:
    """Q8 invite-only landing page. No auth required.

    Reads a transient `v4_attempted_email` cookie set by the OAuth callback
    before redirect, so the page can show which email was rejected. Cookie is
    cleared on read so it doesn't persist or leak across logins.

    Also accepts Meta OAuth error params:
    - email: rejected email address (passed via query param for Meta domain check)
    - detail: error detail string (meta_oauth_error branch)
    - missing: comma-separated missing scope names (meta_scopes_missing branch)
    """
    attempted_email = request.cookies.get("v4_attempted_email") or email
    missing_scopes = missing.split(",") if missing else []
    response = templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            "current_user": None,
            "reason": reason,
            "attempted_email": attempted_email,
            "email": email,
            "detail": detail,
            "missing_scopes": missing_scopes,
        },
    )
    response.delete_cookie("v4_attempted_email", path="/access-denied")
    return response


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    """Dashboard: editorial hero + operational stats + admin extras."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)
        active_sessions = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=False)
        oauth_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)

        # Recent calls (last 5 by this manager)
        recent = await conn.fetch(
            """SELECT occurred_at, operation, customer_id, status,
                      (SELECT descriptive_name FROM google_ads_accounts a
                       WHERE a.customer_id = al.customer_id LIMIT 1) AS account_name
               FROM audit_log al
               WHERE manager_id = $1
               ORDER BY occurred_at DESC LIMIT 5""",
            user.id,
        )

        # Calls today (count + sparkline of last 7 days)
        today = datetime.now(UTC).date()
        calls_today = (
            await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE manager_id = $1 AND occurred_at::date = $2",
                user.id,
                today,
            )
            or 0
        )
        sparkline_rows = await conn.fetch(
            """SELECT (occurred_at::date) as d, count(*) AS c
               FROM audit_log
               WHERE manager_id = $1 AND occurred_at >= $2
               GROUP BY 1 ORDER BY 1""",
            user.id,
            today - timedelta(days=6),
        )
        # Build 7-day series, filling zeros for missing days
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        counts_by_day = {r["d"]: r["c"] for r in sparkline_rows}
        sparkline_values = [counts_by_day.get(d, 0) for d in days]

        admin_ops = None
        if user.is_admin:
            from src.db.repositories import managers as managers_repo

            pending = await managers_repo.count_invited(conn)
            errors_24h = (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_log WHERE status='error' AND occurred_at > now() - interval '24 hours'",
                )
                or 0
            )
            quota_used = (
                await conn.fetchval(
                    "SELECT COALESCE(SUM(operations_used), 0) FROM rate_counters WHERE date = current_date",
                )
                or 0
            )
            active_mgrs = (
                await conn.fetchval("SELECT count(*) FROM managers WHERE status = 'active'") or 0
            )
            total_mgrs = await conn.fetchval("SELECT count(*) FROM managers") or 0
            admin_ops = {
                "pending_invites": pending,
                "quota_used": quota_used,
                "quota_max": 15000,
                "errors_24h": errors_24h,
                "active_managers": active_mgrs,
                "total_managers": total_mgrs,
            }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": user,
            "accounts_count": len(accounts),
            "sessions_count": len(active_sessions),
            "oauth_email": oauth_conn.google_email if oauth_conn else None,
            "oauth_connected_at": oauth_conn.connected_at if oauth_conn else None,
            "calls_today": calls_today,
            "calls_sparkline": sparkline_values,
            "recent_calls": [dict(r) for r in recent],
            "admin_ops": admin_ops,
        },
    )


@router.get("/sessions", response_class=HTMLResponse)
async def sessions_list(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    include_revoked: bool = False,
) -> HTMLResponse:
    """List manager's MCP sessions."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        sessions = await mcp_sessions.list_for_manager(
            conn, user.id, include_revoked=include_revoked
        )

    return templates.TemplateResponse(
        request,
        "sessions/list.html",
        {
            "current_user": user,
            "sessions": sessions,
            "include_revoked": include_revoked,
        },
    )


@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail(
    request: Request,
    session_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    token_flash: bool = False,
) -> HTMLResponse:
    """Permanent detail page for a single MCP session. Shows flash token once on creation."""
    try:
        parsed_session_id = UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Sessão não encontrada") from None
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        session = await mcp_sessions.get_by_id(
            conn,
            session_id=parsed_session_id,
            manager_id=user.id,
        )
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    flash_token = request.cookies.get("v4_session_flash_token") if token_flash else None
    settings = get_settings()
    mcp_url = f"{settings.public_base_url}/mcp"

    response = templates.TemplateResponse(
        request,
        "sessions/detail.html",
        {
            "current_user": user,
            "session": session,
            "flash_token": flash_token,
            "mcp_url": mcp_url,
        },
    )
    if flash_token:
        response.delete_cookie(
            "v4_session_flash_token",
            path=f"/sessions/{session_id}",
        )
    return response


@router.post("/sessions/new", response_class=HTMLResponse, response_model=None)
async def sessions_create(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    label: str = Form(""),
    ttl_days: int = Form(DEFAULT_TTL_DAYS),
) -> RedirectResponse:
    """Create a new MCP session. Redirects to /sessions/{id} with flash-token cookie."""
    if not label:
        label = "Untitled"
    if ttl_days not in (30, 60, 90, 180):
        ttl_days = DEFAULT_TTL_DAYS

    token = generate_session_token()
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        sess = await mcp_sessions.create(
            conn,
            manager_id=user.id,
            token_hash=hash_session_token(token),
            label=label,
            ttl_days=ttl_days,
        )

    # Redirect to permanent detail page; plaintext token travels in a transient cookie.
    response = RedirectResponse(
        url=f"/sessions/{sess.id}?token_flash=true",
        status_code=303,
    )
    response.set_cookie(
        "v4_session_flash_token",
        token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=60,  # 60 seconds — won't persist on devices away from keyboard
        path=f"/sessions/{sess.id}",  # restrict scope to the detail page
    )
    return response


@router.post("/sessions/{session_id}/revoke", response_class=HTMLResponse)
async def sessions_revoke(
    request: Request,
    session_id: UUID,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> Response:
    """Revoke a session. Returns updated list HTML for HTMX swap, OR redirects."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Confirm the session belongs to this manager (defense)
        all_sessions = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=True)
        target = next((s for s in all_sessions if s.id == session_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if target.revoked_at is None:
            await mcp_sessions.revoke(conn, session_id)

    _toast_trigger = '{"toast": {"message": "Sessão revogada.", "kind": "success"}}'

    # If HTMX request, decide by the originating page.
    # Detail page (/sessions/<id>) → send HX-Redirect so HTMX navigates cleanly.
    # List page (/sessions) → swap table fragment in-place (existing behaviour).
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        current_url = request.headers.get("HX-Current-URL", "")
        current_path = urlparse(current_url).path
        if current_path.startswith("/sessions/") and current_path.rstrip("/") != "/sessions":
            # Came from the detail page — redirect without flashing the fragment.
            return Response(
                status_code=204,
                headers={"HX-Redirect": "/sessions", "HX-Trigger": _toast_trigger},
            )
        # Came from the list page — return fresh table fragment for in-place swap.
        # Preserve include_revoked from the originating page's query string.
        qs = parse_qs(urlparse(current_url).query)
        include_revoked = qs.get("include_revoked", ["0"])[0] in ("1", "true", "True")
        async with pool.acquire() as conn:
            sessions = await mcp_sessions.list_for_manager(
                conn, user.id, include_revoked=include_revoked
            )
        resp = templates.TemplateResponse(
            request,
            "sessions/_table.html",
            {"current_user": user, "sessions": sessions, "include_revoked": include_revoked},
        )
        resp.headers["HX-Trigger"] = _toast_trigger
        return resp
    # Sem HTMX: POST-redirect-GET. Renderizar a lista com 200 faria o refresh
    # re-executar a revogacao e sujaria o historico.
    return RedirectResponse(url="/sessions", status_code=303)


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
                       ORDER BY al.occurred_at DESC LIMIT ${idx} OFFSET ${idx + 1}"""
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
    async with pool.acquire() as conn:
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
    async with pool.acquire() as conn:
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


@router.get("/admin/accounts", response_class=HTMLResponse)
async def admin_accounts(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accs = await google_ads_accounts.list_all(conn)
    mccs = sorted({a.mcc_id for a in accs if a.mcc_id})
    pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/accounts.html",
        {
            "current_user": user,
            "accounts": accs,
            "mccs": mccs,
            "pending_invites_count": pending,
        },
    )


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

    pool = connection.get_pool()
    async with pool.acquire() as conn:
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
                       ORDER BY al.occurred_at DESC LIMIT ${idx} OFFSET ${idx + 1}"""
        params_with_pagination = params + [page_size, offset]
        rows = await conn.fetch(rows_sql, *params_with_pagination)

        managers_rows = await conn.fetch(
            "SELECT id, email FROM managers WHERE is_active = true ORDER BY email"
        )
        accs = await google_ads_accounts.list_all(conn)

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
