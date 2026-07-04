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

Python 3.13 (`.python-version`; `requires-python >=3.12,<3.14`) · FastAPI + Jinja2 + Tailwind CDN + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (v24) · `facebook-business>=21.0.0` · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict. Sem build step de frontend.

## Current state

**Última atualização:** 2026-07-04. Produção verde no **projeto GCP novo** (`v4-ads-mcp`, Wellington owner), `/health?deep=1` db=ok. **~64 MCP tools** (58 Google + 6 Meta), bucket ~23 always + 41 defer. Agora com **alerting** (uptime+job-failed+logs), **backup semanal→GCS**, **lockfile pinado** e **CI DB ~45-90s** (era ~8min).

**Sessões recentes** (detalhe canônico nos handoffs — leia só o da sessão relevante):
- **2026-07-04** — investigação 2026-07-03 → **3 ondas**: **O1 governança** (F73 quota leak + cap por gestor · audit ações admin do painel · run_gaql limit/query no audit · validate_gaql rate-limit · purge diário), **O2 falhar bem** (alerting GCP · lockfile `requirements.txt` universal + pip-audit · smoke MCP autenticado · backup→GCS · infra-setup), **O3 dívida** (test-infra template DB · `_mutate_common` dedup 22 mutates + `error_message` canônico · dedup trio Meta + BUC via kwarg · dead code/micros/labels/CSV-injection). 2 fix-forwards no CI (lockfile pywin32 sem marker; mock-target Meta pós-dedup). **Deferido** (follow-up): sync Meta header, GAQL escape, oauth logs, migrations guard, pool config, doc-drift. [`session-2026-07-04-handoff.md`](docs/operacao/session-2026-07-04-handoff.md).
- **2026-07-02** — investigação → **6 ondas**: URL nova + decrypt UX no cutover (F68/F70), **F66 resolvido** (jobs CNB `/cnb/process/<type>`) + **scheduler resync recriado** (F69) + resync Meta deletion-detection (F65), Customer Match audit+rate-limit (F71) + **gate Meta `ad_account_id` obrigatório** (F72) + guards F57/F57-Meta/F58 + `create_rsa` policy topic, **deploy gated pelo CI** (`needs: test`), testes do núcleo + refactors Onda 4, **steering Fase 2B** (não tombstone). [`session-2026-07-02-handoff.md`](docs/operacao/session-2026-07-02-handoff.md).
- **2026-06-30** — **MIGRAÇÃO GCP** lift-and-shift pro projeto novo `v4-ads-mcp` (`299432068772`, Wellington owner, billing própria); `aes-master-key`/`session-signing-key` regeneradas (→ gestores reconectam Google), token Meta all-targets. [`session-2026-06-30-handoff.md`](docs/operacao/session-2026-06-30-handoff.md).
- **2026-06-20** — Onda 0/1 hardening + observabilidade + M.4 + Fase 2A · **2026-06-19** — recuperação conta + Meta 12→22 + GAQL error UX (F61/F62/F63). [handoffs `-06-20`/`-06-19`] · **2026-05-29** — acesso/segurança (hard-gate + CSP).

**O que existe:** Foundation (Phases 0-1b/3a) + 40 sprints Google (3b.1→3b.40) + **Fase 2A** (`get_performance_breakdown` consolida 8 reports, aditivo) + família Meta (M.1→M.4 breakdowns) + camada de acesso/segurança (Modelo B + hard-gate + CSRF/CSP) + governança (audit sempre em mutates, **incl. Customer Match desde 07-02**) + **deploy gated pelo CI**. Detalhe: [`sprint-history.md`](docs/operacao/sprint-history.md) + handoffs em `docs/operacao/`.

**Tokens válidos:** v4-ads Bearer (procedure abaixo; **Bearers antigos seguem válidos** pós-migração — validados por hash no DB compartilhado). Meta system-user token **all-targets** no secret `meta-system-user-token` (app *V4 Ads MCP* `1522411803012799`, SU `v4-ads-mcp-integracao` `61590110716028`, não expira). Meta OAuth pessoal do Wellington dormante (expira 27/07/2026).

**✅ IAM GCP (resolvido 2026-06-30):** o projeto novo `v4-ads-mcp` tem **Wellington como owner** — lê/grava secrets, Cloud Run, jobs, rollback direto via gcloud (`gcloud ... --project=v4-ads-mcp`, autenticado `wellington.ribeiro@v4company.com`). **Não depende mais de Org Admin V4.** (O antigo `v4-ads-mcp-prod` seguia sem owner humano — motivo da migração; a decomissionar.)

