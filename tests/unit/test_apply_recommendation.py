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
from typing import Any, cast
from uuid import uuid4

import pytest
from google.ads.googleads.v24.enums.types.recommendation_type import RecommendationTypeEnum
from google.ads.googleads.v24.resources.types.recommendation import Recommendation

from src.db import connection
from src.google_ads.queries.recommendations import (
    CAMPOS_DE_DETALHE,
    TIPOS_DE_MIGRACAO,
    TIPOS_QUE_CONFIRMAM,
    frase_do_produto_derivado,
    parse_recommendation_detail_row,
)
from src.mcp.tools import apply_recommendation as mod

_CUSTOMER = "1171969590"
_CAMPANHA_ID = "22922100363"
_CAMPANHA_RN = f"customers/{_CUSTOMER}/campaigns/{_CAMPANHA_ID}"
_REC_RN = f"customers/{_CUSTOMER}/recommendations/NzMyNjkxNjcxNC0xMDAtMTc4ODcxMDQ2NDg4My0"

# A lista dos 23 e LITERAL de proposito. Parametrizar sobre
# `TIPOS_QUE_CONFIRMAM` faria a sabotagem "tirar um tipo da whitelist" APAGAR o
# caso de teste em vez de deixa-lo vermelho — o modo de falha que o CLAUDE.md
# chama de "asserir o adjacente".
#
# Estes nomes vieram do PROTO (`v24/resources/types/recommendation.py`), campo a
# campo, e nao de um grep do enum — o I2 da revisao da Task 2 mostrou que o grep
# por nome (`BUDGET|BID|TARGET_CPA|...`) deixava o `USE_BROAD_MATCH_KEYWORD` de
# fora, que converte TODAS as keywords da campanha para ampla e declara o mesmo
# `required_campaign_budget_amount_micros` do `TARGET_ROAS_OPT_IN`. O criterio
# completo (dois eixos) e a varredura que o refaz vivem em
# `test_whitelist_de_recomendacao_bate_com_o_proto.py`.
#
# Os 5 ultimos entraram pelo EIXO 2 (C1 da revisao final): nao declaram alavanca
# nenhuma — tres tem mensagem vazia — mas MIGRAM a campanha para Performance Max,
# e migracao nao tem volta.
_OS_VINTE_E_TRES = (
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
    "PERFORMANCE_MAX_OPT_IN",
    "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX",
    "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX",
    "MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX",
    "SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX",
)

