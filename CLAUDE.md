# V4 Ads MCP — agent context

Auto-loaded by Claude Code. Read first.

**V4 Ads MCP** é tool interna da V4 Company (marketing digital, BR) que conecta Google Ads + Meta Ads accounts a Claude/Codex/Cursor via Model Context Protocol. Gestores pedem em PT-BR — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — e o assistente executa via tools curadas read/mutate com governança (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto, **hard-gate de acesso por conta**).

Interno only, não SaaS, sem terceiros. Substitui Supermetrics.

- **Production:** `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`
- **MCC Google Ads:** `6436352492` (V4 Maceió, 25 client accounts)
- **BM Meta Ads:** V4 Lima Soares & Co (22 ad accounts; execução via **system-user token** compartilhado — Modelo B)
- **Unidade operacional:** V4 Lima Soares & Co (João Pessoa, PB) — Wellington dev + 3 colaboradores futuros
- **Admin:** `wellington.ribeiro@v4company.com`

## Stack

Python 3.12 · FastAPI + Jinja2 + Tailwind CDN + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (v24) · `facebook-business>=21.0.0` · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict. Sem build step de frontend.

## Current state

**Última atualização:** 2026-05-29. Produção verde em `82d1060`, `/health` 200. **~62 MCP tools** (57 Google + 5 Meta), bucket ~22 always + 40 defer.

**O que existe:** Foundation (Phases 0-1b/3a) + 40 sprints Google (3b.1→3b.40) + família Meta (M.1→M.3.1.1) + **camada de acesso/segurança** (sessão 2026-05-28/29): Meta Access Matrix com system-user token (Modelo B), **hard-gate de acesso por conta** enforçado na camada MCP (Google + Meta), middleware de segurança (CSRF + CSP enforcing + SRI), e melhorias de UX/a11y do painel. Detalhe completo: [`sprint-history.md`](docs/operacao/sprint-history.md) (tabela por sprint) + [`session-2026-05-29-handoff.md`](docs/operacao/session-2026-05-29-handoff.md) (última sessão).

**Tokens válidos:** v4-ads Bearer (procedure abaixo, NÃO inventar). Meta system-user token no secret `meta-system-user-token` (não expira). Meta OAuth pessoal do Wellington dormante (expira 26/07/2026).

**Próximo sprint (escolha 1):** M.4 (Meta breakdowns geo+device+hourly — alta volume Caminho B+) · M.5 (Meta audience+top_creatives) · 3b.41 (refactor Fase 2: `get_performance_breakdown` consolida 9 reports). Roadmap Meta: [`specs/2026-05-24-meta-ads-incorporation-design.md`](docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md).

**Decision gates:** 2026-06-01 feedback F1 (bucket classification) · 2026-06-25→07-10 checkpoint volume Meta Caminho B+ (500 calls/15d → re-submit Full Access) · 2026-07-25 reconectar Meta OAuth Wellington.

**Pendente operacional:** quando os 3 colaboradores entrarem → conceder grants por gestor em `/admin/access` (Google + Meta); o hard-gate torna isso obrigatório pra eles operarem. Backlog técnico (sprint-history pra detalhe): audit_log gap em `run_gaql`/`get_my_audit_log`, `verify_campaign_state`, breakdowns Meta.

**Quando ler outros docs:** [bug suspeito → `findings-catalog.md`] [o que shipou / detalhe sprint → `sprint-history.md`] [última sessão → `session-2026-05-29-handoff.md`] [executar pendente → spec+plan em `docs/superpowers/`].

## Read these first when continuing work

