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

**Last updated:** 2026-05-26 — pós-Sprint M.3 ship (3 tools Meta performance: campaign always + ad_set/ad defer) — pending smoke real Wellington. **52 findings** (F1-F52 + A1-A6 + D1-D3). Token rotation procedure documentado em conventions (Bearer issued via UI `/sessions/new`).

### Quick-start próxima sessão (TL;DR)

- **Sprint atual:** Sprint M.3 ✅ shipped código — 3 tools Meta performance (`meta_get_campaign_performance` always + `meta_get_ad_set_performance` defer + `meta_get_ad_performance` defer). Tool count 59→62 (22 always + 40 defer). Pending smoke real Wellington manual (runbook `phase-M-3-bootstrap.md` 10 tests T1-T10).
- **Próximo natural:** Wellington smoke M.3 manual + per-value probe effective_status (após restart Claude Code pra refresh tool cache); senão Sprint M.4 plan (`meta_get_geo_performance` + `meta_get_device_performance` + `meta_get_hourly_performance` — multiplica volume Caminho B+) OR Sprint 3b.40 plan (Fase 2 refactor Caminho C consolidação).
- **Token v4-ads:** rotacionado 25/05 funcional. Procedure pra futuro: UI `/sessions/new` (NÃO inventar tokens, backend valida via hash).
- **Quando ler outros docs:** `findings-catalog.md` se bug suspeito, `sprint-history.md` se detalhe per-sprint, specs/plans se executar fase pending.

### Shipped — 62 MCP tools (57 Google + 5 Meta)

