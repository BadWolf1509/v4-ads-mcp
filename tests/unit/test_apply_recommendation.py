"""apply_recommendation (C2): recomendacao de orcamento/lance passa a exigir confirmacao.

Ate 2026-09-07 a tool computava `classify(...)` e chamava
`run_recommendation_action` na linha seguinte: `risk.level` nao era lido em lugar
nenhum e `risk.reason` virava o campo cosmetico `auto_applied_reason` (F112 no
pior caso). Como `blast_radius` classificava `apply_recommendation` como AUTO,
uma chamada so aplicava qualquer recomendacao — inclusive as de orcamento.

Medido em 07/09 na conta `1171969590` (Montes Claros), campanha `22922100363`:
`CAMPAIGN_BUDGET` viva com `current_budget_amount_micros: 50000000` e
`recommended_budget_amount_micros: 180000000` — R$ 50,00 -> R$ 180,00, 3,6x, sem
token, sem preview e sem nunca mostrar o numero. O mesmo efeito pelo
`update_campaign_budget` sempre exigiu confirmacao: duas portas, governanca
oposta.

**Por que os fakes daqui montam a row com o proto de verdade:** proto-plus nunca
omite atributo — campo que a GAQL nao pediu chega com o zero-value, nao com erro
(F145). Um fake que devolvesse dicts prontos passaria verde com o campo de
detalhe FORA do SELECT. Aqui a row e um `Recommendation()` real onde so os campos
que o SELECT pediu sao setados; tirar `recommendation.campaign_budget_recommendation`
da query faz os valores virarem 0.0 e o teste fica vermelho.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from google.ads.googleads.v24.enums.types.recommendation_type import RecommendationTypeEnum
from google.ads.googleads.v24.resources.types.recommendation import Recommendation

from src.db import connection
from src.google_ads.queries.recommendations import CAMPOS_DE_DETALHE, TIPOS_QUE_CONFIRMAM
from src.mcp.tools import apply_recommendation as mod

_CUSTOMER = "1171969590"
_CAMPANHA_ID = "22922100363"
_CAMPANHA_RN = f"customers/{_CUSTOMER}/campaigns/{_CAMPANHA_ID}"
_REC_RN = f"customers/{_CUSTOMER}/recommendations/NzMyNjkxNjcxNC0xMDAtMTc4ODcxMDQ2NDg4My0"

# A lista dos 18 e LITERAL de proposito. Parametrizar sobre
# `TIPOS_QUE_CONFIRMAM` faria a sabotagem "tirar um tipo da whitelist" APAGAR o
# caso de teste em vez de deixa-lo vermelho — o modo de falha que o CLAUDE.md
# chama de "asserir o adjacente".
#
# Estes nomes vieram do PROTO (`v24/resources/types/recommendation.py`), campo a
# campo, e nao de um grep do enum — o I2 da revisao da Task 2 mostrou que o grep
# por nome (`BUDGET|BID|TARGET_CPA|...`) deixava o `USE_BROAD_MATCH_KEYWORD` de
# fora, que converte TODAS as keywords da campanha para ampla e declara o mesmo
# `required_campaign_budget_amount_micros` do `TARGET_ROAS_OPT_IN`. O criterio
# completo e a varredura que o refaz vivem em
# `test_whitelist_de_recomendacao_bate_com_o_proto.py`.
_OS_DEZOITO = (
    "CAMPAIGN_BUDGET",
    "FORECASTING_CAMPAIGN_BUDGET",
    "MARGINAL_ROI_CAMPAIGN_BUDGET",
    "MOVE_UNUSED_BUDGET",
    "ENHANCED_CPC_OPT_IN",
    "MAXIMIZE_CLICKS_OPT_IN",
    "MAXIMIZE_CONVERSIONS_OPT_IN",
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN",
    "TARGET_CPA_OPT_IN",
    "TARGET_ROAS_OPT_IN",
    "SET_TARGET_CPA",
    "SET_TARGET_ROAS",
    "RAISE_TARGET_CPA",
    "RAISE_TARGET_CPA_BID_TOO_LOW",
    "LOWER_TARGET_ROAS",
    "FORECASTING_SET_TARGET_CPA",
    "FORECASTING_SET_TARGET_ROAS",
    "USE_BROAD_MATCH_KEYWORD",
)

# Numero de enum que o v24 nao conhece — o tipo que o Google lancar amanha.
# proto-plus aceita o int, avisa por `UserWarning`, e `_nome_do_enum` devolve a
# string crua "999".
_TIPO_QUE_O_SDK_NAO_CONHECE = "999"


# --------------------------------------------------------------------------- #
# Fakes: a row sai do proto real, e so o que o SELECT pediu e setado nela.
# --------------------------------------------------------------------------- #
def _campos_do_select(query: str) -> set[str]:
    m = re.search(r"\bSELECT\b(.+?)\bFROM\b", query, re.S | re.I)
    assert m is not None, f"GAQL sem SELECT..FROM: {query!r}"
    return {c.strip() for c in m.group(1).split(",") if c.strip()}


def _setar(msg: Any, caminho: str, valor: Any) -> None:
    partes = caminho.split(".")
    for parte in partes[:-1]:
        msg = getattr(msg, parte)
    setattr(msg, partes[-1], valor)


# Valores-sentinela por unidade. Nao sao "o valor real do Google" — sao valores
# distinguiveis do zero-value, que e o ponto: se o campo sair do SELECT, o que
# chega e 0 e a asserção cai.
_SENTINELA = {
    "brl": 77_000_000,
    "razao": 4_500_000,
    "numero": 1.35,
    "inteiro": 120,
    "booleano": True,
    "texto": "customers/1/x",
}


def _linha_de_recomendacao(query: str, tipo: str, *, atual: int, recomendado: int) -> Any:
    pedidos = _campos_do_select(query)
    rec = Recommendation()
    if "recommendation.type" in pedidos:
        membros = RecommendationTypeEnum.RecommendationType.__members__
        rec.type_ = membros[tipo] if tipo in membros else int(tipo)
    if "recommendation.resource_name" in pedidos:
        rec.resource_name = _REC_RN
    if "recommendation.campaign" in pedidos:
        rec.campaign = _CAMPANHA_RN

    spec = CAMPOS_DE_DETALHE.get(tipo)
    if spec is not None and f"recommendation.{spec.campo}" in pedidos:
        detalhe = getattr(rec, spec.campo)
        if spec.atual_brl is not None:
            _setar(detalhe, spec.atual_brl, atual)
        if spec.recomendado_brl is not None:
            _setar(detalhe, spec.recomendado_brl, recomendado)
        for _chave, caminho, unidade in spec.outros:
            _setar(detalhe, caminho, _SENTINELA[unidade])
    return SimpleNamespace(recommendation=rec)


def _linha_de_campanha(query: str) -> Any:
    pedidos = _campos_do_select(query)
    campaign = SimpleNamespace(
        id=int(_CAMPANHA_ID) if "campaign.id" in pedidos else 0,
        name="[CP] [MDO MONTES CLAROS] [PESQUISA]" if "campaign.name" in pedidos else "",
        status="ENABLED" if "campaign.status" in pedidos else "UNSPECIFIED",
        bidding_strategy_type=(
            "MAXIMIZE_CONVERSIONS" if "campaign.bidding_strategy_type" in pedidos else "UNSPECIFIED"
        ),
    )
    budget = SimpleNamespace(
        amount_micros=50_000_000 if "campaign_budget.amount_micros" in pedidos else 0
    )
    return SimpleNamespace(campaign=campaign, campaign_budget=budget)


class _FakeConn:
    async def __aenter__(self) -> _FakeConn:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False


class _FakePool:
    def acquire(self) -> _FakeConn:
        return _FakeConn()


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tipo: str,
    atual: int = 50_000_000,
    recomendado: int = 180_000_000,
    sem_recomendacao: bool = False,
) -> dict[str, Any]:
    capturado: dict[str, Any] = {"queries": [], "aplicou": False}

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q: str = kwargs["query"]
        fmt = kwargs["row_formatter"]
        capturado["queries"].append(q)
        if "FROM campaign" in q:
            return [fmt(_linha_de_campanha(q))]
        if sem_recomendacao:
            return []
        return [fmt(_linha_de_recomendacao(q, tipo, atual=atual, recomendado=recomendado))]

    async def _executar(**kwargs: Any) -> dict[str, Any]:
        capturado["aplicou"] = True
        capturado["payload"] = kwargs["payload"]
        return {"applied_count": 1, "provider_request_id": "req-fake"}

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        capturado.update(kwargs)
        return "TOKEN123"

    monkeypatch.setattr(mod, "run_report", _run)
    monkeypatch.setattr(mod, "run_recommendation_action", _executar)
    monkeypatch.setattr(mod, "create_pending", _create_pending)
    monkeypatch.setattr(connection, "get_pool", lambda: _FakePool())
    return capturado


@pytest.fixture(autouse=True)
def _ctx() -> Any:
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


async def _aplicar(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tipo: str,
    atual: int = 50_000_000,
    recomendado: int = 180_000_000,
) -> dict[str, Any]:
    _wire(monkeypatch, tipo=tipo, atual=atual, recomendado=recomendado)
    envelope: dict[str, Any] = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    return envelope


# --------------------------------------------------------------------------- #
# 1. Orcamento exige confirmacao E mostra o numero.
# --------------------------------------------------------------------------- #
async def test_recomendacao_de_orcamento_exige_confirmacao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2: ate 07/09 isto aplicava um aumento de 3,6x sem mostrar o numero."""
    env = await _aplicar(monkeypatch, tipo="CAMPAIGN_BUDGET")

    assert env["status"] == "dry_run", "orcamento aplicado sem confirmacao"
    assert env["confirmation_token"]
    assert env["current_amount_brl"] == 50.0
    assert env["recommended_amount_brl"] == 180.0, "o preview nao mostra o valor novo"
    assert env["delta_pct"] == 260.0


