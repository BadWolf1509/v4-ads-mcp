# V4 Ads MCP — agent context

Auto-loaded by Claude Code. Read first.

**V4 Ads MCP** é tool interna da V4 Company (marketing digital, BR) que conecta Google Ads + Meta Ads accounts a Claude/Codex/Cursor via Model Context Protocol. Gestores pedem em PT-BR — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — e o assistente executa via tools curadas read/mutate com governança (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto, **hard-gate de acesso por conta**).

Interno only, não SaaS, sem terceiros. Substitui Supermetrics.

- **Production:** `https://v4-ads-mcp-299432068772.southamerica-east1.run.app` — projeto GCP **`v4-ads-mcp`** (Wellington é **owner**; migrado 2026-06-30 do antigo `v4-ads-mcp-prod`). Custom domain `mcpv4.fluxocerto.dev.br` pendente (via LB).
- **MCC Google Ads:** `6436352492` (V4 Maceió, 25 client accounts)
- **BM Meta Ads:** V4 Lima Soares & Co (`619664032237208`; ~19 ad accounts + 25 páginas via **system-user token all-targets** — Modelo B)
- **Unidade operacional:** V4 Lima Soares & Co (João Pessoa, PB) — Wellington dev + 3 colaboradores futuros
- **Admin:** `wellington.ribeiro@v4company.com`

## Stack

Python 3.13 (`.python-version`; `requires-python >=3.12,<3.14`) · FastAPI + Jinja2 + Tailwind (CSS gerado offline) + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (v24) · `facebook-business>=21.0.0` · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict. Sem build step no runtime nem no deploy — o CSS do Tailwind é **gerado offline** (`python scripts/build_tailwind.py`, pin 3.4.17) e **commitado** em `src/web/static/v4-tailwind.css`, com guard de diff no CI.

## Current state

**Última atualização:** 2026-08-15. **64 MCP tools** (58 Google + 6 Meta), bucket **23 always + 41 defer** — contagem verificada, não estimada. Smoke autenticado F58 segue dormente. F76/F77 encerrados.

**A sessão 2026-08-14/15 foi uma investigação ampla de bugs** (19 findings catalogados, **todos fechados** em duas ondas). O núcleo mudou de comportamento em pontos que valem saber de cara:

- Bookkeeping em `finally` não derruba mais a operação (`best_effort`, F83); chamada do SDK Google roda **fora do event loop** (`run_blocking`, F86); escape GAQL usa barra invertida (`_gaql.py`, F87).
- Gates de sessão usam `Manager.is_deactivated` (F84); pool caiu pra **5** conexões/instância (F92); jobs auditam crash e inventário parcial (F93).
- Tools Meta paginam e devolvem `truncated` (F88), e **não devolvem mais** `effective_status`/`creative_id`/`daily_budget_brl`/`billing_event` (F89).
- httpx silenciado (as linhas `HTTP Request:` sumiram do Cloud Logging de propósito) **e o token Meta saiu da query string** — vai em `Authorization: Bearer`, inclusive em cada página da paginação (F82).

Detalhe e lições: [`session-2026-08-14-15-handoff.md`](docs/operacao/session-2026-08-14-15-handoff.md).

**Frontend pós 2026-08-11** (o que mudou de premissa): **Tailwind não é mais CDN** — CSS gerado offline e commitado, com guard de diff no CI. **A CSP não tem nenhuma diretiva `unsafe-*`**: zero JS e zero CSS inline nas templates; comportamento em `v4-panel.js` via `data-v4-*`, estilo via classe. Assets com gzip + `Cache-Control` imutável versionado por `K_REVISION`. `domContentLoaded` do `/login`: **1128 ms → 261 ms**.

**Sessões recentes** (detalhe canônico nos handoffs — leia só o da sessão relevante):
- **2026-08-14/15** — investigação ampla de bugs sem escopo prévio: 19 findings catalogados (F82-F100), **todos fechados** em duas ondas (11 + 8). Núcleo, auth, jobs, Meta, pool, painel e backup tocados. [`session-2026-08-14-15-handoff.md`](docs/operacao/session-2026-08-14-15-handoff.md).
- **2026-08-11** — frontend medido no DOM de produção: Play CDN aposentado, CSP sem `unsafe-*`, a11y, +F78-F81. [`-08-11`](docs/operacao/session-2026-08-11-frontend-handoff.md).
- **2026-07-22/23** — 500 e 503 intermitentes por conexão asyncpg stale → F76 (`run_with_reconnect`) + F77 (deep health resiliente) + `severity` no Cloud Logging. [`-07-22`](docs/operacao/session-2026-07-22-handoff.md) · [`-07-23`](docs/operacao/session-2026-07-23-handoff.md).
- **2026-07-04** — 3 ondas de governança/dívida (F73 quota leak + cap por gestor; `_mutate_common`; lockfile; backup) e, na 2ª sessão, o pacote UI/UX do painel (F74/F75). [`-07-04`](docs/operacao/session-2026-07-04-handoff.md) · [`-07-04 UI`](docs/operacao/session-2026-07-04-ui-ux-handoff.md).
- **2026-07-02** — pós-migração: cutover (F68/F70), jobs CNB (F66), scheduler (F69), gate Meta obrigatório (F72), deploy gated pelo CI. [`-07-02`](docs/operacao/session-2026-07-02-handoff.md).
- **2026-06-30** — **migração GCP** pro projeto próprio (chaves regeneradas, token Meta all-targets). [`-06-30`](docs/operacao/session-2026-06-30-handoff.md).
- **Anteriores:** 06-20 (observabilidade + M.4 + Fase 2A) · 06-19 (recuperação de conta, F61-F63) · 05-29 (hard-gate + CSP).

**O que existe:** Foundation (Phases 0-1b/3a) + 40 sprints Google (3b.1→3b.40) + **Fase 2A** (`get_performance_breakdown` consolida 8 reports, aditivo) + família Meta (M.1→M.4 breakdowns) + camada de acesso/segurança (Modelo B + hard-gate + CSRF/CSP) + governança (audit sempre em mutates, **incl. Customer Match desde 07-02**) + **deploy gated pelo CI** + **painel web endurecido** (2026-08-11: sem CDN de CSS, sem JS/CSS inline, CSP sem `unsafe-*`, assets comprimidos e cacheados). Detalhe: [`sprint-history.md`](docs/operacao/sprint-history.md) + handoffs em `docs/operacao/`.

