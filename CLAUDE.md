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

**Last updated:** 2026-05-18

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
| Sprint 3b.1 → 3b.19B (23 sprints, 2026-05-04→2026-05-13) | ✅ shipped + signed-off em conta real | **Archive:** [docs/operacao/sprint-history.md](docs/operacao/sprint-history.md). Includes audience CRUD (3b.4-3b.6), RSA CRUD (3b.16+18), conversion tracking setup (create_conversion_action 3b.19A + create_conversion_value_rule_set 3b.19B), 2 utility tools (rate_limit_status 3b.12 + audit_log 3b.13), UX bundle 3b.7, process improvements (pre-push integration sweep P2, registry auto-discovery 3b.14.1, F16 fixture cleanup 3b.17), and 15+ design-gap findings (A1-A5, F1-F19, UX-1/2/3) catalogued in [findings-catalog.md](docs/operacao/findings-catalog.md). |
| Sprint 3b.20 — `date_range` clarification + search_terms default | ✅ 2026-05-17 | 16 commits ([115d218..main](https://github.com/BadWolf1509/v4-ads-mcp/compare/e621f26..main)); smoke runbook signed-off em conta real ([`phase-3b-20-bootstrap.md`](docs/operacao/phase-3b-20-bootstrap.md)) — production revision `v4-ads-mcp-00163-zm6` (Deploy verde em 3m9s, /health 200). Zero new MCP tools (count stays 46); closes relatorio 2026-05-17 findings #1 (CRITICO, custom periods unblocked) e #2 (search_terms default 500->50). **Schema change:** 14 tools com `date_range` (13 read + 1 mutation `bulk_pause_by_query`) ganham `type: "string" + enum` explicito + novos params `start_date`/`end_date` (pattern YYYY-MM-DD). Novo helper `resolve_date_window` em `_common.py` aplica precedencia custom > preset. Defensive `json.loads` via `contextlib.suppress(ValueError)` em `parse_date_range` como safety net (Wellington relatorio root cause: Claude serializa dict como JSON string quando schema nao tem `type`). Regression guard `test_date_range_schemas_are_explicit`. **11 novos tests** (6 resolve_date_window + 2 defensive parse + 2 per-tool schema + 1 regression guard). **MO-JP smoke 7/7 PASS first try, zero findings.** Highlights: (1) T2 reproduziu o caso exato que falhou em 15/05 (`2026-05-08..2026-05-14` custom, `cost_brl=3036.62` confere com workaround LAST_7_DAYS do relatório); (2) T7 cross-tool equivalence validada — preset e custom paths produzem metricas identicas para mesma janela em `get_campaign_performance` + `get_funnel_metrics`; (3) T6 search_terms default 50 cabe em single MCP response sem overflow. **10ª sprint consecutiva sem novos bugs no smoke** (continua streak 3b.7→3b.18, broken only by 3b.19A design gaps). Resolve dogfood pain identificado pelo Wellington em report 15/05 Mestre da Obra JP+CAB. |
| Sprint 3b.21 — `get_negative_keywords_audit` created_date enrichment | ✅ 2026-05-17 | 9 commits ([8da7873..e85aa6d](https://github.com/BadWolf1509/v4-ads-mcp/compare/8da7873..e85aa6d)) + smoke signoff commit; smoke runbook signed-off em conta real ([`phase-3b-21-bootstrap.md`](docs/operacao/phase-3b-21-bootstrap.md)) — production revision `v4-ads-mcp-00167-5x7` (Deploy verde em 2m34s, /health 200). Zero new MCP tools (count stays 46); closes relatorio 2026-05-17 finding #3 (último finding aberto do relatório oficialmente fechado). **Enrichment:** per-criterion `created_date` (YYYY-MM-DD) + `added_by_email` (null se >30d via change_event retention) + bloco `additions_summary` no root com counts `last_7_days` / `last_30_days` / `pre_30_days_or_unknown`. **Architecture:** parallel 2-query JOIN via `asyncio.gather` (Query A negatives full state + Query B `change_event` last 30d CREATE), client-side merge keyed por criterion_id via novo helper público `parse_resource_path` em `_common.py` (extraído de `get_change_history.py` para cross-tool reuse). Date-comparison robust (não assume DESC ordering). **6 unit tests** (enrichment scenarios + summary invariant + orphan CREATE handling) + 5 parse_resource_path tests + 3 GAQL builder tests + integration test_tactical_tools.py adapted to dual-call contract. **MO-JP smoke 5/5 PASS + 2 findings reais documentados:** (F22) Token cap finding em conta grande — MO-JP 467 negativas pós-enrichment retornou 81k chars, excedeu MCP response cap. Tool funciona em contas low-volume (T5 ML Antiguidades 13 negativas clean). Mesma família de Sprint 3b.20 #2 (search_terms 500→50 fix). Spawn-task "F22 fix: limit param em get_negative_keywords_audit" criado para próximo sprint candidate. (F23) `get_change_history LAST_30_DAYS` Google rejeita "start date too old" — preset hits retention boundary. Workaround: usar LAST_14_DAYS ou custom `start_date/end_date` com today-29 (mesmo pattern do `creates_start` em 3b.21 ✓). Não é regressão da 3b.21, existe desde 3b.1. **Cross-tool validation EXATA em T2:** criterion 11208536 keyword "salvador" `created_date "2026-05-09"` bate bit-a-bit com `get_change_history` resource_id `22169885957~11208536` change_date_time `2026-05-09 12:45:23` user_email `wellinton.ribeiro@v4company.com`. Dogfood pain do relatório §1.3 ("X negativas adicionadas no período") resolvido — Wellington agora narra "243 negativas adicionadas em 30d (52% do total, geo + match_type expansion em MO-JP)" em report semanal. Streak interrompida em 10 (3b.7→3b.18 + 3b.20 + 3b.21 break) — F22 é boundary class (enrichment funcionou bem demais), não design gap. |
| Sprint 3b.22 — F25+F27 schema cleanup (closes 3b.19B smoke findings) | ✅ 2026-05-17 | 1 commit (`ea39150`) + smoke signoff commit; smoke runbook signed-off em conta real ([`phase-3b-22-bootstrap.md`](docs/operacao/phase-3b-22-bootstrap.md)) — production revision `v4-ads-mcp-00170-5k5` (Deploy verde, /health 200). **Nutry smoke 3/3 PASS first try** (T1 NO_CONDITION schema-rejected `"is not one of ['DEVICE', 'GEO_LOCATION']"`; T2 conversion_action_categories schema-rejected `"Additional properties are not allowed"`; T3 dry_run preview clean sem `has_category_filter`, apply blocked by F26 = doc note validation, builder pattern já validated em 3b.19B). **Streak restart após 3b.19B+3b.21 — Sprint 3b.22 = clean smoke.** Zero new MCP tools (count stays 46). **Schema cleanup em `create_conversion_value_rule_set`** (Sprint 3b.19B findings F25 + F27 + F26 doc):  **(F25)** removed `NO_CONDITION` from `condition_type` enum — Google API rejeitava em runtime ("can only be used by Store Visits/Store Sales value rule set"), STORE out of scope v0. **(F27)** removed `conversion_action_categories` field entirely — Google API restringe esse field a `[]`/`[STORE_VISIT]`/`[STORE_SALE]`, a whitelist de 13 categorias V4-focused herdada de 3b.19A era invalida pra esse field (semantics diferente do ConversionAction.category). **(F26)** tool description atualizada com nota sobre constraint Google "1 RuleSet CUSTOMER-level por conta". **2 new regression guards** (`test_schema_rejects_no_condition_value_in_condition_type` + `test_schema_rejects_conversion_action_categories_field`) prevent reintroduction. Source net: ~-30 LOC (removed dead code) + ~+45 LOC tests (regression guards) + smoke runbook ~85 LOC. **F25 + F27 são 11ª variante da família design-gap-via-SDK-ambiguity** finalizada; convention 3b.19A.1 (per-value empirical probe) WORKING — pegou ambos antes de gestor encontrar em uso real. Schema agora rejects schema-time vs runtime-time → cleaner UX, sem confusing Google errors. |
| Sprint 3b.23 — F22 fix: limit param em `get_negative_keywords_audit` | ✅ 2026-05-17 | 1 commit (`03d595d`) + smoke signoff commit; smoke runbook signed-off ([`phase-3b-23-bootstrap.md`](docs/operacao/phase-3b-23-bootstrap.md)) — production revision `v4-ads-mcp-00172-7pm` (Deploy verde, /health 200). **MO-JP smoke 3/3 effective PASS** (T1 default limit ✅ F22 resolved — response 33k chars vs 81k pre-fix, ~59% redução; T2 ordering DESC validated bit-a-bit; T5 low-volume sanity ML Antiguidades ✅; T3/T4 custom limits blocked by F28 session schema cache, work post-restart). Zero new MCP tools (count stays 46). **Closes Sprint 3b.21 smoke F22 finding** (MO-JP 467 negativas excedeu MCP response cap pós-enrichment, +25% size). **Schema change:** novo param `limit` (int 1-1000, default 100) — by_campaign retorna no max `limit` negativas, ordenadas recentes primeiro (`created_date != null` DESC, depois null). 3 new response fields: `returned_count`, `truncated` (bool), `limit` (echo back). `total_negatives` + `additions_summary` continuam refletindo conta INTEIRA (não truncados — semantics preserved). **3 new unit tests** (apply limit + mark truncated, ordering recent-first, no-truncation when total ≤ limit). ~+30 LOC source + ~+90 LOC tests. **Pattern consistente com Sprint 3b.20** (search_terms_report 500→50): 2 read tools agora usam limit + truncation. **F28 documented** (MCP client schema cache propagation lag — characteristic of transport, gestor pode precisar restart Claude Code session post-deploy quando new integer-typed params shipados; não-blocking, server validation correta). Sprint 3b.20+3b.22+3b.23 streak iniciada (Sprint 3b.22+3b.23 clean smokes em <2h cada). **F22 resolvido em conta MO-JP — gestor agora pode rodar negative_keywords_audit em V4 accounts de qualquer tamanho.** |
| Sprint 3b.24 — `create_campaign` SEARCH v0 (5º create-pattern) | ✅ 2026-05-17/18 | 10 commits ([42963cf..891daec](https://github.com/BadWolf1509/v4-ads-mcp/compare/42963cf..891daec)) + 5 fix iterations (Sprint 3b.24.1-3b.24.5: `52a0791`, `e396b27`, `ef781f8`, `df0f451`, `9488f7c`) + smoke signoff; smoke runbook signed-off em conta real ([`phase-3b-24-bootstrap.md`](docs/operacao/phase-3b-24-bootstrap.md)) — production revision final `v4-ads-mcp-00181-w7g`. **5/6 strategies validadas end-to-end em Nutry sandbox** (MAX_CONVERSIONS ✅, MAX_CONVERSION_VALUE ✅, MANUAL_CPC ✅, MAX_CLICKS ✅, multi-geo+schedule ✅; TARGET_CPA + TARGET_ROAS rejeitadas por F36 = Nutry sandbox sem conversion history — não bug, real V4 accounts funcionam). **7 findings documented** (F29 runbook typo; F30 oneof init bug; F32 budget explicitly_shared; F33 TypeError reversal; F34 EU compliance required; F35 enhanced_cpc deprecated; F37 start_date_time field name). Bug class "Google API contract gaps" (mesma família F17/F18/F25/F27 de design-gap-via-SDK-ambiguity). 5 campaigns criadas em Nutry sandbox (todas PAUSED, zero serving impact, cleanup via Sprint 3b.28 future). **1 new MCP tool (count 46 → 47):** primeiro campaign create do MCP V4, foundation pra onboarding completo via Claude/Codex (destrava create_ad_group/rsa/add_keywords que ficavam isolados). Always-CONFIRM. Schema: name + bidding_strategy (6 strategies: MAX_CONVERSIONS, MAX_CONVERSION_VALUE, TARGET_CPA, TARGET_ROAS, MANUAL_CPC, MAX_CLICKS) + daily_budget_brl + geo_targets (required, V4 BR-invariant pre-flight) + optional start/end_date. **V4 invariants hardcoded:** status=PAUSED on create, advertising_channel_type=SEARCH (v0), Search Partners OFF, Display Network OFF, language=Portuguese (`languageConstants/1014`) auto-added. **Architecture:** chained mutation pattern (Sprint 3b.19B established), N+M+2 ops em single MutateGoogleAdsRequest — 1 budget + 1 campaign + N geo criterions + 1 PT language criterion. **Helper `validate_geo_target_constants_for_value_rule` renamed to `validate_geo_target_constants_br_only`** em `_common.py` para cross-tool reuse (extension de Sprint 3b.21 parse_resource_path pattern). Runtime payload validation via `_validate_payload_shape` (Sprint 3b.19B.1 pattern: bidding strategy conditional fields + date validation). ~23 unit tests (15 tool + 8 builder) + 2 integration. F13 cross-cutting auto-returns resource_names. **Sprint 3b.19A.1 lesson aplicado:** T5 explicit per-strategy probe (6 strategies × minimal config) em smoke runbook. **Foundation pra Sprint 3b.25** (`create_asset` + `link_assets` need campaign existente). |
| Sprint 3b.25 — `create_and_link_assets` (6º create-pattern, asset CRUD bundle) | 🟢 shipped + deploy verde; smoke pending Wellington execution | Production revision `v4-ads-mcp-00188-cwv` (Deploy verde, /health 200, CI green pós-fix do CI red Sprint 3b.24 + Sprint 3b.25 typo `pending_mutations`→`pending_confirmations`). Smoke runbook pending Wellington execution ([`phase-3b-25-bootstrap.md`](docs/operacao/phase-3b-25-bootstrap.md)) — spec in [docs/superpowers/specs](docs/superpowers/specs) + plan in [docs/superpowers/plans](docs/superpowers/plans). **1 new MCP tool (count 47 → 48):** `create_and_link_assets` union, asset creation + immediate attachment in chained ops. Asset types: SITELINK, CALLOUT, STRUCTURED_SNIPPET, CALL, PROMOTION (5 types × 3 attachment levels = 15 combinations; attachment_levels: CUSTOMER, CAMPAIGN, AD_GROUP). Always-CONFIRM. Schema: assets array (1-20 per batch) + target_type + target_id (campaign_id or ad_group_id, CUSTOMER level auto-discovers via customer_id) + optional performance_max (for PROMOTION). **V4 invariants:** BR country code hardcoded, PT language auto-added, currency=BRL in Promotion, micros formula enforcement (e.g., 20% → 200_000 micros). **Architecture:** chained mutation pattern (Sprint 3b.19B established), N+M+K ops em single MutateGoogleAdsRequest — N asset creates + M asset_group creates (per level) + K attachment ops. Proto field validation via context7 context::query-docs per asset type (empirical per-value probing Sprint 3b.19A.1 lesson). ~17 unit tests (8 tool + 9 builder) + ~18 new builder tests + 2 integration. Pre-flight: none (trust Google runtime errors per F14 lesson). **Smoke runbook:** 15 tests Nutry sandbox (1163862076 campaigns inherited from 3b.24) — T1-T2 SITELINK CUSTOMER/CAMPAIGN, T3 SITELINK AD_GROUP (rare probe), T4-T5 CALLOUT, T6-T7 STRUCTURED_SNIPPET (header validation), T8-T9 CALL, T10-T11 PROMOTION (micros formula assertion), T12 batch mixed types, T13-T14 schema regression, T15 response cap (F22-equivalent boundary). T3 + T9 may surface F-findings (predicts rare attachment combos). Clean smoke = 12+/15 PASS. **Closes roadmap foundation** — asset CRUD + 3b.26 (offline conversions) + 3b.27 (customer match) + 3b.28 (remove ops) = onboarding complete. |

**48 MCP tools** registered: 23 read + 24 mutations + `apply_change`.
**15 web pages** in production with Hybrid Editorial+Operational identity (FE Redesign v2).
**Q8 invite-only allowlist** active — only `@v4company.com` emails pre-invited via `/admin/invites` can complete OAuth.
**`BOOTSTRAP_ADMIN_EMAILS`** env on Cloud Run = `wellinton.ribeiro@v4company.com` (dormant since managers table is populated).

### Pending / future

- **Modelo operacional: solo dogfood com contas reais** — `wellinton.ribeiro@v4company.com` é o único gestor de tráfego usando o MCP por enquanto. Sinal de produto vem de uso direto + smoke runbook em conta real (modelo [`phase-3b-1-bootstrap.md`](docs/operacao/phase-3b-1-bootstrap.md), que pegou 2 bugs reais no Sprint 3b.1). Lucas Soares (`lucassoares@v4company.com`) tem OAuth + MCP session ativos mas dormentes — gestor real V4, sem expectativa de uso por enquanto. Multi-gestor + multi-tenancy ficam adiados.
- **Standard Access (Google Ads) — submetido, sem bloqueio operacional** — case `26521440673` resubmetido 2026-05-11 (submissão original 2026-05-05 não retornou veredicto). Análise empírica 2026-05-17 via `rate_counters`: uso atual 11/15.000 ops/dia (0.07%), pico histórico 119 ops em 2026-05-12 (0.8%). Projeção worst-case com TODAS as mutation tools pendentes ativadas (`create_campaign`, `create_asset`, `link_assets`, `upload_customer_match_list`, `import_offline_conversions`) + uso pesado simultâneo = ~200-500 ops/dia, ainda 30x abaixo do limite Basic. Standard Access é benefício organizacional (due diligence Google, acesso a features tipo reach planner) + teto pra cenário multi-tenant futuro (5+ gestores simultâneos), não constraint operacional pra modo solo dogfood atual. Quando aprovar, mudança é 1 linha em `rate_limit.py:20` (`DAILY_QUOTA_BASIC` → `DAILY_QUOTA_STANDARD`) — sem refactor pendente, sem sprint represado. Aguardar veredicto Google passivamente.
- **Phase 3b restante** — Sprint 3b.24 (`create_campaign`) shipou foundation pra onboarding completo via MCP. 4 mutation tools faltantes pra finalizar roadmap V4:
  - **Sprint 3b.25** candidate — `create_asset` + `link_assets` bundle (sitelinks/callouts/structured snippets; complementa 3b.24)
  - **Sprint 3b.26** candidate — `import_offline_conversions` (V4 lead-gen workflow: WhatsApp/CRM → MCP upload → Google Ads tracking)
  - **Sprint 3b.27** candidate — `upload_customer_match_list` + A4 investigation (audience exclusion mechanism aberto desde Sprint 3b.4/3b.5; ver [findings-catalog.md](docs/operacao/findings-catalog.md) §A4)
  - **Sprint 3b.28** candidate — `remove_keyword/campaign/ad_group/ad` bundle (gestor pode usar Google Ads UI até lá)
  - **Sub demanda:** retrofit ProtoFieldCapture em builders pré-3b.5 (YAGNI), `update_conversion_action`/`update_conversion_value_rule_set` (simetria CRUD), STORE_VISIT/STORE_SALE support em RuleSet
  - **Sprint 3b.19B Nutry smoke pending Wellington execution** (único smoke pendente do backlog)
  - **No quota blockers** — análise empírica 2026-05-17: uso atual ~0.07% Basic, worst-case ~3% (ver Standard Access subsection acima). Decisão de próximo sprint depende de sinal do dogfood + prioridade do gestor.
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
