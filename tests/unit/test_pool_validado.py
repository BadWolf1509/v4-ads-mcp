"""A conexão é testada na retirada do pool, e a retirada se repete uma vez (spec 2026-09-28 §3.1).

O pool do asyncpg não testa a conexão antes de entregá-la (F76): o Supabase fecha o
socket ocioso e a primeira query estoura. O `run_with_reconnect` só cobre leitura — o F91
proíbe repetir escrita às cegas — e cobria só quem se lembrou de usá-lo: 9 leituras no
caminho quente ficaram de fora (varredura de 21/09, 05#2, conferido em 28/09).

Agora o `init_pool` passa `setup=_testa_conexao` (um `SELECT 1` a cada retirada) e o
`get_pool()` devolve o `PoolValidado`, que repete a RETIRADA uma vez quando o teste falha
por conexão derrubada. A repetição acontece antes de o chamador receber a conexão: nenhum
comando dele rodou, então nada é repetido — leitura e escrita ficam cobertas por um lugar só.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
from typing import Any

import asyncpg
import pytest

from src.db import connection
from tests.unit import _guard_harness as h


class _Retirada:
    """O gerenciador de contexto que `pool.acquire()` devolve — o protocolo que os fakes
    dos testes existentes também usam (não é awaitable)."""

    def __init__(self, efeito: object) -> None:
        self._efeito = efeito
        self.soltou = False

    async def __aenter__(self) -> object:
        if isinstance(self._efeito, BaseException):
            raise self._efeito
        return self._efeito

    async def __aexit__(self, *exc: object) -> bool:
        self.soltou = True
        return False


class _PoolFalso:
    def __init__(self, efeitos: list[object]) -> None:
        self._efeitos = efeitos
        self.retiradas: list[_Retirada] = []

    def acquire(self) -> _Retirada:
        r = _Retirada(self._efeitos[len(self.retiradas)])
        self.retiradas.append(r)
        return r


def _derrubada() -> asyncpg.exceptions.ConnectionDoesNotExistError:
    return asyncpg.exceptions.ConnectionDoesNotExistError(
        "connection was closed in the middle of operation"
    )


async def test_retirada_repete_uma_vez_quando_o_teste_de_conexao_falha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viva = object()
    pool = _PoolFalso([_derrubada(), viva])
    monkeypatch.setattr(connection, "_pool", pool)
    corpo = 0

    async with connection.get_pool().acquire() as conn:
        corpo += 1
        assert conn is viva

    assert len(pool.retiradas) == 2
    assert corpo == 1
    assert pool.retiradas[1].soltou


async def test_erro_que_nao_e_de_conexao_derrubada_nao_repete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _PoolFalso([ValueError("outra coisa"), object()])
    monkeypatch.setattr(connection, "_pool", pool)

    with pytest.raises(ValueError, match="outra coisa"):
        async with connection.get_pool().acquire():
            pass

    assert len(pool.retiradas) == 1


async def test_duas_falhas_seguidas_repassam_o_erro(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _PoolFalso([_derrubada(), ConnectionResetError(104, "reset"), object()])
    monkeypatch.setattr(connection, "_pool", pool)

    with pytest.raises(ConnectionError):
        async with connection.get_pool().acquire():
            pass

    assert len(pool.retiradas) == 2


async def test_erro_dentro_do_corpo_nao_repete_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    """A escrita que falha DEPOIS da retirada não é repetida: o invólucro só repete a retirada."""
    pool = _PoolFalso([object(), object()])
    monkeypatch.setattr(connection, "_pool", pool)
    corpo = 0

    with pytest.raises(asyncpg.exceptions.ConnectionDoesNotExistError):
        async with connection.get_pool().acquire():
            corpo += 1
            raise _derrubada()

    assert len(pool.retiradas) == 1
    assert corpo == 1
    assert pool.retiradas[0].soltou


async def test_init_pool_liga_o_teste_de_conexao(monkeypatch: pytest.MonkeyPatch) -> None:
    capturado: dict[str, Any] = {}

    async def create_pool_falso(**kwargs: Any) -> object:
        capturado.update(kwargs)
        return object()

    monkeypatch.setattr(connection.asyncpg, "create_pool", create_pool_falso)
    monkeypatch.setattr(connection, "_pool", None)

    await connection.init_pool("postgresql://ignored")

    assert capturado["setup"] is connection._testa_conexao
    executado: list[str] = []

    class _Conn:
        async def execute(self, sql: str, *, timeout: object = None) -> str:  # noqa: ASYNC109 — assinatura do asyncpg
            executado.append(sql)
            return "SELECT 1"

    await connection._testa_conexao(_Conn())  # type: ignore[arg-type]
    assert executado == ["SELECT 1"]


def test_get_pool_devolve_o_pool_validado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection, "_pool", _PoolFalso([]))
    assert isinstance(connection.get_pool(), connection.PoolValidado)


# Revisão final da branch: o casador só via `asyncpg.connect(...)`/`asyncpg.create_pool(...)`
# chamados pelo nome. Agora vê qualquer REFERÊNCIA a eles (alias `abre = asyncpg.connect`,
# `asyncpg.connection.connect`, `from asyncpg.pool import create_pool`), a CHAMADA a
# `asyncpg.Pool(...)` (a anotação de tipo não abre conexão) e o acesso ao `_pool` cru do
# `connection` — que contorna a repetição da retirada sem abrir conexão nova.
_REFERENCIA_PROIBIDA = {"connect", "create_pool"}
_CHAMADA_PROIBIDA = {"Pool"}


def _ofensores_na_arvore(arv: ast.Module) -> list[int]:
    origens = h.origens_de_import(arv)
    linhas = []
    for no in ast.walk(arv):
        if isinstance(no, ast.Attribute | ast.Name):
            caminho = h.caminho_canonico(no, origens) or ""
            ultimo = caminho.rsplit(".", 1)[-1]
            abre_conexao = caminho.startswith("asyncpg.") and ultimo in _REFERENCIA_PROIBIDA
            if abre_conexao or caminho == "src.db.connection._pool":
                linhas.append(no.lineno)
        if isinstance(no, ast.Call):
            caminho = h.caminho_canonico(no.func, origens) or ""
            if caminho.startswith("asyncpg.") and caminho.rsplit(".", 1)[-1] in _CHAMADA_PROIBIDA:
                linhas.append(no.lineno)
    return sorted(set(linhas))


def _quem_abre_conexao_fora_do_pool() -> list[str]:
    return [
        f"{h.rel(arquivo)}:{linha}"
        for arquivo in h.fontes_py(h.SRC)
        if h.rel(arquivo) != "src/db/connection.py"
        for linha in _ofensores_na_arvore(h.arvore(arquivo))
    ]


def test_so_o_connection_abre_conexao_com_o_banco() -> None:
    """Quem abre conexão fora de `connection.py` escapa do teste na retirada."""
    ofensores = _quem_abre_conexao_fora_do_pool()
    assert not ofensores, (
        f"conexão aberta fora de src/db/connection.py: {ofensores}. Use connection.get_pool() — "
        "a conexão tirada dali é testada antes de ser entregue (spec 2026-09-28 §3.1)."
    )


def test_o_scan_de_conexao_ve_as_duas_formas(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Controle: o scan acha `asyncpg.connect(...)` e `from asyncpg import create_pool`."""
    pasta = tmp_path.resolve() / "src"
    pasta.mkdir()
    (pasta / "a.py").write_text("import asyncpg\nasync def f():\n    await asyncpg.connect('x')\n")
    (pasta / "b.py").write_text(
        "from asyncpg import create_pool as cp\nasync def g():\n    await cp(dsn='x')\n"
    )
    monkeypatch.setattr(h, "SRC", pasta)
    monkeypatch.setattr(h, "RAIZ", tmp_path.resolve())
    assert sorted(_quem_abre_conexao_fora_do_pool()) == ["src/a.py:3", "src/b.py:3"]


