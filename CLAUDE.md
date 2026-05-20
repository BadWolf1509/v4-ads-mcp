# V4 Ads MCP — agent context

This file is auto-loaded by Claude Code when starting a session in this repo. Read it first; it'll save you (and the human) a lot of explaining.

## What this project is

**V4 Ads MCP** is an internal tool from V4 Company (digital marketing agency, Brazil) that connects the company's Google Ads accounts to AI assistants (Claude Desktop, Codex CLI, Cursor, Claude Code) via the Model Context Protocol. Gestores de tráfego pedem em linguagem natural — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — and the assistant executes via curated read tools and governed mutation tools.

It is **internal only**: not a SaaS, not resold, no third-party data. Replaces V4's previous Supermetrics usage.

**Production URL:** `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`
**MCC under management:** `6436352492` (V4 Maceió, ~23 client accounts)
**Sole admin today:** `wellinton.ribeiro@v4company.com`

## Stack

- **Language:** Python 3.12+
- **Web:** FastAPI · Jinja2 templates · Tailwind via CDN (no build step) · HTMX 2.x
- **DB:** Supabase Postgres via `asyncpg` (no ORM, raw SQL with parameterized queries)
- **MCP:** `mcp>=1.2.0` Streamable HTTP transport with Bearer auth gate
- **Google Ads:** `google-ads>=27.0.0` SDK
- **Crypto:** AES-GCM for refresh tokens at rest, HMAC-SHA256 for signed cookies/state
- **Hosting:** Cloud Run (region `southamerica-east1`)
- **CI/CD:** GitHub Actions + Workload Identity Federation (no JSON keys)
- **Tests:** `pytest` + `testcontainers[postgres]` for integration, `respx`/`freezegun` for unit
- **Lint/types:** `ruff` (check + format) + `mypy` strict

## Current state (always update this section after major work)

**Last updated:** 2026-05-20

### Shipped + in production

