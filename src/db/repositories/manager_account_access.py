"""CRUD for `manager_account_access` (which manager can operate which account)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from src.db.repositories.google_ads_accounts import GoogleAdsAccount, _row_to_account


@dataclass(slots=True, frozen=True)
class AccountAccess:
    manager_id: UUID
    customer_id: str
    access_level: str  # 'read' | 'write'
    granted_at: datetime
    granted_by: UUID | None


async def grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
    access_level: str = "write",
    granted_by: UUID | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, customer_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by
        """,
        manager_id,
        customer_id,
        access_level,
        granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    granted_by: UUID | None = None,
) -> int:
    """Grant write access to every active google_ads_accounts row for this manager."""
    result = await conn.execute(
        """
        INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
        SELECT $1, customer_id, 'write', $2
        FROM google_ads_accounts
        WHERE is_active = true
        ON CONFLICT (manager_id, customer_id) DO NOTHING
        """,
        manager_id,
        granted_by,
    )
    return int(result.split()[-1]) if result.startswith("INSERT") else 0


async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
) -> None:
    await conn.execute(
        "DELETE FROM manager_account_access WHERE manager_id = $1 AND customer_id = $2",
        manager_id,
        customer_id,
    )


async def list_accounts_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[GoogleAdsAccount]:
    """Return GoogleAdsAccount rows the manager has any access to (active accounts only)."""
    rows = await conn.fetch(
        """
        SELECT a.*
        FROM google_ads_accounts a
        INNER JOIN manager_account_access m ON m.customer_id = a.customer_id
        WHERE m.manager_id = $1
          AND a.is_active = true
        ORDER BY a.descriptive_name
        """,
        manager_id,
    )
    return [_row_to_account(r) for r in rows]


async def can_manager_access(
    conn: asyncpg.Connection, manager_id: UUID, customer_id: str, *, level: str = "read"
) -> bool:
    """Gate por conta — e, como no Meta, é a ÚNICA fronteira que sobra.

    `build_client_for_manager` usa o token do próprio gestor, mas com
    `login_customer_id` = o MCC, e as identidades dos gestores são usuárias do
    MCC (confirmado 2026-09-05). Logo o token alcança as 26 contas de cliente e
    quem os limita às atribuídas é esta função.

    O JOIN com o inventário é o fix da pendência 10: em 2026-09-05 havia 34
    grants `write` vivos em 9 contas que saíram do MCC, e este predicado
    aprovava os 34. Quem os negava era o Google — delegar ao provedor a
    aplicação de uma regra nossa.
    """
    row = await conn.fetchrow(
        """
        SELECT m.access_level
          FROM manager_account_access m
          JOIN google_ads_accounts a ON a.customer_id = m.customer_id
         WHERE m.manager_id = $1
           AND m.customer_id = $2
           AND a.is_active = true
        """,
        manager_id,
        customer_id,
    )
    if row is None:
        return False
    if level == "read":
        return True
    return bool(row["access_level"] == "write")


async def bulk_grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_ids: list[str],
    granted_by: UUID,
    access_level: str = "write",
) -> int:
    """Idempotent bulk grant. Inserts rows that don't exist; ignores duplicates."""
    if not customer_ids:
        return 0
    rows = [(manager_id, cid, access_level, granted_by) for cid in customer_ids]
    await conn.executemany(
        """INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (manager_id, customer_id) DO NOTHING""",
        rows,
    )
    return len(rows)


async def copy_access(
    conn: asyncpg.Connection,
    *,
    from_manager_id: UUID,
    to_manager_id: UUID,
    granted_by: UUID,
) -> int:
    """Replace destination's access with source's access. Atomic."""
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM manager_account_access WHERE manager_id = $1",
            to_manager_id,
        )
        result = await conn.execute(
            """INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
               SELECT $1, customer_id, access_level, $2
               FROM manager_account_access
               WHERE manager_id = $3""",
            to_manager_id,
            granted_by,
            from_manager_id,
        )
    # asyncpg returns 'INSERT 0 N'
    return int(result.rsplit(" ", 1)[-1])
