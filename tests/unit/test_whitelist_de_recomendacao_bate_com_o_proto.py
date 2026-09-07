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

**E por que ele ganhou um segundo eixo (C1 da revisao final).** O criterio de
07/09 era so "a mensagem declara alavanca de gasto ja existente" — e migracao NAO
declara alavanca: ela substitui a campanha. Os cinco tipos que convertem a campanha
para Performance Max tem mensagem vazia (ou so identificador de Merchant Center),
entao passavam por baixo do criterio inteiro e auto-aplicavam uma conversao de tipo
de campanha SEM CAMINHO DE VOLTA. Irreversibilidade e eixo proprio: "quanto muda" e
"da pra desfazer" sao perguntas diferentes, e a segunda nao se responde olhando os
campos da mensagem. O eixo 2 (`_migra_a_campanha`) e ancorado no
`AdvertisingChannelTypeEnum` pelo mesmo motivo que o 1.2 e ancorado no
`BiddingStrategyTypeEnum`: e lista que o Google mantem, nao padrao inventado aqui.

**As duas fontes sao independentes de proposito.** `TIPOS_QUE_CONFIRMAM` e
derivada de `CAMPOS_DE_DETALHE`, escrita a mao em `src/`; o conjunto daqui vem do
`Recommendation.DESCRIPTOR` do SDK. Um guard que derivasse os dois lados da mesma
fonte seria verdadeiro independente da implementacao. Vale igual para o eixo 2:
`TIPOS_DE_MIGRACAO` e literal em `src/`, e aqui se refaz a derivacao.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from google.ads.googleads.v24.enums.types.advertising_channel_type import (
    AdvertisingChannelTypeEnum,
)
from google.ads.googleads.v24.enums.types.bidding_strategy_type import BiddingStrategyTypeEnum
from google.ads.googleads.v24.resources.types.recommendation import Recommendation

