# Findings Catalog — V4 Ads MCP

> **Purpose:** Central index of all bugs/findings/lessons learned across sprints. Avoids re-introducing same bug class in future sprints. Cross-referenced from CLAUDE.md `Conventions` and individual smoke runbooks.
>
> **Maintainer note:** Add a new entry here whenever a finding is documented in a smoke runbook. Keep entries scannable — link to runbook for detail.
>
> **Last updated:** 2026-05-18 (Sprint 3b.24 signoff)

---

## How to use this catalog

1. **Before designing new mutate tools:** scan "Silent-acceptance design gap" family (A1, A3-A5, F11, F12, F16, F17-F19, F25, F27, F30, F33-F35, F37) to anticipate Google API contract gaps the SDK doesn't expose.
2. **Before writing pre-flight helpers:** scan "Pre-flight + test convention" family to avoid mock-target mistakes.
3. **Before shipping a smoke runbook:** ensure per-value empirical probe step exists for new enum whitelists (Sprint 3b.19A.1 convention).
4. **Bug suspected in production:** grep this file for symptoms first; may be a known class with documented fix.

---

## Bug class 1: Silent-acceptance design gap (Google API contract gaps via SDK ambiguity)

**Pattern:** SDK descriptor (proto enum, field name) accepts a value that Google API runtime rejects, OR Google silently does something different than the SDK suggests. Caught by smoke `apply` step (dry_run + builder tests pass; only real API call reveals).

