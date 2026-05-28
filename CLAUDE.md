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

**Last updated:** 2026-05-27 — Sprint 3b.40 ship (3 quick wins mutate safety A1+B9+A2 + F56 catalog, ICE somado 2030 dogfood MO-JP 27/05). Sprint anterior mesma sessão: M.3 ship + smoke real + hotfix iterativo M.3.1+M.3.1.1 (F53+F54 caught) + Meta MCP oficial analysis (44 tools confirmed + F55 architectural lesson) + CI fix integration test gap. **56 findings** (F1-F56 + A1-A6 + D1-D3).

### Quick-start próxima sessão (TL;DR)

- **Production state:** 62 MCP tools (57 Google + 5 Meta) deployed + `/health` 200. Last commit `ecf926b` (smoke runbook Sprint 3b.40). Bucket: **22 always + 40 defer**. Caminho B+ Meta volume **RESTORED** em produção pós-hotfix F53+F54. Sprint 3b.40 shipped: 3 quick wins mutate safety (A1+B9+A2) — `get_keyword_performance` retorna `negative: bool`, `audit_quality_score` retorna `ad_group_status`, `update_keyword_status` dry-run retorna `sample_keywords` top 5.
- **Próximo natural sprint** (escolha 1, priority ordered):
  1. **Sprint M.4** — `meta_get_geo_performance` + `_device` + `_hourly` (alta volume Caminho B+, multiplica calls/session)
  2. **Sprint M.5** — `meta_get_audience_performance` + `meta_get_top_creatives` (read coverage Meta)
  3. **Sprint 3b.41** — Fase 2 refactor Caminho C (consolidação `get_performance_breakdown(level, dimension)` substitui 9 reports — renumerado de 3b.40, agora 3b.41 pós Sprint 3b.40 Quick Wins ship)
- **Tokens válidos:**
  - v4-ads Bearer: rotacionado 25/05 (procedure: UI `/sessions/new`, NÃO inventar — backend hash valida)
  - Meta OAuth Wellington: reconectado 27/05 00:37 GMT (anterior invalidado server-side antes natural expiry — F-finding candidate B8). Nova expiry 26/07/2026.
- **Meta MCP oficial conectado (2026-05-27):** Wellington testou — **44 tools** (correção 29→44, +15 desde launch Apr/2026). Gradual rollout 2-tier: 7/12 V4 contas enabled + algumas tools "new" blocked. V4 build-strategy validated (100% cobertura vs Meta MCP 58%). 🪄 **Use `ads_get_field_context` (Meta MCP oficial) pra validate Meta fields ANTES de shipping novas V4 Meta tools** — teria evitado F53+F54 100%.
- **Roadmap Meta enxuto (11 sprints pós-M.3.1.1):** M.4 → M.5 → M.6 → M.7 → M.16-M.18 (mutates status/budget/bid) → M.19 → M.20-M.22 (create) → M.23 (Customer Match). Spec original 22 sprints cortado pós-3b.40 cleanup (descartados M.5.5/M.5.6/M.8/M.11-M.15/M.24/M.25 = ~50% reduction). Re-considerar diferenciador competitivo (M.5.5) só se Caminho B+ falhar hit volume 25/06.
- **Decision gates próximas:**
  - **2026-06-01** (D+7): Wellington 7d feedback Sprint 3b.39 F1 → decide F1→F2 timeline
  - **2026-06-25 a 2026-07-10** (D+30-45): Caminho B+ Meta volume checkpoint → atingiu 500 calls/15d? → re-submit Full Access App Review
- **Quando ler outros docs:** [bug suspeito → `findings-catalog.md`] [sprint detail → `sprint-history.md`] [execute pending → spec+plan] [Meta strategy → `2026-05-24-meta-ads-incorporation-design.md`]

### Shipped — 62 MCP tools (57 Google + 5 Meta)

