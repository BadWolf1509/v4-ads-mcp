"""F94: o backup bufferizava cada tabela 3x e tirava snapshot nao-atomico.

**Memoria:** o COPY inteiro ia pra um `io.BytesIO`, depois `gzip.compress` fazia
a 2a copia e `upload_from_string` a 3a — com `--memory=512Mi` e `audit_log` sem
retencao maxima por decisao de produto. Ou seja: o job que protege o artefato de
compliance era o que tendia a morrer por OOM, e justamente quando o artefato
ficasse grande o bastante pra importar.

**Atomicidade:** cada tabela era dumpada num `pool.acquire()` PROPRIO, em
momentos distintos e sem transacao englobante. Um manager criado no meio do run
produz um dump com FK orfa — `mcp_sessions.manager_id` sem linha em
`managers.csv`, porque `managers` vem antes na ordem alfabetica. O restore
quebra, e so se descobre no dia em que ele for necessario.
"""

from __future__ import annotations

import gzip
import io
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from freezegun import freeze_time

from src.jobs import backup

_M = "src.jobs.backup"


class _Escritor:
    """Espelha o `BlobWriter` real de google-cloud-storage 3.12.0.

    Verificado na fonte instalada: `__exit__` chama `terminate()` quando ha
    excecao (`transport.delete(upload.upload_url)` — cancela o upload resumable)
    e `close()` so no caminho limpo. Ou seja, tabela que falha no meio do stream
    NAO deixa um .gz truncado no bucket — o que seria pior que arquivo ausente,
    porque pareceria um backup bom ate o dia do restore.
    """

    def __init__(self, blob: _Blob) -> None:
        self._blob = blob

    def write(self, dados: bytes) -> int:
        return self._blob.buffer.write(dados)

    def flush(self) -> None:
        pass

    def __enter__(self) -> _Escritor:
        return self

    def __exit__(self, exc_type: object, *_exc: object) -> bool:
        if exc_type is not None:
            self._blob.terminado = True
            self._blob.buffer = io.BytesIO()  # upload cancelado, nada persiste
        return False


class _Blob:
    """Blob GCS falso que preserva o conteudo escrito (pra descomprimir depois)."""

    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.buffer = io.BytesIO()
        self.aberto_como: tuple[str, dict[str, Any]] | None = None
        self.terminado = False
        self.upload_from_string = MagicMock()

    def open(self, mode: str, **kwargs: Any) -> _Escritor:
        self.aberto_como = (mode, kwargs)
        return _Escritor(self)

    @property
    def conteudo(self) -> bytes:
        return self.buffer.getvalue()


def _storage_falso() -> tuple[MagicMock, dict[str, _Blob]]:
    blobs: dict[str, _Blob] = {}

    def _blob(nome: str) -> _Blob:
        return blobs.setdefault(nome, _Blob(nome))

    bucket = MagicMock()
    bucket.blob = MagicMock(side_effect=_blob)
    client = MagicMock()
    client.bucket = MagicMock(return_value=bucket)
    return client, blobs


class _Transacao:
    def __init__(self, dono: _Conn, kwargs: dict[str, Any]) -> None:
        self._dono = dono
        self._dono.transacoes.append(kwargs)

    async def __aenter__(self) -> _Transacao:
        self._dono.dentro_da_transacao = True
        return self

    async def __aexit__(self, *exc: object) -> bool:
        self._dono.dentro_da_transacao = False
        return False


class _Conn:
    """Connection falsa que registra transacoes e em que estado cada COPY rodou."""

    def __init__(self, tabelas: list[str], linhas_por_tabela: int = 3) -> None:
        self._tabelas = tabelas
        self._linhas = linhas_por_tabela
        self.transacoes: list[dict[str, Any]] = []
        self.dentro_da_transacao = False
        self.copies: list[tuple[str, bool]] = []
        # Quantos bytes ja tinham chegado ao blob quando o 1o chunk foi enviado.
        self.bytes_no_blob_apos_1o_chunk: int | None = None
        self._blob_atual: _Blob | None = None

    def transaction(self, **kwargs: Any) -> _Transacao:
        return _Transacao(self, kwargs)

    async def fetch(self, *_a: Any, **_k: Any) -> list[dict[str, str]]:
        return [{"table_name": t} for t in self._tabelas]

    def espiar_blob(self, blob: _Blob) -> None:
        self._blob_atual = blob

    async def copy_from_query(self, query: str, *, output: Any, format: str, header: bool) -> str:
        self.copies.append((query, self.dentro_da_transacao))
        for i in range(self._linhas):
            await output(f"col_a,col_b\r\nlinha{i},valor{i}\r\n".encode())
            if i == 0 and self._blob_atual is not None:
                self.bytes_no_blob_apos_1o_chunk = len(self._blob_atual.conteudo)
        return f"COPY {self._linhas}"


def _pool_falso(conn: _Conn) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire() -> Any:
        yield conn

    pool.acquire = _acquire
    return pool


def _patches(pool: MagicMock, client: MagicMock) -> list[Any]:
    return [
        patch(f"{_M}.connection.init_pool", AsyncMock()),
        patch(f"{_M}.connection.close_pool", AsyncMock()),
        patch(f"{_M}.connection.get_pool", MagicMock(return_value=pool)),
        patch(f"{_M}.storage.Client", MagicMock(return_value=client)),
        patch(f"{_M}.record_job_run", AsyncMock(return_value=1)),
    ]


