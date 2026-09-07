"""Guard derivado: a whitelist de recomendacoes que CONFIRMAM sai do proto do v24.

**Por que este guard existe (I2 da revisao da Task 2).** A primeira lista dos
tipos que exigem confirmacao foi montada com um `grep` do enum por
`BUDGET|BID|TARGET_CPA|TARGET_ROAS|MAXIMIZE|ENHANCED_CPC|ROI|CPC`. Filtro por
NOME nao e probe: o `USE_BROAD_MATCH_KEYWORD` nao casa nenhum daqueles padroes,
converte **todas** as keywords da campanha para correspondencia ampla e declara
no proto o MESMO `required_campaign_budget_amount_micros` que ja punha o
`TARGET_ROAS_OPT_IN` dentro da lista — um campo identico decidindo o oposto.

Este teste refaz a varredura no DESCRIPTOR a cada run, e e a unica coisa que faz
a lista de producao (uma tabela escrita a mao) responder ao proto: tipo novo que o
Google lancar com campo de orcamento ou de lance derruba o teste em vez de entrar
calado no caminho auto.

**As duas fontes sao independentes de proposito.** `TIPOS_QUE_CONFIRMAM` e
derivada de `CAMPOS_DE_DETALHE`, escrita a mao em `src/`; o conjunto daqui vem do
`Recommendation.DESCRIPTOR` do SDK. Um guard que derivasse os dois lados da mesma
fonte seria verdadeiro independente da implementacao.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from google.ads.googleads.v24.enums.types.bidding_strategy_type import BiddingStrategyTypeEnum
from google.ads.googleads.v24.resources.types.recommendation import Recommendation

from src.google_ads.queries.recommendations import (
    CAMPOS_DE_DETALHE,
    TIPOS_CONHECIDOS,
    TIPOS_QUE_CONFIRMAM,
)

# Alavanca de gasto JA EXISTENTE da campanha: orcamento, alvo de lance, ou o flag
# de orcamento compartilhado (que decide se subir o valor acrescenta gasto ou
# REALOCA das campanhas irmas — C1). Ancorado no fim do nome de proposito: sem o
# `$`, `budget_options.impact.base_metrics.cost_micros` entraria, e metrica
# projetada nao e alavanca.
_ALAVANCA = re.compile(
    r"(budget_amount_micros"
    r"|budget\.current_amount_micros"
    r"|budget\.recommended_new_amount_micros"
    r"|target_cpa_micros"
    r"|target_roas"
    r"|target_multiplier"
    r"|average_target_micros"
    r"|cpc_bid_micros"
    r"|uses_shared_budget)$"
)

# A UNICA excecao escrita ao criterio, com o motivo. O `KEYWORD` declara
# `recommended_cpc_bid_micros`, mas aquele CPC e atributo de uma palavra-chave
# que ainda NAO existe — nenhuma alavanca vigente se move. A porta equivalente
# deste MCP (`add_keywords`, 1 entidade) e AUTO pela spec §7.1; por-lo sob
# confirmacao repetiria espelhada a incoerencia que o C2 veio fechar. E e o tipo
# mais numeroso de uma conta real (um por ad_group): confirmar o que nao precisa
# treina o gestor a clicar sem ler.
_FORA_POR_ESCRITO = {
    "KEYWORD": "o CPC e de uma keyword que ainda nao existe; add_keywords de 1 entidade e AUTO",
}

_DESC = Recommendation.pb(Recommendation()).DESCRIPTOR
_RAIZ = _DESC.full_name
_DETALHES = {
    f.name: f.message_type
    for f in _DESC.fields
    if f.message_type is not None and f.name.endswith("_recommendation")
}
_ESTRATEGIAS_DE_LANCE = set(BiddingStrategyTypeEnum.BiddingStrategyType.__members__)


def _folhas(md: Any, prefixo: str = "", nivel: int = 0) -> list[str]:
    """Nomes dotted dos campos da mensagem de detalhe.

    Recursa SO em mensagens aninhadas dentro do proprio `Recommendation`
    (`TargetAdjustmentInfo`, `CampaignBudget`...): descer em `Asset` ou `Ad`
    traria 90 campos de ruido por tipo. Pula o ramo `impact`, que e projecao de
    metrica, nao alavanca de gasto.
    """
    achados: list[str] = []
    for f in md.fields:
        if f.name == "impact":
            continue
        nome = prefixo + f.name
        achados.append(nome)
        if (
            f.message_type is not None
            and nivel < 3
            and f.message_type.full_name.startswith(_RAIZ + ".")
        ):
            achados.extend(_folhas(f.message_type, nome + ".", nivel + 1))
    return achados


def _campos_do_tipo(tipo: str) -> list[str]:
    return _folhas(_DETALHES[tipo.lower() + "_recommendation"])


def _o_que_o_proto_manda_confirmar() -> set[str]:
    """Os dois criterios, aplicados a TODOS os tipos que o v24 sabe nomear."""
    saida: set[str] = set()
    for tipo in TIPOS_CONHECIDOS:
        campos = _campos_do_tipo(tipo)
        if any(_ALAVANCA.search(c) for c in campos):
            saida.add(tipo)
        elif not campos and tipo.removesuffix("_OPT_IN") in _ESTRATEGIAS_DE_LANCE:
            # Mensagem vazia = ausencia de PARAMETRO (a troca de estrategia nao
            # tem numero a escolher), nao ausencia de efeito sobre o lance.
            saida.add(tipo)
    return saida


def test_a_varredura_do_proto_ve_a_populacao_inteira() -> None:
    """Sem isto o guard passaria verde varrendo zero tipos (F155, vacuidade)."""
    assert len(TIPOS_CONHECIDOS) >= 54, f"so {len(TIPOS_CONHECIDOS)} tipos no enum do v24"
    faltando = sorted(t for t in TIPOS_CONHECIDOS if t.lower() + "_recommendation" not in _DETALHES)
    assert not faltando, f"tipos do enum sem mensagem de detalhe no proto: {faltando}"


def test_a_whitelist_e_exatamente_o_que_o_proto_declara() -> None:
    """Nos DOIS sentidos: tipo do proto fora da lista, e tipo da lista sem respaldo."""
    esperado = _o_que_o_proto_manda_confirmar() - set(_FORA_POR_ESCRITO)
    assert esperado == set(TIPOS_QUE_CONFIRMAM), (
        f"entrariam e nao estao: {sorted(esperado - set(TIPOS_QUE_CONFIRMAM))}; "
        f"estao e o proto nao respalda: {sorted(set(TIPOS_QUE_CONFIRMAM) - esperado)}"
    )


def test_a_excecao_escrita_continua_valendo() -> None:
    """Excecao apodrece calada: se o Google tirar o campo, ela vira letra morta."""
    do_proto = _o_que_o_proto_manda_confirmar()
    for tipo, motivo in _FORA_POR_ESCRITO.items():
        assert tipo in do_proto, f"{tipo} nao passa mais no criterio — remova a excecao ({motivo})"
        assert tipo not in TIPOS_QUE_CONFIRMAM, f"{tipo} esta excetuado E na whitelist"


def test_use_broad_match_keyword_entra_pelo_mesmo_campo_do_target_roas_opt_in() -> None:
    """O caso concreto do I2: mesmo campo do proto, decisao oposta na lista antiga."""
    campo = "required_campaign_budget_amount_micros"
    assert campo in _campos_do_tipo("USE_BROAD_MATCH_KEYWORD")
    assert campo in _campos_do_tipo("TARGET_ROAS_OPT_IN")
    assert {"USE_BROAD_MATCH_KEYWORD", "TARGET_ROAS_OPT_IN"} <= set(TIPOS_QUE_CONFIRMAM)


@pytest.mark.parametrize("tipo", sorted(CAMPOS_DE_DETALHE))
def test_todo_caminho_da_tabela_resolve_no_proto(tipo: str) -> None:
    """Caminho dotted digitado errado leria o zero-value calado, nunca um erro."""
    spec = CAMPOS_DE_DETALHE[tipo]
    assert spec.campo in _DETALHES, f"{tipo}: campo de detalhe {spec.campo} nao existe"
    campos = set(_campos_do_tipo(tipo))
    caminhos = [c for c in (spec.atual_brl, spec.recomendado_brl) if c is not None]
    caminhos += [caminho for _chave, caminho, _unidade in spec.outros]
    for caminho in caminhos:
        assert caminho in campos, f"{tipo}: {spec.campo}.{caminho} nao existe no proto do v24"
