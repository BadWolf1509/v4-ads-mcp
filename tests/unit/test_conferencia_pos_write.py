"""Guard: nenhum pos_check mexe em `efeito` nem em `changed_count` (decisao "Campo proprio").

`efeito` e `changed_count` sao o ACK do Google, o mesmo numero que o `run_mutation`
grava no audit. O veredito da releitura pos-write vai em `conferencia`, campo proprio da
linha. Se um confirmador voltar a rebaixar `efeito` por causa da releitura, a resposta
passa a discordar da trilha de auditoria — e este teste fica vermelho.

Cobre os dois confirmadores que releem depois do write (`_RSA` e
`_AssinaturaRecomendacao`), em divergencia, em acordo e sem leitura.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.mcp.tools import apply_change as mod
from tests.unit import test_apply_change_assinatura as n3
from tests.unit import test_rsa_pinos as g2

_PINADO = g2._UPD_PINADO
_ADS = ["customers/1234567890/ads/1", "customers/1234567890/ads/2"]


@pytest.fixture(autouse=True)
def _ctx():
    from uuid import uuid4

    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _ack_rsa(n: int) -> tuple[list[str], int]:
    """O que o `_wire` do G2 faz o `run_mutation` devolver (e gravar no audit)."""
    return ["mudou"] * n, n


_CENARIOS_RSA = {
    "pino_diverge": ([_PINADO, {"ad_id": "2", "path1": "x"}], [g2._estado("1", {})]),
    "pino_confere": ([_PINADO], [g2._estado("1", {"HEADLINE_1": ["A"]})]),
    "dois_divergem": (
        [_PINADO, {**_PINADO, "ad_id": "2"}],
        [g2._estado("1", {}), g2._estado("2", {"HEADLINE_2": ["A"]})],
    ),
    "nao_lido": ([_PINADO], [g2._estado("1", {}, lidos=False)]),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("cenario", sorted(_CENARIOS_RSA))
async def test_rsa_pos_check_nao_mexe_no_ack(monkeypatch, cenario: str) -> None:
    updates, rows = _CENARIOS_RSA[cenario]
    nomes = _ADS[: len(updates)]
    g2._wire(monkeypatch, op="update_rsa", payload={"updates": updates}, nomes=nomes, rows=rows)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    efeitos, changed = _ack_rsa(len(nomes))
    assert [pf["efeito"] for pf in out["partial_failures"]] == efeitos
    assert out["changed_count"] == changed


@pytest.mark.asyncio
@pytest.mark.parametrize("relido", [["ENABLED"], ["PAUSED"], [], [None]])
async def test_assinatura_pos_check_nao_mexe_no_ack(monkeypatch, relido: list[Any]) -> None:
    n3._wire(monkeypatch, saved=n3._saved("PAUSED"), releitura=relido)
    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    ack = n3._mutacao()
    assert [pf["efeito"] for pf in out["partial_failures"]] == [
        pf["efeito"] for pf in ack["partial_failures"]
    ]
    assert out["changed_count"] == ack["changed_count"]