| Phase | Status | Commit |
|---|---|---|
| Phase 0 — Foundation | ✅ 2026-05-03 | initial setup |
| Phase 1a — Auth + first MCP tool | ✅ 2026-05-04 | 23 accounts populated |
| Phase 2 — Read tools (16+3) | ✅ 2026-05-04 | 19 read tools live |
| Phase 3a — Core mutations (10) | ✅ 2026-05-04 | code-complete; bug-bash 2026-05-06 (11 fix commits) |
| Phase 1b — Web panel (initial) | ✅ 2026-05-05 | 9 pages |
| FE Redesign v2 (phases 0-5) | ✅ 2026-05-05 | 56 commits, see infra-setup.md |
| Phase 3a+ — `remove_negative_keywords` | ✅ 2026-05-06 | extra mutation tool [8b5d1d8](https://github.com/BadWolf1509/v4-ads-mcp/commit/8b5d1d8) |
| Sprint 3b.1 → 3b.23 (27 sprints, 2026-05-04→2026-05-17) | ✅ shipped + signed-off em conta real | **Archive:** [docs/operacao/sprint-history.md](docs/operacao/sprint-history.md). Includes audience CRUD (3b.4-3b.6), RSA CRUD (3b.16+18), conversion tracking setup (create_conversion_action 3b.19A + create_conversion_value_rule_set 3b.19B), 2 utility tools (rate_limit_status 3b.12 + audit_log 3b.13), date_range fix (3b.20), negative_keywords_audit enrichment+limit (3b.21+3b.23), F25+F27 schema cleanup (3b.22), UX bundle 3b.7, process improvements (pre-push integration sweep P2, registry auto-discovery 3b.14.1, F16 fixture cleanup 3b.17), and 25+ design-gap findings (A1-A5, F1-F28, UX-1/2/3) catalogued in [findings-catalog.md](docs/operacao/findings-catalog.md). |
| Sprint 3b.24 — `create_campaign` SEARCH v0 (5º create-pattern, 1st campaign create) | ✅ 2026-05-17/18 | Production revision final `v4-ads-mcp-00181-w7g`. 5 fix iterations (Sprint 3b.24.1-3b.24.5). **Tool count 46 → 47.** 5/6 bidding strategies validated em Nutry sandbox (TARGET_CPA/TARGET_ROAS rejected por F36 = Nutry sem conversion history; real V4 accounts funcionam). 7 F-findings documented (F29-F37, all design-gap-via-SDK-ambiguity family). Always-CONFIRM, chained mutation N+M+2 ops, V4 invariants: PAUSED + SEARCH + BR + PT. Runbook: [`phase-3b-24-bootstrap.md`](docs/operacao/phase-3b-24-bootstrap.md). |
| Sprint 3b.25 — `create_and_link_assets` (6º create-pattern, asset CRUD bundle) | ✅ 2026-05-18 | Production revisions `00188-cwv` → `00191-f56` (3b.25.1) → final (3b.25.2). **Tool count 47 → 48.** 15/15 PASS após 2 fix iterations em Nutry sandbox. 5 types (SITELINK, CALLOUT, STRUCTURED_SNIPPET, CALL, PROMOTION) × 3 levels (CUSTOMER, CAMPAIGN, AD_GROUP) × 1-20 batch. Chained mutation 2N ops. 3 F-findings: F38 (STRUCTURED_SNIPPET PT-BR header format), F39 (PROMOTION language_code BCP 47 pt-BR), F40 (discount_modifier NONE invalid). V4 invariants: BR + pt-BR + BRL. R6 critical micros formula validated (`percent_off × 10_000`). Runbook: [`phase-3b-25-bootstrap.md`](docs/operacao/phase-3b-25-bootstrap.md). |
| Sprint 3b.26 — `import_offline_conversions` (49th tool, first ConversionUploadService dispatcher) | ✅ 2026-05-18/19 | Production revisions `00196-h22` → `00199-l8v` (3b.26.1 F42 fix). **Tool count 48 → 49.** 9/12 PASS após 1 fix iteration + 3 deferred (F41 Nutry sandbox sem traffic — not a bug). T7 partial_failure path validated 100% com UNPARSEABLE_GCLID errors. F42 (HIGH): `UploadClickConversionsRequest.debug_enabled` removed em v24 SDK (1-line fix). First tool fora de GoogleAdsService.mutate — novo dispatcher `run_conversion_upload` parallel a `run_mutation`. V4 invariants: BRL + -03:00 timezone + LGPD consent.ad_user_data=GRANTED. Always-CONFIRM dry_run, partial_failure=True. Runbook: [`phase-3b-26-bootstrap.md`](docs/operacao/phase-3b-26-bootstrap.md). |
| Sprint 3b.27 — combo `update_conversion_action` (50th tool) + B1/F43 pre-flight fix em `update_keyword_status` | ✅ 2026-05-20 | Production revisions `00202-vhk` (Phase A) → `00203-h2n` (Phase B) → `00204-86d` (3b.27.1 F44 fix). **Tool count 49 → 50.** 14/14 PASS após 1 fix iteration. V0 com 2 fields mutáveis (`name`, `primary_for_goal`) — `include_in_conversions_metric` removido em F44 (immutable em v24). F43 (HIGH) Fixed: pre-flight async `validate_keyword_criterion_types` separa positive/negative criterion_ids + hard reject com `to_retry_with`. F44 (HIGH): Silent-acceptance family (14ª variante: A1-A5/F11/F12/F16-19/F25/F27/F30-37/F38-40/F42/F43/F44). Caso real MO 23/05 (Opção C SIMPLIFICADA — rebaixar Store visits action via `primary_for_goal=false`) destravado. Runbook: [`phase-3b-27-bootstrap.md`](docs/operacao/phase-3b-27-bootstrap.md). |
| Sprint 3b.28 — `upload_customer_match_list` (51st tool, second non-mutate dispatcher) | ✅ 2026-05-20 | Production revisão `v4-ads-mcp-00206-rwv`. **Tool count 50 → 51.** 6/11 PASS + 5 DEFERRED (F45 env limitation — Nutry sandbox sem CRM_BASED_USER_LIST / Customer Match terms acceptance). Validation paths (T1-T6 Layer 1/2/3 reject paths) verified em produção; happy paths (T7-T11) covered via 31 unit tests + 5 integration tests incluindo LGPD raw-query (payload em pending_confirmations SEM plaintext). V0 minimal: 2 identifier types (email + phone_number) × 2 operation types (add + remove). LGPD invariants: consent.ad_user_data + consent.ad_personalization GRANTED hardcoded + enable_partial_failure=True + audit log sem plaintext. Fire-and-forget async (tool retorna `job_resource_name` + run_gaql template pra polling status — jobs processam em horas backend). Segundo dispatcher non-mutate (`run_offline_user_data_job` paralelo a `run_conversion_upload` do 3b.26). 3-step Google API sequence (create_job → add_ops → run_job). QW1 prep: ProtoFieldCapture retrofit em `test_run_conversion_upload.py` commit `e055ef7`. Runbook: [`phase-3b-28-bootstrap.md`](docs/operacao/phase-3b-28-bootstrap.md). |

**51 MCP tools** registered: 23 read + 27 mutations + `apply_change`. Production revision `v4-ads-mcp-00206-rwv` (Sprint 3b.28 Phase A; /health 200, CI green).
**15 web pages** in production with Hybrid Editorial+Operational identity (FE Redesign v2).
**Q8 invite-only allowlist** active — only `@v4company.com` emails pre-invited via `/admin/invites` can complete OAuth.
**`BOOTSTRAP_ADMIN_EMAILS`** env on Cloud Run = `wellinton.ribeiro@v4company.com` (dormant since managers table is populated).

### Pending / future

- **Modelo operacional: solo dogfood com contas reais** — `wellinton.ribeiro@v4company.com` é o único gestor de tráfego usando o MCP por enquanto. Sinal de produto vem de uso direto + smoke runbook em conta real (modelo [`phase-3b-1-bootstrap.md`](docs/operacao/phase-3b-1-bootstrap.md), que pegou 2 bugs reais no Sprint 3b.1). Lucas Soares (`lucassoares@v4company.com`) tem OAuth + MCP session ativos mas dormentes — gestor real V4, sem expectativa de uso por enquanto. Multi-gestor + multi-tenancy ficam adiados.
- **Standard Access (Google Ads) — submetido, sem bloqueio operacional** — case `26521440673` resubmetido 2026-05-11 (submissão original 2026-05-05 não retornou veredicto). Análise empírica 2026-05-17 via `rate_counters`: uso atual 11/15.000 ops/dia (0.07%), pico histórico 119 ops em 2026-05-12 (0.8%). Projeção worst-case com TODAS as mutation tools pendentes ativadas (`create_campaign`, `create_asset`, `link_assets`, `upload_customer_match_list`, `import_offline_conversions`) + uso pesado simultâneo = ~200-500 ops/dia, ainda 30x abaixo do limite Basic. Standard Access é benefício organizacional (due diligence Google, acesso a features tipo reach planner) + teto pra cenário multi-tenant futuro (5+ gestores simultâneos), não constraint operacional pra modo solo dogfood atual. Quando aprovar, mudança é 1 linha em `rate_limit.py:20` (`DAILY_QUOTA_BASIC` → `DAILY_QUOTA_STANDARD`) — sem refactor pendente, sem sprint represado. Aguardar veredicto Google passivamente.
- **Phase 3b restante** — Sprints 3b.24, 3b.25, 3b.26, 3b.27, 3b.28 shipados em produção (51 MCP tools). Sprint 3b.28 entregou `upload_customer_match_list` V0 (2 identifier types email+phone, 2 operation types add+remove, fire-and-forget async). A4 investigation (Customer Match exclusion mechanism aberto desde Sprint 3b.4/3b.5) permanece OPEN — agora desbloqueada via tool entregue, vai pra Phase B futura (Sprint 3b.28.x ou 3b.29 dedicado).
  - **Sprint 3b.29 candidate (next-in-queue)** — família audit_* curadas começando por `audit_quality_score` (#4 ICE 504 do dogfood MO-JP) OR `remove_*` bundle. Decisão depende de prioridade Wellington.
  - **Sprint 3b.30 candidate** — `remove_keyword/campaign/ad_group/ad/asset` bundle (cleanup ops + cleanup de ~75 entities criadas em Nutry sandbox durante smokes 3b.24-3b.28).
  - **Sprint 3b.31+ candidates (família "audit_*" curadas, do ICE dogfood MO-JP)** — `audit_competitor_keywords` (#6 ICE 432), `audit_zombie_keywords`, `audit_orphan_smart_actions`, `audit_negative_criterion_overlap`, `audit_assets_parity_between_campaigns`. Família coesa — vale dispatcher shared. Recorrência alta em sessões de cirurgia (próxima MO + outras contas V4 herdadas).
  - **A4 investigation deferred** — agora desbloqueada via `upload_customer_match_list`. Sprint dedicado 3b.28.x ou 3b.29 pode investigar mecanismo real de Customer Match exclusion (`campaign + user_list` que Google silently overrides hoje).
  - **Sprint 3b.25.x candidate** — per-value empirical probe pros 11 PT-BR STRUCTURED_SNIPPET headers tentativos (`Bairros`, `Comodidades`, etc — 2 validados em smoke: `Serviços` + `Marcas`)
  - **Sub demanda:** retrofit ProtoFieldCapture em builders pré-3b.5 (YAGNI) + em `test_run_conversion_upload.py` (recomendação `mcp-tool-quality-reviewer` 2026-05-19 — mitiga risco F42-recur em dispatchers custom tipo 3b.28); `update_conversion_action`/`update_conversion_value_rule_set` (simetria CRUD); STORE_VISIT/STORE_SALE support em RuleSet; B2/B3/B4/B5 do dogfood MO-JP (UX improvements `validate_gaql` + tool descriptions, LOW severity).
  - **Sprint 3b.19B Nutry smoke pending Wellington execution** (único smoke pendente do backlog antigo)
  - **No quota blockers** — análise empírica 2026-05-17: uso atual ~0.07% Basic, worst-case ~3%. Decisão de próximo sprint depende de sinal do dogfood + prioridade do gestor.
- **Sub-projetos 2-4 (multi-tenancy)** — `unidades` table + 3-tier RBAC, multi-MCC OAuth, migração single→multi. Adiado indefinidamente (sem demanda — modelo solo é o estado atual e Lucas não vai operar).
- **Quality wins menores** — ~~datetime.utcnow → datetime.now(UTC)~~ ✅ 2026-05-11; ~~GitHub Actions Node 20 → 24 (bump `actions/checkout@v4→@v5`, `setup-python@v5→@v6`, `auth@v2→@v3`)~~ ✅ shipped via commits `ad74d8d` (Actions bump) + `cd27c2b` (setup-gcloud@v2→@v3 final holdout); ~~revogar legacy "unknown" OAuth do Phase 1a~~ ✅ 2026-05-11 (connection `43a78bc1-d1e4-4077-9774-5d6a4bd49a89` soft-revoked)

## Read these first when continuing work

```
docs/operacao/findings-catalog.md       # ★ START HERE for bug history (A1-A5, F1-F37, UX-1/2/3 by class)
docs/operacao/sprint-history.md         # ★ Detailed table 3b.1→3b.19B (recent sprints inline above)
docs/operacao/infra-setup.md            # phase sign-offs + infra one-time setup
docs/operacao/phase-1a-bootstrap.md     # test prompts per phase, runbook
docs/operacao/frontend-audit-2026-05.md # before-state of FE redesign
docs/operacao/phase-3b-XX-bootstrap.md  # per-sprint smoke runbook (one per shipped sprint)
docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md             # original spec
docs/superpowers/specs/2026-05-05-frontend-redesign-v2-design.md   # FE v2 spec
docs/superpowers/plans/                  # one plan per phase
```

## Conventions

> **QUICK REFERENCE** — Each convention below is a "what + key code + link to bug history". For full bug taxonomy and lessons learned, see [docs/operacao/findings-catalog.md](docs/operacao/findings-catalog.md). For sprint-level detail of 3b.1→3b.19B, see [docs/operacao/sprint-history.md](docs/operacao/sprint-history.md).

### Git workflow

- **Solo dev on `main`** with admin bypass. Branch protection requires `test` CI; admin can bypass.
- **CI:** ruff + format + mypy + pytest unit + integration (testcontainers). **Deploy:** parallel, builds Docker, runs migrations via Cloud Run Job, rollback on failure.

### Commit messages

```
feat(scope): short imperative   |   fix(scope): ...   |   docs(scope): ...   |   chore: ...
```

Common scopes: `web`, `admin`, `auth`, `db`, `mcp`, `ci`, `design-system`, `config`. Co-author trailer with Claude when assistant did the work.

### Verification cadence (always before commit)

```bash
python scripts/check_pre_push.py        # ~30s: ruff + format + mypy + unit + non-DB integration. No Docker.
python scripts/check_pre_push_full.py   # opt-in 6th step: pytest -m integration via testcontainers (Docker required, ~60-90s)
```

Use full sweep when touching mutate flows or shared helpers in `_common.py` (catches pre-flight test gaps — see findings-catalog §F-class "Pre-flight test mocks", Sprints 3b.5+3b.8). Without Docker, full sweep exits 2 with PT-BR hint (never silently skips).

### Test fixture pattern

Integration tests define **local** `pg` + `db` fixtures per file (NOT shared `db_pool` — doesn't exist):

```python
import pytest
from testcontainers.postgres import PostgresContainer
from src.db import connection, migrate

@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container

@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()
```

Mark with `@pytest.mark.integration` so unit suite skips by default.

### Schema gotchas (commonly-tripped)

- `audit_log.id` is `BIGSERIAL` (int8), NOT UUID. Let DB generate, capture via `RETURNING id`.
- `managers.id` is `UUID PRIMARY KEY` without DEFAULT. Caller MUST provide `uuid4()`.
- `mcp_sessions.id` is `UUID PRIMARY KEY DEFAULT gen_random_uuid()`. Caller can omit.
- `rate_counters` has `operations_used` (NOT `used_today`), composite PK `(developer_token_id, date)`. Aggregate with `SUM`.
- `managers.status` (mig 002): `'invited' | 'active' | 'inactive'`. Pre-002 rows backfilled to `'active'`.

### Mutate builder test convention (post-Sprint 3b.5)

**Always use `tests/unit/fixtures/proto_capture.py::make_capture_client` (NOT MagicMock) when asserting proto field assignments.** MagicMock accepts any attribute silently → masks bugs like A4 (Google overriding `negative=True` on user_list — see findings §A4).

```python
from tests.unit.fixtures.proto_capture import make_capture_client

def test_builder_sets_critical_field():
    client = make_capture_client()
    ops = build_my_thing(client, customer_id, payload)
    op = ops[0]
    assert op.field("ad_group_criterion_operation.create.negative") is True
    assert op.has("ad_group_criterion_operation.create.bid_modifier") is False
```

Retrofit of pre-3b.5 builders is YAGNI (empirically work in production).

### Pre-flight test convention (post-Sprint 3b.8)

When adding a pre-flight call invoking `run_report` via a shared helper in `_common.py`, **existing integration tests MUST mock the new helper at the TOOL's module namespace** (NOT `_common.py`):

```python
with patch("src.mcp.tools.<your_tool>.<helper_name>", AsyncMock(return_value=None)):
    ...
```

Why: helper's `run_report` import lives in `_common.py` namespace, NOT the tool's. Existing patches on `src.mcp.tools.<tool>.run_report` don't cover the pre-flight site. Bug recurred in 3b.5 (`apply_audience`) + 3b.8 (`update_*_bid`). Mitigation: run `check_pre_push_full.py` before push, or rely on CI as catch-all (see findings §"Pre-flight test mocks").

### Schema whitelist empirical validation (post-Sprint 3b.19A)

**Every enum value in a tool's schema whitelist MUST be empirically validated in the smoke runbook** by creating a real entity. SDK descriptors contain values that runtime rejects (legacy values, system-managed, type-restricted, etc.).

Bug history: F17/F18/F19/F25/F27/F31/F32/F34/F36 — all design-gap-via-SDK-ambiguity variants (see findings-catalog §"Schema whitelist gaps").

**Convention:** Smoke runbook for new mutate tools includes explicit per-value probe step (batch 5 per call). On rejection, remove from schema + document out-of-scope.

### No JSON Schema composition keywords in tool input_schema (post-Sprint 3b.19B.1)

**Tool `input_schema` MUST NOT contain `oneOf`, `allOf`, or `anyOf` at any nesting level.** Anthropic Messages API tool-use validator rejects them anywhere (despite error message saying "at the top level").

Bug history: 3b.18 `update_rsa` shipped with `anyOf`, 3b.19B `create_conversion_value_rule_set` shipped with `allOf` — both broke real Claude sessions with 400 errors. Local `jsonschema` is permissive; smoke runbooks bypass `messages.create(tools=[...])` path. See findings-catalog §"Anthropic schema validator".

**Convention:** Express cross-field constraints in private `_validate_*` helper at top of tool body. Pattern: `update_rsa._validate_updates_have_mutable_field`, `create_conversion_value_rule_set._validate_payload_shape`. Defense-in-depth: `tests/unit/test_tools_schemas.py::test_no_composition_keywords_in_any_schema` walks schemas recursively.

### Date range conventions (post-Sprint 3b.20)

All read tools + `bulk_pause_by_query` accept date windows via:
- **Preset:** `date_range: str` with schema `type: "string"` + `enum` of presets (LAST_7_DAYS, etc.).
- **Custom:** `start_date` + `end_date` (both `YYYY-MM-DD`, schema `pattern: "^\\d{4}-\\d{2}-\\d{2}$"`). Overrides preset.

Resolve via:

```python
from src.google_ads.queries._common import resolve_date_window

start, end = resolve_date_window(
    date_range=args.get("date_range", "LAST_30_DAYS"),
    start_date=args.get("start_date"),
    end_date=args.get("end_date"),
)
```

Bug root cause: pre-3b.20 schema lacked `type` declaration → Claude silently serialized dict as JSON string literal (see findings §F1). Defense-in-depth: `test_date_range_schemas_are_explicit` regression guard + `parse_date_range` keeps defensive `json.loads` via `contextlib.suppress` as safety net.

### Deploy/ops flow

1. Code change → `python scripts/check_pre_push.py` (5/5 PASS)
2. `git commit` with proper scope/message
3. `git push origin main` (admin bypass) → triggers CI + Deploy in parallel
4. Watch with `gh run watch <id>` or `gh run list --limit 5`
5. Production smoke: `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health` → 200

### Migrations

- Files: `src/db/migrations/NNN_name.sql`. Append-only; never edit a deployed migration.
- Local tests apply via `migrate.run_all()`. Production: Cloud Run Job in deploy.yml.
- Tracker table `_migrations` prevents re-apply. If applied manually, INSERT row.
- Manual apply (no psql on Windows): use `python -c` + asyncpg with `DATABASE_URL` from Secret Manager. Pattern in [docs/operacao/infra-setup.md](docs/operacao/infra-setup.md).

### Subagent-driven development

Use `superpowers:subagent-driven-development` skill — fresh subagent per task with full task text + scene-setting, then combined spec+quality review. haiku for mechanical, sonnet for reasoning. Common plan adaptations (always check): `db_pool`→`db`, `oauth_conn["..."]`→dataclass attr, `audit_log.id: UUID`→int, `rate_counters.used_today`→`operations_used`, `@pytest.mark.integration` for pure-function tests→drop.

### Design system

Tailwind CDN (no build) + V4 token bridge in `_base.html`. Design tokens in `src/web/static/v4-tokens.css`. 22 components in `_components.html` macros (sparkline, pagination, code_block, empty_state, toast, skeleton, confirm_dialog, modal, breadcrumb, dropdown, tooltip). 5 JS helpers: `toggleDrawer`, `showToast`, `openConfirm`, `v4DropdownToggle`, `v4ToggleRow` — vanilla JS, no Alpine/React.

**Editorial mode** (login, /access-denied, /help, hero of /, /admin) = display 36-56px, V4 red accent, generous whitespace. **Operational mode** (audit, access matrix, /admin/*) = compact 12-14px, mono metadata, sparklines, dense.

## Tools available to the agent (this Claude session)

- **gcloud** authenticated as `wellinton.ribeiro@v4company.com`, project `v4-ads-mcp-prod`
- **gh** CLI authenticated as `BadWolf1509`
- **Direct push to main** allowed (admin bypass)
- **Secret Manager read access** via `gcloud secrets versions access latest --secret=NAME --project=v4-ads-mcp-prod`. Secrets in use: `database-url`, `aes-master-key`, `session-signing-key`, `google-ads-developer-token`, `google-oauth-client-secret`, etc.
- **No psql** in PATH on Windows. Use `python+asyncpg` for direct DB access.
- **Docker** may not be running locally — `testcontainers`-based integration tests will fail at startup. Rely on CI.
- **Supabase MCP server** may or may not be installed in the user's Claude Code config. If installed, prefer `mcp__supabase__*` tools over raw asyncpg for DB introspection.

## When in doubt

- **Brainstorming new feature?** Use `superpowers:brainstorming` skill before touching code.
- **Have a spec?** Use `superpowers:writing-plans` skill to break into atomic tasks.
- **Have a plan?** Use `superpowers:subagent-driven-development` skill to execute.
- **Bug?** Use `superpowers:systematic-debugging` skill.
- **Library/SDK question?** Use `plugin:context7:context7` for current docs (training data may be stale).

## Don't do

- Don't push to main without running `python scripts/check_pre_push.py` first. CI catches lint/type/test failures but it wastes a deploy cycle and may trigger rollback if integration tests reveal a bug. Lesson Sprint 3b.5/3b.8: pre-flight additions to existing mutate tools require the OPT-IN full sweep (`check_pre_push_full.py`, Docker required) — fast script doesn't run DB integration tests where pre-flight mock gaps surface.
- Don't add new dependencies without checking the project's "no build step" principle. We have Tailwind via CDN, HTMX via CDN — no node, no Vite, no React.
- Don't modify production data via raw SQL on Supabase without extreme care. Use Python script with explicit `BEGIN/COMMIT` and idempotency check.
- Don't skip the `superpowers:brainstorming` skill before creative work even if the request seems "simple."
- Don't dispatch parallel implementer subagents for sequential tasks (only one writer at a time on the codebase).