from src.google_ads.queries.recommendations import (
    CAMPOS_DE_DETALHE,
    TIPOS_CONHECIDOS,
    TIPOS_DE_MIGRACAO,
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
# Os TIPOS DE CAMPANHA que o v24 conhece. `UNSPECIFIED`/`UNKNOWN` ficam fora pelo
# mesmo motivo de sempre: sao os dois valores com que o proto diz "nao sei".
_CANAIS = {
    nome
    for nome in AdvertisingChannelTypeEnum.AdvertisingChannelType.__members__
    if nome not in ("UNSPECIFIED", "UNKNOWN")
}


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


def _migra_a_campanha(tipo: str) -> bool:
    """EIXO 2: o nome declara migracao cujo DESTINO e um tipo de campanha do proto.

    Nao ha o que ler na mensagem — tres das cinco sao vazias. O sinal legivel por
    maquina e o nome, e ele so vale ancorado numa lista que o Google mantem: o
    destino depois de `_TO_` (ou a raiz antes de `_OPT_IN`) tem que ser um valor
    de `AdvertisingChannelTypeEnum`.

    E o ancoramento que separa os quase-casos, e por isso ele nao e cosmetico:
    `PERFORMANCE_MAX_FINAL_URL_OPT_IN` tem "PERFORMANCE_MAX" no nome mas raiz
    `PERFORMANCE_MAX_FINAL_URL`, que nao e canal — liga expansao de URL numa PMax
    existente, e desliga de volta; `SHOPPING_ADD_PRODUCTS_TO_CAMPAIGN` tem `_TO_`
    mas destino `CAMPAIGN`, que tambem nao e canal.
    """
    if "_TO_" in tipo:
        destino = tipo.rsplit("_TO_", 1)[-1].removesuffix("_CAMPAIGNS").removesuffix("_CAMPAIGN")
        return destino in _CANAIS
    return tipo.removesuffix("_OPT_IN") in _CANAIS


def _o_que_o_proto_manda_confirmar() -> set[str]:
    """Os DOIS EIXOS, aplicados a TODOS os tipos que o v24 sabe nomear."""
    saida: set[str] = set()
    for tipo in TIPOS_CONHECIDOS:
        campos = _campos_do_tipo(tipo)
        if any(_ALAVANCA.search(c) for c in campos):
            saida.add(tipo)  # eixo 1.1 — alavanca de gasto declarada
        elif not campos and tipo.removesuffix("_OPT_IN") in _ESTRATEGIAS_DE_LANCE:
            # Mensagem vazia = ausencia de PARAMETRO (a troca de estrategia nao
            # tem numero a escolher), nao ausencia de efeito sobre o lance.
            saida.add(tipo)  # eixo 1.2
        # `if` proprio, nao `elif`: os eixos sao independentes, e um tipo futuro
        # pode satisfazer os dois. Encadear esconderia o segundo atras do primeiro.
        if _migra_a_campanha(tipo):
            saida.add(tipo)  # eixo 2 — irreversivel
    return saida


def test_a_varredura_do_proto_ve_a_populacao_inteira() -> None:
    """Sem isto o guard passaria verde varrendo zero tipos (F155, vacuidade)."""
    assert len(TIPOS_CONHECIDOS) >= 54, f"so {len(TIPOS_CONHECIDOS)} tipos no enum do v24"
    faltando = sorted(t for t in TIPOS_CONHECIDOS if t.lower() + "_recommendation" not in _DETALHES)
    assert not faltando, f"tipos do enum sem mensagem de detalhe no proto: {faltando}"


def test_a_varredura_do_eixo_2_ve_a_populacao_de_canais() -> None:
    """Sem isto, `_CANAIS` vazio faria `_migra_a_campanha` devolver False sempre."""
    assert len(_CANAIS) >= 12, f"so {len(_CANAIS)} canais no enum do v24"
    assert "PERFORMANCE_MAX" in _CANAIS


def test_o_eixo_da_irreversibilidade_bate_com_a_lista_escrita_em_src() -> None:
    """Nos DOIS sentidos, contra `TIPOS_DE_MIGRACAO` — que e literal em `src/`.

    Migracao nova que o Google lancar (`*_TO_<CANAL>`) derruba este teste em vez
    de entrar calada no ramo auto: foi assim que os cinco de hoje entraram.
    """
    do_proto = {tipo for tipo in TIPOS_CONHECIDOS if _migra_a_campanha(tipo)}
    assert do_proto == set(TIPOS_DE_MIGRACAO), (
        f"migram e nao estao em TIPOS_DE_MIGRACAO: {sorted(do_proto - set(TIPOS_DE_MIGRACAO))}; "
        f"estao e o proto nao respalda: {sorted(set(TIPOS_DE_MIGRACAO) - do_proto)}"
    )
    assert do_proto, "eixo 2 varreu zero tipos"
    assert do_proto <= set(TIPOS_QUE_CONFIRMAM), (
        f"migracao fora da whitelist (auto-aplicaria sem volta): "
        f"{sorted(do_proto - set(TIPOS_QUE_CONFIRMAM))}"
    )


@pytest.mark.parametrize(
    "tipo",
    [
        # Tem "PERFORMANCE_MAX" no nome e NAO e migracao: liga expansao de URL
        # numa PMax que ja existe, e desliga de volta.
        "PERFORMANCE_MAX_FINAL_URL_OPT_IN",
        # Idem, e sem `_TO_` nem `_OPT_IN`.
        "IMPROVE_PERFORMANCE_MAX_AD_STRENGTH",
        # Tem `_TO_`, mas o destino e `CAMPAIGN`, que nao e canal.
        "SHOPPING_ADD_PRODUCTS_TO_CAMPAIGN",
        # `_OPT_IN` de rede e de formato, nao de tipo de campanha.
        "SEARCH_PARTNERS_OPT_IN",
        "DISPLAY_EXPANSION_OPT_IN",
        "DYNAMIC_IMAGE_EXTENSION_OPT_IN",
    ],
)
def test_o_eixo_da_irreversibilidade_nao_arrasta_os_quase_casos(tipo: str) -> None:
    """Sem esta contraprova, "tudo e migracao" passaria e o eixo 2 nao filtraria nada.

    A alternativa larga que a revisao considerou — "mensagem vazia => CONFIRM" —
    arrastaria estes tipos, e confirmar o que nao precisa treina o gestor a clicar
    sem ler (o mesmo motivo escrito para deixar `KEYWORD` de fora).
    """
    assert tipo in TIPOS_CONHECIDOS, f"{tipo} sumiu do enum do v24 — rever o caso"
    assert not _migra_a_campanha(tipo), f"{tipo} classificado como migracao"
    assert tipo not in TIPOS_DE_MIGRACAO


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
