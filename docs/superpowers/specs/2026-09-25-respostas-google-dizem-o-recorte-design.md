# As respostas Google dizem o recorte que mediram — design

**Data:** 2026-09-25
**Origem:** varredura de 21/09, relatórios 01 (*ausência que é filtro*) e 02 (*resumo ×
detalhe*), arquivados em
[`_archive/varredura-2026-09-21/`](../../_archive/varredura-2026-09-21/README.md). Frente
*respostas Google* da ordem de ataque de 25/09. Mesma classe do **F187**, agora dentro da
resposta das tools, não de documento.

**Decisões do Wellington (2026-09-25):**

1. **Escopo: as três graves + a classe, com guard** — incluindo os reports antigos da
   Fase 2B, que têm 4 a 5 vezes mais uso que o `get_performance_breakdown` (148 × 33
   chamadas em 30 dias, medido em 25/09). A opção aprovada citava os 4 que filtram `status`
   (campanha, grupo, keyword, anúncio); **os outros 4 (dispositivo, geo, horário, público)
   entram pelo mesmo motivo** — uso — e porque as funções de query deles estão entre as 17
   da §3.1. Ampliação declarada aqui, não presumida.
2. **Mecanismo: o padrão do F191** — a função de query devolve `(gaql, filtros)`, a tool
   ecoa `filters_applied`, o teste derivado cobre todas. Um padrão só no repo.
3. **`bulk_pause_by_query` mede sempre no período** — condicionado a confirmar, numa conta
   ativa, que o conjunto a pausar não muda. **Confirmado** (§4.1).
4. **Negativas: declarar o escopo.** Cobrir negativas de grupo e listas compartilhadas vira
   frente própria.

---

## 1. A regra

> **Uma resposta diz o recorte que mediu.** Filtro aplicado, janela e escopo aparecem na
> resposta, derivados da mesma fonte que montou a query. Razão sem denominador é
> **indefinida**, não zero.

É a regra do F191 (*"uma ausência não é uma medição"*) aplicada ao outro lado: lá, um
retorno descartado virava zero; aqui, um corte que a query faz some da resposta, e uma
divisão por zero vira número. E é o remédio que o F187 propôs para a sua classe: **fonte
única + derivação**, porque "lembre de atualizar o resumo junto" é processo humano no lugar
de mecanismo.

## 2. O que a verificação de 25/09 achou

Os relatórios dos agentes afirmavam; nada aqui entrou sem ser conferido no código de hoje
ou por probe. Dois achados mudaram de gravidade na conferência.

| gravidade | achado | como foi conferido |
|---|---|---|
| 🔴 | **`bulk_pause_by_query`**: o preview de mutação diz *"Custo total R$ X no periodo"*, mas a janela só entra na query quando o filtro menciona `metrics.` — com filtro só de entidade, X é o custo **de toda a vida** | probe GAQL em duas contas (§4.1): campanha com **R$ 3.013,88** na vida e **R$ 638,05** nos 30 dias |
| 🔴 | **Razão indefinida vira número** — CPA `0.0` com gasto e zero conversão (o melhor CPA possível), CPC `0.0` sem clique, CTR `0.0` sem impressão, ROAS `0.0` sem gasto. O agente achou no overview; o inventário achou **29 ocorrências em 12 arquivos** (§4.2) | código |
| 🔴 → 🟠 | **`get_negative_keywords_audit`**: a description diz que `total_negatives` reflete a *"conta inteira (nao truncados)"* e a query lê só `campaign_criterion`. O "conta inteira" fala do **corte**, não do escopo — mas lido como escopo afirma o que não mede. A referência do plugin já diz *"nível de campanha"* | código + plugin |
| 🟠 | **5 tools** filtram `status='enabled'` por default e não dizem: os 4 reports antigos (`get_campaign/ad_group/keyword/ad_performance`) e o `get_performance_breakdown` | código |
| 🟠 | `get_top_keywords_creatives` fixa `ENABLED` sem declarar | `client_report.py:81,101` |
| 🟠 → 🟡 | `get_budget_pacing` fixa `ENABLED` — mas a description **declara** "por campanha ativa"; só a resposta não diz | código |
| 🟠 | **`add_negatives_from_search_terms`**: o texto diz *"N aceita(s) pelo Google"* contando como aceita a linha que o Google **recusou** como duplicata (`already_exists`); o `applied_count` do envelope não conta. Dois números para a mesma pergunta, e o texto — o que se lê — é o errado | código: `aplicadas` × `run_mutation.applied_count` |

