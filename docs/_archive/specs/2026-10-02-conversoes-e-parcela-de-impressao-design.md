# Conversões por ação e parcela de impressão — design

> Aprovado pelo Wellington em 02/10/2026 (escopo, abordagem A e as três seções do desenho).
> Branch `spec/conversoes-e-parcela`.

## 1. Problema, medido

O uso real de 30 dias (`audit_log`, até 30/09): 1.896 chamadas, e o **`run_gaql` é 38%** delas
(725). As 259 do `pedro.vytor` — o gestor que usa o MCP de verdade — vêm em rajadas de ~38
consultas por sessão (08, 09, 11, 14, 23 e 28/09): o roteiro do skill
`analise-performance-google-ads` do plugin `v4-trafego-google-ads`, que prescreve GAQL cru em
`references/queries-v4-ads.md`. Nas consultas `FROM customer` dele:

| o que pede | consultas | tool curada hoje |
|---|---|---|
| conversões por ação de conversão (`segments.conversion_action_name`, `conversions` × `all_conversions`) — a Q10 do skill, "OBRIGATÓRIO" | **94** | nenhuma |
| totais da conta em janela longa | 98 | `get_account_overview` (o skill não a usa para isso) |
| parcela de impressão (`search_impression_share`, perdida por orçamento e por classificação, topo) | no roteiro | nenhuma |

Parte dos 26 erros do `run_gaql` e das 184 chamadas de `validate_gaql` (37 com erro) é o LLM
acertando GAQL na mão.

## 2. Fatos sondados (02/10, Mestre da Obra – João Pessoa `7862230676`, só leitura)

1. **Recortar por ação de conversão recusa métrica de custo:** `segments.conversion_action_name`
   com `metrics.cost_micros` → erro da API ("unsupported metrics: 'cost_micros'"). Não existe CPA
   por ação.
2. **`metrics.conversions` por ação segue `include_in_conversions_metric`**, não `primary_for_goal`:
   "Clicks to call" (`primary_for_goal: true`, `include_in_conversions_metric: false`) veio
   `conversions 0` e `all_conversions 11`; "Whatsapp - JPA" (as duas `true`) veio 204/204. **A nota do
   plugin** ("`metrics.conversions` por action retorna mesmo se Secondary") **está errada** para esta
   conta e precisa sair do skill.
3. **Ação que o recurso `conversion_action` não devolve:** "Conversation started" (`7028680990`,
   categoria `UNKNOWN`) teve 173 conversões em setembro, e `FROM conversion_action WHERE
   conversion_action.id = 7028680990` devolve **0 linhas** (provavelmente gerenciada pelo Google ou
   de outra conta). As flags dela não são medíveis.
4. **Parcela de impressão:**
   - `FROM campaign`: os cinco campos (`search_impression_share`,
     `search_budget_lost_impression_share`, `search_rank_lost_impression_share`,
     `search_top_impression_share`, `search_absolute_top_impression_share`) aceitos com janela de data
     — medido 55,2%, 22,9%, 21,9%, 44,0%, 31,9% na campanha JPA.
   - `FROM customer`: os três primeiros aceitos (54,7%, 23,4%, 21,9%); **topo e topo absoluto
     recusados** ("could not support requested resources: 'CUSTOMER'").

## 3. Desenho (abordagem A: estender as tools que existem — nenhuma tool nova)

### 3.1 Conversão por ação: `breakdown='conversion_action'` no `get_performance_breakdown`

- Níveis: `account` (uma linha por ação) e `campaign` (campanha × ação). `_validate_combo` passa a
  aceitar `conversion_action` nos dois; os demais níveis seguem recusando com mensagem.
- **Query principal** (`FROM customer` ou `FROM campaign`): `segments.conversion_action`,
  `segments.conversion_action_name`, `segments.conversion_action_category`, `metrics.conversions`,
  `metrics.all_conversions`, `metrics.conversions_value`, `metrics.all_conversions_value`, janela de
  data; no nível campanha, `campaign.id` e `campaign.name` e o filtro de status como no resto do
  nível. `ORDER BY metrics.all_conversions DESC`, `LIMIT limit+1` (F98: a linha a mais revela o
  corte e sai da resposta). `filters_applied` derivado do WHERE (F191/F193).
- **Segunda query**, só com ação na resposta: `FROM conversion_action WHERE conversion_action.id IN
  (…)` (`int()` em cada id, F163; teto estrutural de ids, `LIMIT` estrutural), com
  `include_in_conversions_metric`, `primary_for_goal`, `status`, `type`.
- **Linha devolvida:** `conversion_action_id`, `conversion_action_name`, `categoria`, `conversions`,
  `all_conversions`, `conversions_value_brl`, `all_conversions_value_brl`, `conta_em_conversoes`
  (= `include_in_conversions_metric`), `primary_for_goal`; no nível campanha também `campaign_id` e
  `campaign_name`.
