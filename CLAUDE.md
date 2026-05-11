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

**Last updated:** 2026-05-11

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

**32 MCP tools** registered: 20 read + 11 mutations + `apply_change`.
**15 web pages** in production with Hybrid Editorial+Operational identity (FE Redesign v2).
**Q8 invite-only allowlist** active — only `@v4company.com` emails pre-invited via `/admin/invites` can complete OAuth.
**`BOOTSTRAP_ADMIN_EMAILS`** env on Cloud Run = `wellinton.ribeiro@v4company.com` (dormant since managers table is populated).

### Pending / future

- **Operação real** com gestores piloto (recomendado próximo passo) — Lucas Soares (`lucassoares@v4company.com`, gestor real da unidade Maceió) já tem OAuth ativo (2026-05-05) e MCP session "Codex Lucas" criada mas **nunca usou** (`last_seen_at`/`last_used_at` null). É piloto #1 natural — agendar onboarding. Convidar +1-2 gestores via `/admin/invites`, acompanhar audit log, validar Phase 3a mutations em uso real
- **Standard Access do Google Ads** — case `26521440673` resubmetido em 2026-05-11 com design doc atualizado em PDF (a submissão original de 2026-05-05 não retornou veredicto na janela estimada de 3 dias). Aguardar nova janela de ~3 dias úteis. Quando aprovar, quota 15k → 1M+ ops/dia
- **Phase 3b** — 14 mutation tools avançadas faltantes da spec (`create_campaign`, `create_ad_group`, `add_keywords`, `update_keyword_match_type`, `add_negatives_from_search_terms`, `create_rsa`, `update_rsa`, `update_ad_status`, `create_asset`, `link_assets`, `apply_audience`, `upload_customer_match_list`, `create_conversion_action`, `import_offline_conversions`, `bulk_pause_by_query`) + 2 utilities (`get_my_rate_limit_status`, `get_my_audit_log`) + 1 read novo crítico (`get_change_history` — 2 skills V4 marcam "CRÍTICO antes de tudo"). Sprint 3b.1 (low-quota, não bloqueado por Standard Access): `add_negatives_from_search_terms` + `get_change_history`. Ordem subsequente priorizada por sinal da operação piloto.
- **Sub-projetos 2-4 (multi-tenancy)** — `unidades` table + 3-tier RBAC, multi-MCC OAuth, migração single→multi. Só faz sentido quando V4 quiser onboardar 2ª unidade
- **Quality wins menores** — ~~datetime.utcnow → datetime.now(UTC)~~ ✅ 2026-05-11; GitHub Actions Node 20 → 24 (bump `actions/checkout@v4→@v5`, `setup-python@v5→@v6`, `auth@v2→@v3` em PR isolado para testar); ~~revogar legacy "unknown" OAuth do Phase 1a~~ ✅ 2026-05-11 (connection `43a78bc1-d1e4-4077-9774-5d6a4bd49a89` soft-revoked)

## Read these first when continuing work

```
docs/operacao/infra-setup.md            # phase sign-offs + infra one-time setup
docs/operacao/phase-1a-bootstrap.md     # test prompts per phase, runbook
docs/operacao/frontend-audit-2026-05.md # before-state of FE redesign
docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md             # original spec
docs/superpowers/specs/2026-05-05-frontend-redesign-v2-design.md   # FE v2 spec
docs/superpowers/plans/                  # one plan per phase
```

## Conventions

### Git workflow

- **Solo dev on `main`** with admin bypass — direct push allowed despite branch protection rules requiring PR.
- **Branch protection** is set: `gh api repos/BadWolf1509/v4-ads-mcp/branches/main/protection` — requires `test` CI check + admin can bypass.
- **CI:** triggered on push to main, runs ruff + format + mypy + pytest unit + pytest integration (with testcontainers).
- **Deploy:** triggered same time, builds Docker image, applies migrations via Cloud Run Job, deploys, smoke tests, rolls back on failure.

### Commit messages

```
feat(scope): short imperative description
fix(scope): ...
docs(scope): ...
chore: ...
```

Common scopes: `web`, `admin`, `auth`, `db`, `mcp`, `ci`, `design-system`, `config`. Co-author trailer with Claude is added when assistant did the work.

### Verification cadence (always before commit)

```bash
python -m ruff check src tests
python -m ruff format --check src tests   # easy to forget — CI catches it
python -m mypy src
python -m pytest tests/unit -q
```

If `ruff format --check` flags issues, run `python -m ruff format src tests` to auto-fix, then commit.

### Test fixture pattern

