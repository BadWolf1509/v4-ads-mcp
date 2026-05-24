"""CRUD for `manager_meta_account_access` (which manager can operate which Meta ad account)."""

from uuid import UUID

import asyncpg

from src.db.repositories.meta_ad_accounts import MetaAdAccount, _row_to_account


async def grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_id: str,
    access_level: str = "write",
    granted_by: UUID | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO manager_meta_account_access
            (manager_id, ad_account_id, access_level, granted_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, ad_account_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by
        """,
        manager_id,
        ad_account_id,
        access_level,
        granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    granted_by: UUID | None = None,
) -> int:
    """Grant write access to every active meta_ad_accounts row for this manager."""
    result = await conn.execute(
        """
        INSERT INTO manager_meta_account_access
            (manager_id, ad_account_id, access_level, granted_by)
        SELECT $1, ad_account_id, 'write', $2
        FROM meta_ad_accounts
        WHERE is_active = true
        ON CONFLICT (manager_id, ad_account_id) DO NOTHING
        """,
        manager_id,
        granted_by,
    )
    return int(result.split()[-1]) if result.startswith("INSERT") else 0


async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_id: str,
) -> None:
    await conn.execute(
        "DELETE FROM manager_meta_account_access WHERE manager_id = $1 AND ad_account_id = $2",
        manager_id,
        ad_account_id,
    )


async def list_accounts_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[MetaAdAccount]:
    """Return MetaAdAccount rows the manager has any access to (active accounts only)."""
    rows = await conn.fetch(
        """
        SELECT a.*
        FROM meta_ad_accounts a
        INNER JOIN manager_meta_account_access m ON m.ad_account_id = a.ad_account_id
        WHERE m.manager_id = $1
          AND a.is_active = true
        ORDER BY a.account_name
        """,
        manager_id,
    )
    return [_row_to_account(r) for r in rows]


async def can_manager_access(
    conn: asyncpg.Connection,
    manager_id: UUID,
    ad_account_id: str,
    *,
    level: str = "read",
) -> bool:
    """Return True if manager has at least `level` access to ad_account_id."""
    row = await conn.fetchrow(
        """
        SELECT access_level FROM manager_meta_account_access
        WHERE manager_id = $1 AND ad_account_id = $2
        """,
        manager_id,
        ad_account_id,
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
    ad_account_ids: list[str],
    granted_by: UUID,
    access_level: str = "write",
) -> int:
    """Idempotent bulk grant. Inserts rows that don't exist; ignores duplicates.

    Returns len(ad_account_ids) — not the count of rows actually inserted.
    executemany with ON CONFLICT DO NOTHING does not expose per-batch counts.
    """
    if not ad_account_ids:
        return 0
    rows = [(manager_id, aid, access_level, granted_by) for aid in ad_account_ids]
    await conn.executemany(
        """INSERT INTO manager_meta_account_access
               (manager_id, ad_account_id, access_level, granted_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (manager_id, ad_account_id) DO NOTHING""",
        rows,
    )
    return len(rows)


# NOTE: copy_access (clone one manager's access to another, present in
# google_ads parallel) is intentionally omitted from M.1 — no caller yet.
# Add in a future sprint if admin UI requires manager-to-manager copy.
