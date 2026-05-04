"""OAuth 2.0 flow with Google for the 'adwords' scope.

Two HTTP endpoints:
  GET /oauth/google/start?invite=<token>  → redirect to Google's consent screen
  GET /oauth/google/callback?code=...&state=... → exchange + persist + return success page

The `invite` token is an HMAC-signed payload with manager_id (created
by the bootstrap CLI). Phase 1b will replace this with a panel session.
"""

from urllib.parse import urlencode
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.auth.domain_check import is_allowed_email
from src.auth.oauth_state import InvalidStateError, sign_state, verify_state
from src.auth.tokens import derive_master_key_from_settings, encrypt_refresh_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import google_oauth_connections, managers

log = structlog.get_logger(__name__)

GOOGLE_ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"
GOOGLE_PROFILE_SCOPE = "https://www.googleapis.com/auth/userinfo.profile"
GOOGLE_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
GOOGLE_OPENID_SCOPE = "openid"

_REQUIRED_SCOPES = [
    GOOGLE_OPENID_SCOPE,
    GOOGLE_EMAIL_SCOPE,
    GOOGLE_PROFILE_SCOPE,
    GOOGLE_ADWORDS_SCOPE,
]

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


router = APIRouter(prefix="/oauth/google", tags=["oauth"])


def _build_redirect_uri(request: Request) -> str:
    """Construct the absolute callback URL based on the running host.

    Cloud Run terminates TLS at the GFE; the container sees HTTP internally,
    so request.url.scheme is "http" even when the client used HTTPS. We force
    https here because the OAuth Client in Google Cloud Console is registered
    with the public https:// URL — sending http:// causes redirect_uri_mismatch.

    --proxy-headers / X-Forwarded-Proto were tried but didn't take effect
    reliably under Cloud Run's CNB-launched uvicorn. Forcing https in code is
    bulletproof and the only callable URL externally is https anyway.
    """
    url = str(request.url_for("oauth_callback"))
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