Integration tests that need Postgres define **local** `pg` + `db` fixtures per file (not a shared `db_pool` — that doesn't exist). Pattern in any `tests/integration/test_*.py`:

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

Mark with `@pytest.mark.integration` so the unit suite skips them by default.

### Schema gotchas (commonly-tripped things)

- **`audit_log.id`** is `BIGSERIAL` (int8), NOT UUID. Don't pass `uuid4()` as id; let DB generate, capture via `RETURNING id`.
- **`managers.id`** is `UUID PRIMARY KEY` without DEFAULT. Caller MUST provide `uuid4()`.
- **`mcp_sessions.id`** is `UUID PRIMARY KEY DEFAULT gen_random_uuid()`. Caller can omit.
- **`rate_counters`** has column `operations_used` (NOT `used_today`) and composite PK `(developer_token_id, date)` — aggregate with `SUM` if you want a global view.
- **`managers.status`** added in migration 002. Values: `'invited' | 'active' | 'inactive'`. Existing pre-002 rows backfilled to `'active'` via DEFAULT.

### Deploy/ops flow

1. Code change locally → ruff + format + mypy + pytest pass
2. `git commit` with proper scope/message
3. `git push origin main` (admin bypass) → triggers CI + Deploy in parallel
4. CI fails fast on lint/format/mypy/test issues; Deploy may still run (no dependency on CI)
5. Watch with `gh run watch <id>` or `gh run list --limit 5`
6. Production smoke: `curl -s https://.../health` should be 200; visit a page in browser

### Migrations

- Files at `src/db/migrations/NNN_name.sql`. Append-only; never edit a deployed migration.
- Local tests apply all migrations via `migrate.run_all()`.
- Production: applied automatically by `Run database migrations` step in deploy.yml using `gcloud run jobs execute v4-ads-mcp-migrate --wait`.
- Migration runner uses `_migrations` table to track applied. If you applied a migration manually (e.g., via `psql` or `asyncpg` directly), you must INSERT into `_migrations` to prevent re-apply.
- Manual apply via Python+asyncpg pattern (no psql available locally on Windows):

```bash
export DATABASE_URL="$(gcloud secrets versions access latest --secret=database-url --project=v4-ads-mcp-prod)"
python -c "
import asyncio, asyncpg, os
async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    try:
        sql = open('src/db/migrations/00X_name.sql').read()
        async with conn.transaction():
            await conn.execute(sql)
        await conn.execute(\"INSERT INTO _migrations (name) VALUES ('00X_name.sql')\")
    finally:
        await conn.close()
asyncio.run(main())
"
unset DATABASE_URL
```

### Subagent-driven development

For multi-task work, I use the `superpowers:subagent-driven-development` skill — dispatch fresh subagent per task with full task text + scene-setting context, then combined spec+quality review. Cheap model (haiku) for mechanical tasks, sonnet for multi-file edits with reasoning.

Common adaptations the plan may have got wrong (always check):
- Plan says `db_pool` fixture; reality is `db` (per-file local).
- Plan accesses `oauth_conn["..."]`; reality is dataclass attribute `oauth_conn.attr`.
- Plan uses `audit_log.id: UUID`; reality is `int` (BIGSERIAL).
- Plan uses `rate_counters.used_today`; reality is `operations_used`.
- Plan tests use `@pytest.mark.integration` for pure-function tests; should be `@pytest.mark.asyncio` only if no DB needed.

### Design system

Tailwind via CDN (Play, no build) with V4 token bridge in `_base.html`. Design tokens in `src/web/static/v4-tokens.css`. 22 components in `_components.html` macros (sparkline, pagination, code_block, empty_state, toast, skeleton, confirm_dialog, modal, breadcrumb, dropdown, tooltip, etc.).

5 JS helpers in `_base.html`: `toggleDrawer`, `showToast`, `openConfirm`, `v4DropdownToggle`, `v4ToggleRow`. All vanilla JS, no Alpine/React.

Editorial mode (login, /access-denied, /help, hero of /, /admin) = display 36-56px, V4 red accent, generous whitespace.
Operational mode (audit, access matrix, /admin/managers, /admin/accounts, /admin/audit) = compact 12-14px, mono metadata, sparklines, dense.

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

- Don't push to main without running `ruff check && ruff format --check && mypy src` locally first. CI will catch it but it wastes a deploy cycle.
- Don't add new dependencies without checking the project's "no build step" principle. We have Tailwind via CDN, HTMX via CDN — no node, no Vite, no React.
- Don't modify production data via raw SQL on Supabase without extreme care. Use Python script with explicit `BEGIN/COMMIT` and idempotency check.
- Don't skip the `superpowers:brainstorming` skill before creative work even if the request seems "simple."
- Don't dispatch parallel implementer subagents for sequential tasks (only one writer at a time on the codebase).