_FORMAS_DA_REVISAO = {
    "pool_submodulo": "from asyncpg.pool import create_pool\nasync def f():\n    await create_pool(dsn='x')\n",
    "connection_submodulo": "import asyncpg\nasync def f():\n    await asyncpg.connection.connect('x')\n",
    "alias": "import asyncpg\nabre = asyncpg.connect\nasync def f():\n    await abre('x')\n",
    "pool_cru": "from src.db import connection\nasync def f():\n    async with connection._pool.acquire():\n        pass\n",
    "pool_construido": "import asyncpg\ndef f():\n    return asyncpg.Pool('x')\n",
}


@pytest.mark.parametrize("forma", sorted(_FORMAS_DA_REVISAO))
def test_o_scan_de_conexao_ve_as_formas_da_revisao(forma: str) -> None:
    """Controle das formas que a revisão final mediu passando: cada uma é acusada."""
    assert _ofensores_na_arvore(ast.parse(_FORMAS_DA_REVISAO[forma]))


def test_o_scan_de_conexao_nao_acusa_anotacao_nem_get_pool() -> None:
    """Controle negativo: anotar `asyncpg.Pool`/`asyncpg.Connection` e usar `get_pool()` é o uso certo."""
    codigo = (
        "import asyncpg\nfrom src.db import connection\n"
        "async def f(conn: asyncpg.Connection, p: asyncpg.Pool | None) -> None:\n"
        "    async with connection.get_pool().acquire() as c:\n        pass\n"
    )
    assert _ofensores_na_arvore(ast.parse(codigo)) == []


