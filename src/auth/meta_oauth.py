"""OAuth 2.0 flow with Meta (Facebook Login for Business).

Long-lived access_token (~60d) — Meta has no refresh_token model. When
expired, user must reconnect via webapp.

Three routes:
  GET  /oauth/meta/start    → redirect to Meta consent screen
  GET  /oauth/meta/callback → exchange code → token → upsert connection
  POST /oauth/meta/revoke   → soft-revoke (sets revoked_at; no Meta API call V0)

Granular permissions: Meta lets users accept ANY subset of requested
scopes. Callback BLOCKS if ads_read or ads_management missing (essentials)
— redirects to /access-denied?reason=meta_scopes_missing&missing=...
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.auth.domain_check import is_allowed_email
from src.auth.oauth_state import InvalidStateError, sign_state, verify_state
from src.auth.tokens import derive_master_key_from_settings, encrypt_refresh_token
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    audit_log,
    manager_meta_account_access,
    meta_ad_accounts,
    meta_oauth_connections,
)
from src.web.deps import CurrentUser, current_manager

log = structlog.get_logger(__name__)

META_FB_AUTH_URL = "https://www.facebook.com/v22.0/dialog/oauth"
META_GRAPH_BASE = "https://graph.facebook.com/v22.0"

META_REQUIRED_SCOPES = [
    "email",
    "public_profile",
    "ads_read",
    "ads_management",
    "business_management",
]

META_ESSENTIAL_SCOPES = {"ads_read", "ads_management"}

router = APIRouter(prefix="/oauth/meta", tags=["meta_oauth"])


def check_meta_granted_scopes(granted: set[str]) -> set[str]:
    """Return set of ESSENTIAL scopes that are MISSING from granted set.

    Empty set return means all essentials granted (consent OK).
    """
    return META_ESSENTIAL_SCOPES - granted


def _build_redirect_uri(request: Request) -> str:
    """Force HTTPS for callback URL (Cloud Run terminates TLS at GFE).

    Mirror src/auth/oauth.py:_build_redirect_uri pattern.
    """
    url = str(request.url_for("meta_oauth_callback"))
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url


@router.get("/start")
async def meta_oauth_start(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> RedirectResponse:
    """Redirect manager to Meta consent screen."""
    settings = get_settings()
    callback_state = sign_state(
        {"manager_id": str(user.id), "aud": "meta_oauth"},
        settings.session_signing_key,
    )
    params = {
        "client_id": settings.meta_app_id,
        "redirect_uri": _build_redirect_uri(request),
        "scope": ",".join(META_REQUIRED_SCOPES),
        "response_type": "code",
        "state": callback_state,
    }
    url = f"{META_FB_AUTH_URL}?{urlencode(params)}"
    log.info("meta_oauth_start", manager_id=str(user.id))
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback", name="meta_oauth_callback", response_model=None)
async def meta_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse | RedirectResponse:
    """Exchange code → long-lived access_token → persist + sync accounts.

    Flow:
    1. Verify state HMAC
    2. POST /oauth/access_token → short-lived token
    3. GET /oauth/access_token?grant_type=fb_exchange_token → long-lived token
    4. GET /me → fb_user_id + fb_email
    5. is_allowed_email check
    6. GET /debug_token → granted_scopes
    7. check_meta_granted_scopes → block if missing essentials
    8. Encrypt + upsert meta_oauth_connections
    9. GET /me/adaccounts → upsert meta_ad_accounts + grant_all_active
    10. audit_log + redirect to /admin
    """
    if error:
        msg = error_description or error
        log.warning("meta_oauth_callback_error_param", error=error, msg=msg)
        return RedirectResponse(
            f"/access-denied?reason=meta_oauth_error&detail={msg[:200]}",
            status_code=302,
        )
    if not code or not state:
        return RedirectResponse(
            "/access-denied?reason=meta_oauth_incomplete",
            status_code=302,
        )

    settings = get_settings()
    try:
        payload = verify_state(state, settings.session_signing_key)
    except InvalidStateError as e:
        log.warning("meta_oauth_invalid_state", error=str(e))
        return RedirectResponse("/access-denied?reason=meta_state_invalid", status_code=302)

    if payload.get("aud") != "meta_oauth":
        log.warning("meta_oauth_wrong_aud", aud=payload.get("aud"))
        return RedirectResponse("/access-denied?reason=meta_state_invalid", status_code=302)

    manager_id_str = payload.get("manager_id")
    if not manager_id_str:
        return RedirectResponse("/access-denied?reason=meta_state_invalid", status_code=302)
    manager_id = UUID(manager_id_str)

    redirect_uri = _build_redirect_uri(request)

    async with httpx.AsyncClient(timeout=30.0) as http:
        # Step 2: code → short-lived
        short_resp = await http.post(
            f"{META_GRAPH_BASE}/oauth/access_token",
            data={
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        if short_resp.status_code != 200:
            log.warning(
                "meta_oauth_short_token_failed",
                status=short_resp.status_code,
                body=short_resp.text,
            )
            return RedirectResponse(
                "/access-denied?reason=meta_token_exchange_failed",
                status_code=302,
            )
        short_token = short_resp.json().get("access_token")
        if not short_token:
            return RedirectResponse(
                "/access-denied?reason=meta_token_exchange_failed",
                status_code=302,
            )

        # Step 3: short → long-lived
        long_resp = await http.get(
            f"{META_GRAPH_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.meta_app_secret,
                "fb_exchange_token": short_token,
            },
        )
        if long_resp.status_code != 200:
            log.warning(
                "meta_oauth_long_token_failed",
                status=long_resp.status_code,
                body=long_resp.text,
            )
            return RedirectResponse(
                "/access-denied?reason=meta_token_exchange_failed",
                status_code=302,
            )
        long_body = long_resp.json()
        access_token = long_body.get("access_token")
        expires_in_seconds = int(long_body.get("expires_in", 5184000))  # default 60d

        # Step 4: GET /me
        me_resp = await http.get(
            f"{META_GRAPH_BASE}/me",
            params={"fields": "id,email,name", "access_token": access_token},
        )
        if me_resp.status_code != 200:
            return RedirectResponse(
                "/access-denied?reason=meta_userinfo_failed",
                status_code=302,
            )
        me_data = me_resp.json()
        fb_user_id = str(me_data.get("id", ""))
        fb_email = str(me_data.get("email", ""))
        if not fb_user_id or not fb_email:
            return RedirectResponse(
                "/access-denied?reason=meta_userinfo_incomplete",
                status_code=302,
            )

        # Step 5: V4 domain check
        if not is_allowed_email(fb_email):
            log.warning("meta_oauth_email_not_v4", fb_email=fb_email)
            return RedirectResponse(
                f"/access-denied?reason=domain&email={fb_email}",
                status_code=302,
            )

        # Step 6: GET /debug_token → check granted scopes
        debug_resp = await http.get(
            f"{META_GRAPH_BASE}/debug_token",
            params={
                "input_token": access_token,
                "access_token": f"{settings.meta_app_id}|{settings.meta_app_secret}",
            },
        )
        granted_scopes: set[str] = set()
        if debug_resp.status_code == 200:
            data = debug_resp.json().get("data", {})
            granted_scopes = set(data.get("scopes", []))
        else:
            log.warning(
                "meta_oauth_debug_token_failed",
                status=debug_resp.status_code,
            )

        # Step 7: block if essentials missing
        missing = check_meta_granted_scopes(granted_scopes)
        if missing:
            log.warning("meta_oauth_missing_essentials", missing=list(missing))
            return RedirectResponse(
                f"/access-denied?reason=meta_scopes_missing&missing={','.join(missing)}",
                status_code=302,
            )

        # Step 8: encrypt + upsert connection
        master_key = derive_master_key_from_settings(settings.aes_master_key)
        encrypted = encrypt_refresh_token(access_token, master_key)
        token_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)

        # Step 9: list ad accounts
        adacc_resp = await http.get(
            f"{META_GRAPH_BASE}/me/adaccounts",
            params={
                "fields": "id,name,business,account_status,currency,timezone_name",
                "access_token": access_token,
            },
        )
        ad_accounts_data: list[dict[str, Any]] = []
        if adacc_resp.status_code == 200:
            ad_accounts_data = adacc_resp.json().get("data", [])

    # Step 8+9 persist (outside http context)
    pool = connection.get_pool()
    accounts_payload: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        await meta_oauth_connections.upsert(
            conn,
            manager_id=manager_id,
            fb_user_id=fb_user_id,
            fb_email=fb_email,
            access_token_enc=encrypted,
            token_expires_at=token_expires_at,
            scopes=list(granted_scopes),
        )
        # Upsert ad accounts
        for a in ad_accounts_data:
            ad_id_raw = a.get("id", "")
            if not ad_id_raw.startswith("act_"):
                ad_id_raw = f"act_{ad_id_raw}"
            business = a.get("business") or {}
            accounts_payload.append(
                {
                    "ad_account_id": ad_id_raw,
                    "business_id": business.get("id"),
                    "business_name": business.get("name"),
                    "account_name": a.get("name", ad_id_raw),
                    "currency": a.get("currency"),
                    "timezone_name": a.get("timezone_name"),
                    "account_status": a.get("account_status"),
                }
            )
        if accounts_payload:
            await meta_ad_accounts.upsert_many(conn, accounts_payload)
            for a in accounts_payload:
                await manager_meta_account_access.grant(
                    conn,
                    manager_id=manager_id,
                    ad_account_id=a["ad_account_id"],
                )

        # Step 10: audit
        await audit_log.record(
            conn,
            manager_id=manager_id,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_oauth_connect",
            target_count=len(accounts_payload),
            params_summary={"fb_email": fb_email, "scopes": list(granted_scopes)},
            status="success",
            platform="meta",
        )

    log.info(
        "meta_oauth_callback_success",
        manager_id=str(manager_id),
        fb_email=fb_email,
        accounts_synced=len(accounts_payload),
    )
    return RedirectResponse("/admin?meta_connected=1", status_code=302)


@router.post("/revoke")
async def meta_oauth_revoke(
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> RedirectResponse:
    """Soft-revoke active Meta connection (sets revoked_at; no Meta API call V0)."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        oc = await meta_oauth_connections.get_active_for_manager(conn, user.id)
        if oc is None:
            raise HTTPException(
                status_code=404,
                detail="No active Meta connection to revoke",
            )
        await meta_oauth_connections.revoke(conn, oc.id)
        await audit_log.record(
            conn,
            manager_id=user.id,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_oauth_revoke",
            status="success",
            platform="meta",
        )
    log.info("meta_oauth_revoked", manager_id=str(user.id))
    return RedirectResponse("/admin?meta_revoked=1", status_code=302)