| Stream | Status | Notes |
|---|---|---|
| Phases 0-1b + 3a + FE Redesign v2 | ✅ 2026-05-03→05 | Foundation. See [`infra-setup.md`](docs/operacao/infra-setup.md). |
| Google Sprint 3b.1 → 3b.37 (37 sprints) | ✅ 2026-05-04→21 | 57 tools shipped + smoke real. Detail per sprint: [`sprint-history.md`](docs/operacao/sprint-history.md). Latest: 3b.33 `detect_drift`, 3b.34 F46 fix, 3b.35 `audit_goal_attribution`, 3b.36 `audit_zombie_keywords`, 3b.37 `audit_orphan_smart_actions`. |
| Meta Sprint M.1 + M.1.1 + M.2a + M.2b | ✅ 2026-05-24→25 | DB foundation (4 tables) + OAuth flow + facebook_business v21 SDK + 2 tools MCP (`meta_list_my_ad_accounts` + `meta_get_account_overview`) + endpoints `/oauth/meta/{data-deletion-callback,refresh-accounts}` + admin UI Revogar/Refresh buttons + A5 fix. **App Review respondido 25/05 10:58 GMT-3: `public_profile` APROVADA, `Marketing API Access Tier` REJEITADA (insufficient calls 15d). Decisão Caminho B+ janela observação 30-45 dias — acelerar M.3+ pra volume natural + re-submit Full Access após atingir 500 calls/15d threshold.** Detail: [`sprint-history.md`](docs/operacao/sprint-history.md) §Meta family. Roadmap M.3-M.25 segue normal (Limited Access permite testing, MAS docs Meta diz "extremamente limitado, não para produção visualizado para cliente publicitário" — observação throttle obrigatória). |
| Sprint 3b.38 | ✅ 2026-05-25 | F52 fix `audit_zombie_keywords` adiciona `ad_group_status` field + description warning (Opção C dogfood B6). F23 fix `get_change_history` clamp LAST_30_DAYS pra today-28 + warning na response (promoted "known limitation" → "fixed"). B1 description refino "HORAS" → "DIAS" (medição empírica dogfood 25/05 >4 dias). Smoke real 5/5 PASS: T1 280 zumbis = 170 REMOVED + 110 ENABLED match exato dogfood (DELL 93 + GPA02 ANDAIME 77 órfãs cosméticas), T2+T3 F23 clamp/no-clamp positive/negative. |
| Sprint 3b.39 (refactor F1) | ✅ 2026-05-25 | Fase 1 do refactor arquitetural V4 Ads MCP (spec: `2026-05-25-architecture-refactor-design.md`). **Tool count stays at 59** (metadata-only F1). 6 tasks A-F via subagent-driven + 2 D-findings cross-layer descobertas (D2 pré-plan via OQ1, D3 pré-Wellington-config). **Final bucket state:** 21 always + 38 defer = 59 (data-driven via audit_log uses_30d). **Server-side mechanism (D3 correct):** `@register_tool` decorator add `bucket: Literal["always", "defer"]` kwarg + `_meta` field per Tool com `{"com.v4company/bucket": ..., "anthropic/alwaysLoad": true}` (omit alwaysLoad em defer) + mass-tag 59 tool files (`# bucket:` line 1 + `[CORE]`/`[DEFER]` description prefix). **D3 finding:** Claude Code v2.x `ENABLE_TOOL_SEARCH=true` por DEFAULT — todas MCP tools defer automaticamente. Mecanismo pra promover always-loaded é `_meta.anthropic/alwaysLoad: true` server-side per-tool (NÃO client-side settings.json como D2 inicialmente assumiu). Wellington action: ZERO config edits — apenas restart Claude Code. **Smoke real validado bit-a-bit em produção** pós-restart: `list_my_accounts` retornou 25 contas via always-loaded path + 38 deferred tools confirmadas via system reminder. **Pre-push 5/5 + 792/792 unit tests + CI verde + token rotation procedure** documentado (UI `/sessions/new` issuing). Decision gate F1→F2 outcome-based timeout 14d (Wellington 7d feedback D+7=2026-06-01). Próxima: Fase 2 (Sprint 3b.40 — Caminho C consolidação `get_performance_breakdown`). |
| Sprint M.3 | ✅ 2026-05-26 | 3 tools Meta performance (paridade Google get_*_performance): `meta_get_campaign_performance` bucket=always (Pareto Meta top), `meta_get_ad_set_performance` bucket=defer, `meta_get_ad_performance` bucket=defer. Approach C — shared `src/meta_ads/insights.py` (~150 LOC) + 3 thin handlers (~30 LOC cada) + `META_EFFECTIVE_STATUS_LABELS` em `_meta_common.py`. 9 tasks subagent-driven (haiku T1+T2, sonnet T3-T5, smoke-runbook-generator T7). 18 unit tests (insights.py TDD) + 14 integration tests + 10 smoke tests T1-T10 (runbook `phase-M-3-bootstrap.md` 821 linhas). Tool count 59→62 (22 always + 40 defer). **Caminho B+ contribution:** +3-6 calls/dia naturais Wellington dogfood → acelera 500 calls/15d threshold pra Full Access re-submit (~30-45d window). Pre-push 5/5 + 8m41s CI + Deploy success. **Pending Wellington smoke manual** (per-value probe T6 effective_status enum + T9/T10 BUC + audit_log validation em conta V4 com Pixel purchase). |

**/health 200, CI green.** **16 web pages** em prod. **Q8 invite-only allowlist** ativo. **52 findings catalogados** (F1-F52 + A1-A6 + D1-D3, alguns IDs skipped): [`findings-catalog.md`](docs/operacao/findings-catalog.md). **Smoke real M.2b 8/8 PASS** com F48 (FacebookSession factory) + F49 (button macro) caught/fixed em prod. **Smoke real 3b.38 5/5 PASS** F52 ad_group_status field + F23 clamp validados bit-a-bit em conta MO-JP+CAB. **Smoke real 3b.39 F1 PASS** em produção: 21 always + 38 deferred + token rotation completa pós-Bearer exposure incident. F50/F51 retrospective trace de F33/F37 (já fixados desde 2026-05-18). **D1-D3 trio decision-not-bug:** D1 (Meta App Review Standard Tier rejeitado — Caminho B+ janela observação 30-45 dias), D2 (MCP defer_loading client-side Anthropic API param — wrong design assumption), D3 (real mechanism is server-side per-tool `_meta.anthropic/alwaysLoad` — Claude Code Tool Search default v2.x). **Lição reinforced 3× consecutiva:** sempre verificar docs oficial cliente ANTES de design refactor cross-layer (D1+D2+D3 cada salvou 2-3 dias wasted work).