**Próximo sprint candidato: M.5** (Meta `meta_get_audience_performance` + `meta_get_top_creatives`) — alimenta o volume do checkpoint Meta e é o próximo do roadmap ([`specs/2026-05-24-meta-ads-incorporation-design.md`](docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md)). **Fase 2B** (tombstone dos 8 reports — §4.1 do [refactor design](docs/superpowers/specs/2026-05-25-architecture-refactor-design.md)) fica **bloqueada no soak REAL**: em 07-02 os 8 antigos seguem em uso ativo e `get_performance_breakdown` está parado desde 06-24 — steering feito (nota de deprecação nas 8 descriptions), mas só tombstonar quando os gestores migrarem (re-checar `audit_log`).

**Decision gates:** **checkpoint volume Meta** (janela 06-25→07-10; 500 calls/15d → re-submit Full Access) — volume real 07-02 = **só 43 calls, 2,3% erro** → longe de 500; M.5 alimentaria OU estender · **soak Fase 2A→2B** → NÃO tombstonar (ver "Próximo sprint" acima) · **2026-07-25** reconectar Meta OAuth Wellington.

**Pendente operacional (AÇÕES HUMANAS — runbook detalhado no handoff 2026-07-02):**
1. **Cutover:** **lucassoares** (token com chave AES antiga → vai ver a mensagem amigável de reconexão, F70) + **anderson** (`invited` → 1º login). Runbook: trocar URL v4-ads no `~/.claude.json` deles → `…299432068772.southamerica-east1.run.app/mcp` (Bearer vale) + relogar no painel novo (`/help` já mostra a URL certa) + restart.
2. **Decomissionar `v4-ads-mcp-prod`** (só após cutovers — o scheduler antigo ainda cobre o resync até lá, agora redundante) · **revogar** o token BTW temporário do Wellington.
3. **F67 custom domain** `mcpv4.fluxocerto.dev.br` via Load Balancer (southamerica-east1 não permite domain mapping direto; domínio já verificado).
4. **Atribuir o SU** às contas Meta faltantes no BM (ML Antiguidades, MDO Pinda, `act_34358720650393626` — erro de permissão 07-01).
5. **Revisar as 4 skills `v4-trafego-google-ads`** no claude.ai (fora do repo) pra apontarem `get_performance_breakdown` · **decisões:** checkpoint Meta (só 43 calls) + soak da Fase 2B.

**Quando ler outros docs:** [bug suspeito → `findings-catalog.md`] [o que shipou / detalhe sprint → `sprint-history.md`] [última sessão → `session-2026-07-02-handoff.md`] [migração GCP → `session-2026-06-30-handoff.md`] [executar pendente → spec+plan em `docs/superpowers/`].

## Read these first when continuing work

```
docs/operacao/findings-catalog.md            # ★ Bug history (F1-F72 + A1-A6 + D1-D3) — scan antes de design mutate/query
docs/operacao/sprint-history.md              # ★ Tabela por sprint (3b.1→3b.40 + M.4 + Fase 2A + Meta); F64+ só nos handoffs/catalog
docs/operacao/session-2026-07-02-handoff.md  # ★ Última sessão: 6 ondas (F66/scheduler, gate Meta, deploy gated pelo CI, Customer Match audit, refactors) + runbook cutover
docs/operacao/session-2026-06-30-handoff.md  # MIGRAÇÃO GCP (projeto novo v4-ads-mcp, owner próprio) + F64/F65/F66/F67
docs/operacao/session-2026-06-20-handoff.md  # Onda 0/1 hardening+observ + M.4 + Fase 2A (consolidação Google)
docs/operacao/session-2026-06-19-handoff.md  # recuperação conta + Meta 12→22 + GAQL error UX + resync
docs/operacao/session-2026-05-29-handoff.md  # acesso/segurança (matrix + hard-gate + CSP)
docs/superpowers/specs/2026-06-20-google-performance-breakdown-design.md  # Fase 2A (+ plano par em plans/) — molde pra Fase 2B
docs/superpowers/specs/2026-05-28-google-mcp-account-gate-design.md   # hard-gate de acesso por conta (Google)
docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md    # roadmap família Meta
docs/superpowers/specs/2026-05-25-architecture-refactor-design.md     # refactor 4 fases (Fases 1 + 2A ✅; 2B/3/4 pendentes)
docs/operacao/tool-buckets-2026-05-25.md     # bucket classification per-tool
docs/operacao/infra-setup.md                 # foundation setup
docs/operacao/dogfood-*.md                   # feedback real (MO-JP, ML Antiguidades, Nutry…)
docs/_archive/                               # sprints SHIPPED ≥7 dias — NÃO grep; use git log primeiro
```

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

