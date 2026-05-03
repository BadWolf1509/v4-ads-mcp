"""Idempotent SQL migration runner.

Reads files from `src/db/migrations/*.sql` in lexical order, applies
each one inside a transaction, and records applied migrations in a
`_migrations` table to avoid re-running them.
"""

import asyncio
from pathlib import Path

import asyncpg
import structlog

from src.config import get_settings
from src.db import connection

log = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS _migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


async def _list_pending(conn: asyncpg.Connection) -> list[Path]:
    rows = await conn.fetch("SELECT name FROM _migrations")
    applied = {r["name"] for r in rows}
    all_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in all_files if f.name not in applied]


async def run_all() -> None:
    """Apply every pending migration in order. Idempotent."""
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_BOOTSTRAP_SQL)
        pending = await _list_pending(conn)
        if not pending:
            log.info("migrations_no_pending")
            return
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (name) VALUES ($1)",
                    path.name,
                )
            log.info("migration_applied", name=path.name)


async def main() -> None:
    """CLI entrypoint: `python -m src.db.migrate`."""
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        await run_all()
    finally:
        await connection.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
