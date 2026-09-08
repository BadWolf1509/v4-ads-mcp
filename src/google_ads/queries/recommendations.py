"""Consultas GAQL + tabela de tipos das recomendacoes do Google Ads.

**A superficie que a GAQL aceita nao e a do proto (classe F87/F89).** Cada tipo
de recomendacao guarda seus numeros num campo de detalhe proprio
(`recommendation.campaign_budget_recommendation` e irmaos). O proto do SDK expoe
as FOLHAS desse campo (`google/ads/googleads/v24/resources/types/recommendation.py`
:575,580 — `current_budget_amount_micros`, `recommended_budget_amount_micros`),
mas a GAQL **nao** as expoe individualmente. Probado em 07/09 na conta
`1171969590` via `validate_gaql`:

    recommendation.campaign_budget_recommendation                    -> valid
    recommendation.campaign_budget_recommendation
        .current_budget_amount_micros                                -> Unrecognized fields

Seleciona-se a MENSAGEM; o SDK a popula; o Python le a folha do objeto. Quem
escrever a query olhando o proto erra.

`CAMPOS_DE_DETALHE` tem os 23 tipos que mexem em ORCAMENTO ou LANCE, ou que
MIGRAM a campanha. Os campos de detalhe foram validados por `validate_gaql` em
07/09, um a um e todos juntos; a linha viva da 1171969590 (`CAMPAIGN_BUDGET`,
campanha 22922100363) devolveu `current_budget_amount_micros: 50000000` e
`recommended_budget_amount_micros: 180000000` — o aumento de 3,6x que ate 07/09
se aplicava sem preview nenhum.

**Como a lista foi escolhida — e as duas vezes que o criterio estava errado.** A
primeira versao saiu de um `grep` do enum por `BUDGET|BID|TARGET_CPA|TARGET_ROAS|
MAXIMIZE|ENHANCED_CPC|ROI|CPC` (17 tipos), e filtro por NOME nao e probe: o
`USE_BROAD_MATCH_KEYWORD` nao casa nenhum daqueles padroes, converte **todas** as
keywords da campanha para correspondencia ampla, e declara no proto o MESMO campo
(`required_campaign_budget_amount_micros`) que ja punha o `TARGET_ROAS_OPT_IN`
dentro da lista. Um campo identico decidindo o oposto e a prova de que o criterio
era o nome, nao o efeito. Com o proto no lugar do grep, 18.

A segunda versao (18) tinha um eixo faltando, nao um tipo. O criterio dizia
"a mensagem de detalhe declara alavanca de gasto ja existente" — e **migracao nao
declara alavanca: ela substitui a campanha**. Os cinco tipos que convertem a
campanha para Performance Max caiam no ramo AUTO, isto e, uma chamada sem token e
sem preview trocava o tipo da campanha **sem caminho de volta**, enquanto a porta
direta equivalente (`update_campaign_bidding`) e sempre CONFIRM. Irreversibilidade
e um eixo proprio: "quanto muda" e "da pra desfazer" sao perguntas diferentes, e a
segunda nao se responde olhando os campos da mensagem.

**O criterio, por extenso.** O criterio e o PROTO
(`v24/resources/types/recommendation.py`) lido campo a campo, mais o enum de tipos
de campanha do mesmo SDK. Entra na tabela o tipo que satisfaz **qualquer** um dos
dois eixos:

**Eixo 1 — a recomendacao mexe numa alavanca de gasto que JA existe.** Vale se a
mensagem de detalhe do tipo:

1. declara um campo de **alavanca de gasto ja existente** — orcamento
   (`*budget*amount_micros`, `*budget.current_amount_micros`,
   `*budget.recommended_new_amount_micros`), alvo de lance
   (`*target_cpa_micros`, `*target_roas`, `*target_multiplier`,
   `*average_target_micros`), CPC (`*cpc_bid_micros`) ou o flag de orcamento
   compartilhado (`*uses_shared_budget`); **ou**
2. e **vazia** e o nome do tipo, sem o sufixo `_OPT_IN`, e um valor de
   `BiddingStrategyTypeEnum` — `ENHANCED_CPC_OPT_IN` e
   `MAXIMIZE_CONVERSION_VALUE_OPT_IN`. Mensagem vazia ali e ausencia de
   PARAMETRO (a troca de estrategia nao tem numero a escolher), nao ausencia de
   efeito sobre o lance.

**Eixo 2 — a recomendacao e IRREVERSIVEL porque MIGRA a campanha para outro tipo
de campanha.** Vale se o nome do tipo declara a migracao e o **destino** e um
valor de `AdvertisingChannelTypeEnum` — ou seja `<CANAL>_OPT_IN`, ou
`..._TO_<CANAL>` (com `_CAMPAIGN`/`_CAMPAIGNS` opcional no fim). Sao cinco:
`PERFORMANCE_MAX_OPT_IN`, `UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX`,
`UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX`,
`MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX` e
`SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX` (ver
`TIPOS_DE_MIGRACAO`). Os campos da mensagem nao decidem nada aqui: tres delas sao
vazias e as outras duas so trazem identificadores do Merchant Center — o que
decide e que a campanha **deixa de ser o que era**. Uma campanha Performance Max
opera apenas sob Smart Bidding, entao a migracao troca junto a estrategia de
lance, e o Google nao expoe operacao inversa.

O eixo 2 e ancorado no enum de canal pelo mesmo motivo que o eixo 1.2 e ancorado
no de estrategia de lance: e uma lista que o Google mantem, nao um padrao que
alguem aqui inventou. E ele separa os quase-casos sozinho —
`PERFORMANCE_MAX_FINAL_URL_OPT_IN` (raiz `PERFORMANCE_MAX_FINAL_URL`, que nao e
canal: liga expansao de URL numa PMax que ja existe, e desliga de volta),
`IMPROVE_PERFORMANCE_MAX_AD_STRENGTH` (nem `_TO_` nem `_OPT_IN`) e
`SHOPPING_ADD_PRODUCTS_TO_CAMPAIGN` (destino `CAMPAIGN`, que nao e canal) ficam
todos de fora.

A UNICA excecao escrita e o `KEYWORD`, que passa no eixo 1 por
`recommended_cpc_bid_micros` e mesmo assim fica de FORA: aquele CPC e atributo de
uma palavra-chave que ainda **nao existe**, nao mudanca de uma alavanca que ja
esta gastando — nem o orcamento diario nem nenhum lance vigente se movem. A porta
equivalente deste MCP, `add_keywords` com 1 entidade, e AUTO (spec §7.1); por-la
sob confirmacao aqui repetiria, espelhada, a incoerencia que o C2 veio fechar. E
`KEYWORD` e o tipo mais numeroso de uma conta real (uma recomendacao por
ad_group): confirmar o que nao precisa treina o gestor a clicar sem ler.

**O que a tabela LE de cada mensagem (I2 da revisao final).** Entrar na whitelist
e mostrar o numero sao coisas diferentes, e a versao de 07/09 acertava a primeira
e errava a segunda: `SET_TARGET_CPA`, `SET_TARGET_ROAS` e as duas variantes
`FORECASTING_*` declaram um `campaign_budget` — orcamento atual e novo — na
PROPRIA mensagem, e o preview so mostrava o alvo de CPA/ROAS. O gestor confirmava
"Definir Target CPA R$ 77,00" e aplicava junto uma mudanca de orcamento diario que
nunca lhe foi mostrada. Pior: o irmao `TARGET_ROAS_OPT_IN` ja lia o campo
equivalente, entao a tabela se contradizia.

Conferido tipo a tipo contra o descriptor, nao por amostragem. O que fica de FORA
tem motivo escrito, porque omissao sem motivo e a mesma classe de bug:

* `*_recommendation.budget_options[]` (nos 3 tipos de orcamento e dentro do
  `MOVE_UNUSED_BUDGET`) — e a GRADE de opcoes com projecao de impacto, nao o valor
  recomendado; este ja e lido do campo singular ao lado. Mostrar a grade inteira
  num resumo de uma linha e ruido, e escolher uma opcao dela seria inventar
  decisao;
* `use_broad_match_keyword_recommendation.keyword[]` — `KeywordInfo` de amostra,
  fora da raiz `Recommendation` (o guard nem desce ali); quantas keywords viram
  ampla ja e dito pelas duas contagens;
* `raise_target_cpa_recommendation.app_bidding_goal` — enum, e so popula em
  campanha de APP; nao e alavanca nem valor, e emitir
  `APP_BIDDING_GOAL_UNSPECIFIED` em todo preview de conta de Search seria ruido;
* `merchant.id` / `merchant.multi_client` e `campaign_budget.new_start_date` dos
  dois `SET_TARGET_*` nao-forecasting — o proto diz, verbatim, que `new_start_date`
  so e preenchido em `FORECASTING_SET_TARGET_ROAS` e `FORECASTING_SET_TARGET_CPA`,
  e e nesses dois que a tabela o le.

**Ausencia nao e zero (F145 pela porta dos fundos).** proto-plus nunca omite
atributo: `campaign_budget` nao preenchido devolve o zero-value, e ler dali daria
"R$ 0,00 -> R$ 0,00" no preview — numero inventado com cara de medido. Por isso
`_valor_de` consulta a PRESENCA de cada segmento antes de emitir a chave, e chave
ausente simplesmente nao aparece em `valores`.

**E ausencia tambem nao pode DESLOCAR o vizinho.** O `TARGET_CPA_OPT_IN` traz uma
GRADE de metas (`options`, REPEATED), cada uma com o seu CPA e o orcamento que ELA
exigiria. Ler as duas folhas como duas listas irmas, pareadas por posicao, era
correto so enquanto toda opcao declarasse as duas: com uma opcao sem orcamento as
listas encurtavam em pontos diferentes e o preview dava o orcamento de uma opcao
ao CPA de outra. A grade sai como UM REGISTRO POR OPCAO — ver `ListaDeOpcoes`.

O guard `tests/unit/test_whitelist_de_recomendacao_bate_com_o_proto.py` refaz essa
varredura no descriptor a cada run — tipo novo que o Google adicionar com campo de
orcamento ou lance derruba o teste em vez de entrar calado. Ele tambem cobra a
COMPLETUDE (toda folha de alavanca de um tipo da whitelist e lida, ou tem excecao
escrita) e a CARDINALIDADE (segmento repetido leva `[]`, singular nao leva) — foi
a cardinalidade que mostrou que `TARGET_CPA_OPT_IN.options` e REPEATED, e que a
correcao "obvia" (`options.required_campaign_budget_amount_micros`) levantaria
`AttributeError` em producao.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from google.ads.googleads.v24.enums.types.recommendation_type import RecommendationTypeEnum

from src.google_ads.queries._common import micros_to_currency
from src.google_ads.queries._gaql import gaql_string_literal

# Unidade de cada valor lido do detalhe:
#   brl      — campo `*_micros` de DINHEIRO; vira reais (micros / 1e6, 2 casas)
#   razao    — campo `*_micros` de RAZAO (ROAS); vira o numero puro, nunca "R$"
#   numero   — ja e um numero direto (multiplicador)
#   inteiro  — contagem (`*_count`); int, nunca float — "120 keywords", nao "120.0"
#   booleano — flag do proto; sai True/False, nao 1.0/0.0 nem "True"
#   texto    — resource name / string
Unidade = Literal["brl", "razao", "numero", "inteiro", "booleano", "texto"]

# Sentinela de "o proto nao declarou nada neste caminho" — distinta de `None`,
# que e um valor legitimo, e de `0`, que e o zero-value do F145.
_AUSENTE: Any = object()


@dataclass(frozen=True, slots=True)
class DetalheDoTipo:
    """Onde vive o numero de um tipo de recomendacao.

    `campo` e o campo de detalhe SELECIONAVEL na GAQL (a mensagem inteira).
    `atual_brl` / `recomendado_brl` sao caminhos dotted DENTRO dela para os dois
    valores monetarios da MESMA dimensao — sao eles que viram
    `current_amount_brl` / `recommended_amount_brl` no preview. Tipo que nao tem
    a dimensao (ou cujo valor e razao, nao dinheiro) deixa `None` e poe o que
    tiver em `outros`, cada item `(chave_de_saida, caminho_dotted, unidade)`.

    Todo caminho de `outros` e SINGULAR. Campo REPEATED nao entra ali: ele vai em
    `opcoes` e sai como LISTA DE REGISTROS — ver `ListaDeOpcoes` para o preview
    errado que a forma anterior produzia.
    """

    campo: str
    atual_brl: str | None = None
    recomendado_brl: str | None = None
    outros: tuple[tuple[str, str, Unidade], ...] = field(default=())
    derivado: ProdutoDerivado | None = None
    opcoes: ListaDeOpcoes | None = None


@dataclass(frozen=True, slots=True)
class ProdutoDerivado:
    """O valor NOVO de um alvo que o proto declara por FATORES (I4).

    `RAISE_TARGET_CPA`, `RAISE_TARGET_CPA_BID_TOO_LOW` e `LOWER_TARGET_ROAS` nao
    trazem o alvo resultante: trazem a ancora ("the current average target") e o
    multiplicador ("the factor by which we recommend the target to be adjusted
    by"). O preview mostrava os dois fatores e nunca o produto, entao quem
    confirmava fazia a multiplicacao de cabeca — ou nao fazia. E a Global
    Constraint do PR ("confirmar sem ver o numero nao e confirmar") aplicada a um
    alvo de lance em vez de a um orcamento.

    `unidade` NAO e detalhe: nos dois CPA o produto e DINHEIRO (2 casas, com
    "R$"), no ROAS e RAZAO (4 casas, nunca "R$"). Somar ou formatar os dois igual
    seria erro de unidade num numero que o gestor usa pra decidir.

    `ancora` e `multiplicador` sao chaves da SAIDA ja convertida — nao caminhos do
    proto. Multiplicar micros por fator e depois converter daria o mesmo numero,
    mas duplicaria a regra de unidade, que e justamente o que se quer num lugar so.
    """

    chave: str
    ancora: str
    multiplicador: str
    unidade: Unidade


@dataclass(frozen=True, slots=True)
class ListaDeOpcoes:
    """Campo REPEATED lido como LISTA DE REGISTROS — nao como listas paralelas.

    `TargetCpaOptInRecommendation.options` e a grade de metas disponiveis: cada
    item traz o CPA daquela meta E o orcamento que ELA exigiria. Ate 07/09 a
    tabela lia os dois como duas listas irmas (`options[].target_cpa_micros` e
    `options[].required_campaign_budget_amount_micros`), pareadas por POSICAO — e
    as duas folhas sao `optional` no v24, entao a leitura descartava o item
    ausente e as listas encurtavam em pontos diferentes. Medido: opcao 1 sem
    orcamento, opcao 2 exigindo R$ 200,00 devolvia

        target_cpa_por_opcao_brl        = [50.0, 70.0]
        orcamento_exigido_por_opcao_brl = [200.0]

    e o gestor lia os R$ 200,00 como exigencia do CPA de 50 — que e o CPA da
    opcao SEM orcamento. O preview mentia exatamente no momento em que ele
    confirma dinheiro, que e a tese inteira deste gate.

    **Por que REGISTRO e nao lista realinhada.** Enfileirar `None` no buraco
    tambem realinha, mas mantem o pareamento como INVARIANTE que alguem tem que
    preservar: quem le faz o zip de cabeca, e o proximo consumidor que filtrar,
    ordenar ou compactar uma das listas reintroduz o mesmo bug calado. Registro
    nao tem posicao a errar — e o passo classico de *parallel arrays* para
    *array of records*. Opcao que nao declara um dos campos simplesmente nao traz
    aquela chave, e a ausencia fica presa DENTRO da opcao a que pertence.

    `caminho` e o segmento repetido COM o marcador `[]`; `campos` sao os caminhos
    dotted dentro de CADA item. O `[]` nao e acucar sintatico: `getattr` num
    `RepeatedComposite` levanta `AttributeError`, entao
    `options.required_campaign_budget_amount_micros` (a forma que a revisao da
    Task 2 sugeriu) quebraria em producao — e o guard de EXISTENCIA passaria
    verde, porque a folha existe no descriptor. E o marcador e o que deixa a
    cardinalidade verificavel pelo guard do proto, que continua cobrando as duas
    folhas por aqui.
    """

    chave: str
    caminho: str
    campos: tuple[tuple[str, str, Unidade], ...]


# Os tres tipos de orcamento compartilham a mesma mensagem (CampaignBudgetRecommendation).
_ORCAMENTO = ("current_budget_amount_micros", "recommended_budget_amount_micros")
_ROAS_RECOMENDADO: tuple[tuple[str, str, Unidade], ...] = (
    ("target_roas_recomendado", "recommended_target_roas", "numero"),
)
# `SET_TARGET_CPA`, `SET_TARGET_ROAS` e as duas variantes FORECASTING_* declaram
# a mesma mensagem `CampaignBudget` aninhada: o alvo novo vem acompanhado do
# ORCAMENTO que ele exige. E outra dimensao que o alvo, entao vai em `outros` — e
# ate 07/09 nao ia a lugar nenhum (I2). Presenca gateia as duas chaves: quando a
# recomendacao nao propoe orcamento, `campaign_budget` chega zerado e o preview
# diria "R$ 0,00 -> R$ 0,00".
_ORCAMENTO_DO_ALVO: tuple[tuple[str, str, Unidade], ...] = (
    ("orcamento_atual_brl", "campaign_budget.current_amount_micros", "brl"),
    ("orcamento_novo_brl", "campaign_budget.recommended_new_amount_micros", "brl"),
)
# So os dois FORECASTING_*: o proto diz, verbatim, que `new_start_date` "will be
# set for the following recommendation types: FORECASTING_SET_TARGET_ROAS,
# FORECASTING_SET_TARGET_CPA".
_INICIO_DO_ORCAMENTO: tuple[tuple[str, str, Unidade], ...] = (
    ("orcamento_novo_a_partir_de", "campaign_budget.new_start_date", "texto"),
)

CAMPOS_DE_DETALHE: dict[str, DetalheDoTipo] = {
    # --- orcamento: os unicos com atual E recomendado na mesma mensagem ---
    "CAMPAIGN_BUDGET": DetalheDoTipo("campaign_budget_recommendation", *_ORCAMENTO),
    "FORECASTING_CAMPAIGN_BUDGET": DetalheDoTipo(
        "forecasting_campaign_budget_recommendation", *_ORCAMENTO
    ),
    "MARGINAL_ROI_CAMPAIGN_BUDGET": DetalheDoTipo(
        "marginal_roi_campaign_budget_recommendation", *_ORCAMENTO
    ),
    "MOVE_UNUSED_BUDGET": DetalheDoTipo(
        "move_unused_budget_recommendation",
        "budget_recommendation.current_budget_amount_micros",
        "budget_recommendation.recommended_budget_amount_micros",
        (("orcamento_de_origem", "excess_campaign_budget", "texto"),),
    ),
    # --- opt-ins que trazem o orcamento que a estrategia nova exige ---
    "MAXIMIZE_CLICKS_OPT_IN": DetalheDoTipo(
        "maximize_clicks_opt_in_recommendation", None, "recommended_budget_amount_micros"
    ),
    "MAXIMIZE_CONVERSIONS_OPT_IN": DetalheDoTipo(
        "maximize_conversions_opt_in_recommendation", None, "recommended_budget_amount_micros"
    ),
    # --- alvos de CPA (dinheiro) ---
    # `options` e REPEATED (`TargetCpaOptInRecommendationOption`): sao as metas
    # disponiveis, cada uma com o CPA e o orcamento que ELA exigiria. Nao ha UM
    # orcamento a mostrar, ha a grade — e ela sai como UM REGISTRO POR OPCAO, com
    # os dois numeros da MESMA opcao juntos. Duas listas pareadas por posicao (a
    # forma ate 07/09) davam o orcamento de uma opcao ao CPA de outra assim que
    # uma delas nao declarasse o campo; ver `ListaDeOpcoes`.
    "TARGET_CPA_OPT_IN": DetalheDoTipo(
        "target_cpa_opt_in_recommendation",
        None,
        "recommended_target_cpa_micros",
        opcoes=ListaDeOpcoes(
            "opcoes_de_target_cpa",
            "options[]",
            (
                ("target_cpa_brl", "target_cpa_micros", "brl"),
                ("orcamento_exigido_brl", "required_campaign_budget_amount_micros", "brl"),
            ),
        ),
    ),
    "SET_TARGET_CPA": DetalheDoTipo(
        "set_target_cpa_recommendation",
        None,
        "recommended_target_cpa_micros",
        _ORCAMENTO_DO_ALVO,
    ),
    "FORECASTING_SET_TARGET_CPA": DetalheDoTipo(
        "forecasting_set_target_cpa_recommendation",
        None,
        "recommended_target_cpa_micros",
        _ORCAMENTO_DO_ALVO + _INICIO_DO_ORCAMENTO,
    ),
    # `target_adjustment.shared_set` (I3): o proto diz, verbatim, "the shared set
    # resource name of the portfolio bidding strategy where the target is defined.
    # Only populated if the recommendation is portfolio level". E o irmao exato do
    # `campaign_budget.explicitly_shared` que o C1 fechou no `update_campaign_budget`:
    # sem ele o preview nomeia UMA campanha enquanto a mutacao atinge todas as que
    # compartilham a estrategia. `optional` no proto, entao a presenca decide — em
    # recomendacao de nivel campanha a chave simplesmente nao aparece.
    "RAISE_TARGET_CPA": DetalheDoTipo(
        "raise_target_cpa_recommendation",
        "target_adjustment.current_average_target_micros",
        None,
        (
            (
                "multiplicador_recomendado",
                "target_adjustment.recommended_target_multiplier",
                "numero",
            ),
            ("estrategia_de_portfolio", "target_adjustment.shared_set", "texto"),
        ),
        ProdutoDerivado(
            "target_cpa_novo_brl", "current_amount_brl", "multiplicador_recomendado", "brl"
        ),
    ),
    "RAISE_TARGET_CPA_BID_TOO_LOW": DetalheDoTipo(
        "raise_target_cpa_bid_too_low_recommendation",
        "average_target_cpa_micros",
        None,
        (("multiplicador_recomendado", "recommended_target_multiplier", "numero"),),
        ProdutoDerivado(
            "target_cpa_novo_brl", "current_amount_brl", "multiplicador_recomendado", "brl"
        ),
    ),
    # --- alvos de ROAS (razao: nunca vira "R$") ---
    "TARGET_ROAS_OPT_IN": DetalheDoTipo(
        "target_roas_opt_in_recommendation",
        None,
        None,
        (
            ("target_roas_recomendado", "recommended_target_roas", "numero"),
            ("orcamento_exigido_brl", "required_campaign_budget_amount_micros", "brl"),
        ),
    ),
    "SET_TARGET_ROAS": DetalheDoTipo(
        "set_target_roas_recommendation", None, None, _ROAS_RECOMENDADO + _ORCAMENTO_DO_ALVO
    ),
    "FORECASTING_SET_TARGET_ROAS": DetalheDoTipo(
        "forecasting_set_target_roas_recommendation",
        None,
        None,
        _ROAS_RECOMENDADO + _ORCAMENTO_DO_ALVO + _INICIO_DO_ORCAMENTO,
    ),
    "LOWER_TARGET_ROAS": DetalheDoTipo(
        "lower_target_roas_recommendation",
        None,
        None,
        (
            ("target_roas_atual", "target_adjustment.current_average_target_micros", "razao"),
            (
                "multiplicador_recomendado",
                "target_adjustment.recommended_target_multiplier",
                "numero",
            ),
            ("estrategia_de_portfolio", "target_adjustment.shared_set", "texto"),
        ),
        # ROAS e RAZAO: o produto sai como 3.6, nunca como "R$ 3,60".
        ProdutoDerivado(
            "target_roas_novo", "target_roas_atual", "multiplicador_recomendado", "razao"
        ),
    ),
    # --- converte TODAS as keywords da campanha para ampla ---
    # Ficou fora da primeira lista porque o nome nao casava o grep (`BUDGET|BID|
    # ...`) — e declara o MESMO `required_campaign_budget_amount_micros` que ja
    # punha o TARGET_ROAS_OPT_IN dentro dela: "the budget recommended to avoid
    # becoming budget constrained after applying the recommendation". O preview
    # mostra os tres fatos decisorios: quantas das quantas keywords viram ampla,
    # quanto orcamento isso vai exigir, e se o orcamento e COMPARTILHADO (nesse
    # caso subir o valor realoca gasto das campanhas irmas, nao acrescenta — C1).
    #
    # Probe (07/09): `recommendation.use_broad_match_keyword_recommendation` e
    # selecionavel — `validate_gaql` valida sozinho e junto com os outros 17, e o
    # SELECT completo de 21 campos devolveu linha viva de OUTRO tipo sem quebrar
    # (`MARGINAL_ROI_CAMPAIGN_BUDGET` na 5894449831). O que NAO foi medido em
    # linha viva sao as folhas: nenhuma das 26 contas do MCC tinha uma
    # recomendacao deste tipo pendente em 07/09. Os caminhos vem do descriptor do
    # v24 e o guard do proto os reconfere a cada run.
    "USE_BROAD_MATCH_KEYWORD": DetalheDoTipo(
        "use_broad_match_keyword_recommendation",
        None,
        None,
        (
            ("orcamento_exigido_brl", "required_campaign_budget_amount_micros", "brl"),
            ("keywords_que_viram_ampla", "suggested_keywords_count", "inteiro"),
            ("keywords_na_campanha", "campaign_keywords_count", "inteiro"),
            ("orcamento_compartilhado", "campaign_uses_shared_budget", "booleano"),
        ),
    ),
    # --- os dois sem numero nenhum: a mensagem e VAZIA no v24 ---
    # Nao e omissao: `EnhancedCpcOptInRecommendation` e
    # `MaximizeConversionValueOptInRecommendation` nao declaram campo algum no
    # descriptor. O preview desses dois se apoia no contexto da campanha (ver
    # `campaign_context_query`) — e a estrategia de lance de hoje que eles trocam.
    "ENHANCED_CPC_OPT_IN": DetalheDoTipo("enhanced_cpc_opt_in_recommendation"),
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN": DetalheDoTipo(
        "maximize_conversion_value_opt_in_recommendation"
    ),
    # --- eixo 2: MIGRAM a campanha, e migracao nao tem volta ---
    # Nenhum destes declara alavanca de gasto — tres tem mensagem VAZIA e os
    # outros dois so trazem identificador de Merchant Center. Era exatamente por
    # isso que caiam no ramo AUTO ate 07/09: o criterio antigo perguntava so
    # "quanto muda", e a resposta aqui e "nada que a mensagem saiba dizer". O que
    # muda e o QUE a campanha e. Os cinco campos de detalhe foram validados por
    # `validate_gaql` na 1171969590 (07/09), um a um e junto com os outros 18.
    "PERFORMANCE_MAX_OPT_IN": DetalheDoTipo("performance_max_opt_in_recommendation"),
    "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX": DetalheDoTipo(
        "upgrade_local_campaign_to_performance_max_recommendation"
    ),
    "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX": DetalheDoTipo(
        "upgrade_smart_shopping_campaign_to_performance_max_recommendation",
        None,
        None,
        (
            ("merchant_center_id", "merchant_id", "inteiro"),
            ("pais_das_ofertas", "sales_country_code", "texto"),
        ),
    ),
    # `apply_link` e o unico campo desta mensagem, e e util de verdade: leva ao
    # painel onde o Google mostra o que a migracao faz. Nao substitui o aviso.
    "MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX": DetalheDoTipo(
        "migrate_dynamic_search_ads_campaign_to_performance_max_recommendation",
        None,
        None,
        (("link_do_painel", "apply_link", "texto"),),
    ),
    "SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX": DetalheDoTipo(
        "shopping_migrate_regular_shopping_campaign_offers_to_performance_max_recommendation",
        None,
        None,
        (
            ("merchant_center", "merchant.name", "texto"),
            ("feed_label", "feed_label", "texto"),
        ),
    ),
}

# DERIVADO, nao enumerado de novo: a lista dos 23 vive num lugar so. Acrescentar
# um tipo a tabela acima ja o poe sob confirmacao.
TIPOS_QUE_CONFIRMAM: frozenset[str] = frozenset(CAMPOS_DE_DETALHE)

# Os do EIXO 2. Escrita a mao aqui de proposito: o guard
# `test_whitelist_de_recomendacao_bate_com_o_proto.py` refaz a derivacao a partir
# do `AdvertisingChannelTypeEnum` e compara nos dois sentidos — duas fontes
# independentes. Derivar as duas do mesmo lugar daria um teste verdadeiro
# independente da implementacao.
#
# Quem le isto e o preview: migracao nao tem numero a mostrar, entao o que o
# gestor precisa ver antes de confirmar e que a conversao NAO TEM VOLTA.
TIPOS_DE_MIGRACAO: frozenset[str] = frozenset(
    {
        "PERFORMANCE_MAX_OPT_IN",
        "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX",
        "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX",
        "MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX",
        "SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX",
    }
)

# Todo tipo que o SDK v24 sabe nomear. `UNSPECIFIED` e `UNKNOWN` ficam de FORA de
# proposito: sao os dois valores com que o proprio proto diz "nao sei o que isto
# e" — o mesmo estado epistemico de um numero de enum que o v24 nao conhece.
#
# Serve ao `blast_radius`: tipo ausente daqui NUNCA e auto. O modulo declara na
# linha 3 que "unknown operations always require confirmation", e ate 07/09 o
# ramo de recomendacao fazia o contrario — um `type_` que o v24 nao conhece
# parseava como a string crua ("999"), caia no else e APLICAVA, com o resumo
# "Aplicar recomendacao 999". Desconhecido nao e "provavelmente inofensivo": e
# "nao sei o que isto faz com o dinheiro do cliente", e as duas leituras so
# coincidem enquanto o Google nao lanca um tipo novo de gasto — que e exatamente
# o que ele lanca (os UPGRADE_*_TO_PERFORMANCE_MAX entraram assim).
TIPOS_CONHECIDOS: frozenset[str] = frozenset(
    nome
    for nome in RecommendationTypeEnum.RecommendationType.__members__
    if nome not in ("UNSPECIFIED", "UNKNOWN")
)


TYPE_PT = {
    "KEYWORD": "Adicionar palavra-chave",
    "ADD_AGE_GROUP_CRITERION": "Adicionar criterio de faixa etaria",
    "TEXT_AD": "Criar texto de anuncio",
    "CALLOUT_EXTENSION": "Adicionar extensao de chamada",
    "CALLOUT_ASSET": "Adicionar asset de chamada",
    "SITELINK_EXTENSION": "Adicionar extensao de sitelink",
    "SITELINK_ASSET": "Adicionar asset de sitelink",
    "ENHANCED_CPC_OPT_IN": "Ativar lance otimizado",
    "SEARCH_PARTNERS_OPT_IN": "Ativar parceiros de pesquisa",
    "MAXIMIZE_CONVERSIONS_OPT_IN": "Migrar pra Maximizar conversoes",
    "MAXIMIZE_CLICKS_OPT_IN": "Migrar pra Maximizar clicks",
    "TARGET_CPA_OPT_IN": "Migrar pra Target CPA",
    "TARGET_ROAS_OPT_IN": "Migrar pra Target ROAS",
    "MAXIMIZE_CONVERSION_VALUE_OPT_IN": "Migrar pra Maximizar valor",
    "PERFORMANCE_MAX_OPT_IN": "Migrar pra Performance Max",
    "MOVE_UNUSED_BUDGET": "Mover orcamento nao usado",
    "FORECASTING_CAMPAIGN_BUDGET": "Aumentar orcamento da campanha",
    "CAMPAIGN_BUDGET": "Ajustar orcamento da campanha",
    "RESPONSIVE_SEARCH_AD": "Criar anuncio responsivo",
    "RESPONSIVE_SEARCH_AD_ASSET": "Adicionar asset em RSA",
    "RESPONSIVE_SEARCH_AD_IMPROVE_AD_STRENGTH": "Melhorar forca do RSA",
    "DYNAMIC_IMAGE_EXTENSION_OPT_IN": "Ativar imagens dinamicas",
    "USE_BROAD_MATCH_KEYWORD": "Usar correspondencia ampla",
    "DISPLAY_EXPANSION_OPT_IN": "Ativar expansao display",
    "LEAD_FORM_ASSET": "Adicionar formulario de leads",
    "IMPROVE_GOOGLE_TAG_COVERAGE": "Melhorar cobertura da Google Tag",
    # Forecasting variants (P3 dogfood F7 finding — FORECASTING_SET_TARGET_CPA missing)
    "FORECASTING_SET_TARGET_CPA": "Definir Target CPA previsto",
    "FORECASTING_SET_TARGET_ROAS": "Definir Target ROAS previsto",
    # Performance Max upgrades (Google pushes these aggressively in 2024+)
    "UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX": "Migrar Local pra Performance Max",
    "UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX": "Migrar Smart Shopping pra Performance Max",
    "MIGRATE_DYNAMIC_SEARCH_ADS_CAMPAIGN_TO_PERFORMANCE_MAX": (
        "Migrar Dynamic Search Ads pra Performance Max"
    ),
    "SHOPPING_MIGRATE_REGULAR_SHOPPING_CAMPAIGN_OFFERS_TO_PERFORMANCE_MAX": (
        "Migrar ofertas do Shopping comum pra Performance Max"
    ),
    "IMPROVE_PERFORMANCE_MAX_AD_STRENGTH": "Melhorar forca do Performance Max",
    # C2 — os que faltavam da familia de orcamento/lance. Sem traducao, o gestor
    # confirmaria uma mudanca de lance lendo so o enum em ingles.
    "MARGINAL_ROI_CAMPAIGN_BUDGET": "Ajustar orcamento pelo ROI marginal",
    "SET_TARGET_CPA": "Definir Target CPA",
    "SET_TARGET_ROAS": "Definir Target ROAS",
    "RAISE_TARGET_CPA": "Aumentar o Target CPA",
    "RAISE_TARGET_CPA_BID_TOO_LOW": "Aumentar o Target CPA (lance baixo demais)",
    "LOWER_TARGET_ROAS": "Reduzir o Target ROAS",
}


def recommendations_query(limit: int = 100) -> str:
    """All pending recommendations for the account.

    NOTE: Impact metrics (base_metrics.*, potential_metrics.*) intentionally
    omitted — they're selectable_with-restricted in v24 and depend on the
    recommendation type. Users can query specific types via run_gaql for
    detailed impact data.

    F98 — pede `limit + 1`: a linha extra é a sentinela que revela o corte. As
    recomendações escalam com o nº de ad_groups (`RESPONSIVE_SEARCH_AD_ASSET` e
    `KEYWORD` são por ad_group), então sem teto uma conta grande estoura o cap
    de token do MCP e a resposta inteira se perde.
    """
    return f"""
        SELECT
          recommendation.resource_name,
          recommendation.type,
          recommendation.dismissed
        FROM recommendation
        WHERE recommendation.dismissed = false
        LIMIT {limit + 1}
    """.strip()


def _campos_de_detalhe_selecionados() -> list[str]:
    """Os 23 campos de detalhe, ordenados — a lista sai da tabela, nao de uma copia."""
    return sorted({f"recommendation.{d.campo}" for d in CAMPOS_DE_DETALHE.values()})


def recommendation_detail_query(resource_name: str) -> str:
    """Uma recomendacao pelo resource_name, com tipo + o detalhe de todos os 23 tipos.

    **Sem join com `campaign` de proposito.** Selecionar `campaign.*` daqui faria
    um join implicito, e nao ha como medir (em 07/09 nenhuma conta do MCC tinha
    recomendacao de nivel CONTA viva) se isso derrubaria a linha de uma
    recomendacao sem campanha — que apareceria como "nao encontrada". O contexto
    da campanha vem de `campaign_context_query`, numa segunda ida que so o
    caminho de confirmacao paga.
    """
    campos = ",\n          ".join(
        [
            "recommendation.resource_name",
            "recommendation.type",
            "recommendation.campaign",
            *_campos_de_detalhe_selecionados(),
        ]
    )
    return f"""
        SELECT
          {campos}
        FROM recommendation
        WHERE recommendation.resource_name = {gaql_string_literal(resource_name)}
        LIMIT 1
    """.strip()


def campaign_context_query(campaign_id: str) -> str:
    """Estrategia de lance + orcamento diario de HOJE da campanha alvo.

    E o que o preview mostra quando o tipo nao carrega numero nenhum
    (`ENHANCED_CPC_OPT_IN`, `MAXIMIZE_CONVERSION_VALUE_OPT_IN`): a recomendacao
    troca a estrategia de lance, e a estrategia trocada e justamente esta.
    """
    if not campaign_id.isdigit():
        raise ValueError(f"campaign_id nao numerico: {campaign_id!r}")
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.bidding_strategy_type,
          campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.id = {campaign_id}
        LIMIT 1
    """.strip()


def campaigns_on_bidding_strategy_query(resource_name: str) -> str:
    """Campanhas VIVAS que compartilham uma estrategia de lance de portfolio (I3).

    Espelha o papel de `campaigns_on_budgets_query` no `update_campaign_budget`:
    quando o recurso mutado e compartilhado, o preview tem que dizer QUEM MAIS a
    mudanca atinge. Aqui o recurso e a estrategia, e o alvo (CPA/ROAS) vive nela.

    `campaign.bidding_strategy = '<resource>'` foi validado por `validate_gaql` na
    1171969590 em 07/09. Filtra `REMOVED` server-side, como a irma faz.
    """
    return f"""
        SELECT
          campaign.id,
          campaign.name,
          campaign.status,
          campaign.bidding_strategy
        FROM campaign
        WHERE campaign.bidding_strategy = {gaql_string_literal(resource_name)}
          AND campaign.status != 'REMOVED'
    """.strip()


def parse_campaign_on_bidding_strategy_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "status": _nome_do_enum(row.campaign.status),
    }