# As 5 do eixo 2, tambem literais — o preview delas nao pode dizer so
# "troca a estrategia de lance".
_AS_CINCO_MIGRACOES = (
    "PERFORMANCE_MAX_OPT_IN",
    "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX",
    "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX",
    "MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX",
    "SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX",
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
    """Popula a folha, criando UM item quando o segmento e repetido (`[]`).

    Um item basta e e o pior caso util: a leitura tem que devolver LISTA mesmo
    com um elemento so, senao o consumidor trata lista como escalar.
    """
    partes = caminho.split(".")
    for i, parte in enumerate(partes[:-1]):
        if parte.endswith("[]"):
            repetido = getattr(msg, parte[:-2])
            if not repetido:
                # proto-plus marshala o dict vazio no tipo certo do repeated.
                repetido.append({})
            msg = repetido[0]
            _setar(msg, ".".join(partes[i + 1 :]), valor)
            return
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


def _linha_de_recomendacao(
    query: str,
    tipo: str,
    *,
    atual: int,
    recomendado: int,
    sobrescreve: dict[str, Any] | None = None,
) -> Any:
    pedidos = _campos_do_select(query)
    rec = Recommendation()
    if "recommendation.type" in pedidos:
        membros = RecommendationTypeEnum.RecommendationType.__members__
        # O `int` cru e DELIBERADO e nao cabe na anotacao do proto-plus: e assim
        # que se representa o tipo que o Google lancar depois do v24 (o caso do
        # `999`). proto-plus aceita, avisa por `UserWarning`, e `_nome_do_enum`
        # devolve a string crua — que e exatamente o estado que o gate precisa
        # tratar. `cast` em vez de `type: ignore` porque a incompatibilidade e do
        # STUB, nao do runtime, e um ignore mudo esconderia um erro de verdade.
        bruto = membros[tipo] if tipo in membros else int(tipo)
        rec.type_ = cast(RecommendationTypeEnum.RecommendationType, bruto)
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
        if spec.opcoes is not None:
            # UMA opcao com TODOS os campos: e o caso denso, e o que interessa
            # aqui e que a grade chegue ao preview. O caso ESPARSO — a opcao que
            # nao declara um dos campos — e o do defeito, e vive no teste que o
            # nomeia, montado a mao com duas opcoes.
            for _chave, caminho, unidade in spec.opcoes.campos:
                _setar(detalhe, f"{spec.opcoes.caminho}.{caminho}", _SENTINELA[unidade])
        # Depois das sentinelas, para cobrir folha cujo VALOR muda o caminho de
        # codigo (o `shared_set` do I3 decide se ha segunda campanha a consultar).
        for caminho, valor in (sobrescreve or {}).items():
            _setar(detalhe, caminho, valor)
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


def _linha_de_irma(campaign_id: str, nome: str, status: str) -> Any:
    return SimpleNamespace(campaign=SimpleNamespace(id=int(campaign_id), name=nome, status=status))


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
    sobrescreve: dict[str, Any] | None = None,
    irmas: list[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    capturado: dict[str, Any] = {"queries": [], "aplicou": False}

    async def _run(**kwargs: Any) -> list[dict[str, Any]]:
        q: str = kwargs["query"]
        fmt = kwargs["row_formatter"]
        capturado["queries"].append(q)
        # As duas consultas de campanha partem de `FROM campaign`; o que as separa
        # e o SELECT. Rotear pelo `FROM` mandaria a query das irmas (I3) para o
        # parser do contexto, e o teste "passaria" medindo a coisa errada.
        if "campaign.bidding_strategy\n" in q:
            return [fmt(_linha_de_irma(*linha)) for linha in (irmas or [])]
        if "FROM campaign" in q:
            return [fmt(_linha_de_campanha(q))]
        if sem_recomendacao:
            return []
        return [
            fmt(
                _linha_de_recomendacao(
                    q, tipo, atual=atual, recomendado=recomendado, sobrescreve=sobrescreve
                )
            )
        ]

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
# 3. Os 23 da probe do proto.
# --------------------------------------------------------------------------- #
def test_a_whitelist_e_exatamente_os_vinte_e_tres() -> None:
    """A lista literal acima contra a tabela de producao — nos dois sentidos."""
    assert frozenset(_OS_VINTE_E_TRES) == TIPOS_QUE_CONFIRMAM
    assert len(_OS_VINTE_E_TRES) == 23


def test_as_cinco_migracoes_estao_na_whitelist() -> None:
    """C1: ate 07/09 os cinco auto-aplicavam uma conversao de campanha sem volta."""
    assert frozenset(_AS_CINCO_MIGRACOES) == TIPOS_DE_MIGRACAO
    assert frozenset(_AS_CINCO_MIGRACOES) <= TIPOS_QUE_CONFIRMAM


def test_os_vinte_e_tres_existem_no_enum_do_google() -> None:
    """Nome digitado errado (ou renomeado pelo Google) viraria buraco silencioso."""
    enum = RecommendationTypeEnum.RecommendationType
    for tipo in _OS_VINTE_E_TRES:
        assert tipo in enum.__members__, f"{tipo} nao existe no enum do v24"


@pytest.mark.parametrize("tipo", sorted(_OS_VINTE_E_TRES))
async def test_todo_tipo_da_familia_confirma(monkeypatch: pytest.MonkeyPatch, tipo: str) -> None:
    """Os 23 vem da leitura do proto, nao de memoria nem de grep no enum."""
    env = await _aplicar(monkeypatch, tipo=tipo)
    assert env["status"] == "dry_run", f"{tipo} aplicado sem confirmacao"
    assert env["confirmation_token"]
    assert env["recommendation_type"] == tipo


@pytest.mark.parametrize("tipo", sorted(_OS_VINTE_E_TRES))
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


@pytest.mark.parametrize("tipo", sorted(_AS_CINCO_MIGRACOES))
async def test_migracao_avisa_que_nao_tem_volta(monkeypatch: pytest.MonkeyPatch, tipo: str) -> None:
    """C1: o gate sozinho nao basta — o preview tem que dizer o que decide.

    Estes cinco nao tem numero nenhum a mostrar, entao antes do C1 caiam no texto
    dos opt-ins de estrategia ("ela TROCA a estrategia de lance"), que descreve a
    consequencia menor e esconde a maior. O aviso vai tambem no `blast_summary`,
    que e o que o `apply_change` reexibe dez minutos depois (achado da Task 1).
    """
    capturado = _wire(monkeypatch, tipo=tipo)
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert env["status"] == "dry_run", f"{tipo} aplicado sem confirmacao"
    for texto in (env["blast_summary"], capturado["blast_summary"]):
        assert "IRREVERSIVEL" in texto, f"{tipo}: summary sem o aviso de migracao: {texto}"
        assert "Performance Max" in texto
        assert "TROCA a estrategia de lance" not in texto, (
            f"{tipo}: caiu no texto dos opt-ins de estrategia"
        )


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


# --------------------------------------------------------------------------- #
# 5. I2 — o preview le o que a mensagem declara, e ausencia nao vira zero.
# --------------------------------------------------------------------------- #
_OS_QUATRO_COM_ORCAMENTO = (
    "SET_TARGET_CPA",
    "SET_TARGET_ROAS",
    "FORECASTING_SET_TARGET_CPA",
    "FORECASTING_SET_TARGET_ROAS",
)


def _row(tipo: str) -> Any:
    """Uma linha crua do proto, para exercitar o PARSER sem passar pela tool."""
    rec = Recommendation()
    rec.type_ = RecommendationTypeEnum.RecommendationType.__members__[tipo]
    rec.resource_name = _REC_RN
    return SimpleNamespace(recommendation=rec)


@pytest.mark.parametrize("tipo", sorted(_OS_QUATRO_COM_ORCAMENTO))
async def test_alvo_de_cpa_e_roas_mostra_o_orcamento_que_vem_junto(
    monkeypatch: pytest.MonkeyPatch, tipo: str
) -> None:
    """I2: os quatro declaram `campaign_budget` na PROPRIA mensagem.

    Ate 07/09 o preview mostrava so o alvo: o gestor confirmava "Definir Target
    CPA R$ 77,00" e aplicava junto uma mudanca do orcamento diario que nunca lhe
    foi mostrada. E o irmao `TARGET_ROAS_OPT_IN` ja lia o campo equivalente — a
    tabela se contradizia. Vale tambem no `blast_summary`, que e o que o
    `apply_change` reexibe.
    """
    capturado = _wire(monkeypatch, tipo=tipo)
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert env["status"] == "dry_run"
    assert env["valores"]["orcamento_atual_brl"] == 77.0, f"{tipo}: orcamento atual nao aparece"
    assert env["valores"]["orcamento_novo_brl"] == 77.0, f"{tipo}: orcamento novo nao aparece"
    assert "orcamento_novo_brl" in capturado["blast_summary"], (
        f"{tipo}: o orcamento nao chega ao summary que o apply_change reexibe"
    )


def test_orcamento_ausente_nao_vira_r_zero_no_preview() -> None:
    """F145 pela porta dos fundos: proto-plus nunca omite atributo.

    Uma `SET_TARGET_CPA` que nao propoe orcamento devolve `campaign_budget`
    ZERADO, nao ausente. Emitir a chave assim mesmo poria "orcamento_atual_brl=0.0"
    num preview — numero inventado com cara de medido. Par com o controle positivo
    abaixo: sem ele, um parser que nunca emitisse a chave passaria neste teste.
    """
    linha = _row("SET_TARGET_CPA")
    linha.recommendation.set_target_cpa_recommendation.recommended_target_cpa_micros = 77_000_000
    info = parse_recommendation_detail_row(linha)
    assert info["recommended_amount_brl"] == 77.0
    assert "orcamento_atual_brl" not in info["valores"], "zero-value virou orcamento no preview"
    assert "orcamento_novo_brl" not in info["valores"]


def test_orcamento_presente_aparece__controle_positivo() -> None:
    """O par do teste acima: com o campo preenchido, as duas chaves saem."""
    linha = _row("SET_TARGET_CPA")
    detalhe = linha.recommendation.set_target_cpa_recommendation
    detalhe.recommended_target_cpa_micros = 77_000_000
    detalhe.campaign_budget.current_amount_micros = 50_000_000
    detalhe.campaign_budget.recommended_new_amount_micros = 180_000_000
    info = parse_recommendation_detail_row(linha)
    assert info["valores"]["orcamento_atual_brl"] == 50.0
    assert info["valores"]["orcamento_novo_brl"] == 180.0


def test_target_cpa_opt_in_le_a_lista_de_opcoes_e_nao_quebra() -> None:
    """`options` e REPEATED: `getattr` nele levanta AttributeError (medido no v24).

    A correcao "obvia" que a revisao sugeriu
    (`options.required_campaign_budget_amount_micros`, sem `[]`) derrubaria a tool
    em producao — e o guard de existencia do proto passaria verde, porque a folha
    existe no descriptor. Nao ha UM orcamento a mostrar: ha a grade das metas
    disponiveis, e e a grade que sai — um REGISTRO por meta, com o CPA e o
    orcamento DAQUELA meta juntos.

    Este e o caso DENSO (toda opcao declara tudo). Ele passava verde tambem com
    as duas listas paralelas de antes; e por isso que ele sozinho nao bastava —
    ver o caso esparso logo abaixo.
    """
    linha = _row("TARGET_CPA_OPT_IN")
    detalhe = linha.recommendation.target_cpa_opt_in_recommendation
    detalhe.recommended_target_cpa_micros = 77_000_000
    detalhe.options.append(
        {"target_cpa_micros": 60_000_000, "required_campaign_budget_amount_micros": 150_000_000}
    )
    detalhe.options.append(
        {"target_cpa_micros": 90_000_000, "required_campaign_budget_amount_micros": 300_000_000}
    )
    info = parse_recommendation_detail_row(linha)
    assert info["valores"]["opcoes_de_target_cpa"] == [
        {"target_cpa_brl": 60.0, "orcamento_exigido_brl": 150.0},
        {"target_cpa_brl": 90.0, "orcamento_exigido_brl": 300.0},
    ]


def test_opcao_sem_orcamento_nao_desloca_o_orcamento_da_opcao_seguinte() -> None:
    """O caso ESPARSO — o defeito, e o que o teste denso acima nao cobria.

    As duas folhas de `TargetCpaOptInRecommendationOption` sao `optional` no v24,
    entao a leitura antiga descartava a ausente DENTRO do ramo repetido e as duas
    listas irmas encurtavam em pontos diferentes. Com a opcao 1 sem orcamento e a
    opcao 2 exigindo R$ 200,00, o preview devolvia

        target_cpa_por_opcao_brl        = [50.0, 70.0]
        orcamento_exigido_por_opcao_brl = [200.0]

    e quem pareasse por posicao — que era a instrucao escrita ao lado da tabela —
    lia os R$ 200,00 como exigencia do CPA de R$ 50,00, que e justamente o da
    opcao SEM orcamento. Numero errado no exato momento em que o gestor confirma
    dinheiro.

    A asserção e sobre o REGISTRO inteiro: o orcamento so existe dentro da opcao
    que o declarou, e a que nao declarou nao ganha o do vizinho.
    """
    linha = _row("TARGET_CPA_OPT_IN")
    detalhe = linha.recommendation.target_cpa_opt_in_recommendation
    detalhe.recommended_target_cpa_micros = 77_000_000
    detalhe.options.append({"target_cpa_micros": 50_000_000})
    detalhe.options.append(
        {"target_cpa_micros": 70_000_000, "required_campaign_budget_amount_micros": 200_000_000}
    )
    info = parse_recommendation_detail_row(linha)
    assert info["valores"]["opcoes_de_target_cpa"] == [
        {"target_cpa_brl": 50.0},
        {"target_cpa_brl": 70.0, "orcamento_exigido_brl": 200.0},
    ]


def test_opcao_que_nao_declara_nada_continua_contando() -> None:
    """A grade tem o tamanho que o Google mandou — registro vazio nao some.

    Descartar a opcao que nao declara campo nenhum encolheria a grade calada, que
    e a mesma familia do defeito acima (sumir com o que falta em vez de mostrar
    que falta). Registro vazio diz "esta opcao existe e nao traz numero"; opcao
    ausente diria "sao duas opcoes" quando sao tres.
    """
    linha = _row("TARGET_CPA_OPT_IN")
    detalhe = linha.recommendation.target_cpa_opt_in_recommendation
    detalhe.options.append({"target_cpa_micros": 50_000_000})
    detalhe.options.append({})
    info = parse_recommendation_detail_row(linha)
    assert info["valores"]["opcoes_de_target_cpa"] == [{"target_cpa_brl": 50.0}, {}]


def test_nenhuma_folha_repetida_sai_como_lista_paralela() -> None:
    """A CLASSE do defeito, presa na tabela — nao so a instancia do TARGET_CPA.

    Duas listas irmas pareadas por posicao so estao certas enquanto todo item
    declarar todos os campos, e o proto nao promete isso em lugar nenhum. Campo
    REPEATED se le por `ListaDeOpcoes`, que devolve registro; `outros` so carrega
    caminho singular. Sem esta asserção, o proximo tipo com grade repetiria o
    mesmo desalinhamento em outro lugar.
    """
    for tipo, spec in CAMPOS_DE_DETALHE.items():
        for chave, caminho, _unidade in spec.outros:
            assert "[]" not in caminho, (
                f"{tipo}.{chave} le um campo REPEATED como lista paralela ({caminho}) — "
                "mova para `opcoes=ListaDeOpcoes(...)`, que pareia por registro"
            )


def test_lista_vazia_de_opcoes_nao_emite_chave__controle_positivo() -> None:
    """Contraprova do repeated: sem opcao nenhuma, a chave nao aparece vazia."""
    linha = _row("TARGET_CPA_OPT_IN")
    linha.recommendation.target_cpa_opt_in_recommendation.recommended_target_cpa_micros = 77_000_000
    info = parse_recommendation_detail_row(linha)
    assert "opcoes_de_target_cpa" not in info["valores"]


@pytest.mark.parametrize("compartilhado", [False, True])
def test_flag_booleano_aparece_mesmo_quando_e_false(compartilhado: bool) -> None:
    """A UNICA excecao a regra de presenca, e ela e necessaria.

    O `in` do proto-plus devolve False tanto para "nao declarado" quanto para
    "declarado como False". Em `campaign_uses_shared_budget`, `False` e RESPOSTA —
    diz "o orcamento e exclusivo", que muda a decisao de subir o valor. Aplicar a
    regra de presenca aqui apagaria a metade negativa da informacao.
    """
    linha = _row("USE_BROAD_MATCH_KEYWORD")
    detalhe = linha.recommendation.use_broad_match_keyword_recommendation
    detalhe.campaign_uses_shared_budget = compartilhado
    info = parse_recommendation_detail_row(linha)
    assert info["valores"]["orcamento_compartilhado"] is compartilhado


# --------------------------------------------------------------------------- #
# 6. I3 — o alvo pode ser da estrategia de PORTFOLIO, nao da campanha.
# --------------------------------------------------------------------------- #
_ESTRATEGIA_RN = f"customers/{_CUSTOMER}/biddingStrategies/987654321"


@pytest.mark.parametrize("tipo", ["RAISE_TARGET_CPA", "LOWER_TARGET_ROAS"])
async def test_alvo_de_portfolio_enumera_as_irmas_e_avisa(
    monkeypatch: pytest.MonkeyPatch, tipo: str
) -> None:
    """I3: o irmao do C1, um nivel acima — recurso compartilhado, preview de UMA campanha.

    `target_adjustment.shared_set` so popula quando a recomendacao e de nivel
    portfolio, e nesse caso mudar o alvo atinge TODAS as campanhas da estrategia.
    O preview dizia `na campanha 'X' (id N)` e nao mencionava as irmas.
    """
    capturado = _wire(
        monkeypatch,
        tipo=tipo,
        sobrescreve={"target_adjustment.shared_set": _ESTRATEGIA_RN},
        irmas=[
            (_CAMPANHA_ID, "[CP] MDO MONTES CLAROS", "ENABLED"),
            ("33333333333", "[CP] MDO IRMA ATIVA", "ENABLED"),
            ("44444444444", "[CP] MDO IRMA PAUSADA", "PAUSED"),
        ],
    )
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    bloco = env["portfolio"]
    assert bloco is not None, f"{tipo}: alvo de portfolio sem bloco no preview"
    assert bloco["bidding_strategy_resource_name"] == _ESTRATEGIA_RN
    assert [c["campaign_id"] for c in bloco["campaigns_outside_batch"]] == [
        "33333333333",
        "44444444444",
    ]
    assert bloco["ativas_fora_do_lote"] == 1
    # No `blast_summary` tambem: e ele que o `apply_change` reexibe dez minutos
    # depois, e um aviso que vive so no envelope some na hora de confirmar.
    for texto in (env["blast_summary"], capturado["blast_summary"]):
        assert "PORTFOLIO" in texto, f"{tipo}: summary sem o aviso de portfolio: {texto}"
        assert _ESTRATEGIA_RN in texto


@pytest.mark.parametrize("tipo", ["RAISE_TARGET_CPA", "LOWER_TARGET_ROAS"])
async def test_alvo_de_campanha_nao_tem_bloco_nem_gasta_consulta(
    monkeypatch: pytest.MonkeyPatch, tipo: str
) -> None:
    """Contraprova: sem `shared_set`, nada de portfolio — e nada de terceira ida a API.

    Sem esta, um bloco emitido incondicionalmente passaria no teste acima e o
    preview de toda recomendacao de nivel campanha ganharia um aviso falso.
    """
    capturado = _wire(monkeypatch, tipo=tipo, sobrescreve={"target_adjustment.shared_set": ""})
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert env["portfolio"] is None
    assert "PORTFOLIO" not in env["blast_summary"]
    assert not [q for q in capturado["queries"] if "campaign.bidding_strategy\n" in q]


async def test_shared_set_em_formato_desconhecido_avisa_sem_inventar_contagem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`campaigns_outside_batch` e None, nao [] — "zero irmas" seria pior que nao medir.

    O campo se chama `shared_set` e a docstring do proto diz que carrega a
    estrategia de portfolio; os dois formatos de resource name sao diferentes e em
    07/09 nao havia recomendacao de nivel portfolio em conta nenhuma do MCC para
    medir qual deles o Google manda. Disparar a GAQL no formato errado devolveria
    zero linhas, e "atinge mais 0 campanhas" passaria por fato medido (F145).
    """
    outro = f"customers/{_CUSTOMER}/sharedSets/555"
    capturado = _wire(
        monkeypatch,
        tipo="RAISE_TARGET_CPA",
        sobrescreve={"target_adjustment.shared_set": outro},
    )
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    bloco = env["portfolio"]
    assert bloco is not None
    assert bloco["campaigns_outside_batch"] is None, "lista vazia leria como zero irmas"
    assert bloco["ativas_fora_do_lote"] is None
    assert "PORTFOLIO" in env["blast_summary"]
    assert not [q for q in capturado["queries"] if "campaign.bidding_strategy\n" in q]


async def test_o_bloco_de_portfolio_nao_entra_no_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As irmas mudam por motivo alheio a recomendacao; o recheck e sobre o VALOR.

    Se o bloco entrasse na impressao, pausar uma campanha irma entre o preview e a
    confirmacao faria o `apply_change` recusar por "o Google revisou" — recusa
    correta na forma e errada no motivo, que treina o gestor a ignorar o aviso.
    """
    capturado = _wire(
        monkeypatch,
        tipo="RAISE_TARGET_CPA",
        sobrescreve={"target_adjustment.shared_set": _ESTRATEGIA_RN},
        irmas=[("33333333333", "[CP] IRMA", "ENABLED")],
    )
    await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    impressao = capturado["payload"]["valores_do_preview"]
    assert "portfolio" not in impressao
    assert "campaigns_outside_batch" not in str(impressao)
    # A estrategia em si ENTRA, porque e a mensagem da recomendacao mudando de
    # nivel — isso sim invalida o consentimento.
    assert impressao["valores"]["estrategia_de_portfolio"] == _ESTRATEGIA_RN


# --------------------------------------------------------------------------- #
# 7. I4 — ancora e multiplicador, e agora tambem o PRODUTO.
# --------------------------------------------------------------------------- #
# (tipo, chave do produto, valor esperado com as sentinelas do fake)
#
# Literal de proposito, como os 23: derivar de `CAMPOS_DE_DETALHE.derivado`
# apagaria o caso quando alguem tirasse a derivacao da tabela, em vez de
# reprova-la. As contas: CPA 50.00 x 1.35 = 67.50 (dinheiro, 2 casas);
# ROAS 4.5 x 1.35 = 6.075 (razao, ate 4 casas — e sem "R$").
_OS_TRES_COM_PRODUTO = (
    ("RAISE_TARGET_CPA", "target_cpa_novo_brl", 67.5),
    ("RAISE_TARGET_CPA_BID_TOO_LOW", "target_cpa_novo_brl", 67.5),
    ("LOWER_TARGET_ROAS", "target_roas_novo", 6.075),
)


@pytest.mark.parametrize(("tipo", "chave", "esperado"), _OS_TRES_COM_PRODUTO)
async def test_o_alvo_novo_aparece_alem_dos_fatores(
    monkeypatch: pytest.MonkeyPatch, tipo: str, chave: str, esperado: float
) -> None:
    """I4: o proto declara ancora + multiplicador, e o valor NOVO e o produto.

    Ate 07/09 o resumo saia "valor atual R$ 50.00; multiplicador_recomendado=1.35"
    e quem confirmava fazia a multiplicacao de cabeca — ou nao fazia. E a Global
    Constraint do PR ("confirmar sem ver o numero nao e confirmar") aplicada a um
    alvo de lance em vez de a um orcamento. Os FATORES continuam saindo: o produto
    e alem deles, nao no lugar deles.
    """
    capturado = _wire(monkeypatch, tipo=tipo)
    env = await mod.apply_recommendation(
        {"customer_id": _CUSTOMER, "recommendation_resource_name": _REC_RN}
    )
    assert env["valores"][chave] == esperado, f"{tipo}: produto errado ou ausente"
    assert env["valores"]["multiplicador_recomendado"] == 1.35, f"{tipo}: o fator sumiu"
    for texto in (env["blast_summary"], capturado["blast_summary"]):
        assert str(esperado) in texto, f"{tipo}: o produto nao chega ao summary: {texto}"
        assert "derivado" in texto, f"{tipo}: o produto sai sem dizer que e derivado"


async def test_o_produto_de_roas_nao_vira_reais(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unidade: ROAS e RAZAO. O produto sai 6.075, nunca "R$ 6.08".

    Micros e razao nao se somam nem se formatam igual — e os dois tipos de CPA ao
    lado usam a MESMA maquinaria com a outra unidade, entao um bug de unidade aqui
    seria invisivel se so o CPA fosse testado.
    """
    env = await _aplicar(monkeypatch, tipo="LOWER_TARGET_ROAS")
    resumo = env["blast_summary"]
    assert "6.075" in resumo
    assert "R$ 6" not in resumo, f"ROAS formatado como dinheiro: {resumo}"
    assert env["current_amount_brl"] is None
    assert env["recommended_amount_brl"] is None


async def test_o_produto_sai_uma_vez_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """A frase ja diz o numero E a procedencia; repeti-lo cru seria ruido.

    Contraprova do lado oposto: `multiplicador_recomendado` (um FATOR) continua na
    listagem crua, entao o filtro nao esta apagando o que deveria ficar.
    """
    env = await _aplicar(monkeypatch, tipo="RAISE_TARGET_CPA")
    resumo = env["blast_summary"]
    assert resumo.count("67.5") == 1, f"produto repetido no resumo: {resumo}"
    assert "target_cpa_novo_brl=" not in resumo
    assert "multiplicador_recomendado=1.35" in resumo


@pytest.mark.parametrize(
    ("descricao", "ancora", "fator"),
    [
        ("sem multiplicador", 77_000_000, None),
        ("sem ancora", None, 1.35),
        ("multiplicador zerado", 77_000_000, 0.0),
    ],
)
def test_fator_faltando_nao_vira_produto_zero(
    descricao: str, ancora: int | None, fator: float | None
) -> None:
    """F145 de novo: meio produto e zero, e "R$ 0.00" passa por valor medido.

    Par com `test_os_dois_fatores_presentes_derivam__controle_positivo`: sem ele,
    uma derivacao que nunca emitisse nada passaria neste teste.
    """
    linha = _row("RAISE_TARGET_CPA")
    detalhe = linha.recommendation.raise_target_cpa_recommendation
    if ancora is not None:
        detalhe.target_adjustment.current_average_target_micros = ancora
    if fator is not None:
        detalhe.target_adjustment.recommended_target_multiplier = fator
    info = parse_recommendation_detail_row(linha)
    assert "target_cpa_novo_brl" not in info["valores"], descricao
    assert frase_do_produto_derivado(info) is None, descricao


def test_os_dois_fatores_presentes_derivam__controle_positivo() -> None:
    """O par do teste acima, com os numeros da probe do proto."""
    linha = _row("RAISE_TARGET_CPA")
    detalhe = linha.recommendation.raise_target_cpa_recommendation
    detalhe.target_adjustment.current_average_target_micros = 77_000_000
    detalhe.target_adjustment.recommended_target_multiplier = 1.35
    info = parse_recommendation_detail_row(linha)
    assert info["valores"]["target_cpa_novo_brl"] == 103.95
    assert frase_do_produto_derivado(info) == "R$ 77.00 -> R$ 103.95 (derivado: atual x 1.35)"


def test_tipo_sem_derivacao_nao_ganha_frase() -> None:
    """Contraprova: a maquinaria so age onde a tabela declara `derivado`."""
    linha = _row("CAMPAIGN_BUDGET")
    detalhe = linha.recommendation.campaign_budget_recommendation
    detalhe.current_budget_amount_micros = 50_000_000
    detalhe.recommended_budget_amount_micros = 180_000_000
    info = parse_recommendation_detail_row(linha)
    assert frase_do_produto_derivado(info) is None