@freeze_time("2026-08-15")
@pytest.mark.asyncio
async def test_todas_as_tabelas_saem_do_mesmo_snapshot() -> None:
    """F94: sem transacao englobante, o dump tem FK orfa e o restore quebra."""
    conn = _Conn(["managers", "mcp_sessions", "audit_log"])
    client, _ = _storage_falso()

    with patch.multiple(f"{_M}.connection", init_pool=AsyncMock(), close_pool=AsyncMock()):
        for p in _patches(_pool_falso(conn), client):
            p.start()
        try:
            rc = await backup.run()
        finally:
            patch.stopall()

    assert rc == 0
    assert len(conn.transacoes) == 1, (
        f"esperava UMA transacao englobando o backup inteiro, houve {len(conn.transacoes)}"
    )
    assert conn.transacoes[0].get("isolation") == "repeatable_read", (
        "sem REPEATABLE READ cada COPY ve um snapshot diferente (read committed)"
    )
    assert all(dentro for _q, dentro in conn.copies), (
        "algum COPY rodou FORA da transacao — nao esta no mesmo snapshot"
    )
    assert len(conn.copies) == 3


@freeze_time("2026-08-15")
@pytest.mark.asyncio
async def test_tabela_vai_pro_gcs_em_stream_e_nao_de_uma_vez() -> None:
    """F94: `upload_from_string` exige a tabela inteira comprimida em memoria."""
    conn = _Conn(["audit_log"], linhas_por_tabela=5)
    client, blobs = _storage_falso()

    # Deixa a conn espiar o blob pra medir o progresso durante o COPY.
    bucket = client.bucket.return_value
    original = bucket.blob.side_effect

    def _blob_espiado(nome: str) -> _Blob:
        b = original(nome)
        conn.espiar_blob(b)
        return b

    bucket.blob = MagicMock(side_effect=_blob_espiado)

    for p in _patches(_pool_falso(conn), client):
        p.start()
    try:
        rc = await backup.run()
    finally:
        patch.stopall()

    assert rc == 0
    blob = blobs["2026-08-15/audit_log.csv.gz"]
    blob.upload_from_string.assert_not_called()
    assert blob.aberto_como is not None, "o blob nao foi aberto em modo stream"
    assert blob.aberto_como[0] == "wb"
    assert conn.bytes_no_blob_apos_1o_chunk, (
        "nada tinha chegado ao GCS depois do 1o chunk — a tabela ainda esta "
        "sendo bufferizada inteira antes do upload"
    )


@freeze_time("2026-08-15")
@pytest.mark.asyncio
async def test_o_gzip_escrito_em_stream_continua_valido() -> None:
    """F94: stream mal fechado produz .gz truncado — e so se descobre no restore."""
    conn = _Conn(["managers"], linhas_por_tabela=4)
    client, blobs = _storage_falso()

    for p in _patches(_pool_falso(conn), client):
        p.start()
    try:
        await backup.run()
    finally:
        patch.stopall()

    bruto = gzip.decompress(blobs["2026-08-15/managers.csv.gz"].conteudo)
    assert bruto.count(b"linha") == 4, "o gzip perdeu linhas no caminho"
    assert bruto.startswith(b"col_a,col_b")


@freeze_time("2026-08-15")
@pytest.mark.asyncio
async def test_erro_de_banco_interrompe_o_snapshot_em_vez_de_fingir() -> None:
    """F94: numa transacao unica, um erro de DB ABORTA o resto — nao esconder isso.

    O antigo `except` por tabela seguia em frente porque cada dump tinha conexao
    propria. Agora, um `PostgresError` envenena a transacao: as tabelas
    seguintes nao teriam snapshot algum, entao sao marcadas como falhas em vez
    de gerar N erros confusos de "current transaction is aborted".
    """
    conn = _Conn(["a_table", "b_table", "c_table"])
    copy_original = conn.copy_from_query

    async def _copy_que_quebra(query: str, **kwargs: Any) -> str:
        if "b_table" in query:
            raise asyncpg.exceptions.UndefinedColumnError("coluna sumiu")
        return await copy_original(query, **kwargs)

    conn.copy_from_query = _copy_que_quebra  # type: ignore[method-assign]
    client, blobs = _storage_falso()

    for p in _patches(_pool_falso(conn), client):
        p.start()
    try:
        rc = await backup.run()
        record = backup.record_job_run
    finally:
        patch.stopall()

    assert rc == 1
    # Só a tabela anterior ao erro tem conteúdo; a que falhou teve o upload
    # CANCELADO (nada de .gz truncado no bucket), e a seguinte nem foi tentada.
    com_conteudo = {nome for nome, b in blobs.items() if b.conteudo}
    assert com_conteudo == {"2026-08-15/a_table.csv.gz"}
    assert blobs["2026-08-15/b_table.csv.gz"].terminado is True
    assert "2026-08-15/c_table.csv.gz" not in blobs, "tabela pos-abort nao deve ser tentada"

    kwargs = record.call_args.kwargs  # type: ignore[attr-defined]
    assert kwargs["status"] == "error"
    assert kwargs["params_summary"]["failed_tables"] == ["b_table", "c_table"]