## 3. O mecanismo: o padrão do F191, estendido

### 3.1 A função de query devolve `(gaql, filtros)`

As 17 funções de query consumidas pelas tools desta frente passam de `-> str` a
`-> tuple[str, dict[str, Any]]`:

| módulo | funções |
|---|---|
| `performance.py` | `campaign_performance_query`, `ad_group_performance_query`, `device_performance_query`, `geo_performance_query`, `hourly_performance_query` |
| `client_report.py` | `funnel_query`, `top_keywords_query`, `top_creatives_query` |
| `overview.py` | `overview_query`, `budget_pacing_query` |
| `tactical.py` | `keyword_performance_query`, `search_terms_query`, `negative_keywords_audit_query`, `ad_performance_query`, `audience_performance_query`, `conversion_actions_query` |
| `bulk_pause.py` | `bulk_pause_query` |

Mais o `build_performance_breakdown_query` (`performance_breakdown.py`), que compõe as de
`performance.py` e `tactical.py` e repassa o `filtros` delas.

**`filtros` é montado na mesma linha da cláusula do `WHERE`.** Quem escreve
`AND campaign.status = 'ENABLED'` escreve `filtros["campaign_status"] = "ENABLED"` ao lado;
quem monta a janela escreve `filtros["date_range"] = {"from": …, "to": …}`. Sem janela na
query, a chave **não existe** — ausência de `date_range` significa "sem janela", e é isso
que o preview do `bulk_pause` lê (§4.1).

**Nomes de chave:** os do F191 onde já existem (`date_range`, `criterion_status`,
`negative`, `conversion_action_status`); os novos seguem `<recurso>_status`
(`campaign_status`, `ad_group_status`, `ad_status`). No `bulk_pause`, o filtro do gestor é
texto livre — entra inteiro como `filtro_do_gestor`, e a janela injetada como `date_range`.

### 3.2 A resposta ecoa `filters_applied`

As 16 tools e o `get_performance_breakdown` passam a devolver `filters_applied` — a mesma
chave que as três tools de auditoria do F191 já usam — com o `filtros` exato que a query
aplicou: `get_campaign/ad_group/keyword/ad/audience/device/geo/hourly_performance`,
`get_performance_breakdown`, `get_account_overview`, `get_budget_pacing`,
`get_funnel_metrics`, `get_top_keywords_creatives`, `get_search_terms_report`,
`get_negative_keywords_audit`, `get_conversion_actions` e o preview do
`bulk_pause_by_query`.

As descriptions ganham uma linha: *"`filters_applied` diz o recorte que a query aplicou"*.

### 3.3 Os guards

1. **Completude derivada** — o `test_filters_applied_e_derivado.py` do F191 passa a cobrir
   as 17. A população vem de **varredura dos cinco módulos pelo harness**, não de lista: toda
   função que devolve GAQL ali tem de devolver a tupla, e cada campo do `WHERE` tem de ter
   chave no `CAMPO_PARA_CHAVE`. Função nova sem isso, ou campo novo fora do mapa, **falha
   com instrução** — o mesmo desenho que o F191 deixou. No `bulk_pause_query`, o filtro do
   gestor é texto livre e entra como um bloco só (`filtro_do_gestor`): ali o guard confere a
   janela injetada, não os campos de dentro do texto.
2. **Eco de verdade** — teste de comportamento, parametrizado pelas tools: cliente falso que
   captura o GAQL enviado; a resposta tem de trazer `filters_applied` **igual** ao `filtros`
   que a função de query devolveu para aquele GAQL. Sem isso a completude provaria só que a
   função sabe o recorte, não que a tool o entrega.

### 3.4 Consumidores em `tests/`

A troca de assinatura quebra teste que espera `str`. O gate roda `mypy src` — `tests/` está
fora do mecanismo de tipo, lição que esta frente de trabalho já pagou duas vezes. **O plano
começa pelo `grep` de todos os consumidores das 17 funções em `src/` e em `tests/`**, com a
contagem, antes de qualquer task.

## 4. As três graves

### 4.1 `bulk_pause_by_query`: sempre no período

