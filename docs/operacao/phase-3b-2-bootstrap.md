# Phase 3b.2 — manual smoke runbook

**Purpose:** Verify `update_ad_status` + `bulk_pause_by_query` work against real V4 accounts before declaring Sprint 3b.2 done.

**Operator:** wellinton.ribeiro@v4company.com
**Account (low-risk mutation):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1 smoke)
**Account (active reads + apply):** TBD — pick from active accounts (`7862230676` "Mestre da Obra - João Pessoa" was used in 3b.1 smoke)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session) — tools list includes `update_ad_status` + `bulk_pause_by_query`

## Test 1 — `update_ad_status` PAUSE 1 ad (AUTO path)

Pick 1 ad in a paused campaign on `1163862076` via `get_ad_performance(customer_id, status="paused")`.

Call:
```
update_ad_status(customer_id="1163862076", ads=[{ad_group_id, ad_id}], new_status="PAUSED")
```

Expected:
- [ ] `status: "applied"`, `applied_count: 1`, real `google_request_id`
- [ ] Google Ads UI Change History (24h) shows the change under `wellinton.ribeiro@v4company.com`

## Test 2 — `update_ad_status` REMOVE 1 ad (CONFIRM path despite count=1)

Same call but `new_status="REMOVED"`.

Expected:
- [ ] `status: "dry_run"`, `confirmation_token` returned
- [ ] **No mutation yet** (token created in pending_confirmations)
- [ ] Calling `apply_change(token)` consumes the token and executes the removal

Validates the Task 1 retrofit (REMOVED-always-confirm for ad_status).

## Test 3 — `bulk_pause_by_query` keyword target, valid count (1..100)

Pick a campaign on the active account with at least 10 enabled keywords.

Call:
```
bulk_pause_by_query(
  customer_id="<active_account>",
  target_type="keyword",
  filter="ad_group_criterion.status = 'ENABLED' AND campaign.id = <pick_one>",
  date_range="LAST_30_DAYS"
)
```

Expected:
- [ ] `status: "dry_run"`, `confirmation_token` + `preview.sample` with up to 10 entries
- [ ] `preview.total_cost_brl` reasonable
- [ ] Calling `apply_change(token)` returns `status: "applied"` with `applied_count > 0`
- [ ] Google Ads UI Change History shows the bulk pauses

## Test 4 — `bulk_pause_by_query` overflow (>100 matches)

Use a broad filter that hits many entities:
```
bulk_pause_by_query(
  customer_id="<active_account>",
  target_type="keyword",
  filter="ad_group_criterion.status != 'REMOVED'"   # broad
)
```

Expected:
- [ ] `status: "error"`, `matched_count: "100+"`
- [ ] `error` message asks to refine filter (in PT-BR)
- [ ] No `confirmation_token` in response

## Test 5 — `bulk_pause_by_query` no matches

```
bulk_pause_by_query(
  customer_id="<active_account>",
  target_type="keyword",
  filter="ad_group_criterion.status = 'ENABLED' AND metrics.clicks > 99999999"
)
```

Expected:
- [ ] `status: "no_op"`, `matched_count: 0`
- [ ] No `confirmation_token`

## Test 6 — `bulk_pause_by_query` filter injection rejection

```
bulk_pause_by_query(
  customer_id="<account>",
  target_type="keyword",
  filter="ad_group_criterion.status = 'ENABLED'; DROP TABLE users"
)
```

Expected:
- [ ] `status: "error"`, PT-BR error mentioning "ponto-e-virgula" or "';"
- [ ] No query reaches Google Ads API

## Sign-off

- [ ] All 6 tests passed
- [ ] No errors in service logs during the tests
- [ ] `/admin/audit` shows expected rows for `update_ad_status` + `bulk_pause_by_query_dry_run` + `bulk_pause_by_query` (apply) under wellinton.ribeiro@v4company.com
- [ ] Production revision running this sprint's HEAD commit
- [ ] CLAUDE.md updated: move Sprint 3b.2 from "next" to "shipped"

Date completed: ____