def _nome_do_enum(valor: Any) -> str:
    """proto-plus IntEnum -> nome; str continua str (mocks de teste)."""
    return str(valor.name) if hasattr(valor, "name") else str(valor)


def _ler(msg: Any, caminho: str) -> Any:
    """Le uma folha dotted DENTRO da mensagem de detalhe.

    Sem checagem de presenca: os dois usos (`atual_brl`/`recomendado_brl`) sao o
    valor PRIMARIO do tipo, que a mensagem daquele tipo sempre declara. Ausencia
    ali nao e "o Google nao propos isso", e sinal de que o campo saiu do SELECT —
    e o 0.0 resultante e justamente o que os fakes dirigidos pelo SELECT pegam.
    """
    for parte in caminho.split("."):
        msg = getattr(msg, parte)
    return msg


def _declarado(msg: Any, campo: str) -> bool:
    """O proto preencheu este campo?

    `in` do proto-plus e `HasField` pra campo com presenca declarada
    (`optional`/mensagem aninhada), "diferente do default" pros escalares e
    "nao vazio" pros repetidos. As tres leituras servem: em todas, `False`
    significa "nao ha nada aqui pra mostrar".
    """
    return bool(campo in msg)


def _valor_de(msg: Any, caminho: str, unidade: Unidade) -> Any:
    """O valor convertido, ou `_AUSENTE` quando o proto nao declarou nada ali.

    **Ausencia nao e zero (F145 pela porta dos fundos).** proto-plus nunca omite
    atributo: uma `SET_TARGET_CPA` que nao propoe orcamento devolve
    `campaign_budget` zerado, e emitir a chave assim mesmo poria
    "orcamento_atual_brl=0.0" num preview — numero inventado com cara de medido,
    exatamente o modo de falha que o F145 cataloga.

    A UNICA excecao e `booleano`: ali `False` e RESPOSTA, nao ausencia
    (`orcamento_compartilhado=False` diz "e exclusivo", que muda a decisao), e o
    `in` do proto-plus nao distingue as duas.

    **Caminho SINGULAR, sempre.** Campo REPEATED se le por `_opcoes`, que devolve
    um registro por item. Ate 07/09 esta funcao tambem descia no repetido e
    filtrava o ausente DENTRO da lista — e duas listas irmas encurtavam em pontos
    diferentes, pareando o orcamento de uma opcao com o CPA de outra
    (`ListaDeOpcoes`).
    """
    partes = caminho.split(".")
    for i, parte in enumerate(partes):
        e_folha = i == len(partes) - 1
        if not (e_folha and unidade == "booleano") and not _declarado(msg, parte):
            return _AUSENTE
        msg = getattr(msg, parte)
    return _converter(msg, unidade)