async def test_o_numero_entra_no_blast_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """`apply_change` reexibe o `blast_summary`, nao o envelope do dry-run.

    Sem o valor ali, quem confirma dez minutos depois le "aplicar recomendacao
    X" e nada sobre os R$ 180.
    """
    capturado = _wire(monkeypatch, tipo="CAMPAIGN_BUDGET")
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    for texto in (env["blast_summary"], capturado["blast_summary"]):
        assert "50" in texto and "180" in texto, f"summary sem os valores: {texto}"
        assert "CAMPAIGN_BUDGET" in texto


async def test_a_pendencia_guarda_o_resource_name_e_o_target_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O que o `apply_change` vai executar tem que estar no payload guardado.

    `__target_count__` e obrigatorio nas tools que criam pendencia (guard em
    `test_create_pending_audita_dry_run.py`): sem ele a trilha grava NULL.
    """
    capturado = _wire(monkeypatch, tipo="CAMPAIGN_BUDGET")
    await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert capturado["operation_type"] == "apply_recommendation"
    assert capturado["payload"]["recommendation_resource_name"] == _REC_RN
    assert capturado["payload"]["__target_count__"] == 1
    assert capturado["aplicou"] is False, "criou pendencia E aplicou"


async def test_a_pendencia_guarda_os_valores_que_o_preview_prometeu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I3: sem esta chave o `apply_change` nao tem contra o que comparar.

    Quem resolve o valor de uma recomendacao e o Google na hora do apply — a
    operacao viaja so com o resource_name. Entre o preview e a confirmacao passam
    ate 10 minutos, e o summary reexibido diria "R$ 50,00 -> R$ 180,00" com outro
    numero aterrissando.
    """
    capturado = _wire(monkeypatch, tipo="CAMPAIGN_BUDGET")
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    impressao = capturado["payload"]["valores_do_preview"]
    assert impressao["type"] == "CAMPAIGN_BUDGET"
    assert impressao["current_amount_brl"] == env["current_amount_brl"] == 50.0
    assert impressao["recommended_amount_brl"] == env["recommended_amount_brl"] == 180.0