- **Adicionou recurso externo** (script/style/font de novo host)? **Atualize `_CSP_POLICY`** no mesmo commit ou ele é bloqueado em produção. Allowlist atual: `cdn.tailwindcss.com`, `unpkg.com`, `fonts.bunny.net`.
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

- **Observabilidade (Onda 1):** `bind_request_context`/`clear_request_context` (em `src/logging.py`) estavam órfãos → plugados em `resolve_session_to_context` (`src/mcp/session.py`): `clear_request_context()` no início (padrão structlog) + `bind_request_context(manager_id=…, session_id=…)` após `set_current`. `merge_contextvars` já estava no pipeline → todo log do request carrega manager_id/session_id. `/health?deep=1` faz `SELECT 1` no pool (readiness: 200 db=ok / 503 degraded); shallow `/health` inalterado (smoke do deploy intacto).
- **Performance breakdown pattern (M.4 + Fase 2A):** dois tools-**irmãos** de mesma forma `(level, breakdown)` — `get_performance_breakdown` (Google) e `meta_get_performance_breakdown` (Meta). **Google:** módulo puro `src/google_ads/performance_breakdown.py` (`_validate_combo`+`_common_metrics`+`build_performance_breakdown_query`+`parse_performance_row`) ENVOLVE os builders `*_query` de `performance.py`/`tactical.py` (não reescreve). Matriz: `{campaign,ad_group,ad,keyword,audience}`+sem-breakdown OU `account`+`{device,geo,hourly}`; `account`+null → erro apontando `get_account_overview`. bucket=always, `audit_this_call=True`. **Meta:** `src/meta_ads/insights.py` (`build_insights_call(breakdowns=)`); breakdown→param Meta confirmado no smoke (platform→`publisher_platform`, device→`impression_device`, geo→`country`, hourly→`hourly_stats_aggregated_by_advertiser_time_zone`). **Aditivo** — os 8 reports Google antigos seguem vivos até a **Fase 2B** (tombstone pós-soak). Ao consolidar, **paridade bit-a-bit** com o report antigo é requisito (cross-check no smoke). `ads_get_field_context` NÃO cobre breakdowns → validação é smoke-probe per-combo (lição F53/F54/F55).
- **Builder test guard (Onda 0):** `test_builder_tests_use_capture_client_not_magicmock` (`tests/unit/test_tools_schemas.py`) — qualquer `test_*_builder.py` que referencie `MagicMock` SEM importar `make_capture_client` falha (anti-reincidência F16/F42/F44).
- **Guards estruturais (07-02):** `tests/unit/test_structural_guards.py` varre o source pra impedir reincidência: **F57** (`build_client_for_manager(` sem `ensure_account_access(`), **F57-Meta** (`build_meta_api(` fora de `reports.py`), **F58** (`.cursor(` sem `conn.transaction()`). Verificado que F57 dispara quando sabotado. Ao adicionar uma classe de bug recorrente, prefira um guard grep-based aqui em vez de "lembrar de fazer grep manual".

### Subagent-driven development

`superpowers:subagent-driven-development` — fresh subagent/task + 2-stage review (spec + quality). Model: **haiku** (mecânico 1-2 arquivos) · **sonnet** (integração multi-arquivo, dispatchers, OAuth) · **opus** (arquitetura/review cross-cutting). Implementers paralelos OK só em arquivos não-overlapping; reviewers paralelos sempre OK. Adaptações comuns: `db_pool`→`db`, `audit_log.id: UUID`→int, `rate_counters.used_today`→`operations_used`.

### Migrations

`src/db/migrations/NNN_name.sql`, append-only (hook PreToolUse bloqueia editar migration commitada). **Sempre atualize a lista hardcoded em `tests/integration/test_migrations.py`** ao adicionar migration (M.1+M.2a tropeçaram). Manual apply (sem psql no Windows): `python -c` + asyncpg + `DATABASE_URL` do Secret Manager.

### Design system

Tailwind CDN (no build) + tokens em `src/web/static/v4-tokens.css`. ~22 macros em `_components.html`. **Editorial mode** (login/access-denied/help/hero): display 36-56px, red `#e50914`. **Operational mode** (audit/matriz/admin): compact 12-14px. `button()`/`<button>` dentro de `<form>` MUST `type="submit"` (F49). Status Meta na UI via filtro Jinja `meta_status_label` (registrado em routes.py). Card por padrão: `v4-card__header`/`v4-card__title` (h3).

### Tool bucket classification (post-3b.39 F1)

