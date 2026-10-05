"""`add_negative_keywords` com leitura previa, cobertura e acento (spec 2026-10-05, §3.2).

O que vai ao Google se confere pelo `payload` do `run_mutation` — o lote real, nao a resposta.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "7862230676"
_CAMPANHA = "21359547724"
_MOD = "src.mcp.tools.add_negative_keywords"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _existente(texto: str, tipo: str, cid: str = "1745061730") -> dict[str, str]:
    return {"criterion_id": cid, "text": texto, "match_type": tipo}


async def _chamar(
    existentes: list[dict[str, Any]] | Exception,
    keywords: list[dict[str, str]],
    **extra: Any,
) -> tuple[dict[str, Any], AsyncMock]:
    from src.mcp.tools.add_negative_keywords import add_negative_keywords

    rr = AsyncMock()
    if isinstance(existentes, Exception):
        rr.side_effect = existentes
    else:
        rr.return_value = existentes
    with (
        patch(f"{_MOD}.run_report", rr),
        patch(f"{_MOD}.run_mutation", new_callable=AsyncMock) as rm,
    ):
        rm.return_value = {"applied_count": 1, "provider_request_id": "req", "resource_names": []}
        out = await add_negative_keywords(
            {"customer_id": _CONTA, "campaign_id": _CAMPANHA, "keywords": keywords, **extra}
        )
    return out, rm


def _lote(rm: AsyncMock) -> list[dict[str, str]]:
    return list(rm.await_args.kwargs["payload"]["keywords"])


def test_formatter_le_a_negativa_da_linha_real() -> None:
    from google.ads.googleads.v24.common.types.criteria import KeywordInfo
    from google.ads.googleads.v24.enums.types.keyword_match_type import KeywordMatchTypeEnum
    from google.ads.googleads.v24.resources.types.campaign_criterion import CampaignCriterion
    from google.ads.googleads.v24.services.types.google_ads_service import GoogleAdsRow

    from src.mcp.tools.add_negative_keywords import _negativa_existente

    row = GoogleAdsRow(
        campaign_criterion=CampaignCriterion(
            criterion_id=1745061730,
            keyword=KeywordInfo(
                text="viga metálica", match_type=KeywordMatchTypeEnum.KeywordMatchType.BROAD
            ),
        )
    )
    assert _negativa_existente(row) == {
        "criterion_id": "1745061730",
        "text": "viga metálica",
        "match_type": "BROAD",
    }


async def test_a_leitura_previa_e_da_campanha_pedida() -> None:
    from src.mcp.tools.add_negative_keywords import add_negative_keywords

    with (
        patch(f"{_MOD}.run_report", new_callable=AsyncMock) as rr,
        patch(f"{_MOD}.run_mutation", new_callable=AsyncMock) as rm,
    ):
        rr.return_value = []
        rm.return_value = {"applied_count": 1, "provider_request_id": "r", "resource_names": []}
        await add_negative_keywords(
            {
                "customer_id": _CONTA,
                "campaign_id": _CAMPANHA,
                "keywords": [{"text": "x", "match_type": "BROAD"}],
            }
        )
    q = rr.await_args.kwargs["query"]
    assert f"campaign.id = {_CAMPANHA}" in q and "campaign_criterion.negative = true" in q


async def test_repetida_sai_do_lote_e_vem_em_ja_existia() -> None:
    e = _existente("Patrol", "BROAD")
    out, rm = await _chamar(
        [e], [{"text": "patrol", "match_type": "BROAD"}, {"text": "brita", "match_type": "BROAD"}]
    )
    assert _lote(rm) == [{"text": "brita", "match_type": "BROAD"}]
    assert out["ja_existia"] == [
        {"text": "patrol", "match_type": "BROAD", "existente": e, "origem": "campanha"}
    ]
    assert out["cobertura_verificada"] is True
    assert out["status"] == "applied"


async def test_repetida_dentro_do_proprio_pedido_vai_uma_vez() -> None:
    out, rm = await _chamar(
        [], [{"text": "brita", "match_type": "BROAD"}, {"text": "Brita ", "match_type": "BROAD"}]
    )
    assert _lote(rm) == [{"text": "brita", "match_type": "BROAD"}]
    assert len(out["ja_existia"]) == 1


async def test_nada_a_gravar_nao_chama_o_mutate() -> None:
    out, rm = await _chamar(
        [_existente("brita", "BROAD")], [{"text": "brita", "match_type": "BROAD"}]
    )
    rm.assert_not_awaited()
    assert out["status"] == "no_changes"
    assert out["applied_count"] == 0
    assert len(out["ja_existia"]) == 1


async def test_coberta_e_gravada_e_avisada() -> None:
    ampla = _existente("patrol", "BROAD")
    out, rm = await _chamar([ampla], [{"text": "patrol", "match_type": "PHRASE"}])
    assert _lote(rm) == [{"text": "patrol", "match_type": "PHRASE"}]
    assert out["avisos"] == [
        {"tipo": "coberta", "text": "patrol", "match_type": "PHRASE", "coberta_por": ampla}
    ]


async def test_acentuada_sem_par_e_avisada_com_a_sugestao() -> None:
    out, rm = await _chamar([], [{"text": "material de construção", "match_type": "PHRASE"}])
    assert _lote(rm) == [{"text": "material de construção", "match_type": "PHRASE"}]
    assert out["avisos"] == [
        {
            "tipo": "sem_variante_sem_acento",
            "text": "material de construção",
            "match_type": "PHRASE",
            "sugestao": "material de construcao",
        }
    ]
    assert out["variantes_incluidas"] == []


async def test_opt_in_grava_o_par_sem_acento() -> None:
    out, rm = await _chamar(
        [],
        [{"text": "macaco hidráulico", "match_type": "BROAD"}],
        incluir_variante_sem_acento=True,
    )
    assert _lote(rm) == [
        {"text": "macaco hidráulico", "match_type": "BROAD"},
        {"text": "macaco hidraulico", "match_type": "BROAD"},
    ]
    assert out["variantes_incluidas"] == [
        {"text": "macaco hidraulico", "match_type": "BROAD", "variante_de": "macaco hidráulico"}
    ]
    assert out["avisos"] == []


@pytest.mark.parametrize("onde", ["campanha", "pedido"])
async def test_par_que_ja_existe_nao_gera_aviso_nem_variante(onde: str) -> None:
    par = {"text": "material de construcao", "match_type": "PHRASE"}
    existentes = [_existente(par["text"], "PHRASE")] if onde == "campanha" else []
    pedido = [{"text": "material de construção", "match_type": "PHRASE"}]
    if onde == "pedido":
        pedido.append(par)
    out, rm = await _chamar(existentes, pedido, incluir_variante_sem_acento=True)
    assert out["avisos"] == [] and out["variantes_incluidas"] == []
    assert len(_lote(rm)) == (1 if onde == "campanha" else 2)


async def test_acesso_negado_na_leitura_previa_propaga() -> None:
    from src.google_ads.access import AccountAccessDeniedError

    with pytest.raises(AccountAccessDeniedError):
        await _chamar(
            AccountAccessDeniedError("sem acesso"), [{"text": "x", "match_type": "BROAD"}]
        )


async def test_falha_amigavel_grava_sem_conferir_e_diz_o_motivo() -> None:
    from src.governance.rate_limit import QuotaExhausted

    out, rm = await _chamar(
        QuotaExhausted("cota diaria esgotada"), [{"text": "brita", "match_type": "BROAD"}]
    )
    assert _lote(rm) == [{"text": "brita", "match_type": "BROAD"}]
    assert out["cobertura_verificada"] is False
    assert "cota diaria esgotada" in out["cobertura_motivo"]


async def test_falha_interna_nao_vaza_a_mensagem() -> None:
    from src.mcp.tools.add_negative_keywords import _MOTIVO_LEITURA_FALHOU

    out, rm = await _chamar(
        ConnectionRefusedError("connect failed ('10.8.0.5', 5432)"),
        [{"text": "brita", "match_type": "BROAD"}],
    )
    rm.assert_awaited_once()
    assert out["cobertura_verificada"] is False
    assert out["cobertura_motivo"] == _MOTIVO_LEITURA_FALHOU


async def test_leitura_bem_sucedida_nao_traz_motivo() -> None:
    out, _ = await _chamar([], [{"text": "brita", "match_type": "BROAD"}])
    assert "cobertura_motivo" not in out


def test_description_diz_o_contrato() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    t = get_tool("add_negative_keywords")
    assert t is not None
    d = t.description
    for ancora in (
        "NAO aplica variante proxima em negativa",
        "ja_existia",
        "avisos",
        "incluir_variante_sem_acento",
        "variantes_incluidas",
        "Plural e erro de digitacao NAO sao tratados",
        "cobertura_verificada: false",
        "no_changes",
    ):
        assert ancora in d, ancora
    assert "incluir_variante_sem_acento" in t.input_schema["properties"]
