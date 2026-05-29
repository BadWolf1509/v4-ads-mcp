# bucket: defer
"""Tool: upload_customer_match_list — upload members (email/phone) pra Customer Match user list.

Sprint 3b.28. V0 minimal:
- 2 identifier types: email + phone_number
- 2 operation types: add + remove
- Fire-and-forget async: returns job_resource_name + to_check_status hint
- LGPD invariants: consent.ad_user_data + consent.ad_personalization GRANTED
- SHA-256 hashing client-side (PII nunca sai do processo unhashed)

Layer 1 (jsonschema): customer_id pattern, user_list_id pattern, operation enum,
  members array maxItems 1000, items minProperties 1.
Layer 2 (sync): rejeita member sem identifier, email já-hashed (^[a-f0-9]{64}$),
  email regex inválido, duplicates após normalize.
Layer 3 (async): validate_user_list_for_upload — exists + CRM_BASED + writable.
"""

import re
from typing import Any

from src.db import connection
from src.google_ads.customer_match import (
    _normalize_and_hash_email,
    _normalize_and_hash_phone,
)
from src.google_ads.queries._common import validate_user_list_for_upload
from src.governance.blast_radius import classify
from src.governance.dry_run import create_pending
from src.mcp.context import get_current
from src.mcp.tools._registry import register_tool

_SHA256_HEX_RE = re.compile(r"^[a-f0-9]{64}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "customer_id": {"type": "string", "pattern": "^[0-9]{10}$"},
        "user_list_id": {"type": "string", "pattern": "^[0-9]+$"},
        "operation": {"type": "string", "enum": ["add", "remove"]},
        "members": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "minLength": 3, "maxLength": 254},
                    "phone_number": {"type": "string", "minLength": 8, "maxLength": 30},
                },
                "additionalProperties": False,
                "minProperties": 1,
            },
        },
    },
    "required": ["customer_id", "user_list_id", "operation", "members"],
    "additionalProperties": False,
}


def _validate_payload_shape(args: dict[str, Any]) -> str | None:
    """Layer 2: synchronous validation pre-Google.

    Rejects:
    - Member sem nenhum identifier (Layer 1 minProperties já pega, mas
      garantia adicional)
    - Email já parece SHA-256 hash (^[a-f0-9]{64}$) — gestor deve passar plaintext
    - Email regex inválido (formato local@domain)
    - Duplicate email (após lowercase + remove whitespace) no batch
    - Duplicate phone (após normalize) no batch
    """
    members = args["members"]

    for idx, member in enumerate(members):
        if not member:
            return f"member item {idx} sem identificador (precisa email OU phone_number)."

        if "email" in member:
            email = member["email"]
            if _SHA256_HEX_RE.match(email):
                return (
                    f"member item {idx}: email '{email[:20]}...' já parece SHA-256 hash. "
                    f"Passe plaintext; tool faz hash internamente."
                )
            if not _EMAIL_RE.match(email):
                return (
                    f"member item {idx}: email '{email}' inválido (formato esperado: local@domain)."
                )

    seen_emails: set[str] = set()
    dup_emails: list[str] = []
    seen_phones: set[str] = set()
    dup_phones: list[str] = []

    for member in members:
        if "email" in member:
            normalized_hash = _normalize_and_hash_email(member["email"])
            if normalized_hash in seen_emails and normalized_hash not in dup_emails:
                dup_emails.append(member["email"])
            seen_emails.add(normalized_hash)

        if "phone_number" in member:
            normalized_hash = _normalize_and_hash_phone(member["phone_number"])
            if normalized_hash in seen_phones and normalized_hash not in dup_phones:
                dup_phones.append(member["phone_number"])
            seen_phones.add(normalized_hash)

    if dup_emails:
        return (
            f"emails duplicados no batch após normalize: {dup_emails}. "
            f"Cada email aparece no máximo 1 vez."
        )
    if dup_phones:
        return (
            f"phone_numbers duplicados no batch após normalize: {dup_phones}. "
            f"Cada phone aparece no máximo 1 vez."
        )

    return None


def _hash_members(members: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Layer 2: SHA-256 hash members + drop plaintext keys.

    Output members têm SÓ hashed_email/hashed_phone_number — plaintext nunca
    é persistido no dry_run_tokens nem no audit_log (LGPD minimização).
    """
    hashed: list[dict[str, str]] = []
    for member in members:
        entry: dict[str, str] = {}
        if "email" in member:
            entry["hashed_email"] = _normalize_and_hash_email(member["email"])
        if "phone_number" in member:
            entry["hashed_phone_number"] = _normalize_and_hash_phone(member["phone_number"])
        hashed.append(entry)
    return hashed


@register_tool(
    name="upload_customer_match_list",
    description=(
        "[DEFER] Upload members (email/phone) pra Customer Match user list. SHA-256 "
        "hash client-side (PII nunca sai unhashed). LGPD invariants: consent "
        "GRANTED + audit log sem plaintext. Operation: 'add' (incluir) ou "
        "'remove' (excluir — opt-out LGPD). User list deve existir (CRM_BASED + "
        "Customer Match policy aceita). Tool retorna job_resource_name + hint "
        "pra checar status (jobs processam em horas no backend Google)."
    ),
    input_schema=_SCHEMA,
    bucket="defer",
)
async def upload_customer_match_list(args: dict[str, Any]) -> dict[str, Any]:
    ctx = get_current()
    customer_id = args["customer_id"]
    user_list_id = args["user_list_id"]
    operation_type = args["operation"]
    members = args["members"]

    # Layer 2: sync validation
    shape_error = _validate_payload_shape(args)
    if shape_error:
        return {
            "status": "error",
            "operation": "upload_customer_match_list",
            "customer_id": customer_id,
            "error": shape_error,
        }

    # Layer 3: async pre-flight
    preflight_error = await validate_user_list_for_upload(
        manager_id=ctx.manager_id,
        session_id=ctx.session_id,
        customer_id=customer_id,
        user_list_id=user_list_id,
    )
    if preflight_error:
        return {
            "status": "error",
            "operation": "upload_customer_match_list",
            "customer_id": customer_id,
            **preflight_error,
        }

    hashed_members = _hash_members(members)

    risk = classify(operation="upload_customer_match_list", params={"members": members})

    payload = {
        "user_list_id": user_list_id,
        "operation": operation_type,
        "hashed_members": hashed_members,
        "__target_count__": len(members),
    }
    summary = (
        f"Upload Customer Match: {operation_type.upper()} {len(members)} membro(s) "
        f"pra user_list_id={user_list_id}."
    )

    # Always CONFIRM (PII upload)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        token = await create_pending(
            conn,
            manager_id=ctx.manager_id,
            session_id=ctx.session_id,
            customer_id=customer_id,
            operation_type="upload_customer_match_list",
            payload=payload,
            blast_summary=summary,
        )

    return {
        "status": "dry_run",
        "operation": "upload_customer_match_list",
        "customer_id": customer_id,
        "user_list_id": user_list_id,
        "operation_type": operation_type,
        "members_count": len(members),
        "blast_summary": summary,
        "confirmation_token": token,
        "expires_in_minutes": 10,
        "to_apply": (
            "Chame apply_change(confirmation_token=<token>) para submeter o job. "
            "Job é assíncrono no backend Google — após apply, tool retorna "
            "job_resource_name. Pra checar status posterior, use run_gaql com "
            "query 'SELECT offline_user_data_job.status, failure_reason FROM "
            "offline_user_data_job WHERE offline_user_data_job.id = <id>'."
        ),
        "confirmation_reason": risk.reason,
    }