@router.get("/start")
async def oauth_start(
    request: Request,
    invite: str | None = None,
    mode: str | None = None,
) -> RedirectResponse:
    """Redirect the manager to Google's consent screen.

    Supports two flows:
    - mode=panel_login: self-onboarding; no invite required.
    - invite=<token>: CLI invite flow with signed manager_id.
    """
    settings = get_settings()

    if mode == "panel_login":
        # Self-onboarding: no invite required. Manager will be looked up or
        # created in the callback by email.
        callback_state = sign_state(
            {"mode": "panel_login"},
            settings.session_signing_key,
        )
    else:
        # CLI invite flow: requires a signed invite carrying manager_id.
        if not invite:
            raise HTTPException(
                status_code=400,
                detail="Either 'invite' (CLI flow) or 'mode=panel_login' is required",
            )
        try:
            invite_payload = verify_state(invite, settings.session_signing_key)
        except InvalidStateError as e:
            raise HTTPException(status_code=400, detail=f"invalid invite: {e}") from e

        manager_id_str = invite_payload.get("manager_id")
        if not manager_id_str:
            raise HTTPException(status_code=400, detail="invite missing manager_id")

        # Validate manager exists.
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_id(conn, UUID(manager_id_str))
            if m is None or not m.is_active:
                raise HTTPException(status_code=404, detail="manager not found or inactive")

        callback_state = sign_state(
            {"manager_id": manager_id_str},
            settings.session_signing_key,
        )

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": _build_redirect_uri(request),
        "scope": " ".join(_REQUIRED_SCOPES),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "state": callback_state,
        "include_granted_scopes": "true",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    log.info("oauth_start", mode=mode)
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", name="oauth_callback", response_model=None)
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse | RedirectResponse:
    """Exchange the auth code for a refresh token and persist it encrypted."""
    if error:
        return _error_page(f"O Google retornou um erro: {error}", status=400)
    if not code or not state:
        return _error_page("Resposta incompleta do Google (faltou code ou state).", status=400)

    settings = get_settings()
    try:
        payload = verify_state(state, settings.session_signing_key)
    except InvalidStateError as e:
        return _error_page(f"State inválido ou expirado: {e}", status=400)

    mode = payload.get("mode")
    manager_id_str = payload.get("manager_id")

    # Exchange code → tokens.
    async with httpx.AsyncClient(timeout=30.0) as http:
        token_resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _build_redirect_uri(request),
            },
        )
        if token_resp.status_code != 200:
            log.warning(
                "oauth_token_exchange_failed", status=token_resp.status_code, body=token_resp.text
            )
            return _error_page(
                f"Troca do code falhou (HTTP {token_resp.status_code}). Tente conectar de novo.",
                status=502,
            )
        tokens = token_resp.json()
        refresh_token = tokens.get("refresh_token")
        access_token = tokens.get("access_token")
        if not refresh_token:
            return _error_page(
                "O Google não devolveu refresh_token. Isso geralmente significa que a conta já tinha autorizado o app antes; revogue em https://myaccount.google.com/permissions e tente de novo.",
                status=400,
            )

        # Fetch the email of the Google account that just authorized.
        userinfo_resp = await http.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo = userinfo_resp.json() if userinfo_resp.status_code == 200 else {}
        google_email = userinfo.get("email") or "unknown"

    if not is_allowed_email(google_email):
        return _error_page(
            f"Conta {google_email} nao autorizada — apenas @v4company.com.",
            status=403,
        )

    # Resolve manager_id based on flow mode.
    pool_resolve = connection.get_pool()
    if mode == "panel_login":
        # Self-onboarding: find existing manager by email or create a new one.
        async with pool_resolve.acquire() as conn:
            existing = await managers.get_by_email(conn, google_email)
            if existing is not None:
                if not existing.is_active:
                    return _error_page(
                        f"Conta {google_email} desativada. Contate um admin.",
                        status=403,
                    )
                manager_id = existing.id
                # Promote first-ever login to admin if there are no admins yet
                # (bootstrap path — saves a manual SQL step).
                row = await conn.fetchrow(
                    "SELECT count(*) AS n FROM managers WHERE role = 'admin' AND is_active = true"
                )
                if row and int(row["n"]) == 0:
                    await conn.execute(
                        "UPDATE managers SET role = 'admin' WHERE id = $1",
                        existing.id,
                    )
            else:
                # First-time user: create as admin if no admin exists yet,
                # otherwise as gestor.
                row = await conn.fetchrow(
                    "SELECT count(*) AS n FROM managers WHERE role = 'admin' AND is_active = true"
                )
                role = "admin" if (row is None or int(row["n"]) == 0) else "gestor"
                from uuid import uuid4

                new_id = uuid4()
                full_name = userinfo.get("name") or None
                await managers.create(
                    conn,
                    manager_id=new_id,
                    email=google_email,
                    full_name=full_name,
                    role=role,
                )
                manager_id = new_id
    elif manager_id_str:
        manager_id = UUID(manager_id_str)
    else:
        return _error_page("State payload missing both manager_id and mode.", status=400)

    # Encrypt + persist.
    master_key = derive_master_key_from_settings(settings.aes_master_key)
    refresh_enc = encrypt_refresh_token(refresh_token, master_key)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await google_oauth_connections.upsert(
            conn,
            manager_id=manager_id,
            google_email=google_email,
            refresh_token_enc=refresh_enc,
            scopes=_REQUIRED_SCOPES,
        )

    if mode == "panel_login":
        # Issue panel session cookie + redirect to dashboard.
        from src.auth.panel_session import (
            PANEL_SESSION_COOKIE_NAME,
            PANEL_SESSION_TTL_SECONDS,
            sign_panel_session,
        )

        cookie_value = sign_panel_session(
            manager_id=str(manager_id),
            email=google_email,
            signing_key=settings.session_signing_key,
        )
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key=PANEL_SESSION_COOKIE_NAME,
            value=cookie_value,
            max_age=PANEL_SESSION_TTL_SECONDS,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/",
        )
        log.info("oauth_panel_login_success", manager_id=str(manager_id), google_email=google_email)
        return response

    log.info("oauth_callback_success", manager_id=str(manager_id), google_email=google_email)
    return _success_page(google_email)


def _success_page(email: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>V4 Ads MCP — Conectado</title>
<style>body{{font-family:system-ui;max-width:640px;margin:80px auto;padding:0 24px;color:#333}}.ok{{color:#228B22}}</style>
</head><body>
<h1 class="ok">✅ Conectado</h1>
<p>Conta Google <code>{email}</code> autorizada.</p>
<p>Próximo passo: o admin precisa atribuir a você as contas Google Ads que você pode operar (no MVP, isso é manual via CLI). Após isso, peça pra ele criar uma sessão MCP e te enviar o token.</p>
<p>Pode fechar esta aba.</p>
</body></html>""",
        status_code=200,
    )


def _error_page(message: str, *, status: int) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>V4 Ads MCP — Erro</title>
<style>body{{font-family:system-ui;max-width:640px;margin:80px auto;padding:0 24px;color:#333}}.err{{color:#c00}}</style>
</head><body>
<h1 class="err">❌ Falha</h1>
<p>{message}</p>
<p><a href="/health">Status do serviço</a></p>
</body></html>""",
        status_code=status,
    )
