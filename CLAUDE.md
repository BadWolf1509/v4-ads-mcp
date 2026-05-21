# V4 Ads MCP — agent context

Auto-loaded by Claude Code. Read first.

**V4 Ads MCP** é tool interna da V4 Company (marketing digital, BR) que conecta Google Ads accounts a Claude/Codex/Cursor via Model Context Protocol. Gestores pedem em PT-BR — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — e o assistente executa via tools curadas read/mutate com governança (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto).

Interno only, não SaaS, sem terceiros. Substitui Supermetrics.

- **Production:** `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`
- **MCC:** `6436352492` (V4 Maceió, ~23 client accounts)
- **Admin:** `wellinton.ribeiro@v4company.com`

## Stack

Python 3.12 · FastAPI + Jinja2 + Tailwind CDN + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (v24) · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict.

## Current state

**Last updated:** 2026-05-21

### Shipped (54 tools em produção)

| Phase | Status | Notes |
|---|---|---|
| Phases 0-1b + 3a + FE Redesign v2 | ✅ 2026-05-03→05 | Foundation done. See [`infra-setup.md`](docs/operacao/infra-setup.md). |
| Sprint 3b.1 → 3b.34 (34 sprints) | ✅ 2026-05-04→21 | All shipped + signed-off em conta real. **Detail per sprint:** [`sprint-history.md`](docs/operacao/sprint-history.md). **Bug history (42 findings, F1-F46):** [`findings-catalog.md`](docs/operacao/findings-catalog.md). |

**54 MCP tools** registered: 26 read + 27 mutations + `apply_change`. Production revision post-Sprint 3b.34 — F46 FIXED (`_format_change_date_between` helper aplica `+1 day` no end_date, restaura semantics inclusive em `get_change_history` + `get_negative_keywords_audit` + `detect_drift`). Sprint 3b.33 — `detect_drift` 54th tool (W1 ICE 486 dogfood 21/05) — 6/6 effective PASS + caso real Pedro Vytor ML Antiguidades. /health 200, CI green.
**15 web pages** in production (FE Redesign v2 Hybrid Editorial+Operational identity).
**Q8 invite-only allowlist** active — only `@v4company.com` emails pre-invited via `/admin/invites` can complete OAuth.

### Pending / future

