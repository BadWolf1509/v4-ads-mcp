# Estado atual — V4 Ads MCP

> **Volátil por natureza.** Esta é a seção que muda a cada sessão; ela vivia no
> `CLAUDE.md` e era o motivo de ele reinchar — estado e convenção no mesmo arquivo
> significa que todo trabalho novo empurra bytes para dentro do que é carregado
> sempre. O `CLAUDE.md` mantém um resumo de poucas linhas e aponta para cá.

> **Ao terminar uma sessão, atualize ESTE arquivo**, não o `CLAUDE.md`.

---

**Última atualização:** 2026-08-19. **64 MCP tools** (58 Google + 6 Meta), bucket **23 always + 41 defer** — contagem verificada, não estimada. Smoke autenticado F58 segue dormente. F76/F77 encerrados.

**Em 2026-08-19 houve tres investigações**: frontend (F101-F108), backend (F109-F112) e infra/CI (F113-F117), **todas fechadas**. Da infra/CI: o `ci.yml` ensinava a regenerar o lockfile **sem `--universal`**, comando que quebra o build Linux (F113); os 3 Cloud Run Jobs precisam dos 8 campos obrigatórios de `Settings` e o `deploy.yml` passou a declará-los com `--update-*` (merge), com guard (F114); o gate local ganhou o check do Tailwind que só existia no CI (F115); e o rollback ancorou na revisão que **estava servindo**, não na ordem de criação (F116). Detalhe: [`session-2026-08-19-infra-ci-handoff.md`](session-2026-08-19-infra-ci-handoff.md). Do backend, o que muda de premissa: **toda** chamada de SDK que atende request sai do event loop por [`src/blocking.py`](../../src/blocking.py) — o helper saiu de `google_ads/` porque agora serve o Meta também, e ganhou o guard que o F86 não tinha (F109); `get_my_rate_limit_status` devolve `manager` + `account` + `blocking_scope`, não mais chaves planas (F110); o audit Meta grava a conta do kwarg obrigatório (F111); e a política de blast radius, embora consultiva em 17 das 26 tools, está amarrada por teste derivado do source (F112). Detalhe: [`session-2026-08-19-backend-handoff.md`](session-2026-08-19-backend-handoff.md).

Do frontend (8 findings, F101-F108, todos fechados): O que mudou de premissa no painel: o rótulo acessível dos checkboxes da matriz vem por **`aria-labelledby` apontando pra fora do nó trocado** (F101); **toda** referência a `/static` carrega `?v=` (F102); a isenção de CSRF é **por rota**, não por prefixo — `/oauth/meta/revoke` e `/oauth/meta/refresh-accounts` deixaram de ser isentos (F106); `sessions_revoke` sem HTMX devolve **303** (F107). Detalhe: [`session-2026-08-19-frontend-handoff.md`](session-2026-08-19-frontend-handoff.md).

**A sessão 2026-08-14/15 foi uma investigação ampla de bugs** (19 findings catalogados, **todos fechados** em duas ondas). O núcleo mudou de comportamento em pontos que valem saber de cara:

- Bookkeeping em `finally` não derruba mais a operação (`best_effort`, F83); chamada do SDK Google roda **fora do event loop** (`run_blocking`, F86); escape GAQL usa barra invertida (`_gaql.py`, F87).
- Gates de sessão usam `Manager.is_deactivated` (F84); pool caiu pra **5** conexões/instância (F92); jobs auditam crash e inventário parcial (F93).
- Tools Meta paginam e devolvem `truncated` (F88), e **não devolvem mais** `effective_status`/`creative_id`/`daily_budget_brl`/`billing_event` (F89).
- httpx silenciado (as linhas `HTTP Request:` sumiram do Cloud Logging de propósito) **e o token Meta saiu da query string** — vai em `Authorization: Bearer`, inclusive em cada página da paginação (F82).

Detalhe e lições: [`session-2026-08-14-15-handoff.md`](session-2026-08-14-15-handoff.md).

