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

**Last updated:** 2026-05-13

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
| Sprint 3b.1 — `add_negatives_from_search_terms` + `get_change_history` | ✅ 2026-05-11 | 11 commits ([f156d99..3549778](https://github.com/BadWolf1509/v4-ads-mcp/compare/c660c6c..3549778)); smoke runbook signed-off ([`phase-3b-1-bootstrap.md`](docs/operacao/phase-3b-1-bootstrap.md), [9fbfb1c](https://github.com/BadWolf1509/v4-ads-mcp/commit/9fbfb1c)) |
| Sprint 3b.2 — `update_ad_status` + `bulk_pause_by_query` | ✅ 2026-05-11 | 11 commits ([1ee0bda..24854dc](https://github.com/BadWolf1509/v4-ads-mcp/compare/edbb8ba..24854dc)); smoke runbook signed-off em conta real ([`phase-3b-2-bootstrap.md`](docs/operacao/phase-3b-2-bootstrap.md)) — 2 bugs reais pegos pelo pre-smoke (GAQL parens + REMOVED retrofit gap nos 3 status ops existentes) fixados em `24854dc`. Retrofit completo: `blast_radius.classify` + extends `run_report` com `params_summary` + 4 status ops passam `new_status`. |
| Sprint 3b.3 — `add_keywords` | ✅ 2026-05-12 | 5 commits ([220ae25e..657f8f6](https://github.com/BadWolf1509/v4-ads-mcp/compare/4d54878..657f8f6)); smoke runbook signed-off em conta real ([`phase-3b-3-bootstrap.md`](docs/operacao/phase-3b-3-bootstrap.md)) — production revision `v4-ads-mcp-00096-mzm`. **2 achados reais** documentados: (A1) Google faz silent dedupe em vez de `CRITERION_EXISTS` quando KW duplicada, portanto idempotência via Google API behavior (não via nosso `_classify_partial` mapping); (A2) **bug pré-existente Sprint 3a:** `update_*_status(REMOVED)` passa dry-run mas `apply_change` falha — Google rejeita REMOVED em `.status.update`. Spawn-task criado pra fix posterior. Pivot original `update_keyword_match_type` → `add_keywords` por API immutability finding (KeywordInfo.text+match_type são identidade do criterion, não modificáveis). |
| Sprint 3b.4 — `apply_audience` | ✅ 2026-05-12 | 5 commits ([9b2aaf7..528d77c](https://github.com/BadWolf1509/v4-ads-mcp/compare/72e98ed..528d77c)); smoke runbook signed-off em conta real ([`phase-3b-4-bootstrap.md`](docs/operacao/phase-3b-4-bootstrap.md)) — production revision `v4-ads-mcp-00102-6td`. **2 achados graves documentados:** (A3) Google silent-drops user_interest com taxonomy_type incompatível (VERTICAL_GEO em SEARCH ad_group) — retorna applied_count=1 + request_id mas criterion não persiste. Validado in-prod com IN_MARKET (id 80001) persistindo criterion `56976936578`. (A4) Google silently overrides `negative=True` → `false` em CampaignCriterion user_list creates — T3 apply (Customer Match exclusion na Mestre da Obra JP) criou criterion `2480650242694` mas como POSITIVE observation, NÃO exclusion. V4 playbook `-10% CPA via exclusion` requer mecanismo API diferente a investigar. Spawn-tasks A3 + A4 criados. **Lição test coverage:** MagicMock-everywhere em unit tests não verifica atribuição real de proto fields — A4 passou nos 8 builder tests sem detecção. Padrão de teste pra mutate builders precisa capturar field assignments via mock state, não MagicMock default. |
| Sprint 3b.5 — stabilization fixes (A2 + A3 + A4) | ✅ 2026-05-12 | 6 commits ([ffd50fa..3c23fc5](https://github.com/BadWolf1509/v4-ads-mcp/compare/178ab18..3c23fc5)); smoke runbook signed-off em conta real ([`phase-3b-5-bootstrap.md`](docs/operacao/phase-3b-5-bootstrap.md)) — production revision `v4-ads-mcp-00111-ljc`. **Composite stabilization sprint:** A2 schema-restrict `update_*_status` para `["ENABLED", "PAUSED"]` em 4 status tools + remove dead-code Sprint 3b.2 retrofit do `blast_radius.classify`. A4 pre-flight rejection no `apply_audience` pra combo `(campaign + exclusion + user_list)` — direciona gestor pra ad_group level. A3 pre-flight GAQL batch taxonomy validation no `apply_audience` pra `user_interest` (whitelist IN_MARKET + AFFINITY). ProtoFieldCapture fixture em `tests/unit/fixtures/proto_capture.py` + retrofit do `test_builder_campaign_user_list_exclusion` pra exercitar o pattern. 10 de 10 smoke tests PASS first try (primeira sprint sem novos bugs no smoke — resultado esperado de stabilization). **Lição CI:** pre-push gates rodaram só unit tests; 2 integration tests pré-existentes ficaram inválidos pós-Sprint 3b.5 (REMOVED dead test + apply_audience sem run_report mock) e foram fixados em segundo commit `3c23fc5`. Spawn-task pendente: adicionar integration sweep ao pre-push gates. |
| Sprint 3b.6 — `remove_audience` (closes audience CRUD) | ✅ 2026-05-12 | 6 commits ([eb3ed19..0c68bca](https://github.com/BadWolf1509/v4-ads-mcp/compare/825a830..0c68bca)); smoke runbook signed-off em conta real ([`phase-3b-6-bootstrap.md`](docs/operacao/phase-3b-6-bootstrap.md)) — production revision `v4-ads-mcp-00117-frb` (post-A5 fix). **Closes audience CRUD:** create (3b.4) + validation (3b.5) + delete (3b.6). Tool `remove_audience` com schema target_type + target_id singular + criterion_ids array (cap 100), sempre CONFIRM (spec §7.1 remove). 6 ProtoFieldCapture builder tests + 9 tool tests + 1 integration. **Cross-cutting fix descoberto em T4** (`apply_change.py`): propagação de `__params_summary__` via payload key (mesmo pattern que `__partial_failure__` + `__target_count__`) — beneficia TODAS as CONFIRM-path tools com custom audit summaries. Nutry smoke 6/6 PASS + Mestre da Obra JP cleanup do criterion `2480650242694` (Sprint 3b.4 A4 artifact). **Achado A5 (smoke + post-Nutry):** CampaignCriterion resource_name é compound `{campaign_id}~{criterion_id}` (mesmo padrão de AdGroupCriterion), NÃO flat como spec inicial assumia. Builder construía path flat — Google silently aceitou retornando applied_count=1 mas NÃO removia o criterion. 5ª variante da família silent-acceptance (A1 dedupe, A3 drop, A4 override, A5 path-malformed). Fixed em `0c68bca` via SDK path helpers (authoritative source). **Real biz value cumulativo:** 5 orphan criteria limpas em 4 sprints, audience CRUD agora self-contained no MCP. |
| Sprint 3b.7 — UX fixes bundle (P1b dogfood findings) | ✅ 2026-05-12 | 4 commits ([a2d2046..952033a](https://github.com/BadWolf1509/v4-ads-mcp/compare/74af804..952033a)); smoke runbook signed-off em 3 contas reais ([`phase-3b-7-bootstrap.md`](docs/operacao/phase-3b-7-bootstrap.md)) — production revision `v4-ads-mcp-00121-kw7`. **Composite UX-fixes mini-sprint (zero new tools, tool count stays at 39):** UX-1 `tracking_warning` field PT-BR em `get_account_overview` + `get_funnel_metrics` quando `conversions_value == conversions` (1:1 placeholder tracking, ROAS misleading). UX-2/UX-3 (descobertos via brainstorming como **mesmo bug**): proto-plus v20 repr regression — `str(enum).split(".")[-1]` retornava `"2"` em vez de `"ENABLED"`. Fix mecânico para `.name` em 22 call sites across 10 read tools. **Helper validation empírica em 3 shapes:** (a) Mestre da Obra JP — 1:1 placeholder, warning fires ✅; (b) ML Antiguidades (`7455088726`) — real revenue tracking, AOV R$ 515, ROAS 100.79, no warning ✅; (c) Expresso Turismo (`5295988089`) — zero-value tracking gap (conv=95, value=0), no warning ✅ (different gap class, correct). **Bonus catch:** retrofit pegou quality_* enums em `get_keyword_performance` (4 enums adicionais) — coverage maior que spec antecipou. 7 de 7 smoke tests PASS first try (segunda sprint consecutiva sem bugs — stabilization compounding). **Out-of-MCP-scope finding documentado:** V4 accounts default a placeholder tracking; ML Antiguidades é exceção feliz. V4 setup audit fica fora do escopo do MCP. |
| Sprint P2 — pre-push integration sweep (process improvement) | ✅ 2026-05-12 | 8 commits ([88912ab..e6b1a74](https://github.com/BadWolf1509/v4-ads-mcp/compare/8c52a26..e6b1a74)); zero novos MCP tools (tool count stays at 39); zero smoke runbook (internal tooling, sem mudança em production behavior). **Closes Sprint 3b.5 spawn-task:** "adicionar integration sweep ao pre-push gates." Ship 2 scripts Python standalone em `scripts/`: `check_pre_push.py` fast default (ruff + format + mypy + unit + non-DB integration, ~30s, sem Docker) + `check_pre_push_full.py` opt-in full sweep (6º step `pytest -m integration` via testcontainers, exit 2 + PT-BR hint se Docker off). Shared engine `_runner.py` com `Step` frozen dataclass + `run_steps` fail-fast + `check_docker` probe — 7 unit tests cobrem todos os paths. **Marker fix pré-requisito:** `pytestmark = pytest.mark.integration` em `tests/integration/test_update_ad_status.py` (usava testcontainers mas faltava marker — step 5 do fast script teria hung). CLAUDE.md "Verification cadence" agora aponta single entry `python scripts/check_pre_push.py` em vez dos 4 comandos manuais; "Don't do" adiciona bullet sobre não pushar sem rodar o gate. **Achados durante implementação:** (a) deviation no plano: implementer adotou underscore filenames (`check_pre_push.py`) em vez de dash; aceito como mais Pythonic e consistente; (b) Task 3 scope-creep: implementer marcou 5 testes não-Docker como `integration` para suprimir falhas locais quando real root cause era `google-ads` dep não instalada — revertido em `cdb86ae` (5 markers falsos retirados, 3 legit em test_health.py + test_mcp_handshake.py preservados); (c) `tests/unit/test_rate_limit.py` é misplaced (usa testcontainers + tem marker `integration`, mas vive em `tests/unit/`) — fix do filter no pytest unit step matcheia CI behavior, relocate fica pra spawn-task. Gate dogfooded em sua própria merge: 5/5 PASS first time. |
| Sprint 3b.8 — F12 fix (manual CPC bid pre-flight) | ✅ 2026-05-12 | 5 commits ([42f01e3..70ce0a5](https://github.com/BadWolf1509/v4-ads-mcp/compare/1ab076a..70ce0a5)); zero novos MCP tools (tool count stays at 39); zero smoke runbook (Sprint 3b.5 A3 pattern — pre-flight é unit-testable). **Closes silent-acceptance bug family 6ª variante (F12 do P3 dogfood):** pre-flight GAQL batch validation em `update_keyword_bid` + `update_ad_group_bid` rejeita payloads em campaigns que usam auto-bidding strategy (MAXIMIZE_CONVERSIONS, TARGET_CPA, MAXIMIZE_CONVERSION_VALUE, etc) — Google ignora `cpc_bid_micros` silenciosamente nessas strategies (documentado oficialmente em `developers.google.com/google-ads/api/docs/campaigns/bidding/override-strategies`). Whitelist: `{MANUAL_CPC, ENHANCED_CPC}` (únicas strategies que honram `cpc_bid_micros` field). Helper `validate_manual_cpc_strategy` em `src/google_ads/queries/_common.py` compartilhado entre as 2 tools. 9 unit tests (5 helper + 2 per tool). **Investigation finding (Wellington pivotou de C→B via context7 docs):** considerou whitelist liberal com MANUAL_CPM/CPV mas rejeitado — esses usam `cpm_bid_micros`/`cpv_bid_micros` (bid fields diferentes), incluí-los re-introduziria F12 em outro guise. Empirical V4 distribution (7 accounts surveyed): MAXIMIZE_CONVERSIONS dominant (67%), MANUAL_CPC em SHOPPING (ML Antiguidades) confirmed. Silent-acceptance family timeline completa: A1 (3b.3 dedupe), A3 (3b.4 drop), A4 (3b.4 override), A5 (3b.6 path), F11 (P3 enum no-decode), **F12 (3b.8 silent ignore)**. |
| Sprint 3b.9 — F7 fix (get_recommendations type_pt) | ✅ 2026-05-12 | 3 commits ([62f25db..0cb34e4](https://github.com/BadWolf1509/v4-ads-mcp/compare/a1fdd1c..0cb34e4)); zero novos MCP tools (tool count stays at 39). **Closes P3 dogfood F7:** `type_pt` field não duplica mais `type` quando PT-BR mapping ausente — fallback null sinaliza "use type field, no translation available." `_TYPE_PT` mapping expandido de 25 → 30 entries cobrindo categorias mais comuns emitted pelo Google: forecasting variants (`FORECASTING_SET_TARGET_CPA` do dogfood + `FORECASTING_SET_TARGET_ROAS`) + Performance Max upgrades (`UPGRADE_LOCAL_CAMPAIGN_TO_PERFORMANCE_MAX`, `UPGRADE_SMART_SHOPPING_CAMPAIGN_TO_PERFORMANCE_MAX`, `IMPROVE_PERFORMANCE_MAX_AD_STRENGTH`). Tool description updated explicitando contract ("null caso contrario"). 3 unit tests: null fallback + regression (existing KEYWORD entry) + new dogfood FORECASTING_SET_TARGET_CPA entry. Net: ~10 LOC source + ~30 LOC tests. **4ª sprint consecutiva sem novos bugs no smoke** (3b.7 + P2 + 3b.8 + 3b.9 — stabilization compounding mantido). |
| Sprint 3b.10 — test_rate_limit relocate (Sprint P2 finding cleanup) | ✅ 2026-05-12 | 3 commits ([e9ac216..7948255](https://github.com/BadWolf1509/v4-ads-mcp/compare/4af0e99..7948255)); zero novos MCP tools (count stays at 39); zero source code change (move-only). **Sprint P2 finding fechado:** `tests/unit/test_rate_limit.py` → `tests/integration/test_rate_limit.py` via `git mv` (history preservada, 98% rename similarity após cleanup de 2 unused imports). **Coverage improvement descoberto durante design:** os 6 testes estavam DEAD em CI (step 1 excluia via marker, step 2 não escaneava `tests/unit/`). Post-move, step 2 picks them up — `rate_limit` governance code exercitado em CI pela 1ª vez. `scripts/_runner.py` comment atualizado pra refletir new state (filter ainda útil pra defensive "marker é authoritative signal"). 5ª sprint consecutiva sem novos bugs no smoke. |
| Sprint 3b.11 — process cleanup bundle (lesson learned + orphan delete) | ✅ 2026-05-12 | 2 commits ([aa7643c..2ee5f39](https://github.com/BadWolf1509/v4-ads-mcp/compare/5fa1fd3..2ee5f39)); zero novos MCP tools (count stays at 39); zero source code change (docs + dead code removal). **Process cleanup bundle de 2 items:** (1) CLAUDE.md nova subsection "Pre-flight test convention (post-Sprint 3b.8)" documentando bug class recorrente (pre-flight call to shared helper missed by existing integration test mocks — bit Sprint 3b.5 commit `3c23fc5` apply_audience + Sprint 3b.8 commit `5fa1fd3` update_keyword_bid/update_ad_group_bid). Pattern + why + mitigation explicitos. "Don't do" bullet expandido (3b.5 → 3b.5/3b.8). (2) `tests/integration/test_update_ad_status.py` deleted via `git rm` — file tinha 3 orphan fixtures desde Sprint 3b.5 commit `3c23fc5` deletar único test do file (P2 Task 1 spawn-task closed). Net: +28 LOC docs / -47 LOC dead code = -19 LOC. **6ª sprint consecutiva sem novos bugs no smoke.** |
| Sprint 3b.12 — `get_my_rate_limit_status` utility tool | ✅ 2026-05-12 | 2 commits ([c00712e..a53e653](https://github.com/BadWolf1509/v4-ads-mcp/compare/9fc99f4..a53e653)); **1 new MCP tool (count 39 → 40, primeira utility shipada):** thin wrapper read-only around existing `src.governance.rate_limit.get_today_usage()`. Zero params (quota é per dev token V4, atravessa todas as 23 contas). Response shape B (pragmatic): `used`, `limit`, `remaining`, `pct`, `pct_display` (`"8.2%"` formatted), `date_utc`, `warning_threshold_pct`. Hardcoded `DAILY_QUOTA_BASIC` (15k) com inline comment documentando switch pra `DAILY_QUOTA_STANDARD` (1M) post-Standard Access approval (case `26521440673`, ainda pendente). Audit pattern consistente com `list_my_accounts` (account-wide read, audit_log.record). 3 unit tests cobrem zero/partial/high usage paths. Tool allowlist em `test_tools_schemas.py` atualizada (esperado ao adicionar novo tool — mecânico). ~80 LOC source + ~120 LOC tests. **7ª sprint consecutiva sem novos bugs no smoke.** |
| Sprint 3b.13 — `get_my_audit_log` utility tool | ✅ 2026-05-12 | 2 commits ([199cbb8..f625996](https://github.com/BadWolf1509/v4-ads-mcp/compare/7516f92..f625996)); **1 new MCP tool (count 40 → 41, segunda utility shipada):** paginated history das próprias operações do gestor via MCP (mutations + audited reads), scoped automaticamente ao gestor logado. 4 optional filter params: `days` (1-30, default 7), `limit` (1-1000, default 100), `customer_id` (per-account filter), `action_type` (`mutate`/`read`/`auth`/`system`/`all` default `all`). **New repo function** `audit_log.list_for_manager()` em `src/db/repositories/audit_log.py` mirrors `export_csv_rows` structure mas retorna JSON list (vs CSV stream). Omits `params_summary` jsonb pra compact response; gestor pode usar `get_by_id` existente se precisar detail. Response shape: `manager_id`, `filters`, `count`, `events[]` (10 columns: id, occurred_at ISO, operation, customer_id, action_type, target_count, status, duration_ms, google_request_id, error_message). Audit pattern consistente com utility predecessor. 4 unit tests cobrem defaults + customer_id filter + action_type filter + empty result. ~130 LOC source + ~150 LOC tests. **8ª sprint consecutiva sem novos bugs no smoke.** |
| Sprint 3b.14 — `create_ad_group` (primeiro create-pattern do MCP) | ✅ 2026-05-12 | 5 commits ([ef9868a..6d914ac](https://github.com/BadWolf1509/v4-ads-mcp/compare/ebe3262..6d914ac)) + smoke + Sprint 3b.14.1 fix; **1 new MCP tool (count 41 → 42, primeiro create shipado):** batch creation de 1-10 ad_groups por chamada, always-CONFIRM. Schema + pre-flight rejecting missing/REMOVED/channel-mismatch/F12-cpc_bid combinations. New builder + helper + 14 unit/integration tests. **Smoke 5/6 PASS em Nutry sandbox** (T1+T2+T3+T4+T5 ok; T6 revealed spec assumption wrong — F14). **3 findings:** F13 UX (response doesn't return new ad_group_id, gestor needs separate GAQL — fix candidate next sprint), F14 (Google ENFORCES name uniqueness within campaign — tool description claim "NAO idempotente" incorrect, actual behavior is safer), F15 critical (registry auto-discovery — see Sprint 3b.14.1). 4 test ad_groups paused em sandbox para cleanup futura via UI. |
| Sprint 3b.14.1 — registry auto-discovery (critical fix) | ✅ 2026-05-12 | 1 commit ([14d3d7b](https://github.com/BadWolf1509/v4-ads-mcp/commit/14d3d7b)); production revision `v4-ads-mcp-00142-dzf`. **CRITICAL BUG fixed:** `import_all_tools()` em `_registry.py` era manual hardcoded list que **lagged behind actual files**. Sprints 3b.12 + 3b.13 + 3b.14 shipparam 3 new tools (`get_my_rate_limit_status`, `get_my_audit_log`, `create_ad_group`) mas **esqueceram** atualizar a lista → 3 tools DEAD em produção apesar de "shipped" + CI verde. **Tests passed via pytest import side effects** (decorator `@register_tool` runs ao importar tool module from test file → `_TOOLS` populated; production `import_all_tools()` runs WITHOUT those side effects → tools missing). Discovered durante smoke setup do 3b.14 — `create_ad_group` não aparecia no MCP client tool list post-reconnect. **Fix:** replace manual list com `pkgutil.iter_modules` auto-discovery em `_registry.py` (self-maintaining — new tools auto-registered just by file existing). Defense-in-depth: new test `test_registered_tool_count_matches_files_on_disk` (1:1 count match). 3 tools now properly registered em produção. **Lesson:** test side effects can mask production bugs; tests must verify production behavior, not just internal state. |
| Sprint 3b.15 — F13 + F14 bundle (3b.14 smoke findings) | ✅ 2026-05-12 | 3 commits ([c410fc7..8c76721](https://github.com/BadWolf1509/v4-ads-mcp/compare/83442f8..8c76721)); zero new MCP tools (count stays 42). **F13 (cross-cutting, high value):** `run_mutation` now extracts `resource_names` from MutateGoogleAdsResponse via `WhichOneof("response")` + `getattr` for `.resource_name`. Returns `list[str \| None]` (None for failed ops em partial_failure). `apply_change` propagates em response. **ALL future creates auto-inherit benefit** (create_rsa, create_campaign, etc) — gestor no longer needs separate GAQL query to find new entity IDs. Solves F13 UX gap descoberto em Sprint 3b.14 smoke T1. **F14 (description correction):** `create_ad_group.py` description updated — Google ENFORCES name uniqueness within campaign (smoke T6 revealed spec assumption wrong). Idempotency-by-error effective via Google server-side check. 3 new unit tests (extraction: happy/mixed_failure/missing_field) + 1 apply_change extension + 1 integration assertion. ~30 LOC source + ~125 LOC tests. **Additive backward-compatible change** — existing callers ignore new key. Bonus: ruff version drift caught (local 0.14.10 vs CI 0.15.x) — fix shipped em second commit. |
| Sprint 3b.16 — `create_rsa` (segundo create-pattern do MCP) | ✅ 2026-05-12 | 6 commits ([044ea69..1c5ec69](https://github.com/BadWolf1509/v4-ads-mcp/compare/24e4f8e..1c5ec69)); **1 new MCP tool (count 42 → 43):** batch creation de 1-5 Responsive Search Ads (RSAs) por chamada em existing ad_groups. Always-CONFIRM. JSONSchema enforces Google's structural rules declaratively (headlines 3-15 × 30 chars, descriptions 2-4 × 90 chars, final_urls 1+, path1/path2 maxLength 15). Pre-flight helper `validate_parent_ad_groups_for_rsa_create` em `_common.py` (ad_group existence + status != REMOVED + parent campaign channel ∈ {SEARCH, SEARCH_PARTNERS}). **Bonus fixture extension:** ProtoFieldCapture ganhou `_RepeatedCapture` + `field_count(path)` helper (reusable em future creates). 15 tests totais. **Smoke 5/5 PASS em Nutry sandbox (post F16 fix):** F13 production validation SUCCESS — `resource_names` field flows from Google API real response through apply_change. **F16 critical bug found em T1 smoke + fixed inline (Sprint 3b.16.1, commit `1c5ec69`, production rev `v4-ads-mcp-00149-jjz`):** builder usava `rsa.headlines.add()` (raw protobuf API) — tests passaram com ProtoFieldCapture mock mas proto-plus em real SDK só tem `.append(typed_instance)`. Fixed builder pra usar `client.get_type("AdTextAsset")` + `rsa.headlines.append(h)` pattern. **7ª variante da mock-fidelity bug family** (A1/A3/A4/A5/F11/F12/F16). 4 test RSAs criadas em Nutry sandbox (todas PAUSED, parent ad_groups PAUSED — zero serving risk). |
| Sprint 3b.17 — F16 cleanup (mock fidelity) | ✅ 2026-05-13 | 1 commit ([c9b37ea](https://github.com/BadWolf1509/v4-ads-mcp/commit/c9b37ea)); zero new MCP tools (count stays 43); zero source code change (test fixture only). **Closes F16 lesson from Sprint 3b.16.1:** removed `.add()` mock from `ProtoFieldCapture._RepeatedCapture` + `_SubCapture` — proto-plus repeated message fields don't have `.add()`, only `.append(typed_instance)`. Mock surface now mirrors proto-plus reality. Future builders that regress to `.add()` will AttributeError loudly at test time instead of production. Grep verified: zero callers em src/ or tests/ use `.add()` on repeated proto fields post-F16 fix. Net: -15 LOC fixture, 6 builder tests (test_create_rsa_builder.py) continue passing — they use `.append()` since F16 fix. **Defense-in-depth against bug family 7th variant.** |
| Sprint 3b.18 — `update_rsa` (completes RSA CRUD parcial) | ✅ 2026-05-13 | 5 commits ([9a7e877..8f6eb84](https://github.com/BadWolf1509/v4-ads-mcp/compare/551408a..8f6eb84)); smoke runbook signed-off em conta real ([`phase-3b-18-bootstrap.md`](docs/operacao/phase-3b-18-bootstrap.md)) — production revision `v4-ads-mcp-00153-hkl`. **1 new MCP tool (count 43 → 44):** modify existing RSAs via `AdService.mutate_ads` (not `AdGroupAdService` like create_rsa). Always-CONFIRM. Batch up to 5 updates. Each update: ad_id (required) + optional headlines/descriptions/final_urls/path1/path2 — **anyOf** constraint enforces ≥1 mutable field provided. Provided field lists REPLACE existing (proto-plus + field_mask semantics). **First builder em codebase usando `MutateOperation.ad_operation`** (top-level Ad mutation, not via AdGroupAd). Pre-flight `validate_existing_rsas_for_update` em `_common.py`: ad existence + type == RESPONSIVE_SEARCH_AD + parent ad_group status != REMOVED + campaign channel ∈ {SEARCH, SEARCH_PARTNERS}. Builder uses dynamic `update_mask` derived from set fields (only touches what gestor specified). **ProtoFieldCapture extended:** added `AdService.ad_path(cid, ad_id)` mock support (reusable em futuros Ad-level mutations). 15 tests totais (5 helper + 6 ProtoFieldCapture builder + 3 tool + 1 integration). ~290 LOC source + ~520 LOC tests + ~90 LOC smoke runbook. **Nutry smoke 5/5 PASS first try, zero findings.** Highlights: (1) **F13 validated 2ª vez in-prod via `ad_operation`** (Sprint 3b.15 cross-cutting feature; 1ª foi Sprint 3b.16 `create_rsa` via `ad_group_ad_operation`) — auto-inherited via `run_mutation`, zero new code; (2) **proto-plus field_mask precision validated triplo** — T4 single-field partial (path1 changes, path2/headlines/descriptions UNCHANGED), T5 batch cross-update (descriptions em ad1 só, final_urls em ad2 só), `update_mask` derivado dinamicamente funciona com Google API; (3) **9ª sprint consecutiva sem novos bugs no smoke** — mock-fidelity lesson honrada empiricamente (builder usou `client.get_type("AdTextAsset") + .append()` desde initial draft, sem `.add()` regression; Sprint 3b.17 fixture cleanup atuou como defense-in-depth). 4 test RSAs continuam PAUSED em sandbox (zero serving risk). |
| Sprint 3b.19A — `create_conversion_action` (terceiro create-pattern; resolve UX-1 setup gap) | ✅ 2026-05-13 | 7 commits ([2bc6eaf..(F18-fix)](https://github.com/BadWolf1509/v4-ads-mcp/compare/ac5099b..main)); smoke runbook signed-off em conta real ([`phase-3b-19A-bootstrap.md`](docs/operacao/phase-3b-19A-bootstrap.md)) — production revision `v4-ads-mcp-00157-ssp` (smoke run; F18 fix bumpa próximo rev). **1 new MCP tool (count 44 → 45):** cria 1-5 ConversionActions customer-level via `ConversionActionService.mutate_conversion_actions`. Always-CONFIRM. Schema: name (1-100) + category (14 V4-focused values post F17+F18 — was 18 inicialmente) + type (WEBPAGE/UPLOAD_CLICKS/UPLOAD_CALLS) + value_settings opcional + counting_type opcional. Pre-flight `validate_conversion_action_create` em `_common.py` (single GAQL batch sobre `conversion_action` table — name uniqueness). **First builder em codebase usando `MutateOperation.conversion_action_operation`** (terceiro resource type touched: AdGroup/3b.14 + Ad/3b.16+18 + ConversionAction agora). V4 invariants hardcoded: status=ENABLED on create (diferente de RSAs/ad_groups PAUSED default), currency_code=BRL, counting_type=ONE_PER_CLICK default. **ProtoFieldCapture extended:** `ConversionActionService.conversion_action_path` mock + 4 enum mocks via `_EnumDict` helper (reusable em futuros customer-level mutates). Context7 validated `ca.type_` (underscore) + `default_value` decimal (no micros) + `conversion_action_path` signature BEFORE writing builder (Sprint 3b.16 lesson honored). 17 tests totais (5 helper + 6 builder + 5 tool + 1 integration). ~290 LOC source + ~520 LOC tests + ~95 LOC smoke runbook. **Out of scope v0:** tag generation (WEBPAGE manual install via Google Ads UI), offline conversion import (Standard Access blocked), attribution/lookback override, status PAUSED on create, remove/update tools, niche categories/types. **Nutry smoke 5/5 PASS com 2 findings reais documentados:** (F17) `LEAD` removido do google-ads SDK v20 — design assumiu LEAD válido com base em legacy docs; context7 cobriu só exemplo de `type_`, não validou cada enum value do whitelist. Fix: removido do schema, replacement `SUBMIT_LEAD_FORM`. (F18) Lead lifecycle categorias `IMPORTED_LEAD`, `QUALIFIED_LEAD`, `CONVERTED_LEAD` são system-managed pelo Google's lead workflow — válidas no SDK enum mas rejeitadas com `ENUM_VALUE_NOT_PERMITTED`/`INVALID_VALUE` em create-via-API. Empirical probes isolaram pattern. Fix: removidas do schema (17 → 14 values final). F17+F18 são 8ª-9ª variantes da silent-acceptance bug family, ambos design gaps. **F13 cross-cutting validado 3ª vez in-prod** via `conversion_action_operation` — auto-inherited via run_mutation, zero novo código. **Lição:** schema whitelists devem incluir per-value empirical validation step OU live API check no startup. **Real biz value:** 3 ConversionActions úteis criadas em Nutry sandbox (SUBMIT_LEAD_FORM/WEBPAGE WhatsApp lead, PURCHASE/WEBPAGE Compra R$50, PHONE_CALL_LEAD/UPLOAD_CALLS Call Lead). |

**45 MCP tools** registered: 23 read + 21 mutations + `apply_change`.
**15 web pages** in production with Hybrid Editorial+Operational identity (FE Redesign v2).
**Q8 invite-only allowlist** active — only `@v4company.com` emails pre-invited via `/admin/invites` can complete OAuth.
**`BOOTSTRAP_ADMIN_EMAILS`** env on Cloud Run = `wellinton.ribeiro@v4company.com` (dormant since managers table is populated).

### Pending / future

- **Modelo operacional: solo dogfood com contas reais** — `wellinton.ribeiro@v4company.com` é o único gestor de tráfego usando o MCP por enquanto. Sinal de produto vem de uso direto + smoke runbook em conta real (modelo [`phase-3b-1-bootstrap.md`](docs/operacao/phase-3b-1-bootstrap.md), que pegou 2 bugs reais no Sprint 3b.1). Lucas Soares (`lucassoares@v4company.com`) tem OAuth + MCP session ativos mas dormentes — gestor real V4, sem expectativa de uso por enquanto. Multi-gestor + multi-tenancy ficam adiados.
- **Standard Access do Google Ads** — case `26521440673` resubmetido em 2026-05-11 com design doc atualizado em PDF (a submissão original de 2026-05-05 não retornou veredicto na janela estimada de 3 dias). Aguardar nova janela de ~3 dias úteis. Quando aprovar, quota 15k → 1M+ ops/dia
- **Phase 3b restante** — mutation tools faltantes (`create_campaign`, `create_asset`, `link_assets`, `upload_customer_match_list`, `import_offline_conversions`) — ~~`create_ad_group`~~ ✅ 3b.14, ~~`create_rsa`~~ ✅ 3b.16, ~~`update_rsa`~~ ✅ 3b.18, ~~`create_conversion_action`~~ ✅ 3b.19A; utilities ~~`get_my_rate_limit_status`~~ ✅ 3b.12, ~~`get_my_audit_log`~~ ✅ 3b.13. `update_keyword_match_type` descartado por API immutability (Sprint 3b.3 finding). `remove_audience` shipado em Sprint 3b.6 — `remove_keyword`/`remove_campaign`/`remove_ad`/`remove_ad_group` ainda pendentes se demanda real surgir (gestor pode usar Google Ads UI por enquanto). UX fixes bundle (UX-1 ROAS placeholder warning + UX-2/UX-3 enum decode) shipados em Sprint 3b.7. Pre-push integration sweep (lesson 3b.5) shipado em Sprint P2. F12 manual CPC bid pre-flight (P3 dogfood finding) shipado em Sprint 3b.8. F7 type_pt null fallback (P3 dogfood finding) shipado em Sprint 3b.9. test_rate_limit.py relocate (Sprint P2 finding) shipado em Sprint 3b.10. Process cleanup bundle (lesson learned + orphan fixtures) shipado em Sprint 3b.11. Primeira utility tool `get_my_rate_limit_status` shipada em Sprint 3b.12. Segunda utility tool `get_my_audit_log` shipada em Sprint 3b.13. Primeiro create-pattern `create_ad_group` shipado em Sprint 3b.14 (smoke 5/6 PASS). F13 + F14 fixes do 3b.14 smoke shipados em Sprint 3b.15 (resource_names cross-cutting). Segundo create `create_rsa` shipado em Sprint 3b.16 (15 tests + smoke 5/5 PASS post F16 fix). F16 cleanup (mock fidelity) shipado em Sprint 3b.17. `update_rsa` shipado em Sprint 3b.18 (smoke 5/5 PASS, zero findings; F13 validated 2ª vez via `ad_operation`; 9ª sprint consecutiva sem novos bugs). `create_conversion_action` shipado em Sprint 3b.19A (terceiro create-pattern; primeiro tracking setup tool; resolve gap UX-1 primeiro passo; smoke 5/5 PASS com 2 findings reais F17+F18 documentados — categorias system-managed e LEAD removed do SDK; 10ª sprint streak break, mas findings são design gaps, não regressions de pattern). **Sprint 3b.19B candidatos** (sem dependência de Standard Access): retrofit ProtoFieldCapture nos builders pré-Sprint 3b.5 (negatives, keywords, ad_groups — YAGNI candidate, mas fixture extension de 3b.16+3b.18 facilitou retrofit), dogfood expansion em outras contas, ou completing tracking setup tools (import_offline_conversions blocked por Standard Access; create_*_conversion_value_rule alternative). **Sprints 3b.20+** (alto quota — bloqueado parcialmente por Standard Access): `create_campaign` + assets. Decisão de próximo sprint depende de sinal do dogfood + veredicto do Standard Access (case `26521440673`, esperado ~14/maio).
- **Sub-projetos 2-4 (multi-tenancy)** — `unidades` table + 3-tier RBAC, multi-MCC OAuth, migração single→multi. Adiado indefinidamente (sem demanda — modelo solo é o estado atual e Lucas não vai operar).
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
python scripts/check_pre_push.py
```

Roda em sequência (fail-fast): ruff check → ruff format check → mypy → pytest
unit (com filter `-m "not integration"`) → pytest non-DB integration. ~30s.
Sem Docker.

Opt-in full sweep (requer Docker Desktop rodando):

```bash
python scripts/check_pre_push_full.py
```

Adiciona um 6º step (`pytest tests/integration -m integration`) com
testcontainers. ~60-90s. Use antes de push quando mudou mutate flow ou
qualquer caminho exercitado por DB integration tests. Sem Docker, exit 2
com hint clara — não silenciosamente skipa.

Se algum step falhar, corrija e re-rode. Comandos individuais listados em
`scripts/_runner.py` para debug isolado.

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

### Mutate builder test convention (post-Sprint 3b.5)

New mutate builder tests MUST use `tests/unit/fixtures/proto_capture.py::make_capture_client`
instead of MagicMock when asserting on proto field assignments. MagicMock accepts any
attribute set silently, masking bugs like Sprint 3b.4 A4 (Google override of `negative=True`
on CampaignCriterion user_list — shipped the bug because the test couldn't verify the
field was actually being set).

Pattern:

```python
from tests.unit.fixtures.proto_capture import make_capture_client

def test_builder_sets_critical_field():
    client = make_capture_client()
    ops = build_my_thing(client, customer_id, payload)
    op = ops[0]
    assert op.field("ad_group_criterion_operation.create.negative") is True
    assert op.has("ad_group_criterion_operation.create.bid_modifier") is False
```

Retrofitting existing builder tests (negatives, keywords, ad_groups) is optional and
deferred — only the audiences builder has been retrofitted (Sprint 3b.5). The existing
builders empirically work in production, so retrofit is a YAGNI candidate unless a specific
bug is suspected.

### Pre-flight test convention (post-Sprint 3b.8)

When adding a pre-flight call to an existing mutate tool — especially one that
invokes `run_report` via a shared helper in `src/google_ads/queries/_common.py` —
the existing integration tests MUST mock the new helper. Pattern:

```python
with patch(
    "src.mcp.tools.<your_tool>.<helper_name>",
    AsyncMock(return_value=None),  # pre-flight passes
):
    ...
```

Why this matters: the helper's `run_report` import lives in `_common.py`
namespace, NOT the tool's namespace. Existing test patches targeting
`src.mcp.tools.<tool>.run_report` do NOT cover the pre-flight call site.

Bug class recorrente — appeared in Sprint 3b.5 (commit `3c23fc5`,
`apply_audience` pre-flight) and Sprint 3b.8 (commit `5fa1fd3`,
`update_keyword_bid` + `update_ad_group_bid` pre-flight). Both shipped to
main + caught by CI (DB integration step) but missed by local
`check_pre_push.py` (fast script doesn't run DB integration tests).

Mitigation: before pushing a pre-flight change, run
`python scripts/check_pre_push_full.py` (Docker required) to catch this
class locally. Alternative: rely on CI as catch-all + plan for 1 follow-up
fix commit if CI red.

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

- Don't push to main without running `python scripts/check_pre_push.py` first. CI catches lint/type/test failures but it wastes a deploy cycle and may trigger rollback if integration tests reveal a bug. Lesson Sprint 3b.5/3b.8: pre-flight additions to existing mutate tools require the OPT-IN full sweep (`check_pre_push_full.py`, Docker required) — fast script doesn't run DB integration tests where pre-flight mock gaps surface.
- Don't add new dependencies without checking the project's "no build step" principle. We have Tailwind via CDN, HTMX via CDN — no node, no Vite, no React.
- Don't modify production data via raw SQL on Supabase without extreme care. Use Python script with explicit `BEGIN/COMMIT` and idempotency check.
- Don't skip the `superpowers:brainstorming` skill before creative work even if the request seems "simple."
- Don't dispatch parallel implementer subagents for sequential tasks (only one writer at a time on the codebase).