### Pending / future

- **Meta App Review RESPONDIDO 2026-05-25 10:58 GMT-3** — `public_profile` ✅ APROVADA, `Marketing API Access Tier` ❌ REJEITADA. Critério literal Meta: ≥500 calls/15d + <15% error rate (atualizado, era 1.500 antes). Nomenclatura atual: **Limited Access** (ex-"Standard", default sem App Review — "extremamente limitado, NÃO para produção visualizado para cliente publicitário" docs Meta literal) vs **Full Access** (ex-"Advanced", o que rejeitou). **Decisão Caminho B+ janela observação 30-45 dias** — V4 LS&Co (Wellington + 3 colab futuros) = 4 users ≤ 25 cap Dev Mode/Limited OK pra testing, MAS red flag throttle em produção real. **Estratégia:** acelerar M.3+ pra ship mais tools Meta (`meta_get_campaign_performance` etc) → Wellington usa naturalmente day-to-day → volume cresce → ~30-45 dias atinge 500 calls cumulativas → re-submit Full Access com fundamento. Não-Caminho A permanente (risk throttle production), não-Caminho B forçado (3×/dia waste). **Monitorar X-Business-Use-Case-Usage** em `meta_rate_counters` table — se Wellington bater throttle real antes da janela, priorize re-submit imediato. **Decision gate atualizado:** continuar M.3 = ≥3 calls/semana dogfood; senão pivot Google. **Action quando colab entrarem:** add como App Roles → Administrators no Meta Dev Console (Dev Mode permite 25). Ver D1 finding pra detalhes técnicos + 2 conceitos diferentes (Marketing API tier vs resource access tier).
- **Refactor arquitetural Sprint 3b.39 ✅ F1 SHIPPED + VALIDATED** — bucket classification (22 always + 40 defer = 62 pós-M.3) + server-side `_meta.anthropic/alwaysLoad` (D3 correct mechanism). Wellington action = restart Claude Code (zero settings.json edits, D2 inicialmente errado). Smoke real produção PASS (system reminder confirmou "38 deferred tools available" antes-M.3). Wellington 7d feedback collection: D+7 = 2026-06-01 (5 perguntas estruturadas). Decision gate F1→F2 outcome-based timeout 14d. **Próximo Sprint 3b.40 (Fase 2):** Caminho C consolidação `get_performance_breakdown(level, dimension)` substitui 9 reports = -9 tools permanente. Spec: [`2026-05-25-architecture-refactor-design.md`](docs/superpowers/specs/2026-05-25-architecture-refactor-design.md).
- **Sprint M.3 ✅ SHIPPED código — Wellington smoke real PENDING** — 3 tools Meta performance shipped código + CI/Deploy verde + production /health 200. Runbook `phase-M-3-bootstrap.md` 10 tests T1-T10 (3 happy paths + status ALL + custom date + per-value probe 4 effective_status + 2 error paths + BUC tracking + audit_log validation). Wellington action: restart Claude Code → escolher ad_account com Pixel purchase configurado → executar T1-T10 (~30min). Per-value probe T6 vai validar 4 valores enum (ACTIVE/PAUSED/ARCHIVED/ALL) — se algum Meta rejeitar, remover do schema enum + catalog F-finding. **Caminho B+ Meta volume começa acumular D+1** (Wellington dogfood +3-6 calls/dia naturais → 30-45d viável atingir 500 calls/15d threshold Full Access).
- **Próximo Sprint M.4 candidate** — `meta_get_geo_performance` + `meta_get_device_performance` + `meta_get_hourly_performance` (3 tools breakdowns paralelos a Google equivalents). Alta prioridade Caminho B+ — multiplica volume per session (gestor pede geo/device como follow-up natural ao campaign-level).
- **Sprint 3b.39+ post-F1 candidates** (fora-refactor): audit_negative_criterion_overlap, audit_assets_parity_between_campaigns, remove_* bundle, audit_log gap fix em `run_gaql`/`get_my_audit_log`/`get_my_rate_limit_status`, W2 `verify_campaign_state` ICE 280.
- **A4 OPEN finding:** Customer Match exclusion mechanism (3b.4/3b.5+). Sprint dedicated candidate.
- **3 colaboradores V4 LS&Co como Meta App Administrators** quando time começar a usar — adicionar via Meta Dev Console > App Roles > Administrators (Limited Access/Dev Mode permite 25 admins/testers sem Full Access tier, OK pra janela observação Caminho B+).
- **Real biz findings dogfood** (fora-MCP, owner gestor V4 não-dev): ML Antiguidades cross-platform tracking pixel + MDO Cotia 2 accounts duplicadas + WJX FECHADO. Ver [`dogfood-2026-05-25-meta-first-tool-real-biz-findings.md`](docs/operacao/dogfood-2026-05-25-meta-first-tool-real-biz-findings.md).
- **LOW pendings:** simetria CRUD (`update_conversion_value_rule_set` STORE), 3b.19B Nutry smoke, 3b.30 T7-T8 production Nutry sem QS, G2 `change_event` em `list_gaql_resources`, UX1 GAQL fields opcionais vazios, B2/B3 schema hints `get_change_history`/`validate_gaql`.
- **WATCH (não-blocker):** 3b.36 default `limit=200` estoura MCP cap em contas 500+ entries (V1 bump). 3b.37 já default=100.
- **YAGNI sem demanda:** ProtoFieldCapture retrofit pré-3b.5 builders.
- **Standard Access GAds:** case `26521440673` passive. Uso ~0.07% Basic, zero blocker. Quando aprovar, 1-line em `rate_limit.py:20`.