**Frontend pós 2026-08-11** (o que mudou de premissa): **Tailwind não é mais CDN** — CSS gerado offline e commitado, com guard de diff no CI. **A CSP não tem nenhuma diretiva `unsafe-*`**: zero JS e zero CSS inline nas templates; comportamento em `v4-panel.js` via `data-v4-*`, estilo via classe. Assets com gzip + `Cache-Control` imutável versionado por `K_REVISION`. `domContentLoaded` do `/login`: **1128 ms → 261 ms**.

**Sessões recentes** (detalhe canônico nos handoffs — leia só o da sessão relevante):
- **2026-08-14/15** — investigação ampla de bugs sem escopo prévio: 19 findings catalogados (F82-F100), **todos fechados** em duas ondas (11 + 8). Núcleo, auth, jobs, Meta, pool, painel e backup tocados. [`session-2026-08-14-15-handoff.md`](session-2026-08-14-15-handoff.md).
- **2026-08-19** — três investigações. **Infra/CI**: 5 findings (F113-F117) [`-08-19 infra`](session-2026-08-19-infra-ci-handoff.md). **Frontend**: 8 findings (F101-F108), os três mais graves em pontos cegos de guards **verdes** [`-08-19 front`](session-2026-08-19-frontend-handoff.md). **Backend**: 4 findings (F109-F112) — o F86 tinha sido fechado **sem guard**, e 3 caminhos que servem request seguiam bloqueando o event loop [`-08-19 back`](session-2026-08-19-backend-handoff.md).
- **2026-08-11** — frontend medido no DOM de produção: Play CDN aposentado, CSP sem `unsafe-*`, a11y, +F78-F81. [`-08-11`](session-2026-08-11-frontend-handoff.md).
- **2026-07-22/23** — 500 e 503 intermitentes por conexão asyncpg stale → F76 (`run_with_reconnect`) + F77 (deep health resiliente) + `severity` no Cloud Logging. [`-07-22`](session-2026-07-22-handoff.md) · [`-07-23`](session-2026-07-23-handoff.md).
- **2026-07-04** — 3 ondas de governança/dívida (F73 quota leak + cap por gestor; `_mutate_common`; lockfile; backup) e, na 2ª sessão, o pacote UI/UX do painel (F74/F75). [`-07-04`](session-2026-07-04-handoff.md) · [`-07-04 UI`](session-2026-07-04-ui-ux-handoff.md).
- **2026-07-02** — pós-migração: cutover (F68/F70), jobs CNB (F66), scheduler (F69), gate Meta obrigatório (F72), deploy gated pelo CI. [`-07-02`](session-2026-07-02-handoff.md).
- **2026-06-30** — **migração GCP** pro projeto próprio (chaves regeneradas, token Meta all-targets). [`-06-30`](session-2026-06-30-handoff.md).
- **Anteriores:** 06-20 (observabilidade + M.4 + Fase 2A) · 06-19 (recuperação de conta, F61-F63) · 05-29 (hard-gate + CSP).

**O que existe:** Foundation (Phases 0-1b/3a) + 40 sprints Google (3b.1→3b.40) + **Fase 2A** (`get_performance_breakdown` consolida 8 reports, aditivo) + família Meta (M.1→M.4 breakdowns) + camada de acesso/segurança (Modelo B + hard-gate + CSRF/CSP) + governança (audit sempre em mutates, **incl. Customer Match desde 07-02**) + **deploy gated pelo CI** + **painel web endurecido** (2026-08-11: sem CDN de CSS, sem JS/CSS inline, CSP sem `unsafe-*`, assets comprimidos e cacheados). Detalhe: [`sprint-history.md`](sprint-history.md) + handoffs em `docs/operacao/`.

