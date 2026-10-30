"""Restore manual do backup semanal: `python -m src.jobs.restore <pasta>`.

A pasta e a de uma data (`<tabela>.csv.gz`, ou `.csv` ja descompactado) baixada
do GCS, e o banco de destino precisa ser LIMPO e ja migrado
(`python -m src.db.migrate`); destino com linha em qualquer tabela e recusado, e
o CLI exige `--confirmar-host <host do DATABASE_URL>` antes de conectar. O restore e deliberadamente manual: automatizar
restore e perigoso.

Tres fatos medidos que o runbook antigo nao cobria:

- `copy_to_table` grava o `id` explicito e NAO avanca a sequence do
  `audit_log` (unica tabela com SERIAL): o INSERT seguinte batia em
  `UniqueViolationError (id)=(1)`. Por isso o `setval` no fim.
- O dump inclui `_migrations`, que conflita com o schema ja migrado: pulada.
- Tudo roda numa transacao so — restore pela metade nao deixa o banco num
  estado que parece restaurado.
"""

import asyncio
import csv
import gzip
import io
import sys
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

import asyncpg
import structlog

from src.config import get_settings
from src.db import connection

log = structlog.get_logger(__name__)

# Ordem de FK: managers -> (conexoes Google, contas, sessoes) -> (acessos,
# confirmacoes, audit, contadores) -> tabelas Meta. Um teste de integracao
# garante que esta lista cobre todas as tabelas do schema migrado.
ORDEM_RESTORE: tuple[str, ...] = (
    "managers",
    "google_oauth_connections",
    "google_ads_accounts",
    "mcp_sessions",
    "manager_account_access",
    "pending_confirmations",
    "audit_log",
    "rate_counters",
    "meta_oauth_connections",
    "meta_ad_accounts",
    "manager_meta_account_access",
    "meta_rate_counters",
)
_PULADAS = frozenset({"_migrations"})

_SETVAL_AUDIT = """
SELECT setval(
    pg_get_serial_sequence('audit_log', 'id'),
    GREATEST((SELECT max(id) FROM audit_log), 1),
    (SELECT max(id) IS NOT NULL FROM audit_log)
)
"""


def _arquivo_da_tabela(pasta: Path, tabela: str) -> Path | None:
    for sufixo in (".csv.gz", ".csv"):
        caminho = pasta / f"{tabela}{sufixo}"
        if caminho.exists():
            return caminho
    return None


def _abrir(caminho: Path) -> IO[bytes]:
    if caminho.suffix == ".gz":
        return gzip.open(caminho, "rb")  # type: ignore[return-value]
    return caminho.open("rb")


def _colunas(caminho: Path) -> list[str]:
    """Colunas do cabecalho do CSV: a ordem do dump nao precisa casar com a do destino."""
    with _abrir(caminho) as f:
        primeira = io.TextIOWrapper(f, encoding="utf-8", newline="").readline()
    return next(csv.reader([primeira]))


def _validar_pasta(pasta: Path) -> dict[str, Path]:
    if not pasta.is_dir():
        raise FileNotFoundError(f"pasta de backup inexistente: {pasta}")
    arquivos: dict[str, Path] = {}
    for p in pasta.iterdir():
        nome = p.name
        for sufixo in (".csv.gz", ".csv"):
            if nome.endswith(sufixo):
                arquivos[nome.removesuffix(sufixo)] = p
                break
    desconhecidas = sorted(set(arquivos) - set(ORDEM_RESTORE) - _PULADAS)
    if desconhecidas:
        raise ValueError(
            f"tabela(s) no backup fora da ordem de restore: {desconhecidas} — "
            "atualize ORDEM_RESTORE em src/jobs/restore.py"
        )
    faltando = [t for t in ORDEM_RESTORE if _arquivo_da_tabela(pasta, t) is None]
    if faltando:
        raise FileNotFoundError(
            f"backup incompleto, faltam: {faltando} — nao complete com outra data"
        )
    return arquivos


async def restaurar_tabelas(conn: asyncpg.Connection, pasta: Path) -> dict[str, int]:
    """Restaura a pasta num banco migrado e limpo; devolve linhas por tabela."""
    _validar_pasta(pasta)  # antes de qualquer COPY: pasta ruim nao toca o banco
    for tabela in ORDEM_RESTORE:
        # Destino com dado nao e "limpo": o COPY somaria ao que existe (ou colidiria).
        if await conn.fetchval(f'SELECT EXISTS (SELECT 1 FROM "{tabela}")'):
            raise ValueError(
                f"destino nao esta vazio: a tabela {tabela!r} ja tem linhas — "
                "restore so roda num banco recem-migrado e limpo; nada foi alterado"
            )
    contagens: dict[str, int] = {}
    async with conn.transaction():
        for tabela in ORDEM_RESTORE:
            caminho = _arquivo_da_tabela(pasta, tabela)
            assert caminho is not None
            with _abrir(caminho) as f:
                # timeout=None: o COPY de uma tabela grande nao cabe no limite padrao.
                await conn.copy_to_table(
                    tabela,
                    source=f,
                    columns=_colunas(caminho),
                    format="csv",
                    header=True,
                    timeout=None,
                )
            # timeout=None tambem aqui: estourar o limite do pool desfaria o restore inteiro.
            contagens[tabela] = int(
                await conn.fetchval(f'SELECT count(*) FROM "{tabela}"', timeout=None)
            )
        await conn.execute(_SETVAL_AUDIT)
    log.info("restore_complete", tabelas=contagens)
    return contagens


async def run(pasta: Path) -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url, min_size=1, max_size=1)
    try:
        async with connection.get_pool().acquire() as conn:
            contagens = await restaurar_tabelas(conn, pasta)
    finally:
        await connection.close_pool()
    for tabela, n in contagens.items():
        print(f"{tabela}: {n}")
    return 0


def _host_do_dsn(dsn: str) -> str:
    """So o host do DSN: usuario e senha nunca chegam a uma mensagem."""
    return urlsplit(dsn).hostname or "<desconhecido>"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    uso = "uso: python -m src.jobs.restore <pasta> --confirmar-host <host-do-DATABASE_URL>"
    confirmado: str | None = None
    posicionais: list[str] = []
    it = iter(args)
    for a in it:
        if a == "--confirmar-host":
            confirmado = next(it, None)
        else:
            posicionais.append(a)
    if len(posicionais) != 1:
        print(uso, file=sys.stderr)
        return 2
    host = _host_do_dsn(get_settings().database_url)
    if confirmado != host:
        print(
            f"restore recusado: o DATABASE_URL aponta para o host {host!r}. "
            f"Se e esse o destino, repita com --confirmar-host {host}\n{uso}",
            file=sys.stderr,
        )
        return 2
    return asyncio.run(run(Path(posicionais[0])))


if __name__ == "__main__":
    sys.exit(main())
