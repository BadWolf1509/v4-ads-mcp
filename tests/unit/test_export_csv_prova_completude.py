"""Um CSV truncado nao pode ser indistinguivel de um CSV curto."""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from src.db.repositories import audit_log

MARCA_OK = "# v4-ads-mcp: export completo"
MARCA_RUIM = "# v4-ads-mcp: EXPORT INCOMPLETO"


class _CursorQueExplode:
    def __init__(self, ate: int) -> None:
        self.ate = ate

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gerar()

    async def _gerar(self) -> AsyncIterator[Any]:
        for i in range(self.ate):
            yield {
                "occurred_at": None,
                "email": f"a{i}@v4company.com",
                "operation": "op",
                "customer_id": "1",
                "action_type": "read",
                "status": "success",
                "target_count": None,
                "duration_ms": None,
                "error_message": None,
                "provider_request_id": None,
            }
        raise ConnectionError("conexao caiu no meio do cursor")


class _ConnFake:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def cursor(self, *_a: Any, **_k: Any) -> Any:
        return self._cursor

    def transaction(self) -> Any:
        class _T:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *a: Any) -> bool:
                return False

        return _T()


@pytest.mark.asyncio
async def test_falha_no_meio_marca_o_arquivo() -> None:
    """Consumo manual, nao list-comprehension.

    Um gerador async que da `yield` dentro do `except` e depois um `raise` nu
    so levanta essa excecao na chamada SEGUINTE de `__anext__` — ou seja,
    DEPOIS que a linha-sentinela ja foi entregue. Um `[x async for x in
    gen()]` nao tem como capturar isso: a excecao escapa da propria
    list-comprehension e a lista nunca e atribuida, entao a marca de erro
    nunca chega a ser inspecionada (confirmado empiricamente com um gerador
    minimo fora da suite antes deste ajuste). `pytest.raises` ao redor de um
    `async for` manual acumula o que foi entregue ATE a excecao — e de
    quebra confere que o `raise` do gerador REALMENTE sobrevive ate o
    chamador (preserva log/traceback do lado do servidor), coisa que a
    list-comprehension original nunca teria testado.
    """
    conn = _ConnFake(_CursorQueExplode(ate=3))
    linhas: list[str] = []
    with pytest.raises(ConnectionError):
        async for linha in audit_log.export_csv_rows(conn, days=7):
            linhas.append(linha)
    texto = "".join(linhas)
    assert MARCA_RUIM in texto, (
        "CSV cortado no meio e sintaticamente valido: sem marca, e "
        "indistinguivel de um export que achou poucas linhas"
    )
    assert MARCA_OK not in texto


@pytest.mark.asyncio
async def test_caminho_feliz_marca_completude() -> None:
    """CONTROLE POSITIVO. Sem ele, uma implementacao que NUNCA emite a marca de
    sucesso passa no teste de cima — e ai a ausencia da marca deixa de
    significar "incompleto", porque ela nunca esta la."""

    class _CursorOk:
        def __aiter__(self) -> AsyncIterator[Any]:
            return self._gerar()

        async def _gerar(self) -> AsyncIterator[Any]:
            for i in range(2):
                yield {
                    "occurred_at": None,
                    "email": f"a{i}@v4company.com",
                    "operation": "op",
                    "customer_id": "1",
                    "action_type": "read",
                    "status": "success",
                    "target_count": None,
                    "duration_ms": None,
                    "error_message": None,
                    "provider_request_id": None,
                }

    conn = _ConnFake(_CursorOk())
    texto = "".join([linha async for linha in audit_log.export_csv_rows(conn, days=7)])
    assert f"{MARCA_OK}, 2 linhas" in texto
    assert MARCA_RUIM not in texto