def _opcoes(msg: Any, spec: ListaDeOpcoes) -> list[dict[str, Any]]:
    """Um REGISTRO por opcao, na ordem e na quantidade em que o Google as mandou.

    Registro que sai sem chave nenhuma **nao e descartado**: a opcao existe, e
    some-la encolheria a grade sem dizer — a mesma familia de erro que o defeito
    corrigido aqui. O que falta no registro e o que AQUELA opcao nao declarou, e a
    ausencia fica presa na opcao a que pertence, nunca deslocando a vizinha.

    Repetido vazio (nenhuma opcao) devolve `[]`, e o chamador nao emite a chave —
    "sem opcao" nao vira lista vazia no preview.
    """
    nome = spec.caminho.removesuffix("[]")
    if not _declarado(msg, nome):
        return []
    registros: list[dict[str, Any]] = []
    for item in getattr(msg, nome):
        registro: dict[str, Any] = {}
        for chave, caminho, unidade in spec.campos:
            valor = _valor_de(item, caminho, unidade)
            if valor is not _AUSENTE:
                registro[chave] = valor
        registros.append(registro)
    return registros


def _converter(bruto: Any, unidade: Unidade) -> Any:
    if unidade == "brl":
        return micros_to_currency(int(bruto))
    if unidade == "razao":
        return round(int(bruto) / 1_000_000.0, 4)
    if unidade == "numero":
        return float(bruto)
    if unidade == "inteiro":
        return int(bruto)
    if unidade == "booleano":
        return bool(bruto)
    return str(bruto)


