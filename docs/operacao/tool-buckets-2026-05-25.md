# Tool Bucket Classification — 2026-05-25 (Sprint 3b.39)

**Source:** audit_log query uses_30d window 2026-04-25→2026-05-25 + semantic overrides.
**Query date:** 2026-05-25
**Total tools:** 59 (57 Google + 2 Meta)
**Always-loaded:** 22 tools (5 core + 14 warm + 3 semantic exceptions)
**Defer-loading:** 37 tools (16 cold + 21 zombies + misc)

---

## Always-loaded bucket (22 tools)

### Core (≥10 uses/30d — 5 tools)

| Tool | Uses | Justificativa |
|---|---|---|
| get_change_history | 29 | Top 1 — Pareto audit/drift use case |
| create_and_link_assets | 22 | Top 2 — Creative asset builder, high-blast |
| audit_competitor_keywords | 16 | Top 3 — Competitive analysis demand |
| list_my_accounts | 14 | Top 4 — Account discovery, entry point |
| add_negative_keywords | 12 | Top 5 — Exclusion workflow, high-cadence |

### Warm (5-9 uses/30d — 14 tools)

| Tool | Uses | Justificativa |
|---|---|---|
| get_conversion_actions | 9 | Conversion setup audit |
| audit_goal_attribution | 8 | Goal/biddable tracking (split 4+4 ops) |
| create_conversion_action | 8 | New conversion action creation |
| update_keyword_status | 8 | Keyword pause/enable workflow |
| audit_zombie_keywords | 7 | Cleanup audit, 3b.36 smoke |
| apply_audience | 6 | Audience attachment CONFIRM flow |
| audit_quality_score | 6 | Quality Score audit |
| get_recommendations | 6 | Google recommendations review |
| bulk_pause_by_query | 5 | Bulk pause/enable (preview + apply) |
| create_campaign | 5 | Campaign creation, foundational |
| meta_get_account_overview | 5 | Meta entry KPI (semantic exception) |
| remove_audience | 5 | Audience detachment |
| update_ad_group_status | 5 | Ad group pause/enable |
| update_keyword_bid | 5 | Bid adjustment workflow |

### Semantic exceptions (3 tools forced always-loaded)

| Tool | Reason |
|---|---|
| detect_drift | 3b.33 shipped 2026-05-20; 60-day grace period (discovery window) |
| meta_list_my_ad_accounts | OAuth entry point, must discover accounts on login |
| meta_get_account_overview | Meta platform overview, strategic KPI (5 uses already warm threshold) |

---

## Defer-loading bucket (37 tools)

### Cold (1-4 uses/30d — 16 tools)

| Tool | Uses | Justificativa |
|---|---|---|
| audit_orphan_smart_actions | 4 | 3b.37 recent, orphan audit |
| remove_negative_keywords | 4 | Negative removal, maintenance |
| update_ad_status | 4 | Ad pause/enable, routine |
| add_keywords | 3 | Keyword add workflow |
| add_negatives_from_search_terms | 3 | Search term exclusion |
| create_conversion_value_rule_set | 3 | Value rule creation, niche |
| create_rsa | 3 | Ad copy creation |
| get_my_audit_log | 3 | Audit log review, occasional |
| update_conversion_action | 3 | Conversion action update, rare |
| update_rsa | 3 | Ad copy update |
| create_ad_group | 2 | Ad group creation |
| update_ad_group_bid | 2 | Bid adjustment, cold path |
| update_campaign_budget | 2 | Budget change, sensitive |
| update_campaign_status | 2 | Campaign pause/enable |
| get_my_rate_limit_status | 1 | Rate limit check, diagnostic |
| import_offline_conversions | 1 | Offline conversion import, 3b.28 |

### Zombies (0 uses/30d — 21 tools)

**Discovery indicators:** No audit_log entries in 30d window. Candidates for tombstone (F3 decision gate) or tool consolidation (Caminho C).