- **Ação ausente da segunda query:** `conta_em_conversoes: null`, `primary_for_goal: null` e
  `flags_motivo: "acao nao listada em conversion_action (gerenciada pelo Google ou de outra conta)"`.
  Nunca `false`: ausência de medição não é resposta (F191).
- **Sem custo, sem CPA por ação** (fato 1). As métricas comuns do breakdown (`impressions`, `clicks`,
  `cost_brl`, `ctr`, `cpc_brl`) não aparecem neste recorte.
- **Description:** que `conversions` só soma ações com `conta_em_conversoes: true` e `all_conversions`
  soma todas (fato 2); que não há custo nem CPA por ação; que as linhas deste recorte têm formato
  próprio; que `flags_motivo` explica flag `null`.

### 3.2 Parcela de impressão

- **`level='campaign'`** (sem breakdown): as linhas ganham os cinco campos do fato 4, na MESMA query —
  sem chamada a mais. Nomes na resposta: `parcela_impressao`, `perdida_orcamento`,
  `perdida_classificacao`, `parcela_topo`, `parcela_topo_absoluto` (fração 0–1, como o `ctr`).
- **`get_account_overview`**: `current` e `previous` ganham os três campos que existem em `customer`
  (tendência no mesmo comparativo). Topo e topo absoluto não existem nesse nível — dito na
  description, não emulado.
- **Campo ausente vira `null`, nunca `0`** — campanha que não é de pesquisa (Display, PMax) pode não
  ter o valor. **Primeira sonda do plano, com controle:** numa campanha não-search real, o campo vem
  ausente (sem presença no proto) ou zerado? O desenho do parse sai da medição (presença do campo no
  proto ou outra regra), não da suposição.
- **"< 10%":** o Google informa parcela abaixo de 10% como 0,0999; ecoar e explicar na description.

### 3.3 O que não muda

Nenhuma tool nova (catálogo 68, buckets intactos). Os recortes e níveis existentes mantêm o formato
de linha atual — as linhas de `level='campaign'` só ganham campos.

## 4. Guards (cada um visto falhar contra o código pré-fix, por sabotagem medida)

1. Flags vindas da segunda query; ação ausente → `null` com `flags_motivo` (sabotagem: `False` no lugar
   de `None`).
2. Linha sentinela e `truncated` no recorte por ação.
3. `filters_applied` derivado nas duas queries novas (o guard derivado do SQL que já existe precisa
   enxergá-las — a função nova entra no `_chamadas()` dele).
4. `int()` no `IN` da segunda query (id não numérico recusado).
5. Parcela de impressão ausente → `null`, presente → o valor (a forma da regra sai da sonda 3.2).
6. Description: os contratos do 3.1 e do 3.2 ditos no texto (o guard de description que já existe
   para `filters_applied`/razão `null` é o modelo).
7. As queries validadas contra a API (`validate_gaql` e leitura) na Mestre da Obra antes do deploy.

## 5. Plugin (na fonte, com o Wellington)

Texto redigido por mim, aplicado por ele no `v4-trafego-google-ads`, junto com o ajuste do `null`
pendente desde 26/09:
- Q10 → `get_performance_breakdown(level='account'|'campaign', breakdown='conversion_action')`;
  parcela de impressão → `level='campaign'` e `get_account_overview`.
- **Remover a nota errada** do fato 2 (`shared/v4-brand.md:132`, `playbook-otimizacao.md:123`,
  `queries-v4-ads.md:11`) e a afirmação de que **não há hora × dia por campanha** em tool nenhuma
  (`SKILL.md:58-59`): `get_performance_breakdown(level='campaign', breakdown='hourly',
  campaign_ids=[…])` existe.

## 6. Fora, com o motivo

- **Cidade, série diária, demografia** — o skill também pede em GAQL cru, mas o uso medido não
  justifica agora; specs próprias se o uso pedir.
- **CPA por ação** — a API não dá (fato 1); custo e conversão por ação só se cruzam por estimativa,
  que não entra.
- **Topo e topo absoluto na conta** — a API não dá (fato 4).

## 7. Verificação em produção

Depois do deploy, smoke de leitura na Mestre da Obra: o recorte por ação com "Whatsapp - JPA"
`conta_em_conversoes: true`, "Clicks to call" `false` e "Conversation started" `null` com motivo; a
parcela de impressão das duas campanhas batendo com o `run_gaql` do fato 4 na mesma janela. Em 30
dias, remedir a fatia do `run_gaql` no uso (meta: as 94 consultas por ação migram depois que o
plugin sair).
