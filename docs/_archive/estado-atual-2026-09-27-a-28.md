# Estado atual — o que saiu em 28/09 (arquivo)

Trechos movidos **literalmente** de `docs/operacao/estado-atual.md` no compact de 28/09, pela
regra do cabeçalho dele: trabalho que fechou sai de lá, a narrativa vem para cá, e lá fica uma
linha. Nada foi reescrito além dos caminhos relativos dos links; o estado vigente está no arquivo de origem.

## Produção — os smokes de 26 e 27/09 e a verificação do F154

**Smoke de leitura do F193 em produção (26/09, `Conta Interna - 02`):** `filters_applied` em `get_campaign_performance` (com `campaign_status`, e sem ele com `status=all`), `get_account_overview` (aninhado `current`/`previous`, janelas iguais às de `period`/`previous_period`), `get_negative_keywords_audit` (`nivel: "campanha"`), `get_budget_pacing` (`{"during": "THIS_MONTH"}`) e `get_performance_breakdown` por keyword (`criterion_status`); razões `null` num período sem atividade. **Limite medido:** para período sem atividade o Google devolve uma linha **zerada**, não nenhuma linha — então `sem_dados_no_periodo` vem `false` com contagens zero, e só fica `true` quando não vem linha nenhuma. Quem protege a leitura são as razões `null`. As descriptions novas só aparecem em sessão MCP nova (F140).

**Smoke de leitura do F194 em produção (27/09, sessão MCP aberta depois do deploy):** na Cheiro | Conta 01, `meta_get_account_overview` e `meta_get_campaign_performance` trazem `purchases` medido (não `0`), `leads`, `messaging_conversations_started`, `ctr` em fração e `atribuicao: "unificada"`, com a soma das 19 campanhas igual ao total da conta; na janela da medição original (`27/08–25/09`), exatamente `purchases` 10, `leads` 13 e 3.531 conversas. `purchases: null` em conta com gasto e sem compra (MI Imports | Conta 02); `sem_dados_no_periodo: true` em conta sem entrega; breakdown horário com `reach` e `frequency` `null` em 50 de 50 linhas; BUC lido do cabeçalho real (`last_throttle_pct` gravado, nenhum `meta_buc_nao_lido`). **O preset do roteiro deu `purchases` 9, não 10:** o `LAST_30_DAYS` Meta inclui o dia corrente (`29/08–27/09`) e a referência terminava na véspera — é o **F195**. Detalhe no F194 do [catálogo](../operacao/findings-catalog.md).

**Smoke de leitura do F195 em produção (27/09, run `36332640719`):** `meta_get_account_overview` na Cheiro | Conta 01 com `LAST_7_DAYS` ecoou `date_range` `20/09–26/09` — exatamente o `date_preset=last_7d` da própria Meta sondado no mesmo dia —, `previous_date_range` `13/09–19/09` e `inclui_dia_corrente: false`; com `TODAY`, `27/09` contra `26/09` e `inclui_dia_corrente: true`, com variações de ~−99% que são o dia ainda aberto — o caso que o campo existe para avisar. Chamado de uma sessão aberta antes do deploy: a resposta é do código novo; as descriptions novas só aparecem em sessão nova (F140).

**Verificação do F154 — conferida em 28/09** (execução das 09:00:03, imagem `e9e728c`): a CHUTE 07 com `su_reachable = true`, o `meta_reconcile` com `unreachable: 0` e `alcance_nao_medido: 0`, a fila "Sem o SU" vazia, a etapa Meta em ~8 s e nenhum aviso no log. O critério, para a próxima: na execução diária do `v4-ads-mcp-resync` (09:00 UTC) seguinte ao deploy — uma sob demanda roda o resync inteiro com as duas reconciliações ligadas, mutação de produção que pede autorização nominal: a CHUTE 07 com `su_reachable = true`, o `meta_reconcile` com `unreachable: 0` e `alcance_nao_medido: 0`, e no painel a fila "Sem o system user atribuído" vazia. Tudo por leitura: o `params_summary` da linha `meta_reconcile` no `audit_log` e o `su_reachable` da `act_1428319651342125`. `unreachable` ou `alcance_nao_medido` acima de 0 se explica pelo log `meta_alcance_nao_medido`, que traz os ids, antes de virar defeito.

## Decision gates — o raio da virada Google e as execuções conferidas

- **Raio medido na virada** (26/09, 18:13 UTC, transação READ ONLY): 3 contas desativadas e
  **46 grants** revogados — 34 do backlog em 9 contas já inativas + 12 das três que deixaram a
  unidade (`4493906974` DR DÉRICK VINHAS, `8726746966` Imperial Alimentos, `9450567241` Dra.
  Paula Minchillo). A **Alumínios Veneza** (`2640486995`, 4 grants) também saiu — churn
  confirmado em 26/09 —, com 1 ausência gravada: saiu na 3ª, em **28/09** (conferido).
- **Conferido na primeira execução com a trava** (sob demanda, 26/09 às 23:21 UTC, execução
  `v4-ads-mcp-resync-6h6q6`): `applied=true`, `removed=3`, `revoked_grants=46` — a previsão
  exata —, 12 linhas `google_access_cleanup` (uma por conta, `left_mcc`), **zero** grant vivo em
  conta Google inativa e 26 contas ativas (as 25 do MCC + a Alumínios em carência). O raio foi
  medido duas vezes no dia (18:13 e 23:14 UTC), igual nas duas. A Meta, no mesmo job:
  `applied=true`, `removed=0`, `revoked_grants=0`; o `unreachable=1` é a CHUTE 07, igual desde
  24/09 pelo menos — artefato do índice `/me/adaccounts`, que o F154 tirou do job em 27/09 (a CHUTE 07 é lida).
- **Conferida a de 28/09:** `removed=1` e `revoked_grants=4` — a Alumínios Veneza na 3ª
  ausência, com a linha `google_access_cleanup` dos 4 gestores e zero grant vivo em conta inativa.
