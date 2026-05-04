"""Dry-run + pending confirmations: generate token, persist payload, consume.

Tokens are 8 alphanumeric chars (uppercase + digits) — short enough for
a human to type from chat if needed, long enough to be unguessable
(36^8 ~ 2.8 trillion). Always tied to (session_id, customer_id) and a
TTL of 10 minutes.

Concurrent consumes are race-safe via `SELECT ... FOR UPDATE` + immediate
update of consumed_at.
"""

import json
import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

DEFAULT_TTL_MINUTES = 10
_TOKEN_ALPHABET = string.ascii_uppercase + string.digits  # 36 chars
_TOKEN_LEN = 8


class InvalidTokenError(Exception):
    """Raised when a confirmation token is not found, expired, already consumed,
    or belongs to a different session."""


@dataclass(slots=True, frozen=True)
class ConsumeResult:
    customer_id: str
    operation_type: str
    payload: dict[str, Any]
    blast_summary: str


def generate_token() -> str:
    """8 random alphanumeric chars (uppercase + digits)."""
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(_TOKEN_LEN))


async def create_pending(
    conn: asyncpg.Connection,
    *,
    session_id: UUID,
    customer_id: str,
    operation_type: str,
    payload: dict[str, Any],
    blast_summary: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> str:
    """Persist a pending confirmation. Returns the token."""
    # Loop on collision (extremely unlikely with 36^8 space + 10min TTL).
    for _ in range(5):
        token = generate_token()
        try:
            await conn.execute(
                """
                INSERT INTO pending_confirmations
                  (token, session_id, customer_id, operation_type, payload, blast_summary, expires_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, now() + ($7 || ' minutes')::interval)
                """,
                token,
                session_id,
                customer_id,
                operation_type,
                json.dumps(payload),
                blast_summary,
                str(ttl_minutes),
            )
            return token
        except asyncpg.UniqueViolationError:
            continue
    raise RuntimeError("Could not generate unique confirmation token after 5 attempts")


async def consume(
    conn: asyncpg.Connection,
    *,
    token: str,
    session_id: UUID,
) -> ConsumeResult:
    """Atomically validate + mark a token as consumed. Returns the saved payload.

    Raises:
        InvalidTokenError: not found / expired / already consumed / wrong session
    """
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT session_id, customer_id, operation_type, payload, blast_summary,
                   expires_at, consumed_at
            FROM pending_confirmations
            WHERE token = $1
            FOR UPDATE
            """,
            token,
        )
        if row is None:
            raise InvalidTokenError(f"Token '{token}' not found")
        if row["consumed_at"] is not None:
            raise InvalidTokenError(f"Token '{token}' already consumed")
        if row["session_id"] != session_id:
            raise InvalidTokenError(
                f"Token '{token}' belongs to a different session — refuse to apply"
            )
        if row["expires_at"] < datetime.now(UTC):
            raise InvalidTokenError(f"Token '{token}' expired")

        await conn.execute(
            "UPDATE pending_confirmations SET consumed_at = now() WHERE token = $1",
            token,
        )

    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return ConsumeResult(
        customer_id=row["customer_id"],
        operation_type=row["operation_type"],
        payload=payload,
        blast_summary=row["blast_summary"],
    )