def id_da_campanha(resource_name: str) -> str | None:
    """`customers/1/campaigns/22922100363` -> `22922100363`; None se nao houver."""
    marcador = "/campaigns/"
    if marcador not in resource_name:
        return None
    cid = resource_name.rsplit(marcador, 1)[-1]
    return cid if cid.isdigit() else None


def _produto(
    derivado: ProdutoDerivado, atual: float | None, valores: dict[str, Any]
) -> float | None:
    """ancora x multiplicador, na unidade do alvo — ou `None` se faltar um fator.

    Fator zerado NAO vira produto zero: seria "R$ 0.00" com cara de valor medido
    (a familia do F145). Zero em ancora ou em multiplicador significa que o Google
    nao declarou aquele lado, e sem os dois nao ha o que derivar.
    """
    bruto = atual if derivado.ancora == "current_amount_brl" else valores.get(derivado.ancora)
    fator = valores.get(derivado.multiplicador)
    if not isinstance(bruto, (int, float)) or not isinstance(fator, (int, float)):
        return None
    if not bruto or not fator:
        return None
    casas = 2 if derivado.unidade == "brl" else 4
    return round(float(bruto) * float(fator), casas)


def chave_do_produto_derivado(tipo: str) -> str | None:
    """A chave que `frase_do_produto_derivado` ja renderiza — o consumidor a pula.

    Sem isto o produto sairia duas vezes no resumo: uma na frase que diz de onde
    ele veio, outra na listagem crua `chave=valor`.
    """
    spec = CAMPOS_DE_DETALHE.get(tipo)
    return spec.derivado.chave if spec is not None and spec.derivado is not None else None


