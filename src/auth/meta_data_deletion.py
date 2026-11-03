"""Callback de exclusao de dados da Meta (exigencia do App Review).

Movido sem mudanca de `src/auth/meta_oauth.py`: o OAuth pessoal da Meta sai do
produto, mas a Meta continua exigindo este endpoint. O path literal
`/oauth/meta/data-deletion-callback` segue isento de CSRF em
`_CSRF_EXEMPT_ROUTES` (a autenticacao e o HMAC do `signed_request`).
"""

import base64
import binascii
import hashlib
import hmac
import json
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException, Request

from src.config import get_settings
from src.db import connection
from src.db.repositories import audit_log

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/oauth/meta", tags=["meta_oauth"])


def _verify_meta_signed_request(signed_request: str, app_secret: str) -> dict[str, object] | None:
    """Validate Meta signed_request HMAC SHA256.

    Format: base64url(signature).base64url(json_payload)
    Returns parsed payload dict, ou None se invalid (wrong sig, malformed, etc).
    """
    try:
        encoded_sig, encoded_payload = signed_request.split(".", 1)
    except ValueError:
        return None

    try:
        sig = base64.urlsafe_b64decode(encoded_sig + "=" * (-len(encoded_sig) % 4))
        payload_bytes = base64.urlsafe_b64decode(
            encoded_payload + "=" * (-len(encoded_payload) % 4)
        )
    except (ValueError, TypeError, binascii.Error):
        return None

    expected_sig = hmac.new(
        app_secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    if not hmac.compare_digest(sig, expected_sig):
        return None

    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    if payload.get("algorithm") != "HMAC-SHA256":
        return None

    return payload


@router.post("/data-deletion-callback", response_model=None)
async def meta_data_deletion_callback(request: Request) -> dict[str, str]:
    """V0 callback: log + confirmation_code (NÃO deleta data imediatamente).

    Wellington (admin) processa manualmente em até 30 dias (LGPD/GDPR window).
    Meta App Review requirement.
    """
    settings = get_settings()
    form = await request.form()
    signed_request = str(form.get("signed_request", ""))
    if not signed_request:
        raise HTTPException(status_code=400, detail="signed_request required")

    payload = _verify_meta_signed_request(signed_request, settings.meta_app_secret)
    if payload is None:
        log.warning("meta_data_deletion_invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    meta_user_id = str(payload.get("user_id", ""))
    confirmation_code = str(uuid4())

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await audit_log.record(
            conn,
            manager_id=None,
            session_id=None,
            customer_id=None,
            action_type="auth",
            operation="meta_data_deletion_request",
            params_summary={
                "meta_user_id": meta_user_id,
                "confirmation_code": confirmation_code,
                "expires": payload.get("expires"),
            },
            status="success",
            platform="meta",
        )

    log.info(
        "meta_data_deletion_request_logged",
        meta_user_id=meta_user_id,
        confirmation_code=confirmation_code,
    )

    url = str(request.url_for("data_deletion_status", code=confirmation_code))
    # Force HTTPS (Cloud Run terminates TLS at GFE, mirror _build_redirect_uri pattern)
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return {
        "url": url,
        "confirmation_code": confirmation_code,
    }