| Tool | Category | Notes |
|---|---|---|
| apply_change | Confirmation | Support tool, called implicitly via CONFIRM flow (not logged as standalone operation) |
| apply_recommendation | Google API | Recommendation apply (low adoption) |
| dismiss_recommendation | Google API | Recommendation dismiss (low adoption) |
| get_account_overview | Performance read | Consolidated in Sprint 3b.20 refactor (zombie design candidate) |
| get_ad_group_performance | Performance read | Consolidated (zombie design candidate) |
| get_ad_performance | Performance read | Consolidated (zombie design candidate) |
| get_audience_performance | Audience audit | Consolidated (zombie design candidate) |
| get_budget_pacing | Performance read | Consolidated (zombie design candidate) |
| get_campaign_performance | Performance read | Consolidated (zombie design candidate) |
| get_device_performance | Performance read | Consolidated (zombie design candidate) |
| get_funnel_metrics | Performance read | Consolidated (zombie design candidate) |
| get_geo_performance | Performance read | Consolidated (zombie design candidate) |
| get_hourly_performance | Performance read | Consolidated (zombie design candidate) |
| get_keyword_performance | Performance read | Consolidated (zombie design candidate) |
| get_negative_keywords_audit | Audit | Consolidated (zombie design candidate) |
| get_search_terms_report | Performance read | Consolidated (zombie design candidate) |
| get_top_keywords_creatives | Performance read | Consolidated (zombie design candidate) |
| list_gaql_resources | Helper | Schema reference tool, low direct usage |
| run_gaql | Escape hatch | Advanced escape hatch, low adoption |
| update_campaign_bidding | Campaign config | Strategy update, low cadence |
| upload_customer_match_list | Customer Match | CRM audience upload, low adoption |
| validate_gaql | Helper | GAQL validation, implicit usage |

**Consolidation candidate (Caminho C):** 13 performance/audit reads could collapse into 2-3 generic tools (e.g., `get_performance_breakdown(level, dimension)`) → reduce tool count 22% (59 → 45-48 range). See [`tool-audit-2026-05-25.md`](tool-audit-2026-05-25.md).

---

## Re-classification schedule

- **Cadence:** Monthly (end of month)
- **Trigger:** New query run; reclassify tools crossing thresholds
- **Promotion rule:** Cold (1-4) or warm (5-9) → Core (≥10) = add to always-loaded
- **Demotion rule:** Core/warm with 0 uses for 60+ days = candidate for review (F3 findings + Caminho C consolidation)
- **Exception review:** Semantic exceptions re-evaluated quarterly (grace periods, entry point status)

---

## Findings summary (Task A)

**Total audit_log operations analyzed:** 43 distinct operation names (59 tool files mapped)
**Mapping notes:**
- `audit_goal_attribution` splits into `audit_goal_attribution_goals` (4 uses) + `audit_goal_attribution_actions` (4 uses) = 8 total
- `bulk_pause_by_query` combines preview (dry_run, 4 uses) + apply (1 use) = 5 total
- Meta OAuth ops logged separately: `meta_oauth_connect`, `meta_oauth_revoke`, `meta_refresh_accounts`, `meta_data_deletion_request`

**Data quality notes:**
- No schema/query errors
- RLS (Row-Level Security) on audit_log allows read by authenticated managers
- Timestamp filter: `occurred_at > NOW() - INTERVAL '30 days'` captures 2026-04-25 00:00:00 UTC → 2026-05-25 00:00:00 UTC

**Notable findings:**
1. **apply_change is invisible:** Confirmation support tool does not generate audit_log.operation entries; counted as "zombie" but is actually support path, not dead code
2. **Performance read consolidation opportunity:** 13 tools (get_*_performance, get_funnel_metrics, etc.) with 0 uses = strong Caminho C consolidation signal
3. **Meta entry points healthy:** Both `meta_list_my_ad_accounts` (0 direct uses, but discovery via OAuth) and `meta_get_account_overview` (5 uses) reach warm tier
4. **Detect_drift grace period justified:** 3b.33 shipped 2026-05-20 (5 days ago), 0 uses expected, 60-day discovery window appropriate
5. **Escape hatch low adoption:** `run_gaql` (0 uses), `validate_gaql` (0 uses), `list_gaql_resources` (0 uses) = advanced paths rarely needed; candidates for deferred loading or docs expansion

---

## References

- [`tool-audit-2026-05-25.md`](tool-audit-2026-05-25.md) — Detailed tool count analysis, zombie list, consolidation blueprint
- [`sprint-history.md`](sprint-history.md) — Sprint 3b.33→3b.37 tool shipping timeline
- `docs/superpowers/specs/2026-05-25-architecture-refactor-design.md` §3 — 3-bucket strategy design
