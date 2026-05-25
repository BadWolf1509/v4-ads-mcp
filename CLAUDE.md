# V4 Ads MCP — agent context

Auto-loaded by Claude Code. Read first.


**V4 Ads MCP** é tool interna da V4 Company (marketing digital, BR) que conecta Google Ads + Meta Ads accounts a Claude/Codex/Cursor via Model Context Protocol. Gestores pedem em PT-BR — _"top 5 campanhas por gasto últimos 7 dias"_, _"pause keywords sem conversão"_ — e o assistente executa via tools curadas read/mutate com governança (audit_log, rate_limit, always-CONFIRM em mutates de blast radius alto).

Interno only, não SaaS, sem terceiros. Substitui Supermetrics.

- **Production:** `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app`
- **MCC Google Ads:** `6436352492` (V4 Maceió, 25 client accounts)
- **BM Meta Ads:** V4 Lima Soares & Co (12 ad accounts via Wellington personal FB)
- **Unidade operacional:** V4 Lima Soares & Co (João Pessoa, PB) — Wellington dev + 3 colaboradores futuros
- **Admin:** `wellinton.ribeiro@v4company.com`

## Stack

Python 3.12 · FastAPI + Jinja2 + Tailwind CDN + HTMX 2 · `mcp>=1.2.0` Streamable HTTP · `google-ads>=27.0.0` (v24) · `facebook-business>=21.0.0` · Supabase Postgres via `asyncpg` (raw SQL, no ORM) · Cloud Run (`southamerica-east1`) · GitHub Actions + WIF · pytest + testcontainers + `respx`/`freezegun` · ruff + mypy strict.

## Current state

**Last updated:** 2026-05-25

### Shipped — 59 MCP tools (57 Google + 2 Meta)

| Stream | Status | Notes |
|---|---|---|
| Phases 0-1b + 3a + FE Redesign v2 | ✅ 2026-05-03→05 | Foundation. See [`infra-setup.md`](docs/operacao/infra-setup.md). |
| Google Sprint 3b.1 → 3b.37 (37 sprints) | ✅ 2026-05-04→21 | 57 tools shipped + smoke real. Detail per sprint: [`sprint-history.md`](docs/operacao/sprint-history.md). Latest: 3b.33 `detect_drift`, 3b.34 F46 fix, 3b.35 `audit_goal_attribution`, 3b.36 `audit_zombie_keywords`, 3b.37 `audit_orphan_smart_actions`. |
| Meta Sprint M.1 + M.1.1 + M.2a + M.2b | ✅ 2026-05-24→25 | DB foundation (4 tables) + OAuth flow + facebook_business v21 SDK + 2 tools MCP (`meta_list_my_ad_accounts` + `meta_get_account_overview`) + endpoints `/oauth/meta/{data-deletion-callback,refresh-accounts}` + admin UI Revogar/Refresh buttons + A5 fix. **App Review pendente Wellington manual fora-MCP.** Detail: [`sprint-history.md`](docs/operacao/sprint-history.md) §Meta family. Roadmap M.3-M.25. |

**/health 200, CI green.** **16 web pages** em prod. **Q8 invite-only allowlist** ativo. **45 findings catalogados** (F1-F48 + A1-A6, A5 closed em M.2b, F48 caught + fixed em M.2b smoke real): [`findings-catalog.md`](docs/operacao/findings-catalog.md).

### Pending / future

