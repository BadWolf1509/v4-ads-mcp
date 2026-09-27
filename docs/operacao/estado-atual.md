# Estado atual — V4 Ads MCP

> **Volátil por natureza.** Esta é a seção que muda a cada sessão; ela vivia no
> `CLAUDE.md` e era o motivo de ele reinchar — estado e convenção no mesmo arquivo
> significa que todo trabalho novo empurra bytes para dentro do que é carregado sempre.
> O `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.

> **Ao terminar uma sessão, atualize ESTE arquivo**, não o `CLAUDE.md`.

> 🔑 **E mantenha-o curto.** Em 20/09 ele estava com **91 KB**, dos quais 83 eram a
> narrativa de uma frente **já concluída** — narrando como *"falta só o merge"* sete PRs
> mesclados, e contradizendo a própria tabela duas telas abaixo. Arquivo de estado que
> narra o passado deixa de ser confiável sobre o presente, que é a única coisa que ele
> faz. A narrativa foi para
> [`_archive/varredura-2026-09-06-frentes.md`](../_archive/varredura-2026-09-06-frentes.md).
> **Trabalho que fechou sai daqui:** o defeito vai para o catálogo, a narrativa para o
> arquivo, e aqui fica uma linha.

> **Última sessão:** [`session-2026-09-27-handoff.md`](session-2026-09-27-handoff.md)
> — o mapa de 27/09: o F194 em produção e conferido, o **F195** (janelas `LAST_N_DAYS` até
> ontem, como no Google e na Meta), as descriptions Meta com as chaves reais, o alerta dos avisos
> Meta de quota no GCP e a frente **F154** em execução na branch `spec/f154-alcance` (como
> retomar está lá). O dia anterior: [`session-2026-09-25-26-handoff.md`](session-2026-09-25-26-handoff.md).

---

## Produção — medido em 2026-09-27

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00131-cjv`**, 100% do tráfego (medido por `gcloud` em 27/09, 17:40 UTC) — o deploy do **#119** (descriptions Meta com as chaves reais; run `36333559354`, `test` e `deploy` `success`), sobre o **#116** (F194) e o **#118** (F195); `/health?deep=1` devolveu `db: ok` e `tools: 68`. ⚠️ O smoke do pipeline segue sem handshake MCP **autenticado** (F186): as descriptions novas só aparecem em sessão MCP aberta depois do deploy (F140) |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | 22 always + 46 defer — **próxima remedição 04/10** ([método](tool-buckets-2026-09-04.md)) |
| Catálogo | até **F195** (~5.700 linhas, 572 KB) |

**Smoke de leitura do F193 em produção (26/09, `Conta Interna - 02`):** `filters_applied` em `get_campaign_performance` (com `campaign_status`, e sem ele com `status=all`), `get_account_overview` (aninhado `current`/`previous`, janelas iguais às de `period`/`previous_period`), `get_negative_keywords_audit` (`nivel: "campanha"`), `get_budget_pacing` (`{"during": "THIS_MONTH"}`) e `get_performance_breakdown` por keyword (`criterion_status`); razões `null` num período sem atividade. **Limite medido:** para período sem atividade o Google devolve uma linha **zerada**, não nenhuma linha — então `sem_dados_no_periodo` vem `false` com contagens zero, e só fica `true` quando não vem linha nenhuma. Quem protege a leitura são as razões `null`. As descriptions novas só aparecem em sessão MCP nova (F140).

**Smoke de leitura do F194 em produção (27/09, sessão MCP aberta depois do deploy):** na Cheiro | Conta 01, `meta_get_account_overview` e `meta_get_campaign_performance` trazem `purchases` medido (não `0`), `leads`, `messaging_conversations_started`, `ctr` em fração e `atribuicao: "unificada"`, com a soma das 19 campanhas igual ao total da conta; na janela da medição original (`27/08–25/09`), exatamente `purchases` 10, `leads` 13 e 3.531 conversas. `purchases: null` em conta com gasto e sem compra (MI Imports | Conta 02); `sem_dados_no_periodo: true` em conta sem entrega; breakdown horário com `reach` e `frequency` `null` em 50 de 50 linhas; BUC lido do cabeçalho real (`last_throttle_pct` gravado, nenhum `meta_buc_nao_lido`). **O preset do roteiro deu `purchases` 9, não 10:** o `LAST_30_DAYS` Meta inclui o dia corrente (`29/08–27/09`) e a referência terminava na véspera — é o **F195**. Detalhe no F194 do [catálogo](findings-catalog.md).

