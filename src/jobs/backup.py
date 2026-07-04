"""Cloud Run Job: backup semanal do DB -> GCS (dump csv.gz por tabela).

O DB Supabase (refresh tokens cifrados, matriz de acesso, audit trail de
compliance) não tinha backup próprio — near-miss real em 06-19 (conta admin
excluída). Este job descobre as tabelas via information_schema, faz dump de
cada uma em CSV (asyncpg COPY), comprime com gzip e sobe pro bucket GCS
(infra + IAM já provisionados fora deste código).

Entry point: `python -m src.jobs.backup`
"""

import asyncio
import gzip
import io
import sys
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog
from google.cloud import storage  # type: ignore[import-untyped]

from src.config import get_settings
from src.db import connection
from src.jobs._audit import record_job_run

log = structlog.get_logger(__name__)


async def _list_tables(conn: asyncpg.Connection) -> list[str]:
    """Tabelas base do schema public, ordenadas por nome (inclui _migrations)."""
    rows = await conn.fetch(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
           ORDER BY table_name"""
    )
    return [r["table_name"] for r in rows]


async def _dump_table_csv_gz(conn: asyncpg.Connection, table_name: str) -> bytes:
    """COPY de 1 tabela pra CSV (com header) em memória, depois gzip.

    table_name vem do information_schema (não de input externo) — sem risco de
    injeção; ainda assim qualificamos com aspas duplas por hábito defensivo.
    copy_from_query é um comando COPY próprio, não um server-side cursor (F58)
    — não precisa de transação explícita.
    """
    buf = io.BytesIO()

    async def _sink(chunk: bytes) -> None:
        buf.write(chunk)

    await conn.copy_from_query(
        f'SELECT * FROM "{table_name}"',
        output=_sink,
        format="csv",
        header=True,
    )
    return gzip.compress(buf.getvalue())


async def run() -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            tables = await _list_tables(conn)

        date_prefix = datetime.now(UTC).date().isoformat()
        client = storage.Client()
        bucket = client.bucket(settings.backup_bucket)

        uploaded: list[str] = []
        failed: list[str] = []
        total_bytes = 0

        for table_name in tables:
            try:
                async with pool.acquire() as conn:
                    gz_bytes = await _dump_table_csv_gz(conn, table_name)
                blob_name = f"{date_prefix}/{table_name}.csv.gz"
                bucket.blob(blob_name).upload_from_string(gz_bytes, content_type="application/gzip")
                uploaded.append(table_name)
                total_bytes += len(gz_bytes)
            except Exception as e:  # noqa: BLE001
                log.error("backup_table_failed", table=table_name, error=str(e))
                failed.append(table_name)

        status = "success" if not failed else "error"
        params_summary: dict[str, Any] = {
            "tables": uploaded,
            "total_bytes": total_bytes,
            "bucket": settings.backup_bucket,
        }
        if failed:
            params_summary["failed_tables"] = failed

        async with pool.acquire() as conn:
            await record_job_run(
                conn,
                operation="db_backup",
                platform="google",
                target_count=len(uploaded),
                status=status,
                error_message=f"{len(failed)} tabela(s) falharam: {failed}" if failed else None,
                params_summary=params_summary,
            )

        if failed:
            log.error("backup_partial_failure", uploaded=len(uploaded), failed=failed)
            print(
                f"ERROR: backup parcial — {len(uploaded)} ok, falharam: {failed}", file=sys.stderr
            )
            return 1

        log.info("backup_complete", uploaded=len(uploaded), total_bytes=total_bytes)
        print(
            f"OK: backup de {len(uploaded)} tabelas ({total_bytes} bytes) -> {settings.backup_bucket}/{date_prefix}/"
        )
        return 0
    finally:
        await connection.close_pool()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