| Stream | Range | Highlights |
|---|---|---|
| Foundation (Phases 0-1b + 3a + FE Redesign v2) | 2026-05-03→05 | See [`infra-setup.md`](docs/operacao/infra-setup.md). |
| Google sprints 3b.1 → 3b.40 (40 sprints) | 2026-05-04→27 | 57 tools shipped + 3 enrichments. Latest: 3b.33 `detect_drift`, 3b.35 `audit_goal_attribution`, 3b.36 `audit_zombie_keywords`, 3b.37 `audit_orphan_smart_actions`, 3b.38 (F52+F23+B1 fixes), 3b.39 (bucket classification F1 + D3 alwaysLoad mechanism), 3b.40 (Quick Wins Mutate Safety A1+B9+A2 + F56 catalog — sample_keywords dry-run + negative field + ad_group_status). Detail per sprint: [`sprint-history.md`](docs/operacao/sprint-history.md). |
| Meta family M.1 → M.3.1.1 | 2026-05-24→27 | 5 tools shipped: `meta_list_my_ad_accounts` (M.2a, cache) + `meta_get_account_overview` (M.2b, Graph API) + `meta_get_campaign_performance` (M.3, always) + `meta_get_ad_set_performance` (M.3, defer) + `meta_get_ad_performance` (M.3, defer). DB foundation (4 tables) + OAuth flow + admin UI Revogar/Refresh + endpoints data-deletion-callback + refresh-accounts. **Meta App Review respondido 2026-05-25:** `public_profile` ✅, `Marketing API Tier` ❌ (insufficient calls 15d) → Caminho B+ janela observação 30-45d (acelerar M.3+ pra volume natural). **M.3 smoke real 2026-05-27 caught F53+F54** (Meta Insights API rejeita `effective_status`/`billing_event`/`daily_budget`/`creative_id` em fields=) → **M.3.1+M.3.1.1 hotfix iterativo** (commits `984a7ae`+`b3ba6b5`) → tools restored em produção. **Smoke final 8/10 PASS** em ML Antiguidades: T1+T2+T3 success com data real (spend=411.83, ctr=3.77%, hierarquia campaign→adset→ad math consistente), T5+T7+T8+T9+T10 PASS, T4+T6 DEFERRED V1 (effective_status filter feature gone até V1 2-step query restore). |

**Production:** `/health` 200, CI green em `ecf926b` (smoke runbook Sprint 3b.40). 16 web pages prod. Q8 invite-only allowlist ativo.

**56 findings catalogados** ([`findings-catalog.md`](docs/operacao/findings-catalog.md)):
- **F56 (MED, sessão 2026-05-27 Sprint 3b.40):** `get_keyword_performance` retornava positive E negative `ad_group_criterion` indistintamente — workflow risk em mutate downstream. Mitigation Opção A+C (field `negative: bool` + description warning). Family design-gap-via-missing-discriminator (variant silent-acceptance, similar F52 missing parent filter).
- **F53+F54+F55 trio (HIGH, sessão 2026-05-27):** Meta /insights vs /entities endpoints separation arquitetura — root cause Meta Insights API field whitelist gaps. F55 = architectural lesson catalogado via Meta MCP oficial `ads_get_field_context` empirical probe.
- **D1-D3 trio (decision-not-bug):** D1 Meta App Review Standard rejeitado → Caminho B+, D2 MCP defer_loading client-side (initial wrong assumption), D3 real mechanism server-side `_meta.anthropic/alwaysLoad`.
- **F47-F52 (recent):** F47 PowerShell secret pipe CRLF, F48 FacebookSession factory, F49 button macro form submit, F50/F51 retrospective F33/F37 traces, F52 ad_group_status órfãs cosméticas.
- **Lição reinforced N× consecutiva:** sempre verificar docs oficial cliente ANTES de design refactor cross-layer (D1+D2+D3 + F53+F54+F55 cada salvou 1-3 dias wasted work).

### Pending / future (priority ordered)

