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

> **Última sessão:** [`session-2026-09-25-26-handoff.md`](session-2026-09-25-26-handoff.md)
> — o mapa de 25 e 26/09: PRs #108 a #112, o F193 e o fim do soak Google.

---

## Produção — medido em 2026-09-26

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00127-9x6`**, 100% do tráfego (medido por `gcloud` em 26/09) — o deploy do **#111** (F193). `/health?deep=1` devolveu `db: ok` e `tools: 68`. ⚠️ O smoke do pipeline segue sem handshake MCP **autenticado** (F186); em 26/09 as tools responderam por uma sessão autenticada (smoke abaixo), que prova `tools/call`, não o `tools/list` da revisão nova |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | 22 always + 46 defer — **próxima remedição 04/10** ([método](tool-buckets-2026-09-04.md)) |
| Catálogo | até **F193** (~5.400 linhas, 563 KB) |

**Smoke de leitura do F193 em produção (26/09, `Conta Interna - 02`):** `filters_applied` em `get_campaign_performance` (com `campaign_status`, e sem ele com `status=all`), `get_account_overview` (aninhado `current`/`previous`, janelas iguais às de `period`/`previous_period`), `get_negative_keywords_audit` (`nivel: "campanha"`), `get_budget_pacing` (`{"during": "THIS_MONTH"}`) e `get_performance_breakdown` por keyword (`criterion_status`); razões `null` num período sem atividade. **Limite medido:** para período sem atividade o Google devolve uma linha **zerada**, não nenhuma linha — então `sem_dados_no_periodo` vem `false` com contagens zero, e só fica `true` quando não vem linha nenhuma. Quem protege a leitura são as razões `null`. As descriptions novas só aparecem em sessão MCP nova (F140).

⚠️ **`deploy: skipped` NAO significa "PR de documentação".** O gate do F138 pula o
deploy só quando o push mexeu **exclusivamente** em `docs/` e markdown — um arquivo em
`tests/` conta como código e publica revisão. Em 20/09 o merge do #97 (guard novo +
docs) deployou, e eu só percebi remedindo: **cheque a revisão servindo, não o rótulo
do PR.**

Contagens de tool e bucket vêm do registry (`import_all_tools()`), não de `grep` —
**`grep` e `ast.literal_eval` já erraram esta medição**, o segundo devolvendo zero (F183).

## Decision gates abertos

**`GOOGLE_RECONCILE_APPLY=false` — a virada está destravada e é decisão do Wellington.** O laço
de reconciliação Google roda em **observação** (compara, conta, não revoga); o lado **Meta já
revoga** (`META_RECONCILE_APPLY=true` desde 09/09). O soak terminou: 22 execuções diárias (05/09
a 26/09), todas `success` e `complete`, e a de **26/09 confirmou a previsão** — `removed=3` e
`revoke_candidates=46` (34 do backlog em 9 contas já inativas + 12 das três contas que deixaram a
unidade: `4493906974`, `8726746966`, `9450567241`), lido no `audit_log` em transação READ ONLY.
A contagem por estado segue em 34: em observação a remoção só é projetada. O PR 3 do
[spec do gate](../superpowers/specs/2026-09-05-gate-google-design.md) — filas no painel, alerta,
runbook — já está feito.

- **Como virar:** `GOOGLE_RECONCILE_APPLY=false` → `true` em **duas** linhas do
  `.github/workflows/deploy.yml`: o `JOB_ENV_VARS`, que o job lê, e o `--set-env-vars` do serviço,
  inerte mas mantido igual de propósito (o comentário ao lado explica). É PR com deploy.
- **Efeito:** a primeira execução seguinte (09:00 UTC) marca as três contas como inativas e revoga
  os 46 grants, cada um com trilha no `audit_log`; reconceder pelo painel restaura.
- **O freio:** em 26/09 o classificador do auto mode **recusou** a edição do `deploy.yml` como
  deploy em produção, depois de um "pode prosseguir" genérico. A virada precisa de
  **autorização nominal** na sessão ("autorizo virar a trava Google…").
- **Novo em 26/09:** `bumped=1` — Alumínios Veneza (`2640486995`, 4 grants vivos) faltou no
  inventário, 1ª ausência de 3 (ver pendências).

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

- **Autorizar nominalmente a virada da trava Google** — ver *Decision gates* acima.
- **Aplicar no plugin `v4-trafego-google-ads` o ajuste do `null`.** Seis pontos fazem conta ou ranking com campos que, desde o deploy de 26/09, podem vir `null` (`analise-performance-google-ads/SKILL.md:44,137`; `relatorio-cliente-google-ads/SKILL.md:33,76-89,112-116`; `shared/v4-brand.md:43`). O texto das mudanças foi entregue em 26/09; a cópia instalada é upload do app, então o ajuste é na fonte. Até lá o relatório de cliente pode imprimir `None`.
- **Alumínios Veneza (`2640486995`) faltou no inventário do MCC em 26/09** — 1ª de 3 ausências, 4 grants vivos. Saiu da unidade ou é transitório? Se seguir fora em 27 e 28/09 a reconciliação a remove; com a trava virada, revoga os 4 grants.
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
sub-projeto nenhum** — viraram a frente *métricas Meta*.

### Ordem de ataque (atualizada em 26/09)

Medir a exposição, dar dado às decisões, consertos pequenos, e só então specs — um por vez.

1. **Rollout Google** — soak concluído (26/09); falta a autorização nominal da virada.
2. **Fase 2B** — em 04/10, separar o uso por gestor, junto da remedição dos buckets.
3. **Métricas Meta** (spec) — zero no lugar de "não veio", e o limitador que lê "não sei" como 0%.
4. **F154** (spec).
5. **Infra e guards** (spec) — o resto dos sub-projetos 3 e 4.
6. **`recommendation_subscription`** — tool de leitura no MCC.

### Os abertos, um por linha

| ID | o que é |
|---|---|
| **F180** | **em parte, provavelmente para sempre** — a flag `partial_failure` está ligada, mas a falha por-linha **nunca foi exercitada**: o Google aceita operação impossível em vez de errar (campanha `REMOVED`, `final_urls` inválida, anúncio apagado entre preview e apply). O único gatilho conhecido é a variação de experimento, que o **F181 agora bloqueia no pre-flight**. Consequência: `failed_count` é constante zero — leia `efeito` e `changed_count` |
| **F154** | `/me/adaccounts` não é prova de alcance |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e **sem chave nenhuma** — limitação da API, sem correção possível deste lado |
| **F187** | o **resumo no topo** de um artefato é a superfície de decisão e o **detalhe embaixo** é a verdade — 4 instâncias medidas, uma quase custou mutação em conta real. Remédio proposto: derivar o resumo, ou guard que cobre a igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado** — e o manager dele **não existe**: criar exige identidade de serviço no Workspace, acesso que o gestor **não tem**. **ABERTO como risco ACEITO.** No lugar entrou `tools` no `/health?deep=1` (sem credencial), e o desarme aparece como `::warning::` em todo deploy — **observado disparando** nos dois deploys de 21/09, que é o que separa "o aviso existe" de "o aviso avisa" |
| — | *negativas de grupo e listas compartilhadas na auditoria de negativas* (spec §7: frente própria) |
| — | follow-ups do **F193** (Minor, não bloqueiam) — listados no corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111): comentário da isenção do `apply_recommendation`, frase do eco nas três tools do F191, cobertura estreita de alguns testes |

**Fechados de 20 a 26/09:** **F179**, **F181–F184**, **F188**, **F189**, **F190**, **F191** e **F193**. O defeito de cada um está no [catálogo](findings-catalog.md); a narrativa desses dias, que morava aqui, foi para [`_archive/estado-atual-2026-09-20-a-26.md`](../_archive/estado-atual-2026-09-20-a-26.md). 🔑 A lição que atravessa todos: **existia a regra e não existia o mecanismo** — a invariante escrita, e nada que a aplicasse.
