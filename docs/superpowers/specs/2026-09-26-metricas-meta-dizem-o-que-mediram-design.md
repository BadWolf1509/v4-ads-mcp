# As métricas Meta dizem o que mediram — design

**Data:** 2026-09-26
**Origem:** varredura de 21/09, relatórios 01 (item 4) e 03 (itens 4, 5, 6, 7 e 9), arquivados
em [`_archive/varredura-2026-09-21/`](../../_archive/varredura-2026-09-21/README.md). Frente
*métricas Meta* da ordem de ataque (item 3 do `estado-atual`). Mesma família do **F191** e do
**F193** — uma resposta que afirma mais do que mediu —, agora do lado Meta. O **F190** deixou
estes itens explicitamente para cá ("todos do sub-projeto 2 da mesma varredura, e ainda não
verificados").

**Decisões do Wellington (2026-09-26):**

1. **Escopo: o contrato das métricas + o sinal BUC.** Moeda e paginação ficam fora,
   declaradas (§7).
2. **Conversões: totais canônicos + conversas iniciadas.** O que a conta não reporta vem
   `null`, não 0. Um mapa só, usado pelas 5 tools.
3. **Desenho: um módulo de contrato único, com guard estrutural** (§3).

---

## 1. A regra

> **Uma métrica Meta diz o que a Meta mediu.** Campo que a Meta não mandou é `null`, não zero;
> o mesmo campo sai pela mesma regra em todas as tools; e a resposta diz a atribuição e a
> unidade que usou.

## 2. O que as sondagens de 26/09 mediram

Leitura na Graph API v22.0, token no header (F82), nas 24 contas ativas e alcançáveis, janela
de 30 dias (27/08 a 25/09). O script fica versionado com este spec:
`scripts/probe_meta_metricas.py`.

| # | pergunta | medido | consequência hoje |
|---|---|---|---|
| M1 | escala do `ctr` | a Meta manda **porcentagem** (6,603116 = cliques ÷ impressões × 100), nas 14 contas com gasto | o trio divide por 100 e sai em fração, como o `ctr` do Google (`razao(clicks, impr)`); o overview devolve a porcentagem crua — as duas tools mais usadas discordam em 100× |
| M2 | nomes das conversões | só 1 das 14 contas com gasto tem compra ou lead (Cheiro \| Conta 01). Nela, as mesmas **10 compras** aparecem sob 5 nomes (`omni_purchase`, `onsite_conversion.purchase`, `onsite_web_purchase`, `onsite_app_purchase`, `onsite_web_app_purchase`) e os mesmos **13 leads** sob 7 (`lead`, `onsite_conversion.lead`, `onsite_conversion.lead_grouped`, `onsite_web_lead` e três `offsite_*_add_meta_leads`) | o trio busca o nome exato `purchase`, que não existe: **`purchases: 0` sobre 10 compras reais**. O overview soma uma lista de 6 nomes que só casa `lead`; numa conta com `lead` e `offsite_conversion.fb_pixel_lead` juntos ele contaria o mesmo lead duas vezes |
| M3 | o que as contas medem | **14 de 14** contas com gasto têm `onsite_conversion.messaging_conversation_started_7d` | nenhuma tool expõe conversa iniciada; para 13 das 14 contas a resposta diz `purchases: 0, leads: 0`, lido como "nenhum resultado" |
| M4 | valor e ROAS | `action_values` e `purchase_roas` vazios nas 14 contas | `purchases_value_brl: 0` e `purchase_roas: 0.0` são "não medido" em 100% das linhas |
| M5 | alcance sob breakdown | `reach`/`frequency` presentes em `publisher_platform`, `impression_device` e `country`; **ausentes em 50 de 50 linhas** do breakdown horário | saem `0` e `0.0` |
| M6 | atribuição | o padrão, `use_unified_attribution_setting=true`, `action_report_time=conversion`/`impression` e `action_attribution_windows=["1d_click"]` deram os mesmos números na conta com conversões; valor inválido volta **HTTP 400** nos três parâmetros, então a API os lê | impacto medido: nenhum nesta conta e janela; o contrato segue implícito |
| M7 | período sem entrega | 10 das 24 contas não devolveram **linha nenhuma** | a Meta não manda linha zerada (o Google manda, F193); o overview Meta devolve zeros sem marcador |
| M8 | cabeçalhos de uso | `x-business-use-case-usage` vem com a chave da conta consultada (o parser casa certo); **`x-app-usage` não vem** em chamada de insights; a quota do app vem em `x-fb-ads-insights-throttle` (`app_id_util_pct`, `acc_id_util_pct`) | o parser grava "não entendi" como `0`; o cabeçalho com a quota do app nunca é lido |

Medido também no código e no banco, em 26/09:

- **Ninguém lê o `last_throttle_pct`** gravado em `meta_rate_counters`: fora do repositório que
  o grava, só o purge diário toca a tabela. O efeito vivo do zero falso é o aviso
  `meta_rate_limit_warning` (acima de 75%) não disparar. **Não existe limitador que barre
  chamada por esse valor.**
- **O overview ainda manda `ad_account_id` como parâmetro da Graph API**
  (`meta_get_account_overview.py:143,167`): o transporte do F190 repassa `params` como recebe
  (`reports.py:269`). O índice da varredura marca o item 03#10 como fechado pelo F190 —
  **errado**; ele fecha aqui, pelo construtor único (§4.2).
- **Uso em 30 dias** (`audit_log`): overview 161 chamadas de 4 gestores, campaign 124, ad set
  83, ad 24, breakdown 3.
- **Moeda:** as 30 contas Meta (25 ativas) estão em BRL.
- **Nível de acesso:** o cabeçalho de throttle diz `ads_api_access_tier: development_access` —
  o app segue no Limited Access do D1 de maio. Fora deste spec (§7).
- **Consumidores fora do repo:** o plugin `v4-trafego-google-ads` não referencia nenhuma tool
  Meta (grep de 26/09). O consumidor das respostas é o LLM, pela description e pela resposta.

## 3. O mecanismo: um módulo de contrato

`src/meta_ads/metricas.py` — puro, sem IO — é o **único** código que lê chave de métrica de uma
linha da Graph API. `insights.py` (trio e breakdown) e `account_overview.py` (overview) passam
a chamá-lo; nenhum dos dois lê mais `actions`, `action_values`, `purchase_roas`, `reach`,
`frequency`, `ctr`, `cpc`, `spend`, `impressions` ou `clicks` direto da linha.

O padrão é **fonte única de verdade com mecanismo que a aplica**. É a lição do F189 e do F190 —
a regra consertada num gêmeo e não no outro — e a razão de existir o guard estrutural da §6.
A alternativa de consertar os dois parsers e amarrá-los por teste de concordância foi
descartada: duas respostas erradas e iguais também concordam.

### 3.1 O mapa canônico

| campo da resposta | fonte na linha Graph | por quê |
|---|---|---|
| `purchases` | `actions[omni_purchase]` | o total entre canais que o Gerenciador chama de "Compras"; os outros quatro nomes de M2 são recortes do mesmo número |
| `purchases_value_brl` | `action_values[omni_purchase]` | mesma chave |
| `purchase_roas` | `purchase_roas[omni_purchase]` | idem; hoje o trio pega a primeira entrada da lista sem olhar o tipo |
| `leads` | `actions[lead]` | o total que o Gerenciador chama de "Leads"; os outros seis nomes de M2 são recortes |
| `messaging_conversations_started` | `actions[onsite_conversion.messaging_conversation_started_7d]` | **campo novo** — o resultado de 14 de 14 contas (M3) |

**Um nome por campo, nunca soma de nomes:** somar recortes conta o mesmo evento várias vezes
(M2). O mapa vive em uma constante só, no módulo do contrato.

### 3.2 Ausente é `null`

- **Tipo de ação ausente da lista, ou a lista ausente → `null`.** A Meta **omite** o tipo que
  teve zero ocorrência, então `null` quer dizer *"não reportado: zero ou não rastreado — a API
  não distingue"*. A description diz isso com essas palavras.
- **`reach`/`frequency` ausentes → `null`** (M5). A description do breakdown diz que o horário
  não traz alcance nem frequência.
- **Toda métrica escalar segue a mesma regra** (`spend`, `impressions`, `clicks`, `ctr`, `cpc`,
  `reach`, `frequency`): ausente → `null`; zero só quando a Meta manda zero.
- **Valor que não converte para número → `null`** (hoje vira `0`).
- **Contagens arredondam, não truncam** (`int(2.9) == 2` hoje): `impressions`, `clicks`,
  `reach` e os três eventos.

### 3.3 Unidade

`ctr` sai em **fração** em todas as tools, como o `ctr` do Google: a Meta manda porcentagem
(M1), o contrato divide por 100. `null` quando ausente.

### 3.4 Período sem linha

Quando a Meta não devolve linha nenhuma (M7), o overview traz:

- contagens de entrega (`spend_brl`, `impressions`, `clicks`, `reach`) em `0` — verdade: não
  houve entrega;
- eventos, valores e razões (`purchases`, `purchases_value_brl`, `leads`,
  `messaging_conversations_started`, `purchase_roas`, `ctr`, `cpc_brl`, `frequency`) em
  `null`;
- `sem_dados_no_periodo: true`.

É o contrato do overview Google (F193, `get_account_overview.py::_aggregate`), com uma
diferença deliberada: lá as conversões sem linha são `0`, porque a conversão Google é
definida pela conta; aqui os eventos são `null`, pela mesma regra da linha (§3.2) — a Meta não
diz se a conta rastreia o evento. No trio e no breakdown, período sem linha já é lista vazia
com `total_rows: 0`; não muda.

## 4. As tools

### 4.1 Trio e breakdown

`parse_insights_row` delega ao contrato, e as linhas passam a trazer
`messaging_conversations_started`. A ordenação por `spend_brl` aceita `null` sem quebrar (não
acontece em linha com entrega, mas o `sort` não pode estourar).

### 4.2 Construtor único e atribuição

- **Toda chamada `/insights` sai de `build_insights_call`.** O overview passa a usá-lo, no
  nível `account`, o que remove o `ad_account_id` espúrio dos params (§2).
- **Atribuição fixada:** `build_insights_call` põe `use_unified_attribution_setting=true` em
  toda chamada — a atribuição configurada no conjunto de anúncios, que é o que o Gerenciador
  mostra. Medido (M6): o parâmetro é lido e, na conta com conversões, não mudou os números.
- **A resposta diz a atribuição que usou:** `atribuicao: "unificada"`, nas 5 tools.

### 4.3 Overview

- `current` e `previous` passam pelo contrato e trazem os **mesmos nomes do trio**:
  `spend_brl`, `impressions`, `clicks`, `ctr`, `cpc_brl`, `reach`, `frequency`, `purchases`,
  `purchases_value_brl`, `purchase_roas`, `leads`, `messaging_conversations_started`.
- **Saem `conversions` e `conversion_value`:** a soma de nomes mistura resultados diferentes e
  pode contar o mesmo evento duas vezes (M2).
- `ctr` passa a fração (M1).
- `deltas` para `spend_brl`, `impressions`, `clicks`, `purchases`, `purchases_value_brl`,
  `leads`, `messaging_conversations_started` e `purchase_roas` (sufixo `_pct`, como hoje):
  `null` quando um dos lados é `null` ou o anterior é `0`.
- `sem_dados_no_periodo` em `current` e em `previous` — cada período pode não ter linha.

### 4.4 Descriptions

As 5 descriptions dizem: o significado do `null` (a frase da §3.2), a unidade do `ctr`, a
atribuição unificada, o campo de conversas iniciadas; a do breakdown diz que o horário não
traz alcance nem frequência; a do overview, que as conversões agora saem por evento.

## 5. O sinal BUC

- **`_parse_buc_header_pct` devolve `int | None`:** `None` para cabeçalho vazio, JSON
  malformado, não-dict ou sem a chave da conta.
- **`record_actual_meta` com `None` não chama `update_throttle`** — o último valor medido
  fica — e registra `meta_buc_nao_lido` com o motivo. `increment_calls` segue: a chamada
  aconteceu.
- **Lê `x-fb-ads-insights-throttle`** (`app_id_util_pct`, `acc_id_util_pct`, M8). O aviso
  `meta_rate_limit_warning` passa a disparar quando **qualquer** sinal medido passar de 75%, e
  diz qual — a quota que barra é a que tem menos folga (F110). Cabeçalho ausente ou malformado
  é "não sei", nunca `0`.
- **`run_meta_graph_get` passa os dois cabeçalhos**, e chama o registro quando qualquer um
  vier (hoje só com o BUC presente).
- **Sem migration:** o valor gravado não tem leitor (§2); o que precisa ficar certo é o aviso.

## 6. Testes e guards

1. **Fixtures com as formas medidas** (M2, M3, M4, M5, M7), como dicts literais sem nome de
   conta, **vistas vermelhas contra o parser atual**:
   - compra sob os 5 nomes → `purchases == 10` (hoje `0`);
   - lead sob os 7 nomes → `leads == 13`, nunca 91;
   - conversa iniciada → o campo novo;
   - `action_values` e `purchase_roas` ausentes → `null`;
   - linha do horário sem `reach` → `null`;
   - sem linha → `sem_dados_no_periodo: true`, eventos `null`, entrega `0`.
2. **Guard estrutural do contrato:** só `metricas.py` lê chave de métrica de linha Graph. AST
   sobre `src/meta_ads/` e as tools `meta_*`/`_meta_*`, procurando subscrição e `.get` com os
   literais do conjunto de chaves de métrica. **O conjunto de raízes é afirmado**, não um piso
   numérico. Mordida provada por sabotagem em cópia — um `row.get("actions")` plantado em
   `insights.py` — com controle positivo.
3. **Guard do construtor único:** nenhum literal `"/insights"` fora de `build_insights_call`
   (mesmas raízes), e o dict que ele monta traz `use_unified_attribution_setting`. O overview
   de hoje, com params à mão, fica vermelho.
4. **BUC:** cabeçalho malformado, ausente ou sem a conta → `update_throttle` não é chamado e o
   valor anterior fica (vermelho contra o pré-fix, que grava `0`); throttle de insights com
   `app_id_util_pct` acima de 75 dispara o aviso nomeando a quota.
5. **Testes que afirmam o zero revogado** — `test_meta_insights.py:223-226,272,287,291-292,310-311`,
   `test_meta_account_overview.py:78-80,84,141,147-149` e `test_buc_header_parsing.py:32-47` —
   afirmam a regra que este spec revoga, e são **reescritos**. Não é enfraquecer guard: é o
   caso da T5 do F193, teste que afirmava a regra que o spec revogou.
6. **Frases das descriptions conferidas por varredura**, como no F193: a população sai do
   registry, não de lista.

## 7. Fora de escopo, com o motivo

- **Chaves `_brl`:** 30 de 30 contas em BRL (medido); `currency` já vem ao lado. Renomear
  chave é custo sem defeito hoje. Volta se entrar conta em outra moeda.
- **Unificar as duas paginações** (`graph.py` × `reports.py`): débito declarado no F190; as
  duas autenticam por header; mexer em `graph.py` arrisca a reconciliação.
- **Nível de acesso da API** (`development_access`): pendência D1, decisão do Wellington —
  pedir o Full Access. Vai para o `estado-atual`.
- **Métricas derivadas** (custo por conversa, CPL): o LLM divide com os campos honestos;
  entram se o uso pedir.
- **Dia do contador BUC no fuso da conta** (`date.today()` do servidor, o gêmeo Meta do F141):
  o contador não tem leitor.
- **Status da entidade** (`effective_status`, F89): enriquecimento em dois passos, frente
  própria.
- **Modelo de freshness para métricas** (01#12): desenho à parte.

## 8. Riscos

1. **Contrato número → `null` em 5 tools:** o maior, o mesmo do F193. Consumidor medido: só o
   LLM. Mitigado pela description.
2. **O overview muda de forma** — saem `conversions`/`conversion_value`, o `ctr` muda de
   escala, as chaves passam aos nomes do trio. É a tool Meta mais usada (161 chamadas em 30
   dias). Sem consumidor fora do LLM; a mudança vai na description e no catálogo.
3. **O mapa canônico foi confirmado numa conta só** (Cheiro | Conta 01). `omni_purchase` e
   `lead` são os totais do Gerenciador, mas "os outros nomes são recortes do mesmo número" é
   medição de uma conta. O script fica versionado; refazer quando entrar conta com pixel de
   compra.
4. **Atribuição fixada** pode mudar número em conta cujos conjuntos usam janela diferente do
   padrão — é o objetivo (bater com o Gerenciador), e a resposta diz qual usou.

## 9. Critério de pronto

1. `python scripts/check_pre_push.py` 6/6, EXIT=0; CI verde.
2. Cada medição com defeito (M1–M5, M7, M8) tem teste que fica vermelho contra o código
   anterior.
3. Os três guards (contrato único, construtor único, BUC) com a mordida provada por sabotagem.
4. Catálogo: entrada nova (**F194**) com a classe no lado Meta e o que ficou de fora; o índice
   da varredura com os destinos atualizados, **inclusive corrigindo o 03#10**; o
   `estado-atual` sem a frente e com a pendência do nível de acesso.
5. Descriptions atualizadas nas 5 tools.
6. Smoke de leitura em produção depois do deploy: overview e campaign na Cheiro | Conta 01
   (`purchases: 10`, não `0`) e numa conta com conversas iniciadas; breakdown horário com
   `reach: null`.