**🔥 Next sprint (escolha 1):**
- **Sprint M.4** (3 tools breakdowns geo+device+hourly) — alta volume Caminho B+, multiplica calls/session
- **Sprint M.5** (audience + top_creatives) — completa read coverage Meta
- **Sprint 3b.41** (Fase 2 refactor Caminho C) — consolidação `get_performance_breakdown(level, dimension)` substitui 9 reports = -9 tools permanente. Spec: [`2026-05-25-architecture-refactor-design.md`](docs/superpowers/specs/2026-05-25-architecture-refactor-design.md). Aguardar M.5 shipped antes (refactor precisa de ≥9 reports estáveis).

**⏰ Decision gates (calendário):**
- **2026-06-01** (D+7 desde Sprint 3b.39 F1 ship): Wellington 7d feedback Sprint 3b.39 F1 → decide F1→F2 timeline. 5 perguntas estruturadas.
- **2026-06-25 a 2026-07-10** (D+30-45 desde Caminho B+ ativado): Meta volume checkpoint. Se atingiu 500 calls/15d threshold → re-submit Full Access App Review. Monitor `meta_rate_counters` table X-Business-Use-Case-Usage. Decision gate atualizado: continuar Meta = ≥3 calls/semana dogfood; senão pivot Google.
- **2026-07-25** (Meta OAuth Wellington expira): reconectar via `/admin` ANTES desta data (token expira 26/07/2026).

**🗺️ Roadmap Meta family enxuto (11 sprints pós-M.3.1.1, ~3 meses dev solo):**
- Reads: M.4 (geo+device+hourly) → M.5 (audience+top_creatives) → M.6 (budget_pacing+funnel) → M.7 (change_history+conversion_events)
- Mutates: M.16-M.18 (update status+budget+bid) → M.19 (create campaign) → M.20-M.22 (create adset+ad+creative)
- Audiences: M.23 (Customer Match — apply/remove/create custom)
- Spec original: [`2026-05-24-meta-ads-incorporation-design.md`](docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md) §7 — **DESCARTADOS** em 2026-05-27 cleanup: M.5.5/M.5.6 (diferenciador competitivo cosmético), M.8 (pages_for_business niche), M.11-M.15 (5 audits — dogfood manual via run_gaql cobre), M.24-M.25 (lookalike+offline conversions avançadas)
- Re-considerar M.5.5 (anomaly+benchmarks) só se Caminho B+ falhar 500 calls/15d em 25/06 (diferenciador pra re-pitch Full Access)

**📋 Backlog Google sprints 3b.39+ post-F1:** audit_negative_criterion_overlap, audit_assets_parity_between_campaigns, remove_* bundle, audit_log gap fix em `run_gaql`/`get_my_audit_log`/`get_my_rate_limit_status`, W2 `verify_campaign_state` ICE 280.

