# Phase 3b.3 — manual smoke runbook

**Purpose:** Verify `add_keywords` works against real V4 account before declaring Sprint 3b.3 done.

**Operator:** wellinton.ribeiro@v4company.com
**Account (mutation sandbox):** `1163862076` "Rayane Ribeiro - Nutry" (paused campaigns, zero traffic — same sandbox used in 3b.1 + 3b.2 smokes)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] Reload MCP client (restart Claude Code session) — tools list includes `add_keywords`

## Test 1 — Add 1 KW EXACT in existing ad_group (AUTO path)

Pick an existing ad_group on Nutry (e.g., `183008426336` from previous smokes).

Call:
```
add_keywords(
  customer_id="1163862076",
  ad_group_id="183008426336",
  keywords=[{"text": "claude smoke kw 001", "match_type": "EXACT"}]
)
```

Expected:
- [ ] `status: "applied"`, `applied_count: 1`, real `google_request_id`
- [ ] `added[0].status: "added"`, `added[0].criterion_id` populated (?)
- [ ] Google Ads UI Change History (24h) shows the keyword under `wellinton.ribeiro@v4company.com`

## Test 2 — Add SAME KW (idempotency / already_exists)

Re-run Test 1 with identical text + match_type:

Expected:
- [ ] `status: "applied"`, `applied_count: 0`
- [ ] `added[0].status: "already_exists"` (NOT failed)
- [ ] No new criterion created in Google Ads (verify via Change History — no entry)

## Test 3 — Add 25 KWs (CONFIRM path)

Bulk batch over threshold:

```
add_keywords(
  customer_id="1163862076",
  ad_group_id="183008426336",
  keywords=[{"text": f"claude smoke kw {i:03d}", "match_type": "EXACT"} for i in range(2, 27)]
)
```

Expected:
- [ ] `status: "dry_run"`, `confirmation_token` returned
- [ ] **Do NOT call apply_change** (would create 25 test KWs; skip to avoid clutter)
- [ ] Token expires after 10min naturally

## Test 4 — Schema rejection

Pass invalid match_type:

```
add_keywords(
  customer_id="1163862076",
  ad_group_id="183008426336",
  keywords=[{"text": "x", "match_type": "REGEX"}]   # invalid
)
```

Expected:
- [ ] Schema rejection at MCP layer (validation error before tool runs)
- [ ] No mutation in Google Ads

## Cleanup

- [ ] Remove the test KW from Test 1: `update_keyword_status(customer_id="1163862076", keywords=[{ad_group_id, criterion_id}], new_status="REMOVED")` — paused campaign, no traffic impact

## Sign-off

- [ ] All 4 tests passed
- [ ] No errors in service logs during the tests
- [ ] `/admin/audit` shows expected `add_keywords` row under wellinton.ribeiro@v4company.com with custom params_summary
- [ ] CLAUDE.md updated: Sprint 3b.3 marked as shipped

Date completed: ____