**Mitigation convention:** Sprint 3b.19A.1 — per-value empirical probe step in smoke runbook (Sprint 3b.24 added per-strategy probe). For each enum whitelist value, create a minimal real entity with that value.

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **A1** | MED | 3b.3 | not-a-bug | Google silent-dedupes duplicate keyword adds (vs spec assumption `CRITERION_EXISTS` error). Idempotency works via Google's behavior, not our `_classify_partial` mapping. [phase-3b-3-bootstrap.md] |
| **A3** | HIGH | 3b.4 | 3b.5 | Google silent-drops `user_interest` criterion when taxonomy_type incompatible with ad_group channel (VERTICAL_GEO em SEARCH). Returns `applied_count=1` mas criterion não persiste. Fix: pre-flight GAQL taxonomy whitelist (IN_MARKET + AFFINITY only). [phase-3b-4-bootstrap.md] |
| **A4** | HIGH | 3b.4 | 3b.5 + open | Google silently overrides `negative=true` → `false` em CampaignCriterion user_list creates. T3 apply criou criterion como POSITIVE observation, não exclusion. Sprint 3b.5 mitigated via pre-flight rejection do combo `(campaign + exclusion + user_list)` direcionando gestor pra ad_group level. **Real biz mechanism for V4's "-10% CPA via exclusion" playbook ainda pendente investigação** (Sprint 3b.27 candidate). [phase-3b-4-bootstrap.md, phase-3b-5-bootstrap.md] |
| **A5** | HIGH | 3b.6 | 3b.6 | `CampaignCriterion.resource_name` é compound `{campaign_id}~{criterion_id}` (não flat). Builder construía path flat; Google silently aceitou (`applied_count=1`) mas NÃO removia o criterion. Fix: usar SDK path helpers (`campaign_criterion_path`). [phase-3b-6-bootstrap.md] |
| **F11** | LOW | P3 dogfood | 3b.5 | `update_*_status(REMOVED)` passa dry-run mas Google API rejeita REMOVED em `.status.update`. Sprint 3b.5 fix: schema-restrict enum para `["ENABLED", "PAUSED"]`. Remove* tools (Sprint 3b.28 future) precisarão API path diferente. |
| **F12** | MED | P3 dogfood | 3b.8 | Google silently ignora `cpc_bid_micros` em campaigns com auto-bidding strategy (MAX_CONVERSIONS, TARGET_CPA, etc). Pre-flight whitelist `{MANUAL_CPC, ENHANCED_CPC}` em `update_keyword_bid` + `update_ad_group_bid`. |
| **F16** | HIGH | 3b.16 | 3b.16.1 | RSA builder usava `rsa.headlines.add()` (raw protobuf API) — tests passaram com ProtoFieldCapture mock mas proto-plus em real SDK só tem `.append(typed_instance)`. Mock fidelity gap. [phase-3b-16-bootstrap.md] |
| **F17** | HIGH | 3b.19A | 3b.19A | `LEAD` removido do google-ads SDK v20 — design assumiu legacy docs. Replacement = `SUBMIT_LEAD_FORM`. [phase-3b-19A-bootstrap.md] |
| **F18** | HIGH | 3b.19A | 3b.19A | Lead lifecycle categorias `IMPORTED_LEAD`/`QUALIFIED_LEAD`/`CONVERTED_LEAD` são system-managed (Google's lead workflow), rejeitadas em create-via-API. [phase-3b-19A-bootstrap.md] |
| **F19** | HIGH | 3b.19A.1 | 3b.19A.1 | `DOWNLOAD` ConversionAction rejected em WEBPAGE + UPLOAD_CLICKS types — provável require `GOOGLE_PLAY_DOWNLOAD` (app-install niche). [phase-3b-19A-bootstrap.md] |
| **F25** | HIGH | 3b.19B | 3b.22 | `NO_CONDITION` em ConversionValueRule só é permitido em Store Visits/Sales RuleSets (STORE out of scope v0). Schema fix: removed from `condition_type` enum. [phase-3b-19B-bootstrap.md, phase-3b-22-bootstrap.md] |
| **F27** | HIGH | 3b.19B | 3b.22 | `conversion_action_categories` filter só aceita `[]`/`[STORE_VISIT]`/`[STORE_SALE]` — semantically different from `ConversionAction.category` field. 13-cat V4 whitelist herdada de 3b.19A era inválida. Schema fix: removed field entirely. [phase-3b-19B-bootstrap.md, phase-3b-22-bootstrap.md] |
| **F30** | HIGH | 3b.24 | 3b.24.1 (attempt) + 3b.24.4 (final) | Bidding strategy oneof not initialized — bare `campaign.maximize_conversions` access em proto-plus NÃO inicializa oneof. Fix: for scalar-bearing strategies use bare access (`campaign.X.field = Y` auto-inits); for no-scalar strategies (MANUAL_CPC, etc) explicit assignment `campaign.X = client.get_type("X")`. [phase-3b-24-bootstrap.md] |
| **F33** | HIGH | 3b.24.3 | 3b.24.4 | `client.get_type("X")()` invalid — SDK returns INSTANCE not class, can't call `()` on instance. TypeError. F33 = reversal of wrong F30 attempt. [phase-3b-24-bootstrap.md] |
| **F34** | HIGH | 3b.24 | 3b.24.4 | `campaign.contains_eu_political_advertising` REQUIRED on Campaign create (Google EU compliance, May 2024+). V4 BR-invariant: hardcoded `DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING`. [phase-3b-24-bootstrap.md] |
| **F35** | MED | 3b.24 | 3b.24.4 | `manual_cpc.enhanced_cpc_enabled` deprecated by Google — `OPERATION_NOT_PERMITTED_FOR_CONTEXT` on create. Schema fix: removed `enhanced_cpc` field entirely. [phase-3b-24-bootstrap.md] |
| **F37** | HIGH | 3b.24 | 3b.24.5 | `Campaign.start_date`/`end_date` are NOT valid v24 proto fields — only `start_date_time`/`end_date_time` (YYYYMMDD HH:MM:SS format). Builder converts YYYY-MM-DD schema input. [phase-3b-24-bootstrap.md] |
| **F38** | HIGH | 3b.25 | 3b.25.1 + 3b.25.2 | `StructuredSnippetAsset.header` é STRING (not proto enum) — Google rejects ALL_CAPS values like `"SERVICE_CATALOG"`/`"BRANDS"`. API expects PT-BR display strings (V4 invariant). Sprint 3b.25.1 fix had wrong value `"Catálogo de serviços"` (context7 translation off); Sprint 3b.25.2 corrected to `"Serviços"` (matches Nutry existing asset 259782606115 + T6 re-test PASS). Schema enum now: Bairros, Comodidades, Cursos, Cursos de graduação, Destinos, Estilos, Hotéis em destaque, Marcas, Modelos, Programas, **Serviços**, Tipos, Tipos de cobertura do seguro. Verified empirically: Serviços ✅ + Marcas ✅ (T7); other 11 PT-BR values tentative — sprint candidate 3b.25.x per-value probe. [phase-3b-25-bootstrap.md] |
| **F39** | HIGH | 3b.25 | 3b.25.1 | `PromotionAsset.language_code = "pt"` rejected by Google with "The language code is not supported." BCP 47 says `pt` is valid (less specific) but Google PROMOTION requires region-qualified (`pt-BR`). Discovered in T10+T11 smoke. Fix: builder line `promo.language_code = "pt-BR"`. T10 re-test PASS bit-a-bit via GAQL. [phase-3b-25-bootstrap.md] |
| **F40** | HIGH | 3b.25.1 | 3b.25.2 | `PromotionAsset.discount_modifier="NONE"` rejected — Google's `PromotionExtensionDiscountModifierEnum` only has UNSPECIFIED + UP_TO (NOT NONE). Discovered when T11 re-test still failed pós-F39 fix (different root cause). Fix: schema enum `["NONE","UP_TO"]` → `["UP_TO"]`; field moved out of required (optional now — omit for exact discount, UP_TO for "até X% off"); builder only sets if present. T11 re-test PASS pós-fix. [phase-3b-25-bootstrap.md] |

---

## Bug class 2: Schema/serialization gaps (Anthropic API + MCP transport)

**Pattern:** JSON Schema constructs that Anthropic API or MCP client doesn't support.

**Mitigation convention:** see `CLAUDE.md` "No JSON Schema composition keywords" + "Date range conventions" subsections.

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **A2** | LOW | 3b.5 | 3b.5 | GAQL parens bug + REMOVED retrofit gap em 4 status ops. Status ops cap restritos a `["ENABLED", "PAUSED"]`. |
| **F1** | CRIT | dogfood 2026-05-15 | 3b.20 | `date_range` object `{from, to}` rejected — schema sem `type` field fez Claude serializar dict como JSON-stringified literal; `parse_date_range` chamou `.upper()` corrompendo keys. Fix: explicit `type: "string"` + new `start_date`/`end_date` params + defensive JSON parse. [phase-3b-20-bootstrap.md] |
| **F2** | MED | dogfood 2026-05-15 | 3b.20 | `get_search_terms_report.limit` default 500 stourava token cap. Fix: default 500 → 50. [phase-3b-20-bootstrap.md] |
| **F22** | MED | 3b.21 | 3b.23 | `get_negative_keywords_audit` em MO-JP (467 negativas) pós-enrichment retornou 81k chars, excedeu MCP cap. Fix: `limit` param default 100. [phase-3b-21-bootstrap.md, phase-3b-23-bootstrap.md] |
| **F26** | MED | 3b.19B | 3b.22 doc | Google limita 1 RuleSet CUSTOMER-level por conta (undocumented constraint). Doc fix em tool description, sem pre-flight (option (a) — let Google's error surface). |
| **F28** | LOW | 3b.23 | not-fixable | MCP client schema cache propagation lag pós-deploy: client cache não auto-refresh quando new tool/param shipped. Workaround: restart Claude Code session. Characteristic do MCP transport. |

---

## Bug class 3: Pre-flight + test convention (mock target mistakes)

**Pattern:** Adding a pre-flight call to an existing mutate tool — existing integration tests fail to mock the new helper because helper's `run_report` import lives in `_common.py` namespace (not tool's). Slips local fast pre-push gate but caught by CI DB integration step.

**Mitigation convention:** see `CLAUDE.md` "Pre-flight test convention (post-Sprint 3b.8)" subsection.

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **F14** | LOW | 3b.14 | 3b.15 doc | `create_ad_group` description claimed "NÃO idempotente" but Google ENFORCES name uniqueness within campaign. Idempotency-by-error effective via Google server-side check. [phase-3b-14-bootstrap.md] |
| **F15** | CRIT | 3b.14 | 3b.14.1 | `import_all_tools()` em `_registry.py` era manual hardcoded list — Sprints 3b.12+13+14 shipparam 3 new tools mas esqueceram atualizar lista → tools DEAD em prod apesar de tests passing (pytest import side effects masked). Fix: `pkgutil.iter_modules` auto-discovery. |

---

## Bug class 4: UX / dogfood ergonomics

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **UX-1** | LOW | 3b.6/3b.7 | 3b.7 | `conversions_value == conversions` (1:1 ratio) sinal de placeholder tracking; ROAS misleading. Helper `value_proxy_warning` em `get_account_overview` + `get_funnel_metrics`. V4 accounts default a 1:1 tracking (out-of-MCP-scope finding). |
| **UX-2** | LOW | 3b.6/3b.7 | 3b.7 | proto-plus v20 repr regression — `str(enum).split(".")[-1]` retornava `"2"` em vez de `"ENABLED"`. Fix: `.name` access em 22 call sites across 10 read tools. |
| **UX-3** | LOW | 3b.6/3b.7 | 3b.7 | Same as UX-2 (same bug, different surface). Found via P1b dogfood. |
| **F7** | LOW | P3 dogfood | 3b.9 | `get_recommendations.type_pt` duplicava `type` quando PT-BR mapping ausente. Fix: null fallback signaling "use type field, no translation available." |
| **F13** | MED | 3b.14 | 3b.15 | `create_*` responses não retornavam new entity resource_names. Fix: extract via `WhichOneof("response")` + `getattr` em `run_mutation`. **Cross-cutting feature** — all future creates auto-inherit. Validated 5+ times in production smokes. |

---

## Bug class 5: Runbook typos (low severity, documentation fixes)

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **F24** | LOW | 3b.19B | 3b.19B doc | Smoke runbook usou `geoTargetConstants/20114` como "São Paulo" — actually British Columbia (Canada). V4 BR pre-flight rejeitou corretamente. Runbook fixed inline. |
| **F29** | LOW | 3b.24 | 3b.24 doc | Runbook usou `geoTargetConstants/20180` como "SP state" — actually Hunan (China). Correct SP state via GAQL lookup = `geoTargetConstants/20106`. V4 BR pre-flight rejeitou corretamente. |
| **F23** | LOW | 3b.21 | known limitation | `get_change_history LAST_30_DAYS` Google rejects "start date too old" — preset hits retention boundary. Workaround: LAST_14_DAYS ou custom start/end com today-29. Existe desde 3b.1. |

---

## Bug class 6: Google constraint (not a code bug, document as known limitation)

| # | Severity | Discovered | Fixed | Summary |
|---|---|---|---|---|
| **F36** | HIGH | 3b.24 | doc-only | `TARGET_CPA` + `TARGET_ROAS` rejeitam em accounts sem conversion data history. Nutry sandbox tem 14+ conversion actions de 3b.19A mas zero real data → reject. Real V4 production accounts (com tracking history) funcionam. Tool description documenta. |

---

## Summary by status

| Status | Count |
|---|---|
| **Fixed** (source code change) | 22 |
| **Doc fix only** (tool description / runbook update) | 5 |
| **Not-a-bug** (Google behavior, expected) | 2 |
| **Known limitation / workaround documented** | 3 |
| **Open** (real fix pending) | 1 (A4 — Customer Match exclusion mechanism for V4 playbook) |

**Total findings tracked:** 33

---

## Cross-reference: Sprint → findings introduced

(Latest 5 sprints — for older sprints see `docs/operacao/sprint-history.md`.)

| Sprint | Findings introduced |
|---|---|
| 3b.20 | F1 (closed), F2 (closed) — both from 2026-05-15 dogfood report |
| 3b.21 | F22 (→ 3b.23), F23 (limitation, existed since 3b.1) |
| 3b.22 | none (closes 3b.19B F25/F27) |
| 3b.23 | F28 (MCP cache lag, not-fixable) |
| 3b.24 | F29 (doc), F30 (→ 3b.24.4), F32 (→ 3b.24.2), F33 (→ 3b.24.4), F34 (→ 3b.24.4), F35 (→ 3b.24.4), F36 (Google constraint), F37 (→ 3b.24.5) |

---

## Lessons reinforced

1. **Per-value empirical probe** (Sprint 3b.19A.1 convention) is essential for ANY new mutate tool with enum whitelists. Without it, design gaps reach production. **Without exception, every "design-gap-via-SDK-ambiguity" finding was caught by per-value probe in smoke.**
2. **Mock fidelity matters** (F16 lesson) — ProtoFieldCapture mocks must mirror real proto-plus API. `.add()` vs `.append()` distinction caused F16.
3. **Smoke against real account, not pre-flight only.** Builder tests + dry_run validate code path; real API call validates Google's runtime acceptance. The 7 findings from Sprint 3b.24 (F30+F32+F33+F34+F35+F36+F37) were all surfaced ONLY in apply step — not dry_run, not unit tests.
4. **CI catches what fast gate misses** (Sprint 3b.5/3b.8 lesson). Pre-flight test convention requires mocking new helper at TOOL's namespace, not helper's. Local `check_pre_push.py` skips DB integration; full sweep (`check_pre_push_full.py`) catches but requires Docker.
5. **Schema explicit type** (F1 lesson) — every JSON schema property MUST have explicit `type` field; otherwise Claude/MCP client may serialize as string literal causing parsing bugs downstream.