- **Sprint M.2b smoke 5/8 PASS via MCP (T1+T2+T3+T5+T6) + 3/8 pendente Wellington manual** (T4 token expiry mock, T7 revoke button browser, T8 refresh button browser). T6 data-deletion-callback synthetic + tampered + empty negative tests todos validados.
- **Meta App Review SUBMITTED 2026-05-25** (Wellington manual fora-MCP): permissions `Marketing API Access Tier` + `public_profile` em análise Meta (até 10 dias úteis, pode estender). Screencast Loom + 3 sub-processors declarados (Google LLC / Supabase Inc. / Anthropic PBC) + DPO Wellington (CNPJ 58.143.480/0001-20) + LGPD compliance. **Decision gate pós-resposta Meta:** se APPROVED → 2 semanas dogfood Wellington (≥3 usos/semana = continua M.3-M.25; senão pause + Google backlog). Se REJECTED → iterate feedback + re-submit (Dev Mode allow 25 admins meanwhile, sem urgência).
- **Sprint 3b.38 candidates** (post-Meta M.2b decision): audit_negative_criterion_overlap, audit_assets_parity_between_campaigns, remove_* bundle, audit_log gap fix em `run_gaql`/`get_my_audit_log`/`get_my_rate_limit_status`, W2 `verify_campaign_state` ICE 280.
- **Real biz pendente investigação (fora-MCP):** ML Antiguidades 5 primary PURCHASE actions zero conv 30d (Smart Bidding cego, tracking pixel) + MO-JP+ML 527 zombie keywords + 19 orphan actions cleanup. Meta dogfood findings em [`dogfood-2026-05-25-meta-first-tool-real-biz-findings.md`](docs/operacao/dogfood-2026-05-25-meta-first-tool-real-biz-findings.md).
- **A4 OPEN finding:** Customer Match exclusion mechanism (3b.4/3b.5+). Investigation candidate dedicado.
- **3 colaboradores V4 LS&Co como App Admins Meta** quando time começar a usar (deferred M.1 — Dev Mode permite 25 admins sem App Review).
- **LOW pendings:** simetria CRUD (`update_conversion_value_rule_set`, STORE), Sprint 3b.19B Nutry smoke, 3b.30 T7-T8 production Nutry sem QS, G2 `change_event` em `list_gaql_resources`, UX1 GAQL fields opcionais vazios, B2/B3 schema hints `get_change_history`/`validate_gaql`.
- **WATCH (não-blocker):** 3b.36 default `limit=200` estoura MCP cap em contas 500+ entries (V1 bump). 3b.37 já default=100.
- **YAGNI sem demanda:** ProtoFieldCapture retrofit pré-3b.5 builders.
- **Standard Access GAds:** case `26521440673` passive. Uso ~0.07% Basic, zero blocker. Quando aprovar, 1-line em `rate_limit.py:20`.

## Read these first when continuing work

```
docs/operacao/findings-catalog.md       # ★ Bug history (44 findings, F1-F47 + A1-A6)
docs/operacao/sprint-history.md         # Detailed sprint table (3b.1→3b.37 + M.1→M.2a)
docs/operacao/phase-3b-XX-bootstrap.md  # Smoke runbook per Google sprint
docs/operacao/phase-M-2a-bootstrap.md   # Smoke runbook Meta M.2a (template pra M-family)
docs/operacao/phase-M-2b-bootstrap.md   # Smoke runbook Meta M.2b (8 tests pendente Wellington)
docs/operacao/dogfood-2026-05-19-mestre-da-obra-jp-cleanup-massivo.md   # ICE-ranked Google backlog
docs/operacao/dogfood-2026-05-21-mestre-da-obra-jp-drift-detection.md   # Drift detection findings (W1/W2/W3 + B1/B2/B3)
docs/operacao/dogfood-2026-05-25-meta-first-tool-real-biz-findings.md   # Meta dogfood findings (D1/D2/D3 + cross-platform)
docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md      # ★ Meta sprint family overview (M.1-M.25 roadmap)
docs/superpowers/specs/  +  plans/      # Design + implementation per sprint
```

## Conventions

> Quick reference. Full bug taxonomy + lessons: [`findings-catalog.md`](docs/operacao/findings-catalog.md). Sprint detail: [`sprint-history.md`](docs/operacao/sprint-history.md).

### Git workflow

