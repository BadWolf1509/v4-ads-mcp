"""Rodada da revisão final da frente negativas + `run_gaql` compacto (05/10).

Cada teste nomeia o achado (I1, M1...) do `revisao-final.md` da frente.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from google.protobuf.json_format import MessageToDict

from src.mcp.context import McpRequestContext, clear_current, set_current

# --- negativas.py --------------------------------------------------------------------------


def test_m1_chave_iguala_nfd_e_nfc() -> None:
    from src.google_ads.negativas import chave, classificar

    nfd = unicodedata.normalize("NFD", "construção")
    assert nfd != "construção"
    assert chave(nfd) == chave("construção")
    existente = {"text": "construção", "match_type": "BROAD"}
    assert classificar({"text": nfd, "match_type": "BROAD"}, [existente])[0] == "repetida"


def test_m6_match_type_desconhecido_nao_derruba() -> None:
    from src.google_ads.negativas import classificar

    existente = {"text": "x", "match_type": "UNKNOWN"}
    assert classificar({"text": "x", "match_type": "PHRASE"}, [existente]) == ("nova", None)


# --- add_negative_keywords -----------------------------------------------------------------

_MOD = "src.mcp.tools.add_negative_keywords"


@pytest.fixture
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


async def _ank(
    existentes: list[dict[str, Any]] | Exception, keywords: list[dict[str, str]], **extra: Any
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
        rm.return_value = {"applied_count": 1, "provider_request_id": "r", "resource_names": []}
        out = await add_negative_keywords(
            {"customer_id": "7862230676", "campaign_id": "1", "keywords": keywords, **extra}
        )
    return out, rm


@pytest.mark.usefixtures("_ctx")
@pytest.mark.parametrize("ordem", [("PHRASE", "BROAD"), ("BROAD", "PHRASE")])
async def test_m3_cobertura_no_pedido_nao_depende_da_ordem(ordem: tuple[str, str]) -> None:
    out, _ = await _ank([], [{"text": "x", "match_type": t} for t in ordem])
    cobertas = [a for a in out["avisos"] if a["tipo"] == "coberta"]
    assert [(a["match_type"], a["coberta_por"]["match_type"]) for a in cobertas] == [
        ("PHRASE", "BROAD")
    ]


@pytest.mark.usefixtures("_ctx")
async def test_m4_aviso_de_acento_nao_duplica() -> None:
    kw = {"text": "construção", "match_type": "BROAD"}
    out, _ = await _ank([], [kw, dict(kw)])
    assert len([a for a in out["avisos"] if a["tipo"] == "sem_variante_sem_acento"]) == 1


@pytest.mark.usefixtures("_ctx")
async def test_m5_ja_existia_diz_a_origem() -> None:
    e = {"criterion_id": "9", "text": "brita", "match_type": "BROAD"}
    out, _ = await _ank(
        [e],
        [
            {"text": "brita", "match_type": "BROAD"},
            {"text": "areia", "match_type": "BROAD"},
            {"text": "areia", "match_type": "BROAD"},
        ],
    )
    assert [(j["text"], j["origem"]) for j in out["ja_existia"]] == [
        ("brita", "campanha"),
        ("areia", "pedido"),
    ]


@pytest.mark.usefixtures("_ctx")
async def test_m7_erro_amigavel_do_google_grava_com_a_mensagem() -> None:
    from src.google_ads.errors import GoogleAdsFriendlyError

    out, rm = await _ank(
        GoogleAdsFriendlyError("Conta sem permissao de leitura no Google."),
        [{"text": "brita", "match_type": "BROAD"}],
    )
    rm.assert_awaited_once()
    assert out["cobertura_verificada"] is False
    assert "Conta sem permissao de leitura no Google." in out["cobertura_motivo"]


def test_m2_description_diz_que_o_opt_in_pode_dobrar_o_lote() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    for nome in ("add_negative_keywords", "add_negatives_from_search_terms"):
        t = get_tool(nome)
        assert t is not None
        assert "pode dobrar o lote" in t.description, nome


# --- add_negatives_from_search_terms -------------------------------------------------------

_MOD_ST = "src.mcp.tools.add_negatives_from_search_terms"


async def _st(negatives: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    from src.mcp.tools.add_negatives_from_search_terms import add_negatives_from_search_terms

    with patch(f"{_MOD_ST}.run_mutation", new_callable=AsyncMock) as rm:
        rm.return_value = {"applied_count": 2, "provider_request_id": "r", "partial_failures": []}
        return await add_negatives_from_search_terms(
            {"customer_id": "7862230676", "negatives": negatives, **extra}
        )


def _n(termo: str) -> dict[str, str]:
    return {"search_term": termo, "match_type": "PHRASE", "scope": "campaign", "scope_id": "1"}


@pytest.mark.usefixtures("_ctx")
async def test_m4_search_terms_aviso_nao_duplica() -> None:
    out = await _st([_n("construção"), _n("construção")])
    assert len(out["avisos"]) == 1


@pytest.mark.usefixtures("_ctx")
async def test_m10_blast_summary_separa_as_variantes() -> None:
    out = await _st([_n("construção")], incluir_variante_sem_acento=True)
    assert "1 negativa(s) derivada(s) do search_terms_report" in out["blast_summary"]
    assert "1 variante(s) sem acento" in out["blast_summary"]


def test_i2_description_nao_promete_already_exists() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    t = get_tool("add_negatives_from_search_terms")
    assert t is not None
    assert "descarta em silencio" in t.description
    assert "termos ja existentes retornam status" not in t.description


# --- run_gaql compact ----------------------------------------------------------------------


def _change_event(vazio: bool = False) -> dict[str, Any]:
    from google.ads.googleads.v24.resources.types.campaign import Campaign
    from google.ads.googleads.v24.resources.types.change_event import ChangeEvent
    from google.ads.googleads.v24.services.types.google_ads_service import GoogleAdsRow

    antigo = (
        ChangeEvent.ChangedResource()
        if vazio
        else ChangeEvent.ChangedResource(
            campaign=Campaign(resource_name="customers/1/campaigns/2", id=2)
        )
    )
    row = GoogleAdsRow(
        change_event=ChangeEvent(resource_name="customers/1/changeEvents/x", old_resource=antigo)
    )
    return MessageToDict(row._pb, preserving_proto_field_name=True)  # type: ignore[no-any-return]


def test_i1_resource_name_dentro_de_campo_pedido_fica() -> None:
    from src.google_ads.gaql_compacto import campos_do_select, linha_compacta

    pedidos = campos_do_select("SELECT change_event.old_resource FROM change_event")
    plana = linha_compacta(_change_event(), pedidos)
    assert plana["change_event.old_resource.campaign.resource_name"] == "customers/1/campaigns/2"
    assert "change_event.resource_name" not in plana


def test_m8_campo_mensagem_vazio_pedido_fica() -> None:
    from src.google_ads.gaql_compacto import campos_do_select, linha_compacta

    pedidos = campos_do_select("SELECT change_event.old_resource FROM change_event")
    assert linha_compacta(_change_event(vazio=True), pedidos) == {"change_event.old_resource": {}}


def test_m9_description_diz_amostra_de_linhas() -> None:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    t = get_tool("run_gaql")
    assert t is not None
    assert "numa amostra de linhas de campaign_criterion" in t.description


# --- re-revisão da rodada (05/10) ----------------------------------------------------------


@pytest.mark.usefixtures("_ctx")
async def test_n1_variante_do_opt_in_entra_na_cobertura() -> None:
    out, _ = await _ank(
        [],
        [
            {"text": "construcao", "match_type": "EXACT"},
            {"text": "construção", "match_type": "BROAD"},
        ],
        incluir_variante_sem_acento=True,
    )
    cobertas = [(a["text"], a["match_type"]) for a in out["avisos"] if a["tipo"] == "coberta"]
    assert cobertas == [("construcao", "EXACT")]


def test_n2_prefixo_do_campo_pedido_nao_casa_vizinho_de_nome() -> None:
    from src.google_ads.gaql_compacto import linha_compacta

    linha = {"campaign": {"resource_name": "c"}, "campaign_budget": {"resource_name": "b"}}
    assert linha_compacta(linha, {"campaign"}) == {"campaign.resource_name": "c"}
