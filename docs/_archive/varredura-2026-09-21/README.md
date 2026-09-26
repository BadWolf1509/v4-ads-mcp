# Varredura de 21/09 — os 5 relatórios, e o destino de cada achado

A varredura ampla de 21/09 rodou 5 agentes em paralelo, cada um num recorte. Os relatórios
voltaram só como notificação na sessão e **não foram salvos em disco**; uma extração tentada
em 21/09 rodou 2h48 sem produzir nada. Em 25/09 foram recuperados do transcript, por ID de
agente, e estão aqui **sem edição**.

⚠️ **Os status ("CONFIRMADO", "PLAUSÍVEL") são dos agentes.** A regra de 21/09 continua:
achado que ninguém remediu direto no código **não vira trabalho até ser verificado**. A
coluna "destino" diz o que já foi remedido e fechado, e em qual frente da
[ordem de ataque](../../operacao/estado-atual.md) o resto será tratado. "Conferido em 25/09"
marca um probe pontual feito na análise daquele dia — confirma que o defeito existe, não o
conserta.

| arquivo | recorte |
|---|---|
| [`01-ausencia-que-e-filtro.md`](01-ausencia-que-e-filtro.md) | ausência que é filtro — o que as respostas omitem |
| [`02-resumo-x-detalhe.md`](02-resumo-x-detalhe.md) | resumo que diverge do detalhe na mesma resposta |
| [`03-contratos-meta.md`](03-contratos-meta.md) | contratos da camada Meta |
| [`04-mocks.md`](04-mocks.md) | mocks que não conseguem expressar o bug |
| [`05-db-e-migrations.md`](05-db-e-migrations.md) | camada de banco e migrations |

## A decomposição original, e o que aconteceu com ela

| # | sub-projeto | continha | hoje |
|---|---|---|---|
| 1 | credencial + contratos do SDK Meta | token na query string · sem timeout · `cast(dict)` sobre corpo não-JSON · gate não amarrado à URL | fechado — F190 |
| 2 | respostas que afirmam mais do que mediram | `get_ad_schedule` · `Unpack` · `filters_applied` · eco de `status` · `applied_count` × `blast_summary` · escopo do `get_assets` | núcleo fechado no F191; eco de `status` e `get_assets` seguem abertos |
| 3 | infra de dados | CSV do audit falha aberto · escopo do guard de reconnect · lock no `migrate.py` · assimetria do `revoke` Meta | CSV fechado no F191; o resto aberto |
| 4 | guards que não cobrem | o mock que bloqueava o conserto · testes que enumeram em vez de afirmar a propriedade | mock fechado no F191; o resto aberto |

Ainda em 21/09 os achados foram **reclassificados por forma de defeito** (classes A, B, C —
ver a abertura do [spec do F191](../../superpowers/specs/2026-09-21-terceiro-estado-nao-medido-design.md));
o F191 é a classe A. Os IDs F<n> citados abaixo estão no
[catálogo](../../operacao/findings-catalog.md).

## Destino de cada achado

### 01 — ausência que é filtro

| # | achado | destino |
|---|---|---|
| 1 | `filters_applied` omite os filtros que cortam | fechado — F191 |
| 2 | 6 tools com `status` default `'enabled'` não ecoam o filtro | aberto — *respostas Google* |
| 3 | `get_top_keywords_creatives` filtra `ENABLED` sem declarar | aberto — *respostas Google* |
| 4 | Meta: `purchases`/`leads`/`purchase_roas` viram `0` quando o campo não vem | aberto — *métricas Meta* |
| 5 | `get_account_overview`: `if not rows` devolve zeros sem marcador | aberto — *respostas Google* |
| 6 | `bulk_pause_by_query` não diz sobre qual janela mediu | aberto — *respostas Google* |
| 7 | `get_budget_pacing`: `ENABLED` fixo, sem parâmetro nem eco | aberto — *respostas Google* |
| 8 | `audit_zombie_keywords.filters_applied` | fechado — F191 |
| 9 | `get_negative_keywords_audit.total_negatives` sem escopo declarado | aberto — *respostas Google* |
| 10 | `meta_list_my_ad_accounts`: conta desativada pelo reconciliador some sem rastro | aberto — *F154* (a mesma pergunta: o que a lista de contas prova) |
| 11 | `country_name: null` no breakdown geo | aberto, baixo — *respostas Google* |
| 12 | não existe modelo de freshness para métricas | PLAUSÍVEL — fora da fila: é desenho, e o relatório traz o probe que decide |