def frase_do_produto_derivado(info: dict[str, Any]) -> str | None:
    """ "R$ 77.00 -> R$ 103.95 (derivado: atual x 1.35)", com a unidade certa.

    Marcado como DERIVADO de proposito: o Google nao declara este numero, e um
    valor calculado por nos exibido como se fosse dele apagaria a diferenca entre
    "o Google propoe" e "isto e o que dá". Os dois fatores continuam saindo em
    `valores` — mostrar o produto e ALEM deles, nao no lugar deles.

    Vive aqui, e nao na tool, porque a regra de unidade vive aqui: BRL leva "R$" e
    2 casas, RAZAO nao leva "R$" e vale ate 4.
    """
    spec = CAMPOS_DE_DETALHE.get(info["type"])
    if spec is None or spec.derivado is None:
        return None
    d = spec.derivado
    valores = info["valores"]
    produto = valores.get(d.chave)
    ancora = (
        info["current_amount_brl"] if d.ancora == "current_amount_brl" else valores.get(d.ancora)
    )
    fator = valores.get(d.multiplicador)
    if produto is None or ancora is None or fator is None:
        return None
    if d.unidade == "brl":
        return f"R$ {ancora:.2f} -> R$ {produto:.2f} (derivado: atual x {fator})"
    return f"alvo {ancora} -> {produto} (derivado: atual x {fator})"


