"""Data invalida numa tool Google chega ao LLM com a mensagem, nao como "Erro interno".

`resolve_date_window` recusa periodo invalido com `InvalidDateRangeError` (um
`ValueError`): so faltando um dos dois lados, inicio depois do fim, data fora do
formato. Das chamadas dele, so `bulk_pause_by_query` e `update_ad_schedule`
capturavam o erro; nas outras ~21 tools ele subia ate o `_error_envelope`, que so
preserva a mensagem de erro amigavel (F62) — e o LLM recebia "Erro interno ao
executar a ferramenta", sem nada com que se corrigir. Achado na revisao do F196;
zero ocorrencias em 30 dias (medido em 27/09).

O conserto e no envelope, uma vez so, para toda tool. O `ValueError` cru continua
interno: a invariante de `janelas.py` (janela invertida vinda de um preset) e bug
nosso, nao entrada errada de quem chamou.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from uuid import uuid4

import pytest

from src.google_ads.queries._common import InvalidDateRangeError, resolve_date_window
from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.server import _error_envelope
from tests.unit.test_call_tool_valida_schema import _call_tool_do_servidor

_INTERNO = "Erro interno ao executar a ferramenta. O time foi notificado."
_HOJE = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def test_o_envelope_preserva_a_mensagem_do_erro_de_data() -> None:
    env = _error_envelope("get_campaign_performance", InvalidDateRangeError("mensagem util"))
    assert env == {"status": "error", "error_message": "mensagem util"}


def test_value_error_cru_segue_interno() -> None:
    """Controle: so o erro de ENTRADA sai com a mensagem; bug nosso segue scrubado."""
    env = _error_envelope("x", ValueError("janela invertida ou no futuro para 'THIS_MONTH'"))
    assert env["error_message"] == _INTERNO


@pytest.mark.asyncio
async def test_inicio_depois_do_fim_chega_ao_llm_de_ponta_a_ponta() -> None:
    """A tool real, pelo `call_tool` que o servidor registrou: o schema aceita as duas
    datas (formato certo), e quem recusa e o `resolve_date_window` dentro do handler."""
    call_tool = _call_tool_do_servidor()
    (conteudo,) = await call_tool(
        "get_campaign_performance",
        {"customer_id": "1234567890", "start_date": "2026-09-10", "end_date": "2026-09-01"},
    )
    resposta = json.loads(conteudo.text)
    assert resposta["status"] == "error"
    assert resposta["error_message"] != _INTERNO
    assert "start_date (2026-09-10)" in resposta["error_message"]
    assert "end_date (2026-09-01)" in resposta["error_message"]


@pytest.mark.parametrize(
    ("args", "trecho"),
    [
        ({"start_date": "2026-09-10", "end_date": "2026-09-01"}, "depois de end_date"),
        ({"start_date": "2026-09-01", "end_date": None}, "end_date e obrigatorio"),
        ({"start_date": None, "end_date": "2026-09-01"}, "start_date e obrigatorio"),
        ({"start_date": "01/09/2026", "end_date": "2026-09-10"}, "AAAA-MM-DD"),
        ({"date_range": "ONTEM"}, "date_range 'ONTEM' desconhecido"),
    ],
)
def test_cada_recusa_diz_em_portugues_o_que_corrigir(
    args: dict[str, str | None], trecho: str
) -> None:
    with pytest.raises(InvalidDateRangeError) as exc:
        resolve_date_window(
            args.get("date_range"), args.get("start_date"), args.get("end_date"), today=_HOJE
        )
    assert trecho in str(exc.value)