**Tokens válidos:** v4-ads Bearer (procedure abaixo; **Bearers antigos seguem válidos** pós-migração — validados por hash no DB compartilhado). Meta system-user token **all-targets** no secret `meta-system-user-token` (app *V4 Ads MCP* `1522411803012799`, SU `v4-ads-mcp-integracao` `61590110716028`, não expira). Meta OAuth pessoal do Wellington **reconectado em 11/08/2026** (audit `meta_oauth_connect` 23:35) — válido até **10/10/2026**. Continua dormente/opcional: as tools Meta rodam com o system-user token (Modelo B).

**✅ IAM GCP (resolvido 2026-06-30):** o projeto novo `v4-ads-mcp` tem **Wellington como owner** — lê/grava secrets, Cloud Run, jobs, rollback direto via gcloud (`gcloud ... --project=v4-ads-mcp`, autenticado `wellington.ribeiro@v4company.com`). **Não depende mais de Org Admin V4.** (O antigo `v4-ads-mcp-prod` seguia sem owner humano — motivo da migração; a decomissionar.)

**Próximo sprint candidato: M.5** (Meta `meta_get_audience_performance` + `meta_get_top_creatives`) — alimenta o volume do checkpoint Meta e é o próximo do roadmap ([`specs/2026-05-24-meta-ads-incorporation-design.md`](docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md)). **Fase 2B** (tombstone dos 8 reports — §4.1 do [refactor design](docs/superpowers/specs/2026-05-25-architecture-refactor-design.md)) fica **bloqueada no soak REAL**: em 07-02 os 8 antigos seguem em uso ativo e `get_performance_breakdown` está parado desde 06-24 — steering feito (nota de deprecação nas 8 descriptions), mas só tombstonar quando os gestores migrarem (re-checar `audit_log`).

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
4. **Atribuir o SU** às contas Meta faltantes no BM. **Lista reverificada em 11/08** (erros #200 `Ad account owner has NOT grant ads_management or ads_read`, todos em 05/08): `act_773918051591274`, `act_383566922510173`, `act_34358720650393626`, `act_370008662`. **CA-ROL GEAN `act_2399051240507488` saiu da lista** — voltou a responder OK.
5. **Revisar as 4 skills `v4-trafego-google-ads`** no claude.ai (fora do repo) pra apontarem `get_performance_breakdown` · **decisões:** checkpoint Meta (só 43 calls) + soak da Fase 2B.
6. **Smoke F58 dormente** (gestor smoke excluído 07-14) — deploys OK via fail-well; re-armar recriando gestor smoke sem grants + repor `SMOKE_MCP_BEARER` no GitHub se quiser a proteção ativa (memory `ci-smoke-bearer-dormant-2026-07`).

**Ambiente:** o `gcloud` está com credencial expirada (pede `gcloud auth login`) — reautentique antes de qualquer tarefa de infra (foi o que impediu de verificar se o `v4-ads-mcp-prod` ainda existe em 11/08).

**F76/F77 encerrados:** reabrir só se aparecer `mcp_auth_error` pós-`00026`, `health_deep_db_failed` persistente pós-`00028` ou incidente do uptime check.

**Quando ler outros docs:** [bug suspeito → `findings-catalog.md`] [o que shipou / detalhe sprint → `sprint-history.md`] [última sessão → `session-2026-08-11-frontend-handoff.md`] [infra/DB, sessão anterior → `session-2026-07-23-handoff.md`] [migração GCP → `session-2026-06-30-handoff.md`] [executar pendente → spec+plan em `docs/superpowers/`].

## Context bootstrap (minimum)

**Este arquivo já basta pra maioria das tarefas.** Carregue mais só quando a tarefa pedir:

1. **Vai mexer no núcleo** (executores, jobs, auth, tools Meta, pool)? Leia [`session-2026-08-14-15-handoff.md`](docs/operacao/session-2026-08-14-15-handoff.md) — é o estado mais recente e traz os padrões de erro que se repetiram.
2. **Vai mexer no painel web?** [`session-2026-08-11-frontend-handoff.md`](docs/operacao/session-2026-08-11-frontend-handoff.md).
3. **Antes de desenhar ou corrigir código**, faça busca **dirigida** em [`findings-catalog.md`](docs/operacao/findings-catalog.md) pela área/sintoma. O catálogo tem ~370 linhas e **99 IDs** — grep por palavra-chave (`GAQL`, `pool`, `Meta`, `audit`), nunca leitura integral.

> **Os 19 findings da investigação (F82-F100) estão FECHADOS.** Resíduo único e documentado: o `input_token` do `/debug_token` segue na query string — não é credencial do chamador e o endpoint rejeita POST (verificado). Guard AST em `test_no_secrets_in_query_params.py` impede segredo novo em `params=`, com allowlist por **(função, chave)**.

Carregue sob demanda:

- histórico de entrega → [`sprint-history.md`](docs/operacao/sprint-history.md);
- operação/DR/alertas → [`infra-setup.md`](docs/operacao/infra-setup.md) + [`backup-restore-runbook.md`](docs/operacao/backup-restore-runbook.md);
- roadmap Meta/M.5 → [`2026-05-24-meta-ads-incorporation-design.md`](docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md);
- Fase 2B → [`2026-05-25-architecture-refactor-design.md`](docs/superpowers/specs/2026-05-25-architecture-refactor-design.md);
- migração/cutover → [`session-2026-06-30-handoff.md`](docs/operacao/session-2026-06-30-handoff.md) + [`session-2026-07-02-handoff.md`](docs/operacao/session-2026-07-02-handoff.md).

Não grep `docs/_archive/`; use `git log` e abra um arquivo arquivado apenas quando o histórico apontar para ele.

## Conventions

> Full bug taxonomy + lessons: [`findings-catalog.md`](docs/operacao/findings-catalog.md). Detalhe por sprint: [`sprint-history.md`](docs/operacao/sprint-history.md).

### Princípios de código (Karpathy)

Heurísticas-teste pra reduzir erros típicos de LLM. Complementam o system prompt + cultura YAGNI. Fonte: [`andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills).

- **Teste das 200→50:** se escreveu 200 linhas e dava 50, reescreva. "Um eng. sênior chamaria isso de overcomplicado?" → se sim, simplifique.
- **Rastreabilidade da diff:** cada linha alterada rastreia direto ao pedido. Não "melhore" código adjacente nem refatore o que não está quebrado; remova só os órfãos que SUAS mudanças criaram.
- **Tarefa → meta verificável:** "corrige o bug" → "escreve teste que reproduz, depois faz passar".
- **Premissas explícitas:** múltiplas interpretações → apresente, não escolha em silêncio. Push back quando há caminho mais simples.

### Autorização por conta (hard-gate) — post sessão 2026-05-29

A matriz `manager_account_access` (Google) / `manager_meta_account_access` (Meta) é **autoritativa na camada MCP**: um gestor só lê/altera contas concedidas (sem bypass por role — admin idem).

- **Google:** `ensure_account_access(conn, *, manager_id, customer_id, session_id, operation_name, level)` em `src/google_ads/access.py` (raise `AccountAccessDeniedError` + audit `status="denied"`) é chamado no TOPO de TODO executor que builda o client: `run_report` (read), `run_mutation`, `run_conversion_upload`, `run_offline_user_data_job`, `run_recommendation_action` (write), e `create_pending` (build/preview), mais **`validate_gaql`** (gated no nível do TOOL — chama `build_client_for_manager` direto, FORA dos executores; era o site esquecido, classe F57). **Guard automatizado desde 07-02** (`tests/unit/test_structural_guards.py`): todo arquivo com `build_client_for_manager(` precisa ter `ensure_account_access(` (allowlist: `client.py`). Ao adicionar call-site, o guard falha se esquecer o gate.
- **Meta:** `run_meta_graph_get(..., ad_account_id, ...)` — `ad_account_id` é kwarg **OBRIGATÓRIO** (desde 07-02/F72) e o gate `can_manager_access` roda **incondicional** (antes era `params.get("ad_account_id")` + `if` = fail-open). Token de execução = system user compartilhado, então a matriz é o ÚNICO freio; guard `test_meta_graph_execution_is_contained` garante que `build_meta_api` só é chamado em `reports.py`. **Negação é SEMPRE auditada** (`status="denied"` fora do `if audit_this_call` — evento de segurança, espelha o Google).

### Segurança web (middleware) — post sessão 2026-05-29

`src/web/middleware.py`: `CSRFOriginMiddleware` (bloqueia método unsafe com Origin/Referer presente-e-divergente de Host; ausência permitida — SameSite=Lax é a defesa primária; isenta `/oauth/` + `/mcp`) + `SecurityHeadersMiddleware` (XFO/XCTO/Referrer/HSTS + **CSP enforcing** com allowlist em `_CSP_POLICY`).

- **Adicionou recurso externo** (script/style/font de novo host)? **Atualize `_CSP_POLICY`** no mesmo commit ou ele é bloqueado em produção. Allowlist atual (verificada 08-15): `unpkg.com` (script), `fonts.bunny.net` (style+font). `cdn.tailwindcss.com` **saiu** em 08-11 e há guard assertando a ausência — não re-adicione.
- Toda página renderiza HTML de input? Jinja autoescape cobre `{{ }}`; em f-strings/HTML manual use `html.escape` (XSS — `_error_page`, `_toggle_checkbox_fragment`).
- Exception handler em `src/app.py` (`StarletteHTTPException`): 3xx vira redirect (preserva 302→/login), `/mcp`+`/oauth` → JSON, resto → `error.html`. Ao mexer, **preserve o branch 3xx** (senão prende usuário não-autenticado).

### Git workflow + deploy

Solo dev on `main` (admin bypass). Commits: `feat(scope): …` / `fix(scope): …` / `docs(scope): …` / `chore: …`. Scopes: `web`, `admin`, `auth`, `db`, `mcp`, `meta_ads`, `ci`, `design-system`, `security`. Co-author trailer com Claude.

`git push origin main` → **CI roda; o Deploy é GATED** (desde 07-02): `ci.yml` job `test` → se verde, job `deploy` (`needs: test`, `uses: ./.github/workflows/deploy.yml` reusable) roda no MESMO commit (Buildpacks → **migrations Cloud Run Job** [F66 resolvido, `/cnb/process/migrate`] → deploy → route-to-latest → smoke `/health?deep=1`+`/mcp` 401 → rollback-on-failure com guard). NÃO há mais workflow "Deploy" standalone; o deploy aparece como job dentro do run do CI. Break-glass manual: `workflow_dispatch` no `deploy.yml`. **Confirme via `gh run view <id> --json conclusion` — NUNCA pelo exit code de `gh run watch` (engana).** Force secret novo: `gcloud run services update v4-ads-mcp --region=southamerica-east1 --update-secrets="<NAME>=<secret>:latest"` — mas adicione o secret também ao `--set-secrets` do `deploy.yml` (senão o próximo deploy o apaga).

### Verification cadence (always before commit)

```bash
python scripts/check_pre_push.py        # ~40s: ruff + format + mypy + unit + integration NÃO-DB. Sem Docker.
python scripts/check_pre_push_full.py   # opt-in: + pytest -m integration via testcontainers (~60-90s, Docker)
```

`check_pre_push.py` **NÃO roda os integration tests (testcontainers/DB)** — bugs de SQL/JOIN/cursor/transação só aparecem no CI (8min). Use o full sweep (Docker) ao mexer em queries/mutate/`_common`/migrations, OU aceite o CI como validador e corrija forward confirmando via `gh run view`.

### Test fixture pattern (integration)

Consuma `pg`/`db`/`app_with_db`/`client` de `tests/integration/conftest.py`; **NÃO redeclare localmente** (NÃO `db_pool` — não existe). 1 container Postgres **session-scoped** + template database (`tpl_app`, migrations rodam uma vez) — cada teste clona um banco novo via `CREATE DATABASE ... TEMPLATE` (isolamento total, sem pagar boot+migrations por teste). Mark `@pytest.mark.integration`. **Teste que exercita executor real precisa de grant no seed** (`manager_account_access.grant(...)`) senão o hard-gate levanta `AccountAccessDeniedError`. Generator de streaming com cursor: o teste DEVE **consumir** o output, não só disparar a rota (F58 — CSV export ficou quebrado em prod porque nenhum teste iterou).

### Schema gotchas (commonly-tripped)

- `audit_log.id` é `BIGSERIAL` (int8), NÃO UUID. `RETURNING id`.
- `audit_log.platform`: `Literal["google","meta"]`, default `"google"` — Meta tools passam explícito.
- `audit_log.provider_request_id` (renomeado de `google_request_id` em M.2a): genérico.
- `managers.id` UUID sem DEFAULT — caller provê `uuid4()`. `managers.status`: `'invited'|'active'|'inactive'` (+ `is_active` bool).
- `mcp_sessions.id` UUID DEFAULT `gen_random_uuid()`.
- `rate_counters` tem `operations_used` (NÃO `used_today`), PK `(developer_token_id, date)`.
- `pending_confirmations.token` (NÃO `id`) é PK; `payload` é jsonb.
- **JOIN + coluna duplicada (F59):** `audit_log` E `managers` têm coluna `status` → qualifique TODA clause com alias (`al.status`) em queries com JOIN.
- **asyncpg cursor exige transação (F58):** `async for row in conn.cursor(...)` PRECISA de `async with conn.transaction():`.

### Mutate builder test convention (post-3b.5, F16/F42/F44/F51)

**Use `tests/unit/fixtures/proto_capture.py::make_capture_client` (NÃO MagicMock)** ao assertar proto field assignments — MagicMock aceita qualquer atributo e mascara bugs.

```python
from tests.unit.fixtures.proto_capture import make_capture_client
client = make_capture_client()
ops = build_my_thing(client, customer_id, payload)
assert ops[0].field("ad_group_criterion_operation.create.negative") is True
assert ops[0].has("ad_group_criterion_operation.create.bid_modifier") is False
```

**Field rename guard (F51):** campo proto renomeado entre versões SDK → assertar presença do nome novo E **ausência** do antigo (`__setattr__` aceita qualquer atributo silenciosamente):
```python
assert ops[0].has("campaign_operation.create.start_date_time") is True
assert ops[0].has("campaign_operation.create.start_date") is False
```
Meta SDK usa dicts (não proto) — pattern future-only (`MetaCaptureClient` análogo quando houver mutate Meta).

### Pre-flight test convention (post-3b.5/3b.8)

Pré-flight via helper de `_common.py` → **mock o helper no namespace do TOOL** (NÃO `_common.py`):
```python
with patch("src.mcp.tools.<your_tool>.<helper_name>", AsyncMock(return_value=None)):
```
Patches em `src.mcp.tools.<tool>.run_report` NÃO cobrem o site de pré-flight. Mitigação: `check_pre_push_full.py`.

### Schema whitelist empirical validation (post-3b.19A)

Todo valor de enum em whitelist DEVE ser validado empiricamente em smoke runbook (criar entidade real por valor — SDK descriptors contêm valores que o runtime rejeita). Família: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44. Smoke runbook inclui per-value probe (batch 5/call). Rejeitado → remove do schema + documenta out-of-scope.

### No JSON Schema composition keywords (post-3b.19B.1)

`input_schema` NÃO pode ter `oneOf`/`allOf`/`anyOf` em nenhum nível (Anthropic validator rejeita). Constraints cross-field via `_validate_*` helper privado. Guard: `test_no_composition_keywords_in_any_schema`.

### Date range conventions (post-3b.20)

Reads + `bulk_pause_by_query`: **preset** (`date_range: str` com `type:"string"` + `enum`) ou **custom** (`start_date`+`end_date`, `^\d{4}-\d{2}-\d{2}$`, override). Resolve via `resolve_date_window` em `src/google_ads/queries/_common.py` (F1: schema sem `type` → Claude serializa dict como string literal). GAQL `BETWEEN end_date` é midnight-exclusive (F46) — `_format_change_date_between` aplica `+1 day`.

### Meta SDK conventions (post-M.2a/M.2b + Modelo B)

- **Execução = system-user token** (Modelo B, sessão 2026-05-29): `run_meta_graph_get` usa `build_meta_api(system_user_token=settings.meta_system_user_token, …)` em `src/meta_ads/client.py`. `build_meta_api_for_manager` (token pessoal) foi **removido** — o OAuth pessoal é dormante.
- **NUNCA `FacebookAdsApi.init()`** (global state, perigoso em async). Factory `build_facebook_ads_api()` constrói `FacebookSession` primeiro (F48 — `__init__` aceita só `session, api_version, enable_debug_logger`):
  ```python
  session = FacebookSession(app_id=..., app_secret=..., access_token=...)
  api = FacebookAdsApi(session=session, api_version="v22.0")
  ```
- **Audit Meta:** `audit_log.record(... platform="meta", provider_request_id=resp.headers().get("x-fb-trace-id"))`.
- **BUC post-call:** `record_actual_meta()` parseia `X-Business-Use-Case-Usage` → `meta_rate_counters` + throttle warning >75%.
- **2 endpoints, whitelists diferentes (F53/F54/F55):** `/insights` = SÓ metrics (spend, impressions, ctr, cpc, reach, frequency, actions, action_values, purchase_roas); `/campaigns`,`/adsets`,`/ads` = metadata (effective_status, daily_budget, creative_id, …). **Antes de shippar tool Meta com fields novos: use `ads_get_field_context([fields])` do Meta MCP oficial** (configurado em `~/.claude.json`) pra confirmar endpoint + existência — teria evitado F53+F54.
- **Long-lived token (OAuth pessoal, dormante):** Meta pode invalidar server-side antes do expiry natural; handle `to_friendly_meta_error` subcodes 458/467/460/463.

### Pós sessão 2026-06-19 (paginação Meta + GAQL error UX + resync)

- **`/me/adaccounts` paginado (F61):** o sync Meta DEVE seguir `paging.next` — helper `_fetch_all_adaccounts` em `src/auth/meta_oauth.py` (default 25/página; system user com 20+ ativos truncava o cache → MCP só via 12 das 22 contas). NÃO reverter pra single-page.
- **GAQL error UX (F62):** `to_friendly` em `src/google_ads/errors.py` trata o oneof `query_error` — mantém o campo cru E anexa dica (`list_gaql_resources`/`validate_gaql` + nota que auction insights não existem na GAQL). Clientes LLM (Codex) chutam campos via `run_gaql`; a mensagem enriquecida auto-corrige no próximo turno.
- **`get_change_history` clamp (F63):** `start_date` (preset OU custom) é clampado pro teto de 30 dias com warning em vez de deixar o Google rejeitar; janela inteira fora da retenção → `ValueError` claro.
- **Resync Meta piggyback:** `src/jobs/account_resync.py` chama `resync_meta()` (`src/jobs/meta_resync.py`) no fim — o job diário (Cloud Run Job `v4-ads-mcp-resync` + Cloud Scheduler) atualiza `meta_ad_accounts` zero-touch. Secret `META_SYSTEM_USER_TOKEN` montado no job via `deploy.yml --update-secrets`. Grants seguem manuais (Modelo B).
- **Migração de conta + IAM:** a conta admin antiga (owner do GCP) foi excluída → recuperação exigiu re-sync de OAuth/managers/grants. **Lição:** projeto prod sem owner humano = single point of failure (peça 2 owners). A deploy SA é least-privilege (não concede IAM — bom, mas significa sem auto-recuperação). Detalhe: handoff 2026-06-19.

### Pós sessão 2026-06-20 (observabilidade + performance breakdown pattern)

- **Observabilidade + health (Onda 1, F76/F77):** `bind_request_context`/`clear_request_context` estão plugados em `resolve_session_to_context`; `merge_contextvars` propaga `manager_id`/`session_id`; `add_cloud_logging_severity` converte `level`→`severity` no pipeline JSON. `/health?deep=1` executa `SELECT 1` via `connection.run_with_reconnect` com deadline global de 5s (readiness: 200 db=ok / 503 degraded); shallow `/health` segue inalterado. `max_inactive_connection_lifetime=120` é mitigação, não pre-ping.
- **Performance breakdown pattern (M.4 + Fase 2A):** dois tools-**irmãos** de mesma forma `(level, breakdown)` — `get_performance_breakdown` (Google) e `meta_get_performance_breakdown` (Meta). **Google:** módulo puro `src/google_ads/performance_breakdown.py` (`_validate_combo`+`_common_metrics`+`build_performance_breakdown_query`+`parse_performance_row`) ENVOLVE os builders `*_query` de `performance.py`/`tactical.py` (não reescreve). Matriz: `{campaign,ad_group,ad,keyword,audience}`+sem-breakdown OU `account`+`{device,geo,hourly}`; `account`+null → erro apontando `get_account_overview`. bucket=always, `audit_this_call=True`. **Meta:** `src/meta_ads/insights.py` (`build_insights_call(breakdowns=)`); breakdown→param Meta confirmado no smoke (platform→`publisher_platform`, device→`impression_device`, geo→`country`, hourly→`hourly_stats_aggregated_by_advertiser_time_zone`). **Aditivo** — os 8 reports Google antigos seguem vivos até a **Fase 2B** (tombstone pós-soak). Ao consolidar, **paridade bit-a-bit** com o report antigo é requisito (cross-check no smoke). `ads_get_field_context` NÃO cobre breakdowns → validação é smoke-probe per-combo (lição F53/F54/F55).
- **Builder test guard (Onda 0):** `test_builder_tests_use_capture_client_not_magicmock` (`tests/unit/test_tools_schemas.py`) — qualquer `test_*_builder.py` que referencie `MagicMock` SEM importar `make_capture_client` falha (anti-reincidência F16/F42/F44).
- **Guards estruturais (07-02):** `tests/unit/test_structural_guards.py` varre o source pra impedir reincidência: **F57** (`build_client_for_manager(` sem `ensure_account_access(`), **F57-Meta** (`build_meta_api(` fora de `reports.py`), **F58** (`.cursor(` sem `conn.transaction()`). Verificado que F57 dispara quando sabotado. Ao adicionar uma classe de bug recorrente, prefira um guard grep-based aqui em vez de "lembrar de fazer grep manual".

### Núcleo pós 2026-08-15 (invariantes novos — violar quebra guard)

Cinco mecanismos nasceram da investigação de 08-14/15. Cada um tem guard estrutural; o detalhe do porquê está no [handoff](docs/operacao/session-2026-08-14-15-handoff.md).

- **`best_effort` ([`governance/bookkeeping.py`](src/governance/bookkeeping.py)) — todo I/O de bookkeeping em `finally`.** Exceção num `finally` DESCARTA o `return` pendente: sem isso, falha ao gravar audit transformava mutação já aplicada no Google em erro pro gestor (F83). Quota e audit são blocos **independentes** — a falha de um não pode pular o outro.
- **`run_blocking` ([`google_ads/_blocking.py`](src/google_ads/_blocking.py)) — toda chamada do SDK Google.** É gRPC síncrono; no event loop congela a instância inteira, inclusive o `/health` (F86). **Streaming:** offloadar só a chamada não basta — o `for batch in stream` também faz I/O e precisa entrar na função offloaded. **ContextVar não volta da thread:** o `request-id` do interceptor tem que ser lido DENTRO do offload, senão some do audit em silêncio.
- **`gaql_string_literal` ([`queries/_gaql.py`](src/google_ads/queries/_gaql.py)) — todo texto livre em GAQL.** GAQL escapa com **barra invertida**, não com doubling de SQL (`''` é rejeitado — verificado contra a API real). A barra é escapada ANTES da aspa; inverter a ordem corrompe o resultado.
- **`Manager.is_deactivated` — todo gate de sessão.** `status` e `is_active` divergem e nada as sincroniza; ler só uma deixava Bearer MCP vivo após offboarding (F84).
- **`record_job_crash` + completude explícita nos jobs.** `record_job_run.status` é **obrigatório** (era o default `success` que mascarava falha). Inventário parcial NÃO alimenta deletion detection — nem no Meta (F93) nem no Google (F85).
- **`run_with_reconnect` em TODO read pré-operação** — os 9 sites quentes (deps do painel, os 5 gates Google, OAuth do client, gate Meta) já estão cobertos (F91). O gate **não** é read puro: a negação escreve audit, e essa escrita fica fora do retry (separada de fato no Meta; via `best_effort` no Google).
- **Backup = 1 snapshot.** `backup.py` roda descoberta + todos os COPYs numa conexão em `REPEATABLE READ`, em stream pro GCS (F94). Tabela por tabela em conexões distintas gera FK órfã e quebra o restore.
- **Teto em read novo:** `limit` no schema + `LIMIT limit+1` no builder (a sentinela alimenta `truncated`), e **`ORDER BY` sempre que o tool ordenar depois** — cortar antes de ordenar é a classe F88 (F98).

**Pool:** `connection.py` NÃO lê `Settings` — primitivo de infra não depende da config da app (isso derrubou a suíte de integração inteira uma vez). Quem serve tráfego (`app.py`) injeta `settings.db_pool_*`; job e script usam o default. O orçamento é **instâncias × pool ≤ teto do banco**, e há teste que verifica a conta.

### Subagent-driven development

`superpowers:subagent-driven-development` — fresh subagent/task + 2-stage review (spec + quality). Model: **haiku** (mecânico 1-2 arquivos) · **sonnet** (integração multi-arquivo, dispatchers, OAuth) · **opus** (arquitetura/review cross-cutting). Implementers paralelos OK só em arquivos não-overlapping; reviewers paralelos sempre OK. Adaptações comuns: `db_pool`→`db`, `audit_log.id: UUID`→int, `rate_counters.used_today`→`operations_used`.

### Migrations

`src/db/migrations/NNN_name.sql`, append-only (hook PreToolUse bloqueia editar migration commitada). **Sempre atualize a lista hardcoded em `tests/integration/test_migrations.py`** ao adicionar migration (M.1+M.2a tropeçaram). Manual apply (sem psql no Windows): `python -c` + asyncpg + `DATABASE_URL` do Secret Manager.

### Design system

Tailwind **gerado offline e commitado** (não CDN — ver Stack) + tokens em `src/web/static/v4-tokens.css`. **16 macros** em `_components.html`. **Editorial mode** (login/access-denied/help/hero): display 36-56px (use `text-4xl md:text-display` pra responsivo), red `#e50914`. **Operational mode** (audit/matriz/admin): compact 12-14px. `button()`/`<button>` dentro de `<form>` MUST `type="submit"` (F49). Status Meta na UI via filtro Jinja `meta_status_label` (registrado em routes.py). Card por padrão: `v4-card__header`/`v4-card__title` (h3).

Padrões pós-pacote UI/UX 2026-07-04 (2ª sessão):
- **Ação de mutação do painel via HTMX = HX-aware** (espelha `sessions_revoke` em routes.py): se `HX-Request` → `204` + `HX-Redirect`/`HX-Refresh` + `HX-Trigger` toast; senão `303`. NUNCA retornar `303` cru pra um `hx-post` — o XHR segue o redirect e injeta a página inteira no `hx-target` (era o bug do dropdown de Managers). `204` = no-swap por spec, então o `hx-target` legado fica inofensivo.
- **Flash de `?error=`/`?ok`**: mapa fixo código→mensagem PT-BR no handler; o query param NUNCA é ecoado no contexto (a macro `alert` renderiza `{{ message|safe }}` → eco = XSS). Código desconhecido → sem flash.
- **Contraste AA**: texto secundário sobre fundo claro usa `--v4-gray-500` (`#6b6b6b`, ~5.7:1); `--v4-gray-300` fica só em borders e texto sobre fundo escuro (code-block) — e ali exige o marcador `/* on-dark */` na linha, senão o guard `test_gray_300_nunca_usado_como_cor_de_texto` falha. Sobre os fundos soft use `--v4-gold-text`/`--v4-green-text` (o gold puro dava 3,8:1). **Token novo vai SÓ no `v4-tokens.css`** — o `tailwind.config.js` referencia `var(--v4-*)`, não há mais duplicação de hex.

Padrões pós-pacote de frontend 2026-08-11:
- **Tailwind é gerado offline.** Mexeu em classe utilitária de template? Rode `python scripts/build_tailwind.py` e **commite o CSS no mesmo commit** — o CI faz `git diff --exit-code`. O scanner lê o arquivo **inteiro, comentários incluídos**: citar o nome de um utilitário num comentário faz o CSS crescer.
- **`v4-tailwind.css` é o ÚLTIMO stylesheet do `<head>`** (guard `test_tailwind_e_o_ultimo_stylesheet`). O Preflight precisa vencer o `v4-base.css`: hoje `h1` sem classe utilitária é 14px/400, **não** os 36px/800 que o `v4-base.css` declara (essas regras são fallback morto). Reordenar os `<link>` estoura todo heading do painel.
- **Assets versionados**: os `<link>` levam `?v={{ asset_version }}` (de `K_REVISION`), o que torna seguro o `Cache-Control: immutable` do `CachedStaticFiles`. CSS de página específica entra via `{% block head_extra %}` — **top-level na template, nunca dentro de `{% block content %}`** (lá o Jinja renderiza o `<link>` no corpo).
- **Gzip**: `SelectiveGZipMiddleware` comprime tudo menos `/mcp` (SSE — buffering quebra o stream).
- **A11y**: `prefers-reduced-motion` no fim do `v4-motion.css`; foco por teclado via `:focus-visible` com `--v4-focus-color`; skip link `#conteudo`; nav declarada uma vez em `nav_items` e renderizada no header E no drawer (macro `current_attr`).
- **ZERO JavaScript E ZERO CSS inline. A CSP não tem nenhuma diretiva `unsafe-*`.** Atributo `on*=`/`hx-on`, bloco `<script>` ou atributo `style=` numa template é **bloqueado pelo browser**, silenciosamente.
  - Comportamento → [`v4-panel.js`](src/web/static/v4-panel.js), listener delegado por `data-v4-action` (`drawer-toggle`, `dropdown-toggle`, `row-toggle`, `dialog-open`/`dialog-close`, `copy`, `confirm`) ou `data-v4-autosubmit` / `data-v4-submit-once` / `data-v4-filter` / `data-v4-matrix-filter`. Ação nova = entrada no mapa `ACOES` (o guard confere).
  - Estilo → classe (utilitário Tailwind, inclusive arbitrary com `var()`: `top-[var(--v4-subnav-offset)]`) ou classe do design system. CSS de página entra por `{% block head_extra %}`.
  - **Escrita via CSSOM (`el.style.x = y`, `setProperty`) NÃO é bloqueada** — verificado empiricamente sob `style-src 'none'`. É por isso que os filtros, o drawer e a medição sticky funcionam.
  - Trocar `style=` por `class=` num elemento que já tem `class=` cria **dois atributos `class`** e o browser usa só o primeiro — funda no existente.
  - O `<style>` que o htmx injetava está desligado por `<meta name="htmx-config" content='{"includeIndicatorStyles": false}'>`; as regras vivem em `v4-motion.css`.
- **Fragmento HTMX não carrega handler.** O comportamento pós-swap é delegado (`data-v4-access-toggle`), então o HTML de reposição servido por rota não precisa re-emitir nada — era o F74, agora impossível por construção.
- **Tabela responsiva** = envolver em `.v4-table-wrap` (overflow-x + `white-space:nowrap` ESCOPADO ao wrapper em `th`/`.col-mono`). **EXCLUIR** tabelas com `v4-table--sticky-head` (o overflow mata o sticky) e com dropdown `position:absolute` (o wrapper clipa o menu) — ex.: `admin/audit.html` e `admin/managers.html`.
- **Fragmento HTMX de reposição** (ex.: `_toggle_checkbox_fragment`): o HTML de reposição DEVE re-emitir `hx-on::after-request` + `aria-label`, senão o feedback some após o 1º swap (F74). `hx-on` é string estática (sem XSS); preserve `html.escape` nos valores dinâmicos (`hx-vals`).
- **Fontes**: via `<link rel="preconnect">` + `<link rel="stylesheet">` no head de `_base.html` (NÃO `@import` no CSS — waterfall). Host `fonts.bunny.net` já na CSP (Montserrat + JetBrains Mono, sintaxe dual-family `family=a:...|b:...`).

### Tool bucket classification (post-3b.39 F1)

`@register_tool` aceita `bucket: Literal["always","defer"]` (default `"defer"`). Cada tool: `# bucket: …` line 1 + prefix `[CORE]`/`[DEFER]` + `_meta`. **D3:** bucket="always" → `_meta` inclui `"anthropic/alwaysLoad": true` (Claude Code v2.x `ENABLE_TOOL_SEARCH=true` defere tudo por default; este field promove always-loaded). Source: [`tool-buckets-2026-05-25.md`](docs/operacao/tool-buckets-2026-05-25.md).

### Procedimentos operacionais (raros)

- **Rotação Bearer v4-ads:** tokens SÓ válidos se issued via UI (NÃO inventar — backend valida hash, 401 se não bate). `/sessions` → Nova session → flash 60s do plaintext → cola em `~/.claude.json` `mcpServers.v4-ads.headers.Authorization` → restart → revoga antigo. NUNCA cole secret em chat.
- **Criar secret GCP (F47):** SEMPRE arquivo binary intermediário, NUNCA pipe `echo|gcloud` no PowerShell (CRLF mangling): `python -c "open('tmp.bin','wb').write(b'<v>')"` → `gcloud secrets versions add <name> --data-file=tmp.bin` → `Remove-Item tmp.bin; Clear-History`.
- **Remover field de `INSIGHTS_FIELDS_*`/enum whitelist:** `grep -rn "field_name" tests/` ANTES (check_pre_push não pega integration DB).

## Tools available (this Claude session)

- **gcloud** authed `wellington.ribeiro@v4company.com`, **owner** do projeto `v4-ads-mcp` (pós-migração 2026-06-30) — lê/grava secrets, Cloud Run, jobs, rollback direto (`--project=v4-ads-mcp`). `git push` → deploy (WIF/`GCP_DEPLOY_SA`). Antigo `v4-ads-mcp-prod` ainda existe sem owner (a decomissionar).
- **gh** authed `BadWolf1509`.
- **Secret Manager:** `gcloud secrets versions access latest --secret=<NAME> --project=v4-ads-mcp` (owner — funciona). **10 secrets montados** no serviço: `database-url`, `aes-master-key`, `session-signing-key`, `google-oauth-client-id`, `google-oauth-client-secret`, `google-ads-developer-token`, `google-ads-login-customer-id`, `meta-app-id`, `meta-app-secret`, `meta-system-user-token`. Os 3 `supabase-*` **saíram em 08-15** (F95: eram required em Settings sem nenhum leitor) — seguem existindo no Secret Manager, mas não são montados nem lidos; não os reponha. Guard `test_deploy_env_matches_settings.py` cruza as duas direções: env montado sem campo, e campo obrigatório sem montagem.
- **No psql no Windows** — `python+asyncpg` pra DB direto. **Docker** pode não estar rodando — testcontainers falham local, CI roda.
- **Supabase MCP** + **Meta MCP oficial** (`ads_get_field_context` pra validar fields Meta) em config. **Claude in Chrome** disponível pra smoke visual.
- **Hooks:** PostToolUse auto-format ruff em .py + PreToolUse guard contra editar migration commitada. PowerShell pipe converte LF→CRLF mesmo binary (F47).

## When in doubt

- **Feature nova?** `superpowers:brainstorming` ANTES de codar. **Spec pronta?** `writing-plans`. **Plano pronto?** `subagent-driven-development`. **Bug?** `systematic-debugging`.
- **Lib/SDK?** `plugin:context7:context7` (training data stale, esp. facebook_business + Meta Graph quirks).
- **F-finding?** `/findings-add`. **Quality audit?** `mcp-tool-quality-reviewer` subagent. **Smoke runbook?** `smoke-runbook-generator` subagent.

## Don't do

- Don't fazer I/O de bookkeeping em `finally` sem `best_effort` — exceção ali descarta o `return` e transforma operação já aplicada em erro (F83). Don't chamar SDK Google fora de `run_blocking` (F86). Don't interpolar texto livre em GAQL sem `gaql_string_literal` (F87). Don't ler `Settings` dentro de primitivo de infra (pool/cliente/logger) — quem serve tráfego injeta (F92).
- Don't confiar em guard que passou de primeira: verifique contra o código PRÉ-fix (sabotagem ou `git stash`). Aconteceu 3× nesta sessão — grep casando a própria docstring, AST exigindo forma que o codebase não usa, e AST vendo só dict literal quando o call-site monta o dict numa variável.
- Don't envolver em `run_with_reconnect` um bloco que ESCREVE — o retry re-executa a escrita. Separe o read, ou proteja a escrita com `best_effort` (F91). Don't pôr `LIMIT` sem `ORDER BY` num tool que ordena depois (F98/F88). Don't pôr segredo em `params=` de GET (guard AST em `test_no_secrets_in_query_params.py`; use header ou `data=` no POST).
- Don't assertar superfície de API externa por analogia. Teste que codifica a convenção errada é PIOR que teste ausente (aconteceu 3×: F87, F89, e os mocks do F84/F89 que nem conseguiam expressar o bug). Probe empírica primeiro — `validate_gaql` pro Google, `ads_get_field_context` pro Meta.
- Don't push sem `python scripts/check_pre_push.py` antes. Full sweep MANDATORY ao mexer em pré-flight de mutate, queries com JOIN/cursor, ou migrations.
- Don't confiar no exit code de `gh run watch` — confirme via `gh run view <id> --json conclusion`.
- Don't adicionar gate/pré-flight "a todos os executores" sem `grep` TODA função que chama `build_client_for_manager` (F57).
- Don't adicionar recurso externo (CDN/font) sem atualizar `_CSP_POLICY` no mesmo commit (CSP enforcing bloqueia).
- Don't usar `conn.cursor(...)` sem `async with conn.transaction()` (F58); don't deixar coluna sem alias em query com JOIN (F59).
- Don't fazer read idempotente de disponibilidade/hot-path (ex.: resolução de sessão ou deep health) com `pool.acquire()` cru — use `connection.run_with_reconnect(op)` (asyncpg NÃO faz pre-ping; F76/F77). Probe externo deve ter deadline interno menor (`health`: 5s interno < 10s externo). Retry só em read idempotente; mutação NÃO leva retry cego (pode ter commitado). Log Cloud Logging usa `severity` (não `level`) — `add_cloud_logging_severity` já cobre no pipeline JSON.
- Don't mexer em classe utilitária de template sem rodar `python scripts/build_tailwind.py` e commitar o CSS no MESMO commit (o CI faz `git diff --exit-code`). Don't reordenar os `<link>` do `<head>` — `v4-tailwind.css` por último, senão o Preflight perde e todo heading estoura. Don't subir o pin do Tailwind pra v4 (config CSS-first).
- Don't usar `--v4-gray-300` como cor de texto sobre fundo claro (2,1:1) — use `--v4-gray-500`; sobre fundo escuro, marque a linha com `/* on-dark */`. Don't aplicar gzip a `/mcp` (SSE). Don't pôr `{% block head_extra %}` dentro de `{% block content %}`.
- **Don't escrever JS nem CSS inline em template** (`onclick=`, `hx-on`, `<script>`, `style=`): a CSP não tem `unsafe-*`, então o browser bloqueia — e handler inline morre calado. Use `data-v4-*` + listener em `v4-panel.js`, e classe pro estilo. Vale também pra HTML montado dentro de string Jinja passada a macro (aspas escapadas escondem o atributo de grep).
- Don't fazer macro emitir markup que o consumidor não pode alcançar — `search_input` emitia `name=` enquanto o JS procurava `id=`, e os 4 filtros do painel ficaram mortos sem ninguém notar (F81). Handler inline falha em silêncio.
- Don't adicionar dependência sem checar "no build step" (HTMX via CDN; Tailwind gerado offline — sem node/Vite/React no runtime). Ao adicionar uma dep de PROD: editar `pyproject.toml` E **regenerar `requirements.txt` no MESMO commit** com `uv pip compile pyproject.toml -o requirements.txt --universal` (o `--universal` é obrigatório — sem markers de plataforma o `pywin32` win-only quebra o build Linux/CNB; o buildpack e o CI instalam desse lockfile).
- Don't montar envelope de mutate à mão — use `error_envelope`/`applied_envelope`/`preview_envelope` de `src/mcp/tools/_mutate_common.py` (erro canônico = `error_message`+`operation`; TTL via `DEFAULT_TTL_MINUTES`, nunca literal 10). Novo executor Google → padrão `reserved` (before_call global + `mgr:<uuid>` em transação externa, `record_actual` gated por `reserved`, audit SEMPRE; F73). Rate-limit tem cap por gestor via chave `mgr:<uuid>` em `rate_counters`.
- Don't mover uma função sem `grep` TODOS os patch-sites dela em `tests/` (não só os testes novos) — mock target no namespace antigo dá `AttributeError` só no CI com Docker (classe pre-flight mock-target, fix `dedd82a` 2026-07-04).
- Don't modificar dados de produção via SQL cru sem extremo cuidado (Python script + BEGIN/COMMIT + idempotência).
- Don't pular `superpowers:brainstorming` antes de trabalho criativo mesmo que pareça simples.
- Don't dispatch implementers em paralelo em arquivos OVERLAPPING (reviewers paralelos OK).
- Don't shippar tool sem per-value empirical probe em smoke pra enum whitelist (3b.19A.1 — pegou 10+ design-gaps).
- Don't usar MagicMock em builder tests de proto (use `make_capture_client` — F16/F42/F44).
- Don't incluir `oneOf/allOf/anyOf` em `input_schema` (Anthropic rejeita — 3b.19B.1).
- Don't chamar `FacebookAdsApi.init()`; don't passar `access_token`/`app_id`/`app_secret` direto pro `__init__` — use `FacebookSession` bridge / `build_facebook_ads_api()` (F48).
- Don't aplicar `is_allowed_email` (V4 domain) no callback Meta OAuth — `fb_email` é conta FB pessoal (A6); auth é o manager_id no state HMAC.
- Don't usar `{{ button() }}` em `<form>` sem `type="submit"` (F49).
- Don't retornar `303` cru de um handler chamado por `hx-post` — torne HX-aware (`204`+`HX-Redirect`/`HX-Refresh`, espelha `sessions_revoke`), senão o HTMX injeta a página no `hx-target` (dropdown Managers, 2ª sessão 07-04).
- Don't ecoar `request.query_params` no contexto da macro `alert` (`{{ message|safe }}` = XSS) — mapa fixo código→mensagem; don't envolver tabela `sticky-head`/com-dropdown em `.v4-table-wrap` (mata sticky / clipa menu).
- Don't shippar tool Meta com fields novos sem validar via `ads_get_field_context` (F53/F54/F55 — `/insights` vs `/entities`).
- Don't upload secret via pipe PowerShell — arquivo binary intermediário (F47); NUNCA cole secret em chat.