**📝 Backlog LOW (bundle em Sprint Quick Wins #2 Q3):**
- G2 `change_event` em `list_gaql_resources`, UX1 GAQL fields opcionais vazios, B2/B3 schema hints
- B7: BUC tracking observability gap em error path Meta (run_meta_graph_get só parseia BUC header em success — error responses não increment counter)
- A4 OPEN: Customer Match exclusion mechanism (3b.4+ sem demand real — sprint dedicado só se V4 ativar -10% CPA playbook)

**👥 Operational pendings:**
- 3 colaboradores V4 LS&Co como Meta App Administrators (quando time começar a usar — Meta Dev Console > App Roles, Dev Mode permite 25)
- Real biz findings dogfood (fora-MCP, owner gestor): ML Antiguidades cross-platform tracking pixel + MDO Cotia 2 accounts duplicadas + WJX FECHADO. Ver [`dogfood-2026-05-25-meta-first-tool-real-biz-findings.md`](docs/operacao/dogfood-2026-05-25-meta-first-tool-real-biz-findings.md)

**🟢 No-action / monitoring (passive):**
- Standard Access GAds case `26521440673` passive (uso ~0.07% Basic, zero blocker; quando aprovar = 1-line em `rate_limit.py:20`)
- WATCH 3b.36 default `limit=200` estoura MCP cap em contas 500+ entries (workaround docs, V1 bump se demanda)
- B8 candidate: Meta OAuth long-lived token server-side invalidation pattern (caught 1×, wait reincidência pra promover F-finding)

**🗑️ Descartados 2026-05-27 (declarados YAGNI permanente):**
- Simetria CRUD `update_conversion_value_rule_set` STORE (STORE out-of-scope V4 — sem retail físico)
- 3b.19B Nutry smoke pending (prod estável 4 meses, low-risk)
- 3b.30 T7-T8 production Nutry sem QS (known-limitation: Nutry low-volume Google não calcula QS)
- ProtoFieldCapture retrofit pré-3b.5 builders (YAGNI declarado 3b.27)
- `/sprint-bootstrap` skill (zero uso real — `superpowers:brainstorming` + `writing-plans` cobrem)

## Read these first when continuing work

**Critical (read se task envolve):**
```
docs/operacao/findings-catalog.md       # ★ Bug history 56 findings (F1-F56 + A1-A6 + D1-D3) — F53/F54/F55 trio = Meta API endpoint architecture lesson + F56 (3b.40) negative discriminator gap
docs/operacao/sprint-history.md         # ★ Sprint table per-row detail (3b.1→3b.40 + M.1→M.3.1.1) — comprehensive history
docs/superpowers/specs/2026-05-24-meta-ads-incorporation-design.md   # ★ Meta family roadmap (spec original 22 sprints, CLAUDE.md tem versão enxuta 11 pós-cleanup 27/05)
docs/superpowers/specs/2026-05-25-architecture-refactor-design.md   # ★ Refactor arquitetural 4 fases (Fase 1 ✅ shipped 3b.39)
```

**Reference (se relevant pra task atual):**
```
docs/operacao/phase-3b-39-bootstrap.md  # Bucket classification F1 (3b.39)
docs/operacao/phase-3b-40-bootstrap.md  # Quick Wins A1+B9+A2 (3b.40, current)
docs/operacao/phase-M-2a-bootstrap.md   # Meta foundation (M.2a)
docs/operacao/phase-M-2b-bootstrap.md   # Meta account overview (M.2b)
docs/operacao/phase-M-3-bootstrap.md    # Meta performance tools (M.3, 8/10 PASS pós F53+F54)
docs/operacao/tool-buckets-2026-05-25.md  # Bucket classification per-tool (active source-of-truth)
docs/operacao/infra-setup.md            # Foundation setup (Phases 0-1b + 3a)
docs/operacao/dogfood-*.md (7 files)    # Real biz feedback (MO-JP, ML Antiguidades, Nutry, Dr Derick, Meta-first)
docs/superpowers/specs/ (6 active)      # Current sprint specs (3b.40, M.3, M.2b, M.2a, refactor, Meta incorporation)
docs/superpowers/plans/ (6 active)      # Current sprint plans (matching specs)
docs/_archive/ (113 files preserved)    # Sprints SHIPPED ≥7 dias: plans (40) + specs (35) + runbooks (29) + setup docs (3). NÃO grep aqui exceto debug histórico — use git log primeiro.
```

## Conventions

> Quick reference. Full bug taxonomy + lessons: [`findings-catalog.md`](docs/operacao/findings-catalog.md). Sprint detail: [`sprint-history.md`](docs/operacao/sprint-history.md).

### Princípios de código (Karpathy)

Heurísticas-teste pra reduzir erros típicos de LLM. Complementam (não repetem) o system prompt + cultura YAGNI já vigentes. Fonte: [`andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills).

- **Teste das 200→50:** se escreveu 200 linhas e dava 50, reescreva. Pergunte "um eng. sênior chamaria isso de overcomplicado?" — se sim, simplifique.
- **Rastreabilidade da diff:** cada linha alterada deve rastrear direto ao pedido. Não "melhore" código adjacente nem refatore o que não está quebrado; remova só os órfãos que SUAS mudanças criaram.
- **Tarefa → meta verificável:** reformule antes de codar — "corrige o bug" → "escreve teste que reproduz, depois faz passar"; "adiciona validação" → "testes pra inputs inválidos, depois faz passar".
- **Premissas explícitas:** se há múltiplas interpretações, apresente — não escolha em silêncio. Push back quando existe caminho mais simples.

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

### Meta API field validation (post-F53/F54/F55, M.3.1+M.3.1.1 lessons)

Meta tem **2 endpoints separados** com field whitelists diferentes:
- `/insights` = APENAS metrics fields (spend, impressions, ctr, cpc, reach, frequency, actions, action_values, purchase_roas)
- `/campaigns`, `/adsets`, `/ads` = metadata fields (effective_status, daily_budget, creative_id, name, objective, optimization_goal, billing_event, etc.)

**Antes de shipping nova Meta tool com novos fields:**
1. **Use Meta MCP oficial `ads_get_field_context([field_names])` PRIMEIRO** — retorna `levels=[campaign|adset|ad|ad_account]` + `supported_filter_operators` + `enum_values`. Confirma endpoint correto + valida field existe. **Teria evitado F53+F54 100%** em 2 minutos vs 2 deploy cycles + hotfix iteration. Meta MCP oficial configurado em `~/.claude.json` mcpServers.
2. **OU per-value probe contra real Meta sandbox account** (convention 3b.19A.1 análogo Google) em smoke runbook ANTES de production deploy.

**V1 enhancement pattern (Sprint M.3.2 candidate):** 2-step query restaura status/metadata filter:
```python
# Step 1: filter entities by metadata
entity_ids = await fetch("/act_X/{level}s?fields=id,effective_status&filtering=[...]")
# Step 2: get insights filtered by entity_ids
metrics = await fetch("/act_X/insights?level={level}&filtering=[{'field':'{level}_id','operator':'IN','value':entity_ids}]")
```

### When removing fields from schema/whitelist (post-M.3.1.1 CI fix lesson)

Quando remover field de `INSIGHTS_FIELDS_*` (Meta) OU enum whitelist (Google), **MUST grep todos test files** ANTES de commit:
```bash
grep -rn "field_name" tests/    # find ALL assertions
```

`check_pre_push.py` (step 5/5 `non-DB integration`) **NÃO pega** integration tests com testcontainers DB (`@pytest.mark.integration`). `check_pre_push_full.py` pegaria mas Wellington Windows sem Docker → não roda local. CI cloud testcontainers pega — mas é 8+ min cycle. Grep upfront economiza 1 deploy cycle.

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
- Don't shippar nova Meta tool sem validar fields via `ads_get_field_context` (Meta MCP oficial) OR per-value probe contra real Meta sandbox PRIMEIRO. Meta tem `/insights` vs `/entities` endpoint separation (F55) — fields metadata como `effective_status`/`daily_budget`/`creative_id` válidos em entity endpoints, NÃO em `/insights` (F53+F54 = 2 deploy cycles wasted que magic helper teria evitado).
- Don't remover field de `INSIGHTS_FIELDS_*` ou enum whitelist sem `grep -rn "field_name" tests/` PRIMEIRO. `check_pre_push.py` step 5/5 NÃO pega integration tests DB (testcontainers) — só CI cloud pega, com 8min delay. Lição M.3.1.1 CI fix `465656f` (creative_id assertion legacy).
- Don't assumir Meta long-lived token (~60d expiry) é válido só porque `meta_oauth_connections.token_expires_at > now()` — Meta pode invalidar server-side antes do natural expiry por security/policy reasons (caught 2026-05-27, token de 25/05 invalidado após 36h). Sempre handle `to_friendly_meta_error` subcode 458/467/460/463 graciosamente.