## Read these first when continuing work

**Critical (read se task envolve):**
```
docs/operacao/findings-catalog.md       # ★ Bug history 52 findings (F1-F52 + A1-A6 + D1-D3)
docs/operacao/sprint-history.md         # ★ Sprint table per-row detail (3b.1→3b.39 + M.1→M.2b)
docs/superpowers/specs/2026-05-25-architecture-refactor-design.md   # ★ Refactor arquitetural 4 fases
```

**Reference (se relevant pra task atual):**
```
docs/operacao/phase-3b-XX-bootstrap.md  # Smoke runbook per Google sprint
docs/operacao/phase-M-2a-bootstrap.md   # Smoke runbook Meta M.2a (template pra M-family)
docs/operacao/phase-M-2b-bootstrap.md   # Smoke runbook Meta M.2b (8/8 PASS)
docs/operacao/tool-audit-2026-05-25.md  # Tool count analysis (sweet spot 30-45)
docs/operacao/tool-buckets-2026-05-25.md  # Bucket classification per-tool (Sprint 3b.39 source)
docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md   # Meta family roadmap M.1-M.25
docs/operacao/dogfood-2026-05-{19,21,25}-*.md                        # Real biz feedback findings
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

### Mutate builder test convention (post-3b.5, F16/F42/F44/F51 lessons)

**Always use `tests/unit/fixtures/proto_capture.py::make_capture_client` (NOT MagicMock)** when asserting proto field assignments. MagicMock silently accepts any attribute → masks bugs (A4 user_list override, F16 .add()/.append(), F42 removed-field-not-detected, F44 immutable-field-silent-pass, F51 renamed-field-old-name-not-detected).

```python
from tests.unit.fixtures.proto_capture import make_capture_client

