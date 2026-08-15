"""Cloud Run Job: backup semanal do DB -> GCS (dump csv.gz por tabela).

O DB Supabase (refresh tokens cifrados, matriz de acesso, audit trail de
compliance) não tinha backup próprio — near-miss real em 06-19 (conta admin
excluída). Este job descobre as tabelas via information_schema, faz dump de
cada uma em CSV (asyncpg COPY), comprime com gzip e sobe pro bucket GCS
(infra + IAM já provisionados fora deste código).

F94 — duas garantias que o desenho original não dava: **um único snapshot**
(uma conexão numa transação `REPEATABLE READ` cobre a descoberta e todos os
COPYs, então o dump é referencialmente íntegro e o restore não quebra com FK
órfã) e **stream** (COPY → gzip → GCS sem materializar a tabela em memória,
que é o que fazia o job morrer por OOM à medida que `audit_log` crescia).

Entry point: `python -m src.jobs.backup`
"""

import asyncio
import gzip
import sys
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog
from google.cloud import storage  # type: ignore[import-untyped]

from src.config import get_settings
from src.db import connection
from src.jobs._audit import record_job_crash, record_job_run

log = structlog.get_logger(__name__)


async def _list_tables(conn: asyncpg.Connection) -> list[str]:
    """Tabelas base do schema public, ordenadas por nome (inclui _migrations)."""
    rows = await conn.fetch(
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
           ORDER BY table_name"""
    )
    return [r["table_name"] for r in rows]


class _ContaBytes:
    """Passa a escrita adiante contando os bytes COMPRIMIDOS que vão pro GCS.

    Preserva o significado de `params_summary.total_bytes`, que antes vinha do
    `len()` do buffer inteiro — o buffer que deixou de existir (F94).
    """

    def __init__(self, destino: Any) -> None:
        self._destino = destino
        self.total = 0

    def write(self, dados: bytes) -> int:
        self.total += len(dados)
        return self._destino.write(dados)  # type: ignore[no-any-return]

    def flush(self) -> None:
        flush = getattr(self._destino, "flush", None)
        if flush is not None:
            flush()


async def _dump_table_to_blob(conn: asyncpg.Connection, table_name: str, blob: Any) -> int:
    """COPY -> gzip -> GCS em STREAM. Devolve os bytes comprimidos enviados.

    F94 — antes a tabela inteira era bufferizada 3× (BytesIO, `gzip.compress`,
    `upload_from_string`) com `--memory=512Mi`, enquanto `audit_log` cresce sem
    teto por decisão de produto: o job que protege o artefato de compliance era
    o que tendia a morrer por OOM. Agora nada além do buffer do deflate fica em
    memória.

    table_name vem do information_schema (não de input externo) — sem risco de
    injeção; ainda assim qualificamos com aspas duplas por hábito defensivo.

    A ordem dos `with` é carga: o `GzipFile` precisa fechar ANTES do writer do
    blob, senão o trailer não é escrito e o .gz sobe truncado — falha que só
    apareceria no dia do restore.
    """
    with blob.open("wb", content_type="application/gzip") as destino:
        contador = _ContaBytes(destino)
        with gzip.GzipFile(fileobj=contador, mode="wb") as gz:

            async def _sink(chunk: bytes) -> None:
                gz.write(chunk)

            await conn.copy_from_query(
                f'SELECT * FROM "{table_name}"',
                output=_sink,
                format="csv",
                header=True,
            )
    return contador.total


async def run() -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        date_prefix = datetime.now(UTC).date().isoformat()
        # Cliente GCS montado ANTES da transação: o snapshot deve durar o mínimo
        # possível (ele segura o vacuum enquanto estiver aberto).
        client = storage.Client()
        bucket = client.bucket(settings.backup_bucket)

        uploaded: list[str] = []
        failed: list[str] = []
        total_bytes = 0

        # F94 — UMA conexão e UMA transação REPEATABLE READ pro backup inteiro.
        # Antes cada tabela era dumpada num acquire próprio, em momentos
        # distintos: um manager criado no meio do run gerava dump com FK órfã
        # (`mcp_sessions.manager_id` sem linha em `managers.csv`, já que
        # `managers` vem antes na ordem alfabética) e o restore quebrava. A
        # descoberta de tabelas entra no mesmo snapshot de propósito.
        async with pool.acquire() as conn, conn.transaction(isolation="repeatable_read"):
            tables = await _list_tables(conn)
            snapshot_perdido = False

            for table_name in tables:
                if snapshot_perdido:
                    failed.append(table_name)
                    continue
                try:
                    blob = bucket.blob(f"{date_prefix}/{table_name}.csv.gz")
                    total_bytes += await _dump_table_to_blob(conn, table_name, blob)
                    uploaded.append(table_name)
                except Exception as e:  # noqa: BLE001
                    log.error("backup_table_failed", table=table_name, error=str(e))
                    failed.append(table_name)
                    if isinstance(e, asyncpg.PostgresError):
                        # A transação abortou: as tabelas seguintes não teriam
                        # snapshot algum. Marcá-las de uma vez é mais honesto que
                        # gerar N erros de "current transaction is aborted".
                        snapshot_perdido = True
                        log.error("backup_snapshot_lost", table=table_name)

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
    except Exception as e:
        # F93: crash antes do record_job_run (ex.: _list_tables, storage.Client())
        # deixaria o backup — artefato de compliance — sem linha nenhuma no audit.
        await record_job_crash(operation="db_backup", platform="google", exc=e)
        raise
    finally:
        await connection.close_pool()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