class _ConexaoMuda:
    """Conexão cujo `SELECT 1` estoura o prazo (socket buraco-negro) — registra o que recebeu."""

    def __init__(self) -> None:
        self.timeout: object = "nao passado"
        self.terminada = False

    async def execute(self, _sql: str, *, timeout: object = None) -> str:  # noqa: ASYNC109 — assinatura do asyncpg
        self.timeout = timeout
        raise TimeoutError

    def terminate(self) -> None:
        self.terminada = True


async def test_teste_da_retirada_tem_prazo_curto_e_aborta_a_conexao_muda() -> None:
    """Sem prazo proprio o teste herdava os 30 s do `command_timeout`; e no estouro o `close()`
    gracioso do asyncpg esperava, sem prazo, a resposta do cancelamento pelo socket mudo.
    Medido em 29/09 (asyncpg 0.31, proxy que para de repassar bytes): presa aos 75 s."""
    conn = _ConexaoMuda()
    with pytest.raises(connection.ConexaoSemRespostaError):
        await connection._testa_conexao(conn)  # type: ignore[arg-type]
    assert conn.timeout == connection._TIMEOUT_DO_TESTE
    assert connection._TIMEOUT_DO_TESTE <= 2.5, "cabe duas vezes nos 5 s do health profundo"
    assert conn.terminada, "sem terminate() o close() do pool espera o socket mudo"


async def test_conexao_sem_resposta_repete_a_retirada() -> None:
    assert issubclass(connection.ConexaoSemRespostaError, connection._DROPPED_CONNECTION_ERRORS)
    cru = _PoolFalso([connection.ConexaoSemRespostaError("mudo"), "conexao nova"])
    async with connection.PoolValidado(cru).acquire() as conn:
        assert conn == "conexao nova"
    assert len(cru.retiradas) == 2


class _ConexaoDoCorpo:
    def __init__(self) -> None:
        self.terminada = False

    def terminate(self) -> None:
        self.terminada = True


@pytest.mark.parametrize(
    ("erro", "descarta"),
    [
        (TimeoutError(), True),
        (asyncio.CancelledError(), True),
        (ValueError("erro do chamador"), False),
        (None, False),
    ],
    ids=["timeout", "cancelamento", "outro-erro", "saida-normal"],
)
async def test_conexao_que_sai_por_timeout_ou_cancelamento_e_descartada(
    erro: BaseException | None, descarta: bool
) -> None:
    """Depois de timeout ou cancelamento a conexao pode estar no meio de um cancelamento, e a
    devolucao do asyncpg espera o fim dele sem prazo — num socket mudo, para sempre, e protegida
    por `shield`: quem chamou volta, a vaga do pool fica presa (medido em 29/09). Descartar
    antes de devolver libera a vaga na hora."""
    conn = _ConexaoDoCorpo()
    cru = _PoolFalso([conn])
    with pytest.raises(type(erro)) if erro is not None else contextlib.nullcontext():
        async with connection.PoolValidado(cru).acquire():
            if erro is not None:
                raise erro
    assert conn.terminada is descarta
    assert cru.retiradas[0].soltou, "a devolucao ao pool acontece nos quatro casos"
