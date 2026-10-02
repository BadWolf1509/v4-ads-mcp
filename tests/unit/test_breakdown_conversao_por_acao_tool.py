"""A tool `get_performance_breakdown` com `breakdown='conversion_action'` (spec 2026-10-02, §3.1).

As flags de cada ação vêm do recurso `conversion_action`, numa segunda consulta só com as
ações das linhas devolvidas. A que esse recurso não devolve — medido em 02/10: "Conversation
started" (`7028680990`), 173 conversões em setembro e zero linhas em `conversion_action` —
fica com flag `null` e motivo: ausência de medição não é `false` (F191).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current

_CONTA = "7862230676"


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _acao(aid: str, nome: str, conv: float, todas: float) -> dict[str, Any]:
    return {
        "conversion_action_id": aid,
        "conversion_action_name": nome,
        "categoria": "CONTACT",
        "conversions": conv,
        "all_conversions": todas,
        "conversions_value_brl": conv,
        "all_conversions_value_brl": todas,
    }


def _flag(aid: str, conta: bool | None, primaria: bool | None) -> dict[str, Any]:
    """O formato que `_flag_da_acao` devolve — sem campo que o formatter real nao produz."""
    return {
        "conversion_action_id": aid,
        "include_in_conversions_metric": conta,
        "primary_for_goal": primaria,
    }


async def _chamar(respostas: list[list[dict[str, Any]]], **args: Any) -> tuple[Any, AsyncMock]:
    from src.mcp.tools.get_performance_breakdown import get_performance_breakdown

    with (
        patch("src.mcp.tools.get_performance_breakdown.run_report", new_callable=AsyncMock) as rr,
        patch(
            "src.mcp.tools.get_performance_breakdown.resolve_account_today",
            new_callable=AsyncMock,
        ) as hoje,
    ):
        from datetime import date

        hoje.return_value = date(2026, 10, 2)
        rr.side_effect = respostas
        out = await get_performance_breakdown(
            {"customer_id": _CONTA, "level": "account", "breakdown": "conversion_action", **args}
        )
    return out, rr


_LINHAS = [
    _acao("6827189000", "Whatsapp - JPA", 204.0, 204.0),
    _acao("7028680990", "Conversation started", 173.0, 173.0),
    _acao("6826176642", "Clicks to call", 0.0, 11.0),
]


async def test_flags_vem_do_recurso_e_a_acao_ausente_fica_null_com_motivo() -> None:
    out, rr = await _chamar(
        [_LINHAS, [_flag("6827189000", True, True), _flag("6826176642", False, True)]]
    )
    por_id = {r["conversion_action_id"]: r for r in out["rows"]}
    assert por_id["6827189000"]["conta_em_conversoes"] is True
    assert por_id["6827189000"]["primary_for_goal"] is True
    assert por_id["6827189000"]["flags_motivo"] is None
    assert por_id["6826176642"]["conta_em_conversoes"] is False
    assert por_id["6826176642"]["primary_for_goal"] is True
    ausente = por_id["7028680990"]
    assert ausente["conta_em_conversoes"] is None
    assert ausente["primary_for_goal"] is None
    assert "conversion_action" in ausente["flags_motivo"]
    flags = rr.await_args_list[1].kwargs["query"]
    assert "conversion_action.id IN (6827189000, 7028680990, 6826176642)" in flags


async def test_corte_antes_das_flags_e_truncated() -> None:
    out, rr = await _chamar([_LINHAS, [_flag("6827189000", True, True)]], limit=2)
    assert out["truncated"] is True
    assert [r["conversion_action_id"] for r in out["rows"]] == ["6827189000", "7028680990"]
    # a sentinela (a 3a linha) nao entra na consulta das flags
    assert "6826176642" not in rr.await_args_list[1].kwargs["query"]


async def test_sem_linha_nao_roda_a_consulta_das_flags() -> None:
    out, rr = await _chamar([[]])
    assert out["rows"] == []
    assert rr.await_count == 1


async def test_filters_applied_e_period_do_recorte() -> None:
    out, rr = await _chamar([_LINHAS[:1], [_flag("6827189000", True, True)]])
    assert out["filters_applied"]["date_range"] == {"start": "2026-09-02", "end": "2026-10-01"}
    assert "FROM customer" in rr.await_args_list[0].kwargs["query"]


def _description() -> str:
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool("get_performance_breakdown")
    assert tool is not None
    return tool.description


def test_description_diz_os_dois_contratos() -> None:
    d = _description()
    assert "conversion_action" in d
    assert "conta_em_conversoes" in d and "all_conversions" in d
    assert "flags_motivo" in d
    assert "sem custo" in d.lower()


def test_description_nao_generaliza_a_flag_da_conta_para_a_campanha() -> None:
    """Revisao final I2: `include_in_conversions_metric` segue as metas PADRAO da conta (medido
    na conta, spec §2). Campanha com meta propria conta em `conversions` as acoes da meta dela —
    a description nao pode afirmar a regra da conta para a linha campanha x acao."""
    d = _description().replace("`", "")
    assert "metas padrao da conta" in d
    # a regra medida (spec §2) so aparece amarrada ao recorte da conta
    assert "no recorte da conta, conversions soma so as acoes com conta_em_conversoes=true" in d
    assert d.count("conta_em_conversoes=true") == 1
    # a campanha com meta propria nunca foi medida (re-revisao N3): indica, nao afirma
    assert "meta propria" in d and "indica" in d and "nao medido" in d


def test_description_diz_que_status_so_filtra_em_campanha() -> None:
    """Re-revisao (t3-t4 M3 parcial): em account o `status` e ignorado sem aviso."""
    assert "status filtra so em level=campaign" in _description().replace("`", "")


def test_cabeca_da_description_lista_o_recorte_novo_e_a_ordem_dele() -> None:
    """Revisao final M1: a matriz da cabeca e o 'cortada no topo de gasto' valiam para tudo."""
    d = _description()
    assert "account+breakdown (device|geo|hourly|conversion_action)" in d
    assert "cortada no topo de gasto" not in d
    assert "no topo da ordenacao" in d


def test_parcela_so_nas_linhas_de_campanha_sem_breakdown() -> None:
    """Revisao final M2: campaign+hourly e campaign+conversion_action nao trazem a parcela."""
    assert "level='campaign' sem breakdown trazem a parcela" in _description()


def test_limit_em_campanha_conta_pares() -> None:
    """Revisao t3-t4 M3: no nivel campaign o limit e o truncated valem por par campanha x acao."""
    assert "par campanha x acao" in _description()


def test_schema_diz_onde_vale_cada_breakdown_e_que_campaign_ids_e_ignorado() -> None:
    """Revisao final M4."""
    from src.mcp.tools.get_performance_breakdown import _SCHEMA

    props = _SCHEMA["properties"]
    assert (
        "device/geo/hourly/conversion_action em level=account" in props["breakdown"]["description"]
    )
    assert "campaign+conversion_action" in props["campaign_ids"]["description"]


# --- o formatter real das flags (revisao t3-t4 I2 = final I1) -----------------------------
# Os testes acima mockam o `run_report` inteiro, entao o formatter nunca rodava. Aqui ele roda
# sobre a mensagem REAL do SDK: as duas flags sao `optional` no v24, e o atributo de campo
# ausente le `False` — o falso que a spec §3.1 proibe.


def _row_real(**campos: Any) -> Any:
    from google.ads.googleads.v24.resources.types.conversion_action import ConversionAction
    from google.ads.googleads.v24.services.types.google_ads_service import GoogleAdsRow

    return GoogleAdsRow(conversion_action=ConversionAction(id=6826176642, **campos))


def test_formatter_le_as_flags_por_presenca() -> None:
    from src.mcp.tools.get_performance_breakdown import _flag_da_acao

    setadas = _flag_da_acao(_row_real(include_in_conversions_metric=False, primary_for_goal=True))
    assert setadas == {
        "conversion_action_id": "6826176642",
        "include_in_conversions_metric": False,
        "primary_for_goal": True,
    }
    vazia = _row_real()
    assert vazia.conversion_action.primary_for_goal is False  # o falso que o atributo daria
    lida = _flag_da_acao(vazia)
    assert lida["include_in_conversions_metric"] is None
    assert lida["primary_for_goal"] is None


async def test_flag_nao_informada_fica_null_com_motivo_proprio() -> None:
    from src.mcp.tools.get_performance_breakdown import (
        _MOTIVO_FLAG_NAO_INFORMADA,
        _MOTIVO_SEM_FLAG,
    )

    out, _ = await _chamar([_LINHAS[2:], [_flag("6826176642", False, None)]])
    r = out["rows"][0]
    assert r["conta_em_conversoes"] is False  # a medida que veio continua valendo
    assert r["primary_for_goal"] is None
    assert r["flags_motivo"] == _MOTIVO_FLAG_NAO_INFORMADA
    assert _MOTIVO_FLAG_NAO_INFORMADA != _MOTIVO_SEM_FLAG


# --- a consulta das flags nunca derruba a resposta (revisao t3-t4 I1 + final M5) -----------


async def test_id_nao_numerico_nao_vai_a_consulta_e_fica_null() -> None:
    from src.mcp.tools.get_performance_breakdown import _MOTIVO_ID_FORA_DA_CONSULTA

    linhas = [_LINHAS[0], _acao("", "sem recurso", 1.0, 1.0)]
    out, rr = await _chamar([linhas, [_flag("6827189000", True, True)]])
    assert "conversion_action.id IN (6827189000)" in rr.await_args_list[1].kwargs["query"]
    sem_id = out["rows"][1]
    assert sem_id["conta_em_conversoes"] is None
    assert sem_id["flags_motivo"] == _MOTIVO_ID_FORA_DA_CONSULTA
    assert out["rows"][0]["conta_em_conversoes"] is True


async def test_acima_de_1000_acoes_a_consulta_leva_as_1000_primeiras() -> None:
    import re

    from src.mcp.tools.get_performance_breakdown import _MOTIVO_ID_FORA_DA_CONSULTA

    linhas = [_acao(str(10_000 + i), f"a{i}", 1.0, 1.0) for i in range(1001)]
    out, rr = await _chamar([linhas, []], limit=2000)
    consulta = rr.await_args_list[1].kwargs["query"]
    lista = re.search(r"IN \(([^)]*)\)", consulta)
    assert lista is not None
    assert lista.group(1).split(", ") == [str(10_000 + i) for i in range(1000)]
    assert out["rows"][-1]["flags_motivo"] == _MOTIVO_ID_FORA_DA_CONSULTA
    assert len(out["rows"]) == 1001


async def test_falha_interna_da_consulta_nao_vaza_a_mensagem() -> None:
    """Re-revisao N1: o texto de erro cru (host do banco, SQL, driver) nao chega ao gestor —
    o mesmo scrub do `_error_envelope` do servidor. O motivo e fixo."""
    from src.mcp.tools.get_performance_breakdown import _MOTIVO_CONSULTA_FALHOU

    erro = ConnectionRefusedError("connect failed ('10.8.0.5', 5432)")
    out, _ = await _chamar([_LINHAS, erro])
    assert [r["conversion_action_id"] for r in out["rows"]] == [
        "6827189000",
        "7028680990",
        "6826176642",
    ]
    for r in out["rows"]:
        assert r["conta_em_conversoes"] is None
        assert r["primary_for_goal"] is None
        assert r["flags_motivo"] == _MOTIVO_CONSULTA_FALHOU
        assert "10.8.0.5" not in r["flags_motivo"]


async def test_falha_amigavel_da_consulta_leva_a_mensagem_pt_br() -> None:
    """Erro amigavel (Google em PT-BR, quota) foi escrito para o gestor: ele vai no motivo."""
    from src.governance.rate_limit import QuotaExhausted
    from src.mcp.tools.get_performance_breakdown import _MOTIVO_CONSULTA_FALHOU

    out, _ = await _chamar([_LINHAS[:1], QuotaExhausted("cota diaria esgotada")])
    r = out["rows"][0]
    assert r["flags_motivo"].startswith(_MOTIVO_CONSULTA_FALHOU)
    assert "cota diaria esgotada" in r["flags_motivo"]


async def test_acesso_negado_na_consulta_das_flags_propaga() -> None:
    """Acesso negado nao e flag desconhecida: o envelope do servidor responde `denied`."""
    from src.google_ads.access import AccountAccessDeniedError

    with pytest.raises(AccountAccessDeniedError):
        await _chamar([_LINHAS[:1], AccountAccessDeniedError("sem acesso")])


async def test_falha_so_marca_as_linhas_consultadas() -> None:
    """Re-revisao N2: id invalido nunca foi consultado — o motivo dele e o seu, nao a falha."""
    from src.mcp.tools.get_performance_breakdown import (
        _MOTIVO_CONSULTA_FALHOU,
        _MOTIVO_ID_FORA_DA_CONSULTA,
    )

    linhas = [_LINHAS[0], _acao("", "sem recurso", 1.0, 1.0)]
    out, _ = await _chamar([linhas, RuntimeError("x")])
    assert out["rows"][0]["flags_motivo"] == _MOTIVO_CONSULTA_FALHOU
    assert out["rows"][1]["flags_motivo"] == _MOTIVO_ID_FORA_DA_CONSULTA


# --- level='campaign' (revisao t3-t4 M2) ---------------------------------------------------


async def test_campanha_mesma_acao_em_duas_campanhas_recebe_a_flag_nas_duas() -> None:
    def _na(cid: str, aid: str, todas: float) -> dict[str, Any]:
        return {**_acao(aid, "x", todas, todas), "campaign_id": cid, "campaign_name": cid}

    linhas = [
        _na("1", "6827189000", 50.0),
        _na("2", "6827189000", 40.0),
        _na("1", "6826176642", 30.0),  # sentinela com limit=2
    ]
    out, rr = await _chamar([linhas, [_flag("6827189000", True, True)]], level="campaign", limit=2)
    assert out["truncated"] is True
    assert [(r["campaign_id"], r["conta_em_conversoes"]) for r in out["rows"]] == [
        ("1", True),
        ("2", True),
    ]
    assert "conversion_action.id IN (6827189000)" in rr.await_args_list[1].kwargs["query"]
    assert "FROM campaign" in rr.await_args_list[0].kwargs["query"]
