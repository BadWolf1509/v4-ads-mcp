# Phase 3b.1 — manual smoke runbook

**Purpose:** Verify `add_negatives_from_search_terms` + `get_change_history` work against a real V4 account, before declaring Sprint 3b.1 done.

**Operator:** wellinton.ribeiro@v4company.com
**Account:** TBD (pick a low-traffic test campaign in MCC 6436352492)

## Pre-flight

- [ ] Deploy lands successfully (`gh run watch <id>` shows green Deploy)
- [ ] Service `/health` returns 200
- [ ] `claude mcp list` shows `v4-ads` server connected

## Test 1 — `add_negatives_from_search_terms` happy path

In Claude Desktop, ask:

> "Mostra os search terms de last 30 days da conta XXXXXXXXXX, depois adiciona como negativa (EXACT) os 3 piores em termos de cost/conversion, escopo campaign."

Expected behavior:
- Claude calls `get_search_terms_report(customer_id, "LAST_30_DAYS")`
- Picks 3 terms with cost > 0 and conversions = 0
- Calls `add_negatives_from_search_terms(customer_id, negatives=[3 items, scope=campaign, scope_id=...])`
- Returns `{status:"applied", applied_count: 3, google_request_id:"...", added:[3 items, status:"added"]}`

Verification:
- [ ] Open Google Ads UI -> Change History (last 24h) — the 3 negatives appear under `wellinton.ribeiro@v4company.com`
- [ ] `google_request_id` from response matches the change history entry's request ID
- [ ] Re-run the same call with same 3 terms — response shows `status:"already_exists"` for all 3

## Test 2 — `add_negatives_from_search_terms` idempotency

After Test 1, immediately:

> "Repete o mesmo add que acabamos de fazer."

Expected:
- All 3 items return `status: "already_exists"`
- `applied_count: 0`
- No new entries in Google Ads UI Change History

- [ ] Idempotency confirmed

## Test 3 — `get_change_history` happy path

> "Me mostra o change history dessa conta nos ultimos 3 dias."

Expected:
- Tool returns `period: {from: "...", to: "..."}` covering 3 days
- `rows[].operation` in {CREATE, UPDATE, REMOVE}
- `summary.total_changes` > 0
- The 3 negatives from Test 1 appear in the rows
- `summary.by_user` includes `wellinton.ribeiro@v4company.com`

Verification:
- [ ] Find the negative-creation entries from Test 1 in the rows
- [ ] If account has Auto-Apply Recommendations enabled, check `summary.auto_applied_count > 0`

## Test 4 — `get_change_history` filter precision

> "Me mostra so os UPDATEs em campaigns nos ultimos 7 dias, agrupado por usuario."

Expected:
- Tool calls `get_change_history(resource_types=["CAMPAIGN"], operation_types=["UPDATE"], date_range="LAST_7_DAYS")`
- All returned rows have `resource_type == "CAMPAIGN"` and `operation == "UPDATE"`
- `summary.by_user` is correct grouping

## Test 5 — `get_change_history` 30-day enforcement

> "Me mostra change history dos ultimos 60 dias."

Expected:
- Tool refuses with PT-BR error: "Janela maxima de 30 dias para historico de mudancas"
- OR Claude reframes to LAST_30_DAYS automatically

## Sign-off

- [ ] All 5 tests passed without manual intervention beyond the Claude conversation
- [ ] No errors in service logs during the tests
- [ ] `/admin/audit` shows the corresponding rows under wellinton.ribeiro@v4company.com
- [ ] CLAUDE.md updated: move Sprint 3b.1 from "Pending" to "Shipped"

Date completed: ____