`@register_tool` aceita `bucket: Literal["always","defer"]` (default `"defer"`). Cada tool: `# bucket: …` line 1 + prefix `[CORE]`/`[DEFER]` + `_meta`. **D3:** bucket="always" → `_meta` inclui `"anthropic/alwaysLoad": true` (Claude Code v2.x `ENABLE_TOOL_SEARCH=true` defere tudo por default; este field promove always-loaded). Source: [`tool-buckets-2026-05-25.md`](docs/operacao/tool-buckets-2026-05-25.md).

### Procedimentos operacionais (raros)

- **Rotação Bearer v4-ads:** tokens SÓ válidos se issued via UI (NÃO inventar — backend valida hash, 401 se não bate). `/sessions` → Nova session → flash 60s do plaintext → cola em `~/.claude.json` `mcpServers.v4-ads.headers.Authorization` → restart → revoga antigo. NUNCA cole secret em chat.
- **Criar secret GCP (F47):** SEMPRE arquivo binary intermediário, NUNCA pipe `echo|gcloud` no PowerShell (CRLF mangling): `python -c "open('tmp.bin','wb').write(b'<v>')"` → `gcloud secrets versions add <name> --data-file=tmp.bin` → `Remove-Item tmp.bin; Clear-History`.
- **Remover field de `INSIGHTS_FIELDS_*`/enum whitelist:** `grep -rn "field_name" tests/` ANTES (check_pre_push não pega integration DB).

## Tools available (this Claude session)

- **gcloud** authed `wellington.ribeiro@v4company.com`, **owner** do projeto `v4-ads-mcp` (pós-migração 2026-06-30) — lê/grava secrets, Cloud Run, jobs, rollback direto (`--project=v4-ads-mcp`). `git push` → deploy (WIF/`GCP_DEPLOY_SA`). Antigo `v4-ads-mcp-prod` ainda existe sem owner (a decomissionar).
- **gh** authed `BadWolf1509`.
- **Secret Manager:** `gcloud secrets versions access latest --secret=<NAME> --project=v4-ads-mcp` (owner — funciona). 13 secrets: `database-url`, `aes-master-key`, `session-signing-key`, `google-oauth-client-id`, `google-oauth-client-secret`, `google-ads-developer-token`, `google-ads-login-customer-id`, `supabase-url`/`supabase-anon-key`/`supabase-service-key`, `meta-app-id`, `meta-app-secret`, `meta-system-user-token`.
- **No psql no Windows** — `python+asyncpg` pra DB direto. **Docker** pode não estar rodando — testcontainers falham local, CI roda.
- **Supabase MCP** + **Meta MCP oficial** (`ads_get_field_context` pra validar fields Meta) em config. **Claude in Chrome** disponível pra smoke visual.
- **Hooks:** PostToolUse auto-format ruff em .py + PreToolUse guard contra editar migration commitada. PowerShell pipe converte LF→CRLF mesmo binary (F47).

## When in doubt

- **Feature nova?** `superpowers:brainstorming` ANTES de codar. **Spec pronta?** `writing-plans`. **Plano pronto?** `subagent-driven-development`. **Bug?** `systematic-debugging`.
- **Lib/SDK?** `plugin:context7:context7` (training data stale, esp. facebook_business + Meta Graph quirks).
- **F-finding?** `/findings-add`. **Quality audit?** `mcp-tool-quality-reviewer` subagent. **Smoke runbook?** `smoke-runbook-generator` subagent.

## Don't do

- Don't push sem `python scripts/check_pre_push.py` antes. Full sweep MANDATORY ao mexer em pré-flight de mutate, queries com JOIN/cursor, ou migrations.
- Don't confiar no exit code de `gh run watch` — confirme via `gh run view <id> --json conclusion`.
- Don't adicionar gate/pré-flight "a todos os executores" sem `grep` TODA função que chama `build_client_for_manager` (F57).
- Don't adicionar recurso externo (CDN/font) sem atualizar `_CSP_POLICY` no mesmo commit (CSP enforcing bloqueia).
- Don't usar `conn.cursor(...)` sem `async with conn.transaction()` (F58); don't deixar coluna sem alias em query com JOIN (F59).
- Don't adicionar dependência sem checar "no build step" (Tailwind/HTMX via CDN — sem node/Vite/React). Ao adicionar uma dep de PROD: editar `pyproject.toml` E **regenerar `requirements.txt` no MESMO commit** com `uv pip compile pyproject.toml -o requirements.txt --universal` (o `--universal` é obrigatório — sem markers de plataforma o `pywin32` win-only quebra o build Linux/CNB; o buildpack e o CI instalam desse lockfile).
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
- Don't shippar tool Meta com fields novos sem validar via `ads_get_field_context` (F53/F54/F55 — `/insights` vs `/entities`).
- Don't upload secret via pipe PowerShell — arquivo binary intermediário (F47); NUNCA cole secret em chat.