**Smoke de leitura do F195 em produção (27/09, run `36332640719`):** `meta_get_account_overview` na Cheiro | Conta 01 com `LAST_7_DAYS` ecoou `date_range` `20/09–26/09` — exatamente o `date_preset=last_7d` da própria Meta sondado no mesmo dia —, `previous_date_range` `13/09–19/09` e `inclui_dia_corrente: false`; com `TODAY`, `27/09` contra `26/09` e `inclui_dia_corrente: true`, com variações de ~−99% que são o dia ainda aberto — o caso que o campo existe para avisar. Chamado de uma sessão aberta antes do deploy: a resposta é do código novo; as descriptions novas só aparecem em sessão nova (F140).

**Verificação do F154 — pendente**, na execução do `v4-ads-mcp-resync` seguinte ao deploy (a diária ou uma sob demanda): a CHUTE 07 com `su_reachable = true`, o `meta_reconcile` com `unreachable: 0` e `alcance_nao_medido: 0`, e no painel a fila "Sem o system user atribuído" vazia.

⚠️ **`deploy: skipped` NAO significa "PR de documentação".** O gate do F138 pula o
deploy só quando o push mexeu **exclusivamente** em `docs/` e markdown — um arquivo em
`tests/` conta como código e publica revisão. Em 20/09 o merge do #97 (guard novo +
docs) deployou, e eu só percebi remedindo: **cheque a revisão servindo, não o rótulo
do PR.**

Contagens de tool e bucket vêm do registry (`import_all_tools()`), não de `grep` —
**`grep` e `ast.literal_eval` já erraram esta medição**, o segundo devolvendo zero (F183).

## Decision gates abertos

