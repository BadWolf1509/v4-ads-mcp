"""F186: o deep health reporta a contagem do registry MCP, sem credencial.

O smoke autenticado do `/mcp` no deploy prova o stack inteiro — Bearer resolvido,
dispatcher respondendo, registry montado — mas depende de um token que **hoje não há
como provisionar**: `sessions_create` fixa `manager_id=user.id`, login exige identidade
Google do domínio corporativo, e não existe conta de serviço no Workspace. Em 20/09 ele
estava desarmado havia 8 deploys.

A contagem no `?deep=1` não substitui aquele smoke — ela cobre **a parte afirmável sem
credencial**: o app subiu *e* o registry montou. Um check que roda vale mais que um
check que não pode ser provisionado.

**O que isto NÃO cobre, e está dito para não ser confundido com cobertura:** a
resolução `Bearer → sessão` e o streaming SSE de um `tools/list` real. Essas duas só o
smoke autenticado alcança.

A asserção é **derivada** (`len(all_tools())`), nunca um número escrito à mão: contagem
literal num teste é segunda fonte de verdade e passa a mentir na primeira tool nova.
"""

from __future__ import annotations

import sys

import pytest
from httpx import AsyncClient

from src.db import connection
from src.mcp.tools._registry import all_tools


class _Acquire:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    async def __aenter__(self) -> object:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    def acquire(self) -> _Acquire:
        return _Acquire(self._conn)


class _ConexaoSa:
    async def fetchval(self, query: str) -> int:
        assert query == "SELECT 1"
        return 1


class _ConexaoMorta:
    async def fetchval(self, query: str) -> int:
        raise RuntimeError("pool down")


async def test_deep_health_reporta_a_contagem_do_registry(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(connection, "_pool", _Pool(_ConexaoSa()))

    corpo = (await client.get("/health?deep=1")).json()

    assert corpo["tools"] == len(all_tools())
    assert corpo["tools"] > 0, (
        "o registry veio vazio no ambiente de teste — o guard abaixo estaria "
        "passando por vacuidade, e a asserção derivada não distinguiria "
        "'reportou certo' de 'não há nada para reportar'."
    )


async def test_registry_vazio_degrada_em_vez_de_devolver_200(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App de pé com o MCP não montado é o defeito que este campo existe para pegar.

    Sem isto o `?deep=1` devolveria 200 com `tools: 0`, e o smoke do deploy leria
    sucesso — um verde afirmando mais do que mediu, que é a família do F182/F184/F186.
    """
    monkeypatch.setattr(connection, "_pool", _Pool(_ConexaoSa()))
    monkeypatch.setattr(sys.modules["src.app"], "all_tools", list)

    resposta = await client.get("/health?deep=1")

    assert resposta.status_code == 503
    assert resposta.json()["tools"] == 0
    assert resposta.json()["status"] == "degraded"


async def test_o_campo_existe_mesmo_quando_o_db_falha(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tools` ausente e `tools: 0` não podem ser a mesma coisa para quem lê.

    O consumidor é um `grep` no smoke do deploy. Se o campo sumisse no ramo de DB
    degradado, "não reportou" pareceria "registry vazio" — a confusão exata que o
    F182 (`failed_count` vs `null`) documenta.
    """
    monkeypatch.setattr(connection, "_pool", _Pool(_ConexaoMorta()))

    corpo = (await client.get("/health?deep=1")).json()

    assert corpo["db"] == "error"
    assert corpo["tools"] == len(all_tools())