```
docs/operacao/findings-catalog.md            # ★ Bug history (F1-F60 + A1-A6 + D1-D3) — scan antes de design mutate/query
docs/operacao/sprint-history.md              # ★ Tabela por sprint (3b.1→3b.40 + Meta + sessão acesso/segurança)
docs/operacao/session-2026-05-29-handoff.md  # ★ Última sessão: access matrix + hard-gate + segurança + UX
docs/superpowers/specs/2026-05-28-google-mcp-account-gate-design.md   # hard-gate de acesso por conta (Google)
docs/superpowers/specs/2026-05-28-meta-access-matrix-design.md        # Meta Modelo B (system user)
docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md    # roadmap família Meta
docs/superpowers/specs/2026-05-25-architecture-refactor-design.md     # refactor 4 fases (Fase 1 ✅)
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

- **Google:** `ensure_account_access(conn, *, manager_id, customer_id, session_id, operation_name, level)` em `src/google_ads/access.py` (raise `AccountAccessDeniedError` + audit `status="denied"`) é chamado no TOPO de TODO executor que builda o client: `run_report` (read), `run_mutation`, `run_conversion_upload`, `run_offline_user_data_job`, `run_recommendation_action` (write), e `create_pending` (build/preview). **São 6 choke points** — ao adicionar gate/pré-flight, `grep` TODA função que chama `build_client_for_manager` (F57: run_recommendation_action foi esquecido no plano inicial).
- **Meta:** `can_manager_access` em `run_meta_graph_get` (quando `params` tem `ad_account_id`). Token de execução = system user compartilhado, então a matriz é o ÚNICO freio.

### Segurança web (middleware) — post sessão 2026-05-29

`src/web/middleware.py`: `CSRFOriginMiddleware` (bloqueia método unsafe com Origin/Referer presente-e-divergente de Host; ausência permitida — SameSite=Lax é a defesa primária; isenta `/oauth/` + `/mcp`) + `SecurityHeadersMiddleware` (XFO/XCTO/Referrer/HSTS + **CSP enforcing** com allowlist em `_CSP_POLICY`).

- **Adicionou recurso externo** (script/style/font de novo host)? **Atualize `_CSP_POLICY`** no mesmo commit ou ele é bloqueado em produção. Allowlist atual: `cdn.tailwindcss.com`, `unpkg.com`, `fonts.bunny.net`.
- Toda página renderiza HTML de input? Jinja autoescape cobre `{{ }}`; em f-strings/HTML manual use `html.escape` (XSS — `_error_page`, `_toggle_checkbox_fragment`).
- Exception handler em `src/app.py` (`StarletteHTTPException`): 3xx vira redirect (preserva 302→/login), `/mcp`+`/oauth` → JSON, resto → `error.html`. Ao mexer, **preserve o branch 3xx** (senão prende usuário não-autenticado).

### Git workflow + deploy

Solo dev on `main` (admin bypass). Commits: `feat(scope): …` / `fix(scope): …` / `docs(scope): …` / `chore: …`. Scopes: `web`, `admin`, `auth`, `db`, `mcp`, `meta_ads`, `ci`, `design-system`, `security`. Co-author trailer com Claude.

`git push origin main` → CI + Deploy paralelos (Buildpacks → migrations Cloud Run Job → deploy → smoke `/health`+`/mcp` 401). **Confirme a conclusão via `gh run view <id> --json conclusion` — NUNCA pelo exit code de `gh run watch` (engana; retornou 0 em run que falhou, 3× nesta sessão).** Force secret novo: `gcloud run services update v4-ads-mcp --region=southamerica-east1 --update-secrets="<NAME>=<secret>:latest"` — mas adicione o secret também ao `--set-secrets` do `deploy.yml` (senão o próximo deploy o apaga).

### Verification cadence (always before commit)

```bash
python scripts/check_pre_push.py        # ~40s: ruff + format + mypy + unit + integration NÃO-DB. Sem Docker.
python scripts/check_pre_push_full.py   # opt-in: + pytest -m integration via testcontainers (~60-90s, Docker)
```

`check_pre_push.py` **NÃO roda os integration tests (testcontainers/DB)** — bugs de SQL/JOIN/cursor/transação só aparecem no CI (8min). Use o full sweep (Docker) ao mexer em queries/mutate/`_common`/migrations, OU aceite o CI como validador e corrija forward confirmando via `gh run view`.

### Test fixture pattern (integration)

Local `pg` + `db` fixtures per file (NÃO `db_pool` — não existe). Mark `@pytest.mark.integration`. **Teste que exercita executor real precisa de grant no seed** (`manager_account_access.grant(...)`) senão o hard-gate levanta `AccountAccessDeniedError`. Generator de streaming com cursor: o teste DEVE **consumir** o output, não só disparar a rota (F58 — CSV export ficou quebrado em prod porque nenhum teste iterou).

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

Reads + `bulk_pause_by_query`: **preset** (`date_range: str` com `type:"string"` + `enum`) ou **custom** (`start_date`+`end_date`, `^\d{4}-\d{2}-\d{2}$`, override). Resolve via `resolve_date_window` em `_common.py` (F1: schema sem `type` → Claude serializa dict como string literal). GAQL `BETWEEN end_date` é midnight-exclusive (F46) — `_format_change_date_between` aplica `+1 day`.

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

- **gcloud** authed `wellinton.ribeiro@v4company.com`, project `v4-ads-mcp-prod`. Admin bypass push OK.
- **gh** authed `BadWolf1509`.
- **Secret Manager:** `gcloud secrets versions access latest --secret=<NAME> --project=v4-ads-mcp-prod`. Secrets: `database-url`, `aes-master-key`, `session-signing-key`, `google-ads-developer-token`, `google-oauth-client-secret`, `meta-app-id`, `meta-app-secret`, `meta-system-user-token`, supabase keys.
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
- Don't adicionar dependência sem checar "no build step" (Tailwind/HTMX via CDN — sem node/Vite/React).
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