**`GOOGLE_RECONCILE_APPLY=true` desde 26/09 — as duas reconciliações revogam.** A Meta revoga
desde 05/09 (`META_RECONCILE_APPLY=true`, #41); a Google foi virada em 26/09, com autorização
nominal do Wellington, depois de 22 execuções de soak (05/09 a 26/09), todas `success` e
`complete` — a de 26/09 bateu a previsão (`removed=3`, `revoke_candidates=46`).

- **Raio medido na virada** (26/09, 18:13 UTC, transação READ ONLY): 3 contas desativadas e
  **46 grants** revogados — 34 do backlog em 9 contas já inativas + 12 das três que deixaram a
  unidade (`4493906974` DR DÉRICK VINHAS, `8726746966` Imperial Alimentos, `9450567241` Dra.
  Paula Minchillo). A **Alumínios Veneza** (`2640486995`, 4 grants) também saiu — churn
  confirmado em 26/09 —, com 1 ausência gravada: sai na 3ª, em **28/09**.
- **Conferido na primeira execução com a trava** (sob demanda, 26/09 às 23:21 UTC, execução
  `v4-ads-mcp-resync-6h6q6`): `applied=true`, `removed=3`, `revoked_grants=46` — a previsão
  exata —, 12 linhas `google_access_cleanup` (uma por conta, `left_mcc`), **zero** grant vivo em
  conta Google inativa e 26 contas ativas (as 25 do MCC + a Alumínios em carência). O raio foi
  medido duas vezes no dia (18:13 e 23:14 UTC), igual nas duas. A Meta, no mesmo job:
  `applied=true`, `removed=0`, `revoked_grants=0`; o `unreachable=1` é a CHUTE 07, igual desde
  24/09 pelo menos — artefato do índice `/me/adaccounts`, que o F154 tirou do job em 27/09 (a CHUTE 07 é lida).
- **Falta conferir a de 28/09:** `removed=1` e `revoked_grants=4` — a Alumínios Veneza na 3ª
  ausência.
- **Para desligar:** `false` nas **duas** linhas do `.github/workflows/deploy.yml` — o
  `JOB_ENV_VARS`, que o job lê, e o `--set-env-vars` do serviço, inerte mas mantido igual. A
  revogação é soft (`revoked_at`) e o painel reconcede com um clique.

**Fase 2B travada no soak** — o tombstone dos 8 reports antigos não acontece enquanto os
gestores não migrarem para `get_performance_breakdown`. Re-checar por `audit_log`.
⚠️ O plugin `v4-trafego-google-ads` **0.4.0 empurrava ativamente na direção errada**, com
duas afirmações falsas sobre o breakdown; o **0.4.1 corrigiu e está instalado** (20/09).
**Medido em 25/09:** o antigo segue mais usado que o novo — em 30 dias,
`get_campaign_performance` teve 148 chamadas de 3 gestores contra 33 do
`get_performance_breakdown` (1 gestor); desde 20/09, 20 contra 14. O 0.4.1 **já** manda
usar o breakdown em todos os skills, então o motor está em outro lugar: versão do plugin
na máquina dos outros gestores, ou o LLM escolhendo a tool pelo nome. Separar por gestor
é a medida de 04/10.

## Pendências que dependem do Wellington

- **Aplicar no plugin `v4-trafego-google-ads` o ajuste do `null`.** Seis pontos fazem conta ou ranking com campos que, desde o deploy de 26/09, podem vir `null` (`analise-performance-google-ads/SKILL.md:44,137`; `relatorio-cliente-google-ads/SKILL.md:33,76-89,112-116`; `shared/v4-brand.md:43`). O texto das mudanças foi entregue em 26/09; a cópia instalada é upload do app, então o ajuste é na fonte. Até lá o relatório de cliente pode imprimir `None`.
- **Remover do BM as contas Meta das quatro clientes que saíram** (decisão de 26/09): Dr. Dérick Vinhas (`act_4051924171730156`), Dra. Paula Minchillo (`act_1479232423809572`), Imperial Alimentos (`act_1648706246292124`) e Panelas Veneza (`act_374213944466235`, da Alumínios Veneza) — medidas em 26/09 alcançáveis pelo system user, com 4 grants vivos cada. A reconciliação Meta só revoga quando o alcance some: fora do BM, ela revoga sozinha em 3 execuções, com trilha. Revogar pelo painel foi descartado — o BM seguiria alcançando, e nada impediria reconceder.
- **Nível de acesso da API Meta.** O cabeçalho `x-fb-ads-insights-throttle` diz `ads_api_access_tier: development_access` (medido em 26/09): o app segue no Limited Access do **D1** de maio. A regra do D1 para pedir o Full Access é 500 chamadas em 15 dias; o uso medido em 26/09 é de ~200 por quinzena (395 chamadas Meta em 30 dias). Decisão sua: pedir agora com o volume atual, ou esperar.
- **F129** — governança do system user Meta: ação humana, fora do código.
- **F67** — custom domain `mcpv4.fluxocerto.dev.br`, pendente via LB.
- **Pedir ao TI da V4 uma identidade `@v4company.com` sem caixa postal** (alias ou conta de serviço) — é o que **desbloqueia o F186 por inteiro**: manager com grant zero, pior caso de vazamento `tools/list`, e a reconciliação não a toca. Sem ela não há token de CI possível: `sessions_create` só emite para o próprio manager logado, e login exige identidade Google do domínio. **Emitir sob um manager existente está recusado** — poria no GitHub Actions um token com alcance de ~38 contas Google e 26 Meta.
- **Varredura de `recommendation_subscription` sobre o MCC** — pedida pela sessão de tráfego a partir do F185. **Recomendado:** a tool de LEITURA, desenhada para varrer **só o que o gestor já alcança** (varredura que vê além do hard-gate de acesso vira caminho lateral para o gate) e para **contar os opacos em vez de descartá-los**. **Não recomendada:** a tool de escrita — o F185 mostra que 4 de 11 não têm chave, então ela alcançaria 7 de 11 e seria obrigada a dizer isso.

## Findings abertos

### Varredura de 21/09 (5 agentes paralelos, 4 sub-projetos)

Os 5 relatórios, recuperados do transcript em 25/09 (a extração de 21/09 tinha falhado),
estão em [`_archive/varredura-2026-09-21/`](../_archive/varredura-2026-09-21/README.md) —
com o destino de cada achado. **Os status lá são dos agentes**: achado que ninguém remediu
no código não vira trabalho até ser verificado.

| sub-projeto (decomposição de 21/09) | status |
|---|---|
| 1 · credencial + contratos do SDK Meta | fechado — **F190** |
| 2 · respostas que afirmam mais do que mediram | **fechado** — núcleo no **F191**, o resto no **F193** |
| 3 · infra de dados (CSV do audit, guard de reconnect, lock no `migrate.py`, `revoke` Meta) | **em parte** — CSV no F191; o resto é a frente *infra e guards* |
| 4 · guards que não cobrem (mock que bloqueava o conserto, testes que enumeram) | **em parte** — mock no F191; o resto é a frente *infra e guards* |

As **métricas Meta** que a nota do F190 chama de "sub-projeto 2" (`_parse_buc_header_pct`,
zero no lugar de campo ausente, `_brl` fixo, atribuição implícita) **nunca estiveram em
sub-projeto nenhum** — viraram a frente *métricas Meta*, fechada no **F194** (27/09).

### Ordem de ataque (atualizada em 26/09)

Medir a exposição, dar dado às decisões, consertos pequenos, e só então specs — um por vez.

1. **Rollout Google** — virado e conferido em 26/09; falta a execução de 28/09 (Alumínios Veneza).
2. **Fase 2B** — em 04/10, separar o uso por gestor, junto da remedição dos buckets.
3. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.
4. **`recommendation_subscription`** — tool de leitura no MCC.

### Os abertos, um por linha

| ID | o que é |
|---|---|
| **F180** | **em parte, provavelmente para sempre** — a flag `partial_failure` está ligada, mas a falha por-linha **nunca foi exercitada**: o Google aceita operação impossível em vez de errar (campanha `REMOVED`, `final_urls` inválida, anúncio apagado entre preview e apply). O único gatilho conhecido é a variação de experimento, que o **F181 agora bloqueia no pre-flight**. Consequência: `failed_count` é constante zero — leia `efeito` e `changed_count` |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e **sem chave nenhuma** — limitação da API, sem correção possível deste lado |
| **F187** | o **resumo no topo** de um artefato é a superfície de decisão e o **detalhe embaixo** é a verdade — 4 instâncias medidas, uma quase custou mutação em conta real. Remédio proposto: derivar o resumo, ou guard que cobre a igualdade |
| — | **`THIS_MONTH` do Google no dia 1 devolve janela invertida** (em 01/10: `01/10–30/09`) — achado em 27/09 ao consertar o F195, conferido na `main`; aceito por **15 tools Google**. Sessão separada sugerida para medir o que a GAQL faz com a janela invertida e propor o conserto. **Próximo dia 1: quinta, 01/10** |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado** — e o manager dele **não existe**: criar exige identidade de serviço no Workspace, acesso que o gestor **não tem**. **ABERTO como risco ACEITO.** No lugar entrou `tools` no `/health?deep=1` (sem credencial), e o desarme aparece como `::warning::` em todo deploy — **observado disparando** nos dois deploys de 21/09, que é o que separa "o aviso existe" de "o aviso avisa" |
| — | *negativas de grupo e listas compartilhadas na auditoria de negativas* (spec §7: frente própria) |
| — | follow-ups do **F193** (Minor, não bloqueiam) — listados no corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111): comentário da isenção do `apply_recommendation`, frase do eco nas três tools do F191, cobertura estreita de alguns testes |

**Fechados de 20 a 27/09:** **F179**, **F181–F184**, **F188**, **F189**, **F190**, **F191**, **F193**, **F194**, **F195** e **F154**. O defeito de cada um está no [catálogo](findings-catalog.md); a narrativa desses dias, que morava aqui, foi para [`_archive/estado-atual-2026-09-20-a-26.md`](../_archive/estado-atual-2026-09-20-a-26.md). 🔑 A lição que atravessa todos: **existia a regra e não existia o mecanismo** — a invariante escrita, e nada que a aplicasse.
