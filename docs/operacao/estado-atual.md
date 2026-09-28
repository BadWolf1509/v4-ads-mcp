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

> **Última sessão:** [`session-2026-09-28-handoff.md`](session-2026-09-28-handoff.md)
> — a noite de 27/09 e o 28/09: o **F196** (`THIS_MONTH` no dia 1), o **F197** (só o job escreve
> o inventário), o **F198** (lockfile fechado), o lote de dependências e o `mcp` 1.30, e a
> verificação da execução diária de 28/09 (18 de 18). Antes: [`session-2026-09-27-handoff.md`](session-2026-09-27-handoff.md)
> (F194, F195, F154).

---

## Produção — medido em 2026-09-28

| | |
|---|---|
| Revisão servindo | **`v4-ads-mcp-00136-lxv`**, 100% do tráfego (medido por `gcloud` em 28/09, 15:41 UTC) — o deploy do **#124** (`mcp` 1.30.0, sozinho; run `36444473607`, `test` e `deploy` `success`, imagem `db71a3f` também no job `v4-ads-mcp-resync`), sobre o **#128** (lote de dependências e F198), o **#122** (F197), o **#121** (F196) e o **#120** (F154); `/health?deep=1` devolveu `db: ok` e `tools: 68`. ⚠️ O smoke do pipeline segue sem handshake MCP **autenticado** (F186); o do `mcp` 1.30 foi feito por uma sessão Claude autenticada |
| Tools | **68** (62 Google + 6 Meta) |
| Buckets | 22 always + 46 defer — **próxima remedição 04/10** ([método](tool-buckets-2026-09-04.md)) |
| Catálogo | até **F198** (~5.800 linhas, 581 KB) |

**Conferidos em produção, por leitura:** os smokes do F193 (26/09), do F194 e do F195 (27/09), a
execução diária de 28/09 (F154 e a Alumínios Veneza saindo: 18 de 18) e o `mcp` 1.30 por uma
sessão autenticada. O detalhe está nos handoffs e no catálogo; a narrativa que morava aqui, em
[`_archive/estado-atual-2026-09-27-a-28.md`](../_archive/estado-atual-2026-09-27-a-28.md). Um
limite medido segue valendo (F193): para período sem atividade o Google devolve uma linha
**zerada**, não nenhuma — quem protege a leitura são as razões `null`.

**Com data:** **01/10** — smoke de leitura do F196 (`THIS_MONTH` numa conta real devolve o dia 1,
não vazio) e do F199 (`get_budget_pacing` com `inclui_dia_corrente: true` e projeção `null`, não
30× o parcial); **04/10** — remedição dos buckets e do uso da Fase 2B por gestor.

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
`complete` — a de 26/09 bateu a previsão (`removed=3`, `revoke_candidates=46`). Conferidas depois
a primeira execução com a trava (26/09: `removed=3`, `revoked_grants=46`) e a de 28/09 (a Alumínios
Veneza na 3ª ausência: `removed=1`, `revoked_grants=4`), as duas com zero grant vivo em conta
inativa.

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
- **Remover do BM as contas Meta das quatro clientes que saíram** (decisão de 26/09): Dr. Dérick Vinhas (`act_4051924171730156`), Dra. Paula Minchillo (`act_1479232423809572`), Imperial Alimentos (`act_1648706246292124`) e Panelas Veneza (`act_374213944466235`, da Alumínios Veneza) — medidas em 26/09 alcançáveis pelo system user, com 4 grants vivos cada. A reconciliação Meta revoga quando a conta sai da parceria do BM: fora dele, em 3 execuções, com trilha — e desde o F197 nenhum botão reinicia essa carência. Revogar pelo painel foi descartado — o BM seguiria alcançando, e nada impediria reconceder.
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
| 3 · infra de dados (CSV do audit, guard de reconnect, lock no `migrate.py`, `revoke` Meta) | **fechado** — CSV no F191; o resto na frente *infra e guards* ([spec 2026-09-28](../superpowers/specs/2026-09-28-infra-e-guards-design.md)) |
| 4 · guards que não cobrem (mock que bloqueava o conserto, testes que enumeram) | **fechado** — mock no F191; o guard de reconexão que enumerava deu lugar ao pool validado, um ponto só ([spec 2026-09-28](../superpowers/specs/2026-09-28-infra-e-guards-design.md)) |

As **métricas Meta** que a nota do F190 chama de "sub-projeto 2" (`_parse_buc_header_pct`,
zero no lugar de campo ausente, `_brl` fixo, atribuição implícita) **nunca estiveram em
sub-projeto nenhum** — viraram a frente *métricas Meta*, fechada no **F194** (27/09).

### Ordem de ataque (atualizada em 28/09)

Medir a exposição, dar dado às decisões, consertos pequenos, e só então specs — um por vez.

1. **Fase 2B** — em 04/10, separar o uso por gestor, junto da remedição dos buckets.
2. **`recommendation_subscription`** — tool de leitura no MCC.
3. **F187** — o remédio do resumo × detalhe.

### Os abertos, um por linha

| ID | o que é |
|---|---|
| **F180** | **em parte, provavelmente para sempre** — a flag `partial_failure` está ligada, mas a falha por-linha **nunca foi exercitada**: o Google aceita operação impossível em vez de errar (campanha `REMOVED`, `final_urls` inválida, anúncio apagado entre preview e apply). O único gatilho conhecido é a variação de experimento, que o **F181 agora bloqueia no pre-flight**. Consequência: `failed_count` é constante zero — leia `efeito` e `changed_count` |
| **F185** | `recommendation_subscription`: 4 de 11 opacos e **sem chave nenhuma** — limitação da API, sem correção possível deste lado |
| **F187** | o **resumo no topo** de um artefato é a superfície de decisão e o **detalhe embaixo** é a verdade — 4 instâncias medidas, uma quase custou mutação em conta real. Remédio proposto: derivar o resumo, ou guard que cobre a igualdade |
| **F186** | 🔴 smoke autenticado do `/mcp` **desarmado** — e o manager dele **não existe**: criar exige identidade de serviço no Workspace, acesso que o gestor **não tem**. **ABERTO como risco ACEITO.** No lugar entrou `tools` no `/health?deep=1` (sem credencial), e o desarme aparece como `::warning::` em todo deploy — **observado disparando** nos dois deploys de 21/09, que é o que separa "o aviso existe" de "o aviso avisa" |
| — | *negativas de grupo e listas compartilhadas na auditoria de negativas* (spec §7: frente própria) |
| — | follow-ups do **F193** (Minor, não bloqueiam) — listados no corpo do [#111](https://github.com/BadWolf1509/v4-ads-mcp/pull/111): comentário da isenção do `apply_recommendation`, frase do eco nas três tools do F191, cobertura estreita de alguns testes |

**Fechados de 20 a 27/09:** **F179**, **F181–F184**, **F188**, **F189**, **F190**, **F191**, **F193**, **F194**, **F195**, **F154**, **F196**, **F197** e **F198**. O defeito de cada um está no [catálogo](findings-catalog.md); a narrativa desses dias, que morava aqui, foi para [`_archive/estado-atual-2026-09-20-a-26.md`](../_archive/estado-atual-2026-09-20-a-26.md). 🔑 A lição que atravessa todos: **existia a regra e não existia o mecanismo** — a invariante escrita, e nada que a aplicasse.