**Tokens válidos:** v4-ads Bearer (procedure abaixo; **Bearers antigos seguem válidos** pós-migração — validados por hash no DB compartilhado). Meta system-user token **all-targets** no secret `meta-system-user-token` (app *V4 Ads MCP* `1522411803012799`, SU `v4-ads-mcp-integracao` `61590110716028`, não expira). Meta OAuth pessoal do Wellington **reconectado em 11/08/2026** (audit `meta_oauth_connect` 23:35) — válido até **10/10/2026**. Continua dormente/opcional: as tools Meta rodam com o system-user token (Modelo B).

**✅ IAM GCP (resolvido 2026-06-30):** o projeto novo `v4-ads-mcp` tem **Wellington como owner** — lê/grava secrets, Cloud Run, jobs, rollback direto via gcloud (`gcloud ... --project=v4-ads-mcp`, autenticado `wellington.ribeiro@v4company.com`). **Não depende mais de Org Admin V4.** (O antigo `v4-ads-mcp-prod` seguia sem owner humano — motivo da migração; a decomissionar.)

**Próximo sprint candidato: M.5** (Meta `meta_get_audience_performance` + `meta_get_top_creatives`) — alimenta o volume do checkpoint Meta e é o próximo do roadmap ([`specs/2026-05-24-meta-ads-incorporation-design.md`](../superpowers/specs/2026-05-24-meta-ads-incorporation-design.md)). **Fase 2B** (tombstone dos 8 reports — §4.1 do [refactor design](../superpowers/specs/2026-05-25-architecture-refactor-design.md)) fica **bloqueada no soak REAL**: em 07-02 os 8 antigos seguem em uso ativo e `get_performance_breakdown` está parado desde 06-24 — steering feito (nota de deprecação nas 8 descriptions), mas só tombstonar quando os gestores migrarem (re-checar `audit_log`).

**Decision gates** (remedidos em **15/08** direto no `audit_log`: 2890 eventos totais desde 04/05; 1242 em 30d, 667 em 15d, 3 gestores ativos): **checkpoint volume Meta** — **221 chamadas/15d** contra a régua de 500/15d (390/30d, 574/90d). Não bate, mas cresceu: a projeção de 11/08 era ~172/15d. **86% do volume Meta é de um único gestor** (ver abaixo) · **soak Fase 2A→2B** → **NÃO tombstonar**: 82 chamadas aos 8 antigos contra 8 do `get_performance_breakdown` em 15d (10,2:1; 147×9 em 30d). **Achado que muda a estratégia:** `get_campaign_performance` sozinho é **179 dos 258** usos dos antigos em 90d (69%) e `get_hourly_performance` tem **zero** — não são 8 tools pra migrar, é essencialmente **uma**.

**Quem realmente usa (15/08, direto no DB — o registro anterior estava errado):**
- **`pedro.vytor@v4company.com`** é o usuário PRINCIPAL: 1659 eventos totais (mais que o admin), 943 em 30d, 335 das 390 chamadas Meta. Criado em 19/05. **Não constava nesta doc até 15/08** — o Gate 1 é movido por ele.
- **`wellington.ribeiro`** (admin): 1063 eventos totais, 204 em 30d.
- **`anderson.cordeiro`**: **1 evento no total**, 3 sessões MCP ativas. Tem Bearer, praticamente não usa.
- **`lucassoares`**: **0 eventos**, `last_seen_at` vazio — mas tem **1 sessão MCP ativa**. Ou seja, ele ENTROU no painel e emitiu um Bearer (só a UI emite, e só o próprio gestor); o que nunca houve foi uso. Não é "falta onboardar" — é token vivo sem uso, que é decisão diferente (revogar ou confirmar intenção).