def parse_recommendation_detail_row(row: Any) -> dict[str, Any]:
    """Tipo + os numeros do detalhe daquele tipo, ja em BRL onde e dinheiro.

    Campo de detalhe de OUTRO tipo chega com o zero-value do proto (F145) — por
    isso a leitura e keyed pelo `recommendation.type`, nunca por "qual campo veio
    preenchido".
    """
    rec = row.recommendation
    tipo = _nome_do_enum(rec.type)
    spec = CAMPOS_DE_DETALHE.get(tipo)

    atual: float | None = None
    recomendado: float | None = None
    valores: dict[str, Any] = {}
    if spec is not None:
        detalhe = getattr(rec, spec.campo)
        if spec.atual_brl is not None:
            atual = micros_to_currency(int(_ler(detalhe, spec.atual_brl)))
        if spec.recomendado_brl is not None:
            recomendado = micros_to_currency(int(_ler(detalhe, spec.recomendado_brl)))
        for chave, caminho, unidade in spec.outros:
            valor = _valor_de(detalhe, caminho, unidade)
            if valor is not _AUSENTE:
                valores[chave] = valor
        if spec.opcoes is not None:
            grade = _opcoes(detalhe, spec.opcoes)
            if grade:
                valores[spec.opcoes.chave] = grade
        if spec.derivado is not None:
            produto = _produto(spec.derivado, atual, valores)
            if produto is not None:
                valores[spec.derivado.chave] = produto

    campanha_rn = str(rec.campaign or "")
    return {
        "resource_name": str(rec.resource_name),
        "type": tipo,
        "type_pt": TYPE_PT.get(tipo),
        "campaign_resource_name": campanha_rn,
        "campaign_id": id_da_campanha(campanha_rn),
        "current_amount_brl": atual,
        "recommended_amount_brl": recomendado,
        "valores": valores,
    }


