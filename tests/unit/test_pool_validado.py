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
        async def execute(self, sql: str) -> str:
            executado.append(sql)
            return "SELECT 1"

    await connection._testa_conexao(_Conn())  # type: ignore[arg-type]
    assert executado == ["SELECT 1"]


def test_get_pool_devolve_o_pool_validado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connection, "_pool", _PoolFalso([]))
    assert isinstance(connection.get_pool(), connection.PoolValidado)


_ABRE_CONEXAO = {"asyncpg.create_pool", "asyncpg.connect"}


def _quem_abre_conexao_fora_do_pool() -> list[str]:
    ofensores = []
    for arquivo in h.fontes_py(h.SRC):
        if h.rel(arquivo) == "src/db/connection.py":
            continue
        arv = h.arvore(arquivo)
        origens = h.origens_de_import(arv)
        for no in ast.walk(arv):
            if isinstance(no, ast.Call) and h.caminho_canonico(no.func, origens) in _ABRE_CONEXAO:
                ofensores.append(f"{h.rel(arquivo)}:{no.lineno}")
    return ofensores


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