async def test_o_caminho_auto_nao_grava_a_impressao(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contraprova do I3: sem TTL no meio nao ha o que reconferir.

    No caminho auto a leitura e a escrita acontecem na mesma chamada. Gravar a
    impressao ali seria estado sem leitor — e mudaria o `params_summary` da
    trilha de auditoria sem motivo.
    """
    capturado = _wire(monkeypatch, tipo="KEYWORD")
    await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert capturado["aplicou"] is True
    assert "valores_do_preview" not in capturado["payload"]


# --------------------------------------------------------------------------- #
# 2. Contraprova: fora da familia, segue auto.
# --------------------------------------------------------------------------- #
async def test_recomendacao_de_keyword_segue_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sem esta, "tudo confirma" passaria e o gate seria inutil.

    `KEYWORD` e a excecao ESCRITA do criterio do proto (I2): ele declara
    `recommended_cpc_bid_micros`, mas aquele CPC e de uma palavra-chave que ainda
    nao existe — nenhuma alavanca vigente se move, e a porta equivalente deste MCP
    (`add_keywords` com 1 entidade) e AUTO pela spec §7.1. A excecao esta presa
    em `test_whitelist_de_recomendacao_bate_com_o_proto.py`, que a derruba se o
    Google tirar o campo do proto.
    """
    capturado = _wire(monkeypatch, tipo="KEYWORD")
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert env["status"] == "applied"
    assert "confirmation_token" not in env
    assert capturado["aplicou"] is True
    assert env["provider_request_id"] == "req-fake"


@pytest.mark.parametrize(
    "tipo", ["KEYWORD", "SITELINK_ASSET", "TEXT_AD", "SEARCH_PARTNERS_OPT_IN", "CALLOUT_ASSET"]
)
async def test_tipos_fora_da_familia_seguem_auto(
    monkeypatch: pytest.MonkeyPatch, tipo: str
) -> None:
    """A contraprova em cinco tipos, nao em um: um gate que confirma tudo morre aqui."""
    assert (await _aplicar(monkeypatch, tipo=tipo))["status"] == "applied"


# --------------------------------------------------------------------------- #
# 3. Os 18 da probe do proto.
# --------------------------------------------------------------------------- #
def test_a_whitelist_e_exatamente_os_dezoito() -> None:
    """A lista literal acima contra a tabela de producao — nos dois sentidos."""
    assert frozenset(_OS_DEZOITO) == TIPOS_QUE_CONFIRMAM
    assert len(_OS_DEZOITO) == 18


def test_os_dezoito_existem_no_enum_do_google() -> None:
    """Nome digitado errado (ou renomeado pelo Google) viraria buraco silencioso."""
    enum = RecommendationTypeEnum.RecommendationType
    for tipo in _OS_DEZOITO:
        assert tipo in enum.__members__, f"{tipo} nao existe no enum do v24"


@pytest.mark.parametrize("tipo", sorted(_OS_DEZOITO))
async def test_todo_tipo_da_familia_confirma(monkeypatch: pytest.MonkeyPatch, tipo: str) -> None:
    """Os 18 vem da leitura do proto, nao de memoria nem de grep no enum."""
    env = await _aplicar(monkeypatch, tipo=tipo)
    assert env["status"] == "dry_run", f"{tipo} aplicado sem confirmacao"
    assert env["confirmation_token"]
    assert env["recommendation_type"] == tipo


@pytest.mark.parametrize("tipo", sorted(_OS_DEZOITO))
def test_todo_tipo_da_familia_tem_traducao_pt(tipo: str) -> None:
    """Confirmar mudanca de lance lendo so o enum em ingles nao e confirmar."""
    from src.google_ads.queries.recommendations import TYPE_PT

    assert TYPE_PT.get(tipo), f"{tipo} sem type_pt"


# --------------------------------------------------------------------------- #
# 4. O que o preview mostra quando o tipo NAO tem numero.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("tipo", ["ENHANCED_CPC_OPT_IN", "MAXIMIZE_CONVERSION_VALUE_OPT_IN"])
async def test_tipo_sem_numero_mostra_a_estrategia_que_vai_ser_trocada(
    monkeypatch: pytest.MonkeyPatch, tipo: str
) -> None:
    """As duas mensagens sao VAZIAS no v24 (verificado no descriptor do proto).

    Confirmar sem ver nada util e quase tao ruim quanto nao confirmar: o preview
    entao mostra o que a recomendacao TROCA — a estrategia de lance e o orcamento
    diario que a campanha tem hoje.
    """
    env = await _aplicar(monkeypatch, tipo=tipo)
    assert env["status"] == "dry_run"
    assert env["current_amount_brl"] is None
    assert env["recommended_amount_brl"] is None
    assert env["valores"] == {}
    assert env["campanha"]["bidding_strategy_type"] == "MAXIMIZE_CONVERSIONS"
    assert env["campanha"]["daily_budget_brl"] == 50.0
    assert "MAXIMIZE_CONVERSIONS" in env["blast_summary"]


async def test_tipo_de_razao_nao_vira_reais(monkeypatch: pytest.MonkeyPatch) -> None:
    """ROAS e razao, nao dinheiro: `4500000` micros e 4,5x — nunca "R$ 4,50"."""
    env = await _aplicar(monkeypatch, tipo="LOWER_TARGET_ROAS")
    assert env["current_amount_brl"] is None
    assert env["recommended_amount_brl"] is None
    assert env["valores"]["target_roas_atual"] == 4.5
    assert env["valores"]["multiplicador_recomendado"] == 1.35


async def test_target_cpa_mostra_o_cpa_recomendado(monkeypatch: pytest.MonkeyPatch) -> None:
    """TARGET_CPA_OPT_IN nao tem "atual", mas tem o alvo proposto — e ele e dinheiro."""
    env = await _aplicar(monkeypatch, tipo="TARGET_CPA_OPT_IN")
    assert env["current_amount_brl"] is None
    assert env["recommended_amount_brl"] == 180.0
    assert env["delta_pct"] is None


async def test_broad_match_mostra_quantas_keywords_e_o_orcamento_que_vai_exigir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I2: o 18o tipo, que o grep por nome deixava aplicar direto.

    Ele converte TODAS as keywords da campanha para ampla. Os tres fatos que
    decidem: quantas de quantas viram ampla, quanto orcamento isso vai exigir, e
    se o orcamento e COMPARTILHADO — nesse caso subir o valor REALOCA gasto das
    campanhas irmas em vez de acrescentar (C1).
    """
    env = await _aplicar(monkeypatch, tipo="USE_BROAD_MATCH_KEYWORD")
    assert env["status"] == "dry_run", "correspondencia ampla aplicada sem confirmacao"
    valores = env["valores"]
    assert valores["orcamento_exigido_brl"] == 77.0
    assert valores["keywords_que_viram_ampla"] == 120
    assert valores["keywords_na_campanha"] == 120
    assert valores["orcamento_compartilhado"] is True, "bool virou numero ou string"
    assert "orcamento_exigido_brl=77.0" in env["blast_summary"]


# --------------------------------------------------------------------------- #
# 4b. I1 — tipo que o SDK v24 nao conhece.
# --------------------------------------------------------------------------- #
async def test_tipo_que_o_sdk_nao_conhece_confirma(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ate 07/09 este caminho APLICAVA, com o resumo "Aplicar recomendacao 999".

    O `blast_radius` declara na linha 3 que operacao desconhecida sempre confirma;
    o ramo de recomendacao era a unica contradicao viva dessa politica. Tipo novo
    de gasto e justamente o que o Google acrescenta entre uma versao do SDK e a
    seguinte.
    """
    capturado = _wire(monkeypatch, tipo=_TIPO_QUE_O_SDK_NAO_CONHECE)
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert env["status"] == "dry_run", "tipo desconhecido aplicado sem confirmacao"
    assert env["confirmation_token"]
    assert capturado["aplicou"] is False
    assert env["recommendation_type"] == _TIPO_QUE_O_SDK_NAO_CONHECE
    assert env["type_pt"] is None


async def test_tipo_desconhecido_nao_inventa_o_que_a_recomendacao_faz(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O preview dos dois opt-ins vazios afirma "ela TROCA a estrategia de lance".

    Para um tipo desconhecido essa frase seria invencao: nao se sabe o que ele
    faz. O gestor confirmaria lendo uma afirmacao que ninguem pode sustentar —
    pior do que nao dizer nada.
    """
    env = await _aplicar(monkeypatch, tipo=_TIPO_QUE_O_SDK_NAO_CONHECE)
    resumo = env["blast_summary"]
    assert "TROCA a estrategia de lance" not in resumo
    assert "nao conhece" in resumo
    # O contexto da campanha continua saindo — e o unico fato verificavel que ha.
    assert "MAXIMIZE_CONVERSIONS" in resumo


# --------------------------------------------------------------------------- #
# 5. Bordas.
# --------------------------------------------------------------------------- #
async def test_recomendacao_inexistente_devolve_erro_sem_aplicar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recomendacao ja aplicada/dispensada some da API. Nao pode virar apply cego."""
    capturado = _wire(monkeypatch, tipo="CAMPAIGN_BUDGET", sem_recomendacao=True)
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert env["status"] == "error"
    assert _REC_RN in env["error_message"]
    assert capturado["aplicou"] is False


async def test_a_query_da_campanha_nao_sai_no_caminho_auto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tipo fora da familia nao paga a segunda ida a API."""
    capturado = _wire(monkeypatch, tipo="KEYWORD")
    await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert len(capturado["queries"]) == 1
    assert "FROM campaign" not in capturado["queries"][0]


async def test_o_resource_name_entra_escapado_na_gaql() -> None:
    """F87: texto livre em GAQL passa por `gaql_string_literal`, nunca interpolado cru."""
    from src.google_ads.queries.recommendations import recommendation_detail_query

    q = recommendation_detail_query("customers/1/recommendations/O'Brien\\x")
    assert "O\\'Brien" in q
    assert "\\\\x" in q