A janela passa a entrar **em toda query** (exceto quando o filtro do gestor já traz
`segments.date`, como hoje). O custo do preview vira o do período — o número de quem decide
pausar agora —, o rótulo *"no periodo"* passa a ser derivado de `filtros["date_range"]`, e a
resposta ecoa as datas.

**A condição da decisão, medida em 25/09:** injetar a janela não pode mudar **quais
entidades** o filtro seleciona para pausar. Contagem de linhas com e sem janela, filtro só de
entidade (`status != 'REMOVED'`), nos quatro alvos:

| alvo (recurso) | conta de teste, parada | conta ativa (`Conta Interna - 02`) | custo 1ª linha: vida → período |
|---|---|---|---|
| keyword (`keyword_view`) | 52 → 52 | 86 → 86 | R$ 55,54 → R$ 21,32 |
| ad (`ad_group_ad`) | 7 → 7 | 7 → 7 | R$ 1.751,87 → R$ 212,37 |
| ad_group (`ad_group`) | 6 → 6 | 7 → 7 | R$ 324,70 → R$ 81,92 |
| campaign (`campaign`) | 6 → 6 | 1 → 1 | R$ 3.013,88 → R$ 638,05 |

Mesmo a `keyword_view` — uma view de métricas, o alvo de maior risco — devolve as linhas
sem atividade no período, com custo zero. **O limite desta prova:** invariância de conjunto é
comportamento da API do Google, não do nosso código; o teste unitário afirma que a janela
entra, não que o Google mantém o conjunto. Se o Google mudar isso, o probe acima é o que se
refaz — e ele está escrito aqui para isso.

### 4.2 Razão indefinida vira `null` — a classe inteira

Uma implementação só, `razao(numerador, denominador) -> float | None`, devolvendo `None`
quando o denominador é zero, substitui as **29 ocorrências** de `x / y if y else 0`:

| arquivo | campos |
|---|---|
| `get_account_overview.py` | `ctr`, `average_cpc_brl`, `cost_per_conversion_brl`, `roas` |
| `get_funnel_metrics.py` | `cost_per_conversion_brl`, `average_order_value_brl`, `roas`, `rate_from_prev_pct` |
| `get_campaign/ad_group/keyword/ad/audience/device/geo/hourly_performance.py`, `get_search_terms_report.py`, `performance_breakdown.py` | `ctr`, `cpc_brl` |

**Correção de 25/09, no levantamento do plano:** o guard por AST mede **33 ocorrências em 14
arquivos**, não 29 em 12 — o inventário acima veio de `grep` por nome de variável. As 4 a
mais são da mesma classe: `get_budget_pacing` (média diária, `spent_pct_of_monthly_budget`,
`projection_vs_budget_pct`) e `update_campaign_budget` (`delta_pct` do preview; o `classify`
o ignora, orçamento é sempre CONFIRM). O plano cobre as 33. E `date_range` segue a forma real
do F191, `{"start", "end"}`, não o `{"from", "to"}` da §3.1.

O helper só divide ou devolve `None`: arredondamento e conversão de micros continuam onde
estão hoje, e ele mora num lugar só (o plano escolhe o módulo; a regra é não haver segunda
implementação).

No `get_account_overview`, período sem nenhuma linha passa a trazer as contagens em `0` — que
é verdade — e `sem_dados_no_periodo: true`, **nos dois períodos** que a tool compara (o atual
e o anterior); as razões ficam `null`.

**Guard:** varredura por AST (harness) em `src/mcp/tools/` e `src/google_ads/` que acusa
expressão condicional cujo ramo verdadeiro divide e cujo ramo falso é `0`/`0.0`. Código novo
que reintroduzir o padrão falha com o nome do helper na mensagem.

⚠️ **Isto muda o contrato de 12 tools: número vira `null`.** Quem consome — o LLM e os skills
do plugin `v4-trafego-google-ads`, que montam relatório de cliente — pode fazer conta ou
formatação com esses campos. As descriptions passam a dizer *"`null` = indefinido
(denominador zero), não zero"*, e **o plano inclui conferir as referências e os skills do
plugin** por aritmética sobre esses campos antes do merge.

### 4.3 `get_negative_keywords_audit`: declarar o escopo