Solo dev on `main` with admin bypass. CI: ruff + format + mypy + pytest unit + integration. Deploy: parallel, Docker build, migrations via Cloud Run Job. Commit messages: `feat(scope): ...` / `fix(scope): ...` / `docs(scope): ...` / `chore: ...`. Common scopes: `web`, `admin`, `auth`, `db`, `mcp`, `meta_ads`, `ci`, `design-system`. Co-author trailer with Claude when assistant did the work.

### Verification cadence (always before commit)

```bash
python scripts/check_pre_push.py        # ~30s: ruff + format + mypy + unit + non-DB integration. No Docker.
python scripts/check_pre_push_full.py   # opt-in 6th step: pytest -m integration via testcontainers (~60-90s, Docker required)
```

Use full sweep when touching mutate flows, `_common.py` helpers, OR DB migrations — catches pre-flight test mock gaps (Sprints 3b.5+3b.8 lesson) + migration regressions (M.1+M.2a `test_migrations_are_idempotent` hardcoded list gap). Without Docker, full sweep exits 2 with PT-BR hint.

### Test fixture pattern (integration)

Local `pg` + `db` fixtures per file (NOT shared `db_pool` — doesn't exist). Mark with `@pytest.mark.integration` so unit suite skips by default.

### Schema gotchas (commonly-tripped)

- `audit_log.id` is `BIGSERIAL` (int8), NOT UUID. Use `RETURNING id`.
- `audit_log.platform` (post-M.2a): `Literal["google","meta"]`, default `"google"`. Meta tools MUST pass explicit.
- `audit_log.provider_request_id` (renamed from `google_request_id` em M.2a): generic across platforms.
- `managers.id` is UUID without DEFAULT — caller must provide `uuid4()`.
- `mcp_sessions.id` is UUID DEFAULT `gen_random_uuid()` — caller can omit.
- `rate_counters` has `operations_used` (NOT `used_today`), composite PK `(developer_token_id, date)`.
- `meta_rate_counters` separado (different BUC quota model per ad_account); `app_id` hashed before persist.
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

Retrofit pré-3b.5 builders YAGNI. Convention novo dispatcher: same pattern em `test_run_conversion_upload.py` (`e055ef7`) + `test_run_offline_user_data_job.py` (3b.28). **Meta SDK uses dicts (not proto), pattern future-only:** M.3+ mutate tools precisarão de `MetaCaptureClient` fixture análogo.

### Pre-flight test convention (post-3b.5/3b.8)

When adding pre-flight call via shared helper em `_common.py`, **mock the helper at the TOOL's module namespace** (NOT `_common.py`):

```python
with patch("src.mcp.tools.<your_tool>.<helper_name>", AsyncMock(return_value=None)):
    ...
```

Helper's `run_report` import lives em `_common.py` namespace; existing patches on `src.mcp.tools.<tool>.run_report` don't cover the pre-flight site. Mitigation: `check_pre_push_full.py` before push.

### Schema whitelist empirical validation (post-3b.19A)

Every enum value em schema whitelist MUST be empirically validated em smoke runbook (create real entity per value). SDK descriptors contain values runtime rejects (legacy, system-managed, type-restricted). Bug family: F17/F18/F19/F25/F27/F31/F32/F34/F36/F44. Smoke runbook MUST include per-value probe step (batch 5 per call). On rejection: remove from schema + document out-of-scope.

### No JSON Schema composition keywords (post-3b.19B.1)

Tool `input_schema` MUST NOT contain `oneOf`, `allOf`, `anyOf` at any nesting level. Anthropic Messages API validator rejects them (despite error saying "at the top level"). Bug history: 3b.18 `update_rsa`, 3b.19B `create_conversion_value_rule_set`. Express cross-field constraints em private `_validate_*` helper. Regression guard: `test_no_composition_keywords_in_any_schema` walks schemas recursively.

### Date range conventions (post-3b.20)

Read tools + `bulk_pause_by_query` accept date windows via:
- **Preset:** `date_range: str` with `type: "string"` + `enum` of presets (LAST_7_DAYS, etc.)
- **Custom:** `start_date` + `end_date` (both YYYY-MM-DD, pattern `^\d{4}-\d{2}-\d{2}$`). Overrides preset.

Resolve via `resolve_date_window` em `_common.py`. Bug F1 root cause: pre-3b.20 schema lacked `type` declaration → Claude serialized dict as JSON string literal. Defense: `test_date_range_schemas_are_explicit` + defensive `json.loads` em `parse_date_range`.

GAQL `BETWEEN end_date` é midnight-exclusive (F46) — `_format_change_date_between` helper aplica `timedelta(days=1)` pra capturar dia inteiro. Shared between `change_history_query` + `negative_criterion_creations_query`.

### Meta SDK conventions (post-M.2a)

- **Never `FacebookAdsApi.init()`** — sets global state, perigoso em async multi-manager. Sempre construir instance direta: `FacebookAdsApi(access_token=..., app_id=..., app_secret=..., api_version="v22.0")`.
- **Long-lived token expiration check:** toda Meta tool MUST chamar `build_meta_api_for_manager()` que valida `token_expires_at` (~60d expiry). Reactive: erro PT-BR pede reconectar; proactive cron M.X+.
- **Audit log Meta:** `audit_log.record(... platform="meta", provider_request_id=response.headers().get("x-fb-trace-id"))`. Default `platform="google"` preserva Google callers existentes.
- **BUC parsing post-call:** `record_actual_meta()` parseia `X-Business-Use-Case-Usage` header → `meta_rate_counters` increment + throttle pct. Structlog warning se >75%.
- **GCP secret creation procedure** (F47 lesson): SEMPRE arquivo binary intermediário, NUNCA pipe `echo $X | gcloud ...` em PowerShell (CRLF mangling). Workflow:
  ```powershell
  python -c "open('tmp.bin', 'wb').write(b'<value>')"
  (Get-Item tmp.bin).Length   # validate binary-exact length
  gcloud secrets versions add <name> --data-file=tmp.bin
  Remove-Item tmp.bin; Clear-History
  ```

### Subagent-driven development

`superpowers:subagent-driven-development` skill — fresh subagent per task + 2-stage review (spec + quality). Model selection:
- **haiku:** mechanical tasks (helpers + tests isolated em 1-2 files)
- **sonnet:** integration tasks (multi-file, dispatchers, proto_capture work, OAuth flows)
- **opus:** architecture/design/cross-cutting reviews

Parallel implementer dispatches OK se arquivos não-overlapping (validated 3b.28: A1+A2+A3+A8 paralelo). Reviewers paralelos sempre OK. Common plan adaptations (always check): `db_pool`→`db`, `oauth_conn["..."]`→dataclass attr, `audit_log.id: UUID`→int, `rate_counters.used_today`→`operations_used`.

### Migrations

Files: `src/db/migrations/NNN_name.sql`. Append-only — never edit a deployed migration (hook PreToolUse blocks it). Tracker `_migrations` prevents re-apply. Local: `migrate.run_all()`. Production: Cloud Run Job em `deploy.yml`. **Always update `tests/integration/test_migrations.py` hardcoded list** when adding new migration (M.1 + M.2a both tripped on this — CI fails noisily but clear fix). Manual apply (no psql on Windows): `python -c` + asyncpg + `DATABASE_URL` from Secret Manager.

### Deploy/ops flow

1. Code change → `python scripts/check_pre_push.py` (5/5 PASS)
2. `git commit` with proper scope/message
3. `git push origin main` (admin bypass) → triggers CI + Deploy parallel
4. Watch with `gh run watch <id>` or `gh run list --limit 5`
5. `curl -s https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/health` → 200

Force Cloud Run pick up new secret versions: `gcloud run services update v4-ads-mcp --region=southamerica-east1 --update-secrets="<NAME>=<secret>:latest"`.

### Design system

Tailwind CDN (no build) + V4 tokens em `src/web/static/v4-tokens.css`. 22 components em `_components.html` macros. Vanilla JS, no Alpine/React. **Editorial mode** (login/access-denied/help/admin hero): display 36-56px, V4 red `#e50914`, generous whitespace. **Operational mode** (audit/access matrix/admin/*): compact 12-14px, mono metadata, dense.

## Tools available (this Claude session)

- **gcloud** authed `wellinton.ribeiro@v4company.com`, project `v4-ads-mcp-prod`. Admin bypass `git push origin main` OK.
- **gh** authed `BadWolf1509`.
- **Secret Manager:** `gcloud secrets versions access latest --secret=<NAME> --project=v4-ads-mcp-prod`. Secrets: `database-url`, `aes-master-key`, `session-signing-key`, `google-ads-developer-token`, `google-oauth-client-secret`, `meta-app-id`, `meta-app-secret`, supabase keys. Allowlist em `.claude/settings.local.json`.
- **No psql on Windows** — use `python+asyncpg` for direct DB.
- **Docker** may not be running locally — `testcontainers` integration tests fail at startup. CI runs them.
- **Supabase MCP** em `.mcp.json` — prefer `mcp__supabase__*` over raw asyncpg pra introspection.
- **Hooks ativos:** PostToolUse auto-format ruff em .py + PreToolUse guard against editing committed migrations.
- **PowerShell secret upload gotcha (F47):** Windows pipes converte LF→CRLF mesmo binary. Sempre arquivo intermediário (procedure em Meta SDK conventions acima).

## When in doubt

- **Brainstorming new feature?** `superpowers:brainstorming` skill BEFORE touching code.
- **Have a spec?** `superpowers:writing-plans` skill.
- **Have a plan?** `superpowers:subagent-driven-development` skill.
- **Bug?** `superpowers:systematic-debugging` skill.
- **Library/SDK question?** `plugin:context7:context7` (training data may be stale, especially for facebook_business + Meta Graph API quirks).
- **New sprint?** `/sprint-bootstrap` (user-only skill — scaffolds plan + runbook).
- **F-finding to catalog?** `/findings-add` (user-only skill — auto-increments F##).
- **Quality audit antes de push?** Dispatch `mcp-tool-quality-reviewer` subagent.
- **Smoke runbook esqueleto?** Dispatch `smoke-runbook-generator` subagent.

## Don't do

- Don't push to main without `python scripts/check_pre_push.py` first. Full sweep (`check_pre_push_full.py`, Docker required) MANDATORY when adding pre-flight to mutate tools OR DB migrations (lições 3b.5/3b.8 + M.1/M.2a).
- Don't add new dependencies without checking "no build step" principle (Tailwind/HTMX via CDN — no node/Vite/React).
- Don't modify production data via raw SQL on Supabase without extreme care. Use Python script + explicit BEGIN/COMMIT + idempotency check.
- Don't skip `superpowers:brainstorming` before creative work even if request seems "simple."
- Don't dispatch implementer subagents in parallel on OVERLAPPING files (writers conflict). Paralelo OK em arquivos isolated (3b.28). Reviewers paralelos sempre OK.
- Don't ship a tool without per-value empirical probe em smoke runbook for any enum whitelist (3b.19A.1 convention — caught 10+ design-gap findings).
- Don't use MagicMock em builder tests when asserting proto field assignments (use `make_capture_client` — F16/F42/F44 lessons).
- Don't include `oneOf/allOf/anyOf` em tool `input_schema` at any nesting level (Anthropic validator rejects — 3b.19B.1 lesson).
- Don't call `FacebookAdsApi.init()` em Meta tools — sets global state, perigoso em async (M.2a convention).
- Don't upload secrets via PowerShell pipe `|` — usa arquivo binary intermediário (F47 lesson). Plus, NUNCA cole secret em chat — rotaciona se exposed.
- Don't apply `is_allowed_email` (V4 domain) check em Meta OAuth callback — `fb_email` é conta FB pessoal do gestor (A6 lesson). Authoritative auth é manager_id no state HMAC.