client = make_capture_client()
ops = build_my_thing(client, customer_id, payload)
assert ops[0].field("ad_group_criterion_operation.create.negative") is True
assert ops[0].has("ad_group_criterion_operation.create.bid_modifier") is False
```

**Field rename guard (post-F51):** quando um proto field é RENOMEADO entre versões SDK (ex: `start_date` → `start_date_time` em Campaign v24), o test MUST assertar tanto presença do nome novo quanto AUSÊNCIA do nome antigo. `CapturedOp._SubCapture.__setattr__` aceita silenciosamente qualquer atributo, então só `has(new) is True` deixa passar bugs que escrevem no nome antigo. Padrão:

```python
assert ops[0].has("campaign_operation.create.start_date_time") is True   # new field ✓
assert ops[0].has("campaign_operation.create.start_date") is False       # old field MUST be absent
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

### Meta SDK conventions (post-M.2a/M.2b)

- **Never `FacebookAdsApi.init()`** — sets global state, perigoso em async multi-manager. Use o factory pure `build_facebook_ads_api()` em `src/meta_ads/client.py`.
- **F48 lesson — factory pattern correto:** `FacebookAdsApi.__init__()` aceita só `(session, api_version, enable_debug_logger)`, NÃO `access_token`/`app_id`/`app_secret` direto. Construir `FacebookSession(...)` primeiro:
  ```python
  from facebook_business.session import FacebookSession
  from facebook_business.api import FacebookAdsApi
  session = FacebookSession(app_id=..., app_secret=..., access_token=...)
  api = FacebookAdsApi(session=session, api_version="v22.0")
  ```
  Integration tests mockam `run_meta_graph_get` (nível acima) → testing gap NÃO pega TypeError em `FacebookAdsApi.__init__`. Mitigação: unit tests em `tests/unit/test_meta_client.py` cobrem factory contract diretamente.
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

**F49 lesson — `button()` macro:** default `type="button"`. Quando usado dentro de `<form>`, MUST passar `type="submit"` explicitly senão NÃO submete form (browser default). Pattern: `{{ button("Salvar", variant="primary", type="submit") }}`.

### Tool bucket classification (post-3b.39 F1)

`@register_tool` decorator aceita `bucket: Literal["always", "defer"]` kwarg (default `"defer"`, conservative). Cada tool file tem `# bucket: always|defer` line 1 (grepability) + description prefix `[CORE]`/`[DEFER]` + `_meta.com.v4company/bucket` em `list_tools()`. **D3 mechanism:** quando bucket="always", `_meta` também inclui `"anthropic/alwaysLoad": true` — Claude Code v2.x default `ENABLE_TOOL_SEARCH=true` defere TODAS MCP tools, esse field per-tool é único way de promover always-loaded. Bucket source-of-truth: [`tool-buckets-2026-05-25.md`](docs/operacao/tool-buckets-2026-05-25.md). Re-classify mensal via audit_log uses_30d query.

### Token rotation procedure (Bearer v4-ads MCP)

Bearer tokens v4-ads-mcp SÓ são válidos se issued via backend UI (NÃO inventar). Procedure:
1. Browser https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/sessions (Google OAuth login)
2. "Nova session" → label + TTL (30/60/90/180 dias)
3. Pós-create, token plaintext flash em `/sessions/{id}?token_flash=true` (cookie expira em 60s — copia imediato OU gera novo)
4. Cole em `~/.claude.json` → `mcpServers.v4-ads.headers.Authorization` substituindo só o token (backup `.bak` first, validate JSON sintaxe pós-edit)
5. Restart Claude Code
6. Revoga token antigo em `/sessions` UI

NUNCA cole secret em chat — backend hash em `mcp_sessions.token_hash`, 401 se Bearer não bate.

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
- Don't pass `access_token`/`app_id`/`app_secret` kwargs direto pra `FacebookAdsApi.__init__()` — use `FacebookSession` bridge (F48). Use factory `build_facebook_ads_api()` em `src/meta_ads/client.py`.
- Don't usar `{{ button() }}` macro dentro de `<form>` sem `type="submit"` explicit — default `type="button"` não submete (F49).