`filters_applied` traz `nivel: "campanha"`, e a description troca o *"conta inteira (nao
truncados)"* por: *"`total_negatives` conta todas as negativas **de campanha** da conta, não
só as da página devolvida; negativas de grupo e listas compartilhadas não entram."*

## 5. Os médios

- **`get_top_keywords_creatives` e `get_budget_pacing`** — entram pelo mecanismo da §3: as
  funções de query deles estão entre as 17, e o `filters_applied` passa a dizer o corte.
- **`add_negatives_from_search_terms`: o resumo derivado do envelope.** O texto passa a ser
  *"X adicionada(s), Y já existia(m), Z falhou/falharam"*, com X vindo do mesmo
  `applied_count` do envelope e Y e Z do status de cada linha; X + Y + Z tem de dar o total
  tentado. **Guard de igualdade:** um teste que falha se o número do texto divergir do campo.
  As duas irmãs que usam o mesmo `classify_partial` (`add_keywords`,
  `add_negative_keywords`) são conferidas no plano: entram se tiverem resumo com contagem.

## 6. Testes e guards

| o quê | tipo | tem de ficar vermelho contra |
|---|---|---|
| completude derivada das 17 | guard (harness) | função de query que devolve `str`, ou campo do `WHERE` sem chave |
| eco de verdade | comportamento | tool que não repassa `filters_applied`, ou repassa outro |
| janela sempre no `bulk_pause` | unitário | o `bulk_pause_query` de hoje com filtro só de entidade |
| rótulo do preview derivado | unitário | o preview de hoje, que diz "no periodo" sem janela |
| razão indefinida | guard (AST) + unitários por tool | as 29 ocorrências de hoje |
| `sem_dados_no_periodo` | unitário | o overview de hoje com zero linhas |
| escopo das negativas | unitário | a resposta de hoje, sem `filters_applied` |
| resumo do `add_negatives` | igualdade | o texto de hoje com uma linha `already_exists` |

**Mordida provada em todos**: rodar contra o código anterior à mudança (sabotagem ou cópia —
nunca `git checkout`), com controle positivo de que o guard enxerga o alvo.

## 7. Fora de escopo, com o motivo

| item | por quê |
|---|---|
| Outras funções de query fora dos cinco módulos (`ad_schedule`, `asset_inventory`, `change_event`, `audit_*`…) | a varredura não achou recorte escondido nelas; as de auditoria já ecoam (F191), o `get_ad_schedule` também. O guard da §3.3 cobre os cinco módulos, e **esse é o limite dele** — declarado aqui, não presumido |
| `get_assets`, `run_gaql`, `audit_competitor_keywords` | resumo sobre o conjunto inteiro e lista cortada, mas **já declarado** por `truncated`, `returned` e `orphan_scope` |
| `country_name: null` no geo | `null` já é o terceiro estado honesto |
| Negativas de grupo e listas compartilhadas | decisão 4: frente própria, com o desenho de resposta que as listas compartilhadas pedem |
| Modelo de freshness para métricas | desenho, não defeito; o relatório 01 traz o probe que decide |
| Custo do período nas outras tools de mutação | nenhuma outra afirma período sem janela; conferir no plano se aparecer |
| Métricas Meta | frente própria, a próxima da ordem de ataque |

## 8. Riscos

1. **Contrato número → `null`** (§4.2): o maior. Mitigado pela conferência do plugin antes
   do merge e pela description.
2. **17 funções mudam de assinatura:** consumidores em `tests/` fora do `mypy` (§3.4).
3. **Os 4 reports antigos recebem o conserto** mesmo marcados para tombstone: justificado
   pelo uso medido, e o conserto é da função de query, que o `get_performance_breakdown`
   também usa.

## 9. Critério de pronto

1. `python scripts/check_pre_push.py` 6/6, EXIT=0, e o CI verde **com a integração** (o sweep
   com banco roda no CI; local só se o Docker estiver de pé).
2. Cada achado confirmado da §2 tem teste que fica vermelho contra o código anterior.
3. Os quatro guards (completude, eco, razão, igualdade) com a mordida provada.
4. Catálogo: entrada nova (F193) registrando a classe nas respostas das tools, com o que
   ficou de fora; o índice da varredura com os destinos atualizados; o `estado-atual` sem a
   frente.
5. Descriptions atualizadas onde o contrato mudou (`filters_applied`, `null`).