- **Modelo operacional:** solo dogfood — Wellington único user. Lucas Soares OAuth dormant. Multi-tenancy adiado indefinidamente.
- **Sprint 3b.35 candidate (next-in-queue):** **W3 `audit_goal_attribution`** (ICE 360 dogfood 21/05 — pre-flight pra `primary_for_goal` mexer Smart Bidding) ou audit_zombie_keywords (#11 ICE 315), audit_orphan_smart_actions (#12 ICE 288), audit_negative_criterion_overlap, audit_assets_parity_between_campaigns OR remove_* bundle OR audit_log gap fix. Decisão Wellington baseada em dogfood. F46 fix shipped Sprint 3b.34.
- **A4 OPEN finding:** Customer Match exclusion mechanism (aberto desde 3b.4/3b.5, desbloqueada via `upload_customer_match_list` 3b.28). Investigation candidate dedicado.
- **LOW priority pendings:** audit_log gap em `run_gaql`/`get_my_audit_log`/`get_my_rate_limit_status` (description "Sempre auditado" sem `audit_log.record()` explicit — descoberto 3b.29); simetria CRUD missing (`update_conversion_value_rule_set`, STORE support); Sprint 3b.19B Nutry smoke pending; smoke 3b.30 T7-T8 em conta production V4 (Nutry sem QS data — F41/F45 pattern); G2 `change_event` em `list_gaql_resources` (ICE 360); UX1 doc nota GAQL fields opcionais vazios (ICE 360); B2 schema enum CONVERSION_ACTION em `get_change_history` (ICE 288); B3 validate_gaql detectar LIKE OR LIKE (ICE 192).
- **YAGNI sem demanda:** ProtoFieldCapture retrofit em builders pré-3b.5 (work empirically em prod).
- **Standard Access GAds:** case `26521440673` passive wait. Uso atual ~0.07% Basic, zero blocker. Quando aprovar, 1-line change em `rate_limit.py:20`.

## Read these first when continuing work

```
docs/operacao/findings-catalog.md       # ★ Bug history (A1-A5, F1-F45 highest ID — 41 unique findings)
docs/operacao/sprint-history.md         # Detailed sprint table 3b.1→3b.31
docs/operacao/phase-3b-XX-bootstrap.md  # Smoke runbook per sprint
docs/operacao/dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md  # ICE-ranked backlog
docs/superpowers/specs/  +  plans/      # Design + implementation per sprint
```

## Conventions

> Quick reference. Full bug taxonomy + lessons: [`findings-catalog.md`](docs/operacao/findings-catalog.md). Sprint detail: [`sprint-history.md`](docs/operacao/sprint-history.md).

### Git workflow

Solo dev on `main` with admin bypass. CI: ruff + format + mypy + pytest unit + integration. Deploy: parallel, Docker build, migrations via Cloud Run Job. Commit messages: `feat(scope): ...` / `fix(scope): ...` / `docs(scope): ...` / `chore: ...`. Common scopes: `web`, `admin`, `auth`, `db`, `mcp`, `ci`, `design-system`. Co-author trailer with Claude when assistant did the work.

### Verification cadence (always before commit)

```bash
python scripts/check_pre_push.py        # ~30s: ruff + format + mypy + unit + non-DB integration. No Docker.
python scripts/check_pre_push_full.py   # opt-in 6th step: pytest -m integration via testcontainers (~60-90s, Docker required)
```

Use full sweep when touching mutate flows or `_common.py` helpers — catches pre-flight test mock gaps (Sprints 3b.5+3b.8 lesson). Without Docker, full sweep exits 2 with PT-BR hint.

### Test fixture pattern (integration)

Local `pg` + `db` fixtures per file (NOT shared `db_pool` — doesn't exist). Mark with `@pytest.mark.integration` so unit suite skips by default. Pattern em qualquer `tests/integration/test_*.py` recente.

### Schema gotchas (commonly-tripped)

- `audit_log.id` is `BIGSERIAL` (int8), NOT UUID. Use `RETURNING id`.
- `managers.id` is UUID without DEFAULT — caller must provide `uuid4()`.
- `mcp_sessions.id` is UUID DEFAULT `gen_random_uuid()` — caller can omit.
- `rate_counters` has `operations_used` (NOT `used_today`), composite PK `(developer_token_id, date)`.
- `managers.status`: `'invited' | 'active' | 'inactive'`.
- `pending_confirmations.token` (NOT `id`) is primary key; `payload` is jsonb.

### Mutate builder test convention (post-3b.5, F16/F42/F44 lessons)

**Always use `tests/unit/fixtures/proto_capture.py::make_capture_client` (NOT MagicMock)** when asserting proto field assignments. MagicMock silently accepts any attribute → masks bugs (A4 user_list override, F16 .add()/.append(), F42 removed-field-not-detected, F44 immutable-field-silent-pass).

```python
from tests.unit.fixtures.proto_capture import make_capture_client

client = make_capture_client()
ops = build_my_thing(client, customer_id, payload)
assert ops[0].field("ad_group_criterion_operation.create.negative") is True
assert ops[0].has("ad_group_criterion_operation.create.bid_modifier") is False
```

Retrofit of pre-3b.5 builders YAGNI (work empirically em prod). Convention novo dispatcher: same pattern em `test_run_conversion_upload.py` (retrofit `e055ef7`) + `test_run_offline_user_data_job.py` (3b.28).

### Pre-flight test convention (post-3b.5/3b.8)

When adding pre-flight call via shared helper em `_common.py`, **mock the helper at the TOOL's module namespace** (NOT `_common.py`):

```python
with patch("src.mcp.tools.<your_tool>.<helper_name>", AsyncMock(return_value=None)):
    ...
```

Helper's `run_report` import lives em `_common.py` namespace; existing patches on `src.mcp.tools.<tool>.run_report` don't cover the pre-flight site. Bug recurred 3b.5+3b.8. Mitigation: `check_pre_push_full.py` before push, ou CI catch-all.

### Schema whitelist empirical validation (post-3b.19A)

Every enum value em schema whitelist MUST be empirically validated em smoke runbook (create real entity per value). SDK descriptors contain values runtime rejects (legacy, system-managed, type-restricted). Bug family: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44 — all design-gap-via-SDK-ambiguity. Smoke runbook MUST include per-value probe step (batch 5 per call). On rejection: remove from schema + document out-of-scope.

### No JSON Schema composition keywords (post-3b.19B.1)

Tool `input_schema` MUST NOT contain `oneOf`, `allOf`, `anyOf` at any nesting level. Anthropic Messages API validator rejects them everywhere (despite error saying "at the top level"). Bug history: 3b.18 `update_rsa` shipped with `anyOf`, 3b.19B `create_conversion_value_rule_set` shipped with `allOf` — both broke real Claude sessions com HTTP 400.

**Convention:** Express cross-field constraints em private `_validate_*` helper at top of tool body. Regression guard: `test_no_composition_keywords_in_any_schema` walks schemas recursively.

### Date range conventions (post-3b.20)

Read tools + `bulk_pause_by_query` accept date windows via:
- **Preset:** `date_range: str` with `type: "string"` + `enum` of presets (LAST_7_DAYS, etc.)
- **Custom:** `start_date` + `end_date` (both YYYY-MM-DD, pattern `^\d{4}-\d{2}-\d{2}$`). Overrides preset.

Resolve via `resolve_date_window` em `_common.py`. Bug F1 root cause: pre-3b.20 schema lacked `type` declaration → Claude serialized dict as JSON string literal. Defense: `test_date_range_schemas_are_explicit` + defensive `json.loads` em `parse_date_range`.

### Subagent-driven development

`superpowers:subagent-driven-development` skill — fresh subagent per task + 2-stage review (spec + quality). Model selection:
- **haiku:** mechanical tasks (helpers + tests isolated em 1-2 files)
- **sonnet:** integration tasks (multi-file, dispatchers, proto_capture work)
- **opus:** architecture/design/cross-cutting reviews

Parallel implementer dispatches OK if arquivos não-overlapping (validated 3b.28: A1+A2+A3+A8 paralelo). Reviewers paralelos sempre OK. Common plan adaptations (always check): `db_pool`→`db`, `oauth_conn["..."]`→dataclass attr, `audit_log.id: UUID`→int, `rate_counters.used_today`→`operations_used`.

### Migrations

Files: `src/db/migrations/NNN_name.sql`. Append-only — never edit a deployed migration (hook PreToolUse blocks it). Tracker `_migrations` prevents re-apply. Local: `migrate.run_all()`. Production: Cloud Run Job em `deploy.yml`. Manual apply (no psql on Windows): `python -c` + asyncpg + `DATABASE_URL` from Secret Manager.

### Deploy/ops flow

1. Code change → `python scripts/check_pre_push.py` (5/5 PASS)
2. `git commit` with proper scope/message
3. `git push origin main` (admin bypass) → triggers CI + Deploy parallel
4. Watch with `gh run watch <id>` or `gh run list --limit 5`
5. `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health` → 200

### Design system

Tailwind CDN (no build) + V4 tokens em `src/web/static/v4-tokens.css`. 22 components em `_components.html` macros. Vanilla JS, no Alpine/React. **Editorial mode** (login/access-denied/help/admin hero): display 36-56px, V4 red, generous whitespace. **Operational mode** (audit/access matrix/admin/*): compact 12-14px, mono metadata, dense.

## Tools available (this Claude session)

- **gcloud** authed `wellinton.ribeiro@v4company.com`, project `v4-ads-mcp-prod`. Admin bypass `git push origin main` OK.
- **gh** authed `BadWolf1509`.
- **Secret Manager:** `gcloud secrets versions access latest --secret=<NAME> --project=v4-ads-mcp-prod`. Secrets: `database-url`, `aes-master-key`, `session-signing-key`, `google-ads-developer-token`, `google-oauth-client-secret`, etc. Allowlist already em `.claude/settings.local.json`.
- **No psql on Windows** — use `python+asyncpg` for direct DB.
- **Docker** may not be running locally — `testcontainers` integration tests fail at startup. Rely on CI.
- **Supabase MCP** em `.mcp.json` — prefer `mcp__supabase__*` over raw asyncpg pra introspection.
- **Hooks ativos:** PostToolUse auto-format ruff em .py + PreToolUse guard against editing committed migrations.

## When in doubt

- **Brainstorming new feature?** `superpowers:brainstorming` skill BEFORE touching code.
- **Have a spec?** `superpowers:writing-plans` skill.
- **Have a plan?** `superpowers:subagent-driven-development` skill.
- **Bug?** `superpowers:systematic-debugging` skill.
- **Library/SDK question?** `plugin:context7:context7` (training data may be stale).
- **New sprint?** `/sprint-bootstrap` (user-only skill — scaffolds plan + runbook).
- **F-finding to catalog?** `/findings-add` (user-only skill — auto-increments F##).
- **Quality audit antes de push?** Dispatch `mcp-tool-quality-reviewer` subagent.
- **Smoke runbook esqueleto?** Dispatch `smoke-runbook-generator` subagent.

## Don't do

- Don't push to main without `python scripts/check_pre_push.py` first. Full sweep (`check_pre_push_full.py`, Docker required) MANDATORY when adding pre-flight to existing mutate tools (3b.5/3b.8 lesson).
- Don't add new dependencies without checking "no build step" principle (Tailwind/HTMX via CDN — no node/Vite/React).
- Don't modify production data via raw SQL on Supabase without extreme care. Use Python script + explicit BEGIN/COMMIT + idempotency check.
- Don't skip `superpowers:brainstorming` before creative work even if request seems "simple."
- Don't dispatch implementer subagents in parallel on OVERLAPPING files (writers conflict). Paralelo OK if arquivos isolated (validated 3b.28). Reviewers paralelos sempre OK.
- Don't ship a tool without per-value empirical probe em smoke runbook for any enum whitelist (3b.19A.1 convention — caught 10+ design-gap findings).
- Don't use MagicMock em builder tests when asserting proto field assignments (use `make_capture_client` — F16/F42/F44 lessons).
- Don't include `oneOf/allOf/anyOf` em tool `input_schema` at any nesting level (Anthropic validator rejects — 3b.19B.1 lesson).