def parse_campaign_context_row(row: Any) -> dict[str, Any]:
    return {
        "campaign_id": str(row.campaign.id),
        "campaign_name": str(row.campaign.name),
        "status": _nome_do_enum(row.campaign.status),
        "bidding_strategy_type": _nome_do_enum(row.campaign.bidding_strategy_type),
        "daily_budget_brl": micros_to_currency(int(row.campaign_budget.amount_micros)),
    }


# --------------------------------------------------------------------------- #
# Concorrencia otimista entre o preview e o apply (mesmo padrao do
# `schedule_fingerprint`, Ruling 10 do ad_schedule).
# --------------------------------------------------------------------------- #
def recommendation_fingerprint(info: dict[str, Any]) -> dict[str, Any]:
    """Impressao dos NUMEROS que o preview prometeu — recomputada antes de aplicar.

    Quem resolve o valor de uma recomendacao e o Google, **na hora do apply**: a
    operacao viaja so com o `resource_name`, sem parametro nenhum. Entre o preview
    e a confirmacao passa o TTL inteiro (`DEFAULT_TTL_MINUTES`), e nele o Google pode
    revisar a recomendacao — o `blast_summary` continuaria dizendo
    "R$ 50,00 -> R$ 180,00" enquanto outro numero aterrissa. Mostrar o numero e o
    ponto inteiro do gate C2; um numero que pode nao valer mais nao gateia nada.

    Listas e dicts simples, nunca tuplas: isto atravessa JSONB no
    `pending_confirmations`, e tupla volta lista — comparar tupla com lista daria
    divergencia em TODO apply (a mesma armadilha do `schedule_fingerprint`).

    As duas pontas chamam ESTA funcao: fingerprint calculado de dois jeitos
    diferentes e a classe do F81 — cada lado certo sozinho, o par errado.
    """
    return {
        "type": info["type"],
        "current_amount_brl": info["current_amount_brl"],
        "recommended_amount_brl": info["recommended_amount_brl"],
        "valores": dict(info["valores"]),
    }


def descrever_divergencia(esperado: dict[str, Any], agora: dict[str, Any]) -> str:
    """O que mudou entre o preview e o apply, em PT-BR e com os dois valores.

    "A recomendacao mudou" sem dizer o que mudou obriga o gestor a refazer o
    preview so pra descobrir se a mudanca importa.
    """
    mudou: list[str] = []
    for chave in ("type", "current_amount_brl", "recommended_amount_brl"):
        if esperado.get(chave) != agora.get(chave):
            mudou.append(f"{chave}: {esperado.get(chave)} -> {agora.get(chave)}")
    antes: dict[str, Any] = esperado.get("valores") or {}
    depois: dict[str, Any] = agora.get("valores") or {}
    for chave in sorted(set(antes) | set(depois)):
        if antes.get(chave) != depois.get(chave):
            mudou.append(f"{chave}: {antes.get(chave)} -> {depois.get(chave)}")
    return "; ".join(mudou) if mudou else "o detalhe da recomendacao mudou"
