"""O export CSV do audit tem teto de linhas, e o corte é dito no arquivo (spec 2026-09-28 §3.3.2).

`days` já tinha teto (365, 25/09), mas o resultado não: o cursor server-side ia até a
última linha da janela segurando 1 das 5 conexões do pool pelo download inteiro. Agora a
query pede `teto + 1` (a linha sentinela do F98) e, passando do teto, o arquivo termina
numa marca de CORTE — nunca na de "export completo", que afirmaria o que não é. Medido
em 28/09: 5.795 linhas em 365 dias, então o teto de 50.000 não muda nada hoje.
"""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from structlog.testing import capture_logs

from src.db.repositories import audit_log


def _linha(i: int) -> dict[str, Any]:
    return {
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


class _Cursor:
    def __init__(self, n: int) -> None:
        self.n = n

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gerar()

    async def _gerar(self) -> AsyncIterator[Any]:
        for i in range(self.n):
            yield _linha(i)


class _Conn:
    def __init__(self, n: int) -> None:
        self._n = n
        self.sql = ""
        self.params: tuple[Any, ...] = ()

    def cursor(self, sql: str, *params: Any) -> _Cursor:
        self.sql, self.params = sql, params
        return _Cursor(self._n)

    def transaction(self) -> Any:
        class _T:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *a: Any) -> bool:
                return False

        return _T()


async def _exportar(n: int) -> tuple[str, _Conn, list[dict[str, Any]]]:
    conn = _Conn(n)
    with capture_logs() as logs:
        texto = "".join([x async for x in audit_log.export_csv_rows(conn, days=365)])  # type: ignore[arg-type]
    return texto, conn, logs


@pytest.mark.asyncio
async def test_passando_do_teto_o_arquivo_termina_no_corte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_log, "_TETO_LINHAS_EXPORT", 2, raising=False)
    texto, conn, logs = await _exportar(3)

    assert "a0@v4company.com" in texto and "a1@v4company.com" in texto
    assert "a2@v4company.com" not in texto
    assert "# v4-ads-mcp: EXPORT CORTADO em 2 linhas" in texto
    assert "export completo" not in texto
    assert conn.params[-1] == 3, "a query pede teto + 1: a linha extra é o que revela o corte"
    assert "LIMIT" in conn.sql
    assert any(e["event"] == "audit_export_cortado" for e in logs)


@pytest.mark.asyncio
async def test_no_teto_exato_o_export_e_completo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Controle: exatamente o teto não é corte — a sentinela não veio."""
    monkeypatch.setattr(audit_log, "_TETO_LINHAS_EXPORT", 2, raising=False)
    texto, _, logs = await _exportar(2)

    assert "# v4-ads-mcp: export completo, 2 linhas" in texto
    assert "CORTADO" not in texto
    assert not any(e["event"] == "audit_export_cortado" for e in logs)


def test_o_teto_de_producao_e_50_mil() -> None:
    assert audit_log._TETO_LINHAS_EXPORT == 50_000