**Pendente operacional (AÇÕES HUMANAS — runbook detalhado no handoff 2026-07-02):**
1. **`lucassoares`: token vivo sem uso — decidir revogar ou confirmar intenção.** Remedido em 15/08 e o registro anterior ("nunca onboardou") estava errado: ele tem **1 sessão MCP ativa**, logo entrou no painel e emitiu um Bearer. O que não existe é uso — `last_seen_at` vazio e **0 eventos desde 05/05**. Como o Bearer não expira sozinho, a pergunta não é mais "como ajudo ele a entrar", e sim **"ele vai usar?"** — se não, revogue a sessão em `/sessions` (credencial viva sem dono ativo é superfície à toa, com 34 grants Google + 28 Meta atrás dela). `anderson.cordeiro` está no mesmo padrão em menor grau: 3 sessões ativas e **1 evento no total**.
2. **Decomissionar `v4-ads-mcp-prod`** (só após cutovers — o scheduler antigo ainda cobre o resync até lá, agora redundante) · **revogar** o token BTW temporário do Wellington.
3. **F67 custom domain** `mcpv4.fluxocerto.dev.br` via Load Balancer (southamerica-east1 não permite domain mapping direto; domínio já verificado).
4. ~~**Atribuir o SU** às contas Meta faltantes~~ — **ENCERRADO em 15/08, e não como estava escrito.** A lista de 4 vinha dos erros #200 observados em 05/08, sem os nomes. Ao resolvê-los, nenhuma precisava de atribuição: `Mestre da Obra - Pinda` e `CA - ML Antiguidades` são **ex-clientes** da unidade; `WJX Construções` tem `account_status=101` (**conta fechada** no Meta); e `Wellington Ribeiro` é **conta pessoal sem business** — conta pessoal não pode receber system user, que vive dentro de um BM. A única conta real do problema (`CA - MDO João Pessoa`, `act_27798855556414269`) **não estava na lista** — apareceu só ao buscar os nomes — e foi **atribuída pelo gestor em 15/08**, verificada nas 3 camadas (GET no node, inventário `/me/adaccounts`, leitura de insights). O SU alcança **24 contas**.
   **Limpeza feita (autorizada, 15/08):** as 4 saíram do inventário (`is_active=false`) e **16 grants foram revogados** (4 contas × 4 gestores), com linha `meta_access_cleanup` no `audit_log`. O cache passou a bater com a realidade: **24 ativas, 24 alcançáveis**.
   **Duas lições que valem além deste item.** (a) `can_manager_access` **NÃO consulta `is_active`** — só a tabela de grants. Desativar no inventário sozinho não remove acesso nenhum; quem manda é o grant. (b) O resync **não** limpa isso sozinho, **por desenho**: `_deactivate_churned` agrupa por `business_id` e só cobre conta ausente de **BM ainda visível**. BM que some inteiro não deixa keep-list, e conta sem `business_id` é pulada de propósito (desativar sem escopo derrubaria conta viva — o F65). Logo, offboarding de cliente **exige limpeza manual** da matriz; não espere o job.
5. **Revisar as 4 skills `v4-trafego-google-ads`** no claude.ai (fora do repo) pra apontarem `get_performance_breakdown` · **decisões:** checkpoint Meta (só 43 calls) + soak da Fase 2B.
6. **Smoke F58 dormente** (gestor smoke excluído 07-14) — deploys OK via fail-well; re-armar recriando gestor smoke sem grants + repor `SMOKE_MCP_BEARER` no GitHub se quiser a proteção ativa (memory `ci-smoke-bearer-dormant-2026-07`).

**Ambiente:** o `gcloud` está com credencial expirada (pede `gcloud auth login`) — reautentique antes de qualquer tarefa de infra (foi o que impediu de verificar se o `v4-ads-mcp-prod` ainda existe em 11/08).

**F76/F77 encerrados:** reabrir só se aparecer `mcp_auth_error` pós-`00026`, `health_deep_db_failed` persistente pós-`00028` ou incidente do uptime check.

**Quando ler outros docs:** [bug suspeito → `findings-catalog.md`] [o que shipou / detalhe sprint → `sprint-history.md`] [última sessão → `session-2026-08-19-infra-ci-handoff.md` + `-backend-` + `-frontend-`] [infra/DB, sessão anterior → `session-2026-07-23-handoff.md`] [migração GCP → `session-2026-06-30-handoff.md`] [executar pendente → spec+plan em `docs/superpowers/`].