### 02 — resumo × detalhe

| # | achado | destino |
|---|---|---|
| 1 | `get_ad_schedule`: resumo e lista com filtros de status diferentes | fechado — F191 |
| 2 | `add_negatives_from_search_terms`: dois números para a mesma pergunta | aberto — *respostas Google* (instância do F187) |
| 3 | `get_assets`: `summary` do conjunto inteiro, `links[]` cortado | aberto — *respostas Google* (instância do F187) |
| 4 | `bulk_pause_by_query`: "no período" para custo que pode ser vitalício | PLAUSÍVEL — *respostas Google* |
| 5 | `get_performance_breakdown` (`campaign`+`hourly`): `truncated` ambíguo | fechado — F188 |
| 6 | `run_gaql`: `row_count` é o universo, `rows` é o cortado | aberto, baixo — *respostas Google* |
| 7 | `audit_competitor_keywords`: custo do veredito × lista cortada | aberto, baixo — *respostas Google* |

### 03 — contratos Meta

| # | achado | destino |
|---|---|---|
| 1 | token do system user na query string | fechado — F190 |
| 2 | nenhum timeout HTTP | fechado — F190 (`_TIMEOUT_GRAPH` no httpx) |
| 3 | 5xx com corpo não-JSON / `cast(dict)` | fechado — F190 (`MetaGraphHTTPError` em não-200 e em corpo que não é dict) |
| 4 | três regras diferentes para os mesmos campos | aberto — *métricas Meta* |
| 5 | contrato de atribuição implícito | aberto — *métricas Meta* |
| 6 | `reach`/`frequency` sob breakdown: ausência vira `0` | aberto — *métricas Meta* |
| 7 | BUC: "desconhecido" gravado como `0`; quota de app nunca lida | aberto — *métricas Meta*. Conferido em 25/09: `src/governance/rate_limit.py` devolve `0` em três caminhos |
| 8 | gate não amarrado ao alvo da requisição | fechado — F190 (guard de contenção) |
| 9 | `_brl` fixo num inventário multi-moeda | aberto — *métricas Meta* |
| 10 | `ad_account_id` sobrando na query | fechado — F190 (o transporte novo não o envia) |
| — | duas paginações, só uma consertada | débito declarado no F190 |

### 04 — mocks

| # | achado | destino |
|---|---|---|
| 1 | `customer_match`: `membros_recusados` vinha só de `erros_por_indice` | fechado — F191 |
| 2 | `mutations.py` / `conversions.py`: detecção de falha por outra via | fechado — F191 |

### 05 — DB e migrations

| # | achado | destino |
|---|---|---|
| 1 | export CSV do audit falha aberto | fechado — F191 |
| 2 | `pool.acquire()` cru em leituras quentes, fora do guard estrutural | aberto — *infra e guards* |
| 3 | `migrate.py` sem advisory lock | aberto — *infra e guards*. Conferido em 25/09: nenhum `pg_advisory` no arquivo |
| 4 | `days` e resultado sem teto nos exports CSV | `days`: fechado em 25/09 — teto de 365, validado na rota; resultado: aberto — *infra e guards* |
| 5 | `revoke` Meta sem `AND revoked_at IS NULL` | aberto — *infra e guards*. Conferido em 25/09: falta no `revoke` manual de `manager_meta_account_access.py`; o `revoke_for_account`, que a reconciliação usa em produção, tem. O `revoke` de `google_oauth_connections.py` também não tem |
| 6 | `get_active_for_manager`: `LIMIT 1` sobre chave de ordenação não-única | aberto, baixo — *infra e guards* |
| 7 | `IndexError` com `limit=0` nos dois pagers keyset | aberto, inalcançável hoje — *infra e guards* |
| 8 | itens menores | ver o relatório |
| 9 | F179 localizado | fechado — F191 |
