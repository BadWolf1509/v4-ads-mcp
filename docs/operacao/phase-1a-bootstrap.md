# Phase 1a — Bootstrap runbook

This runbook walks through the first end-to-end onboarding using the CLI
(no panel UI yet). Execute from the project root with venv active.

## Prereqs

- `gcloud` authenticated against the `v4-ads-mcp-prod` project.
- Cloud Run service deployed and healthy (`curl https://<URL>/health`).
- All 10 secrets in Secret Manager populated.

## 1. Fetch DATABASE_URL into env (one-shot)

In Bash (Git Bash or WSL):

```bash
export PATH="/c/Program Files (x86)/Google/Cloud SDK/google-cloud-sdk/bin:$PATH"

export DATABASE_URL=$(gcloud secrets versions access latest --secret=database-url)
export AES_MASTER_KEY=$(gcloud secrets versions access latest --secret=aes-master-key)
export SESSION_SIGNING_KEY=$(gcloud secrets versions access latest --secret=session-signing-key)
export GOOGLE_OAUTH_CLIENT_ID=$(gcloud secrets versions access latest --secret=google-oauth-client-id)
export GOOGLE_OAUTH_CLIENT_SECRET=$(gcloud secrets versions access latest --secret=google-oauth-client-secret)
export GOOGLE_ADS_DEVELOPER_TOKEN=$(gcloud secrets versions access latest --secret=google-ads-developer-token)
export GOOGLE_ADS_LOGIN_CUSTOMER_ID=$(gcloud secrets versions access latest --secret=google-ads-login-customer-id)
export SUPABASE_URL=$(gcloud secrets versions access latest --secret=supabase-url)
export SUPABASE_ANON_KEY=$(gcloud secrets versions access latest --secret=supabase-anon-key)
export SUPABASE_SERVICE_KEY=$(gcloud secrets versions access latest --secret=supabase-service-key)
export APP_ENV=production
```

## 2. Bootstrap the first admin

```bash
./.venv/Scripts/python.exe -m src.scripts.admin bootstrap-admin \
    --email wellinton@v4company.com \
    --name "Wellinton Ribeiro"
```

Expected: `Created admin: <uuid> (wellinton@v4company.com)`

## 3. Issue invite URL + complete OAuth in browser

```bash
./.venv/Scripts/python.exe -m src.scripts.admin invite \
    --email wellinton@v4company.com
```

Open the printed URL in a browser logged into your V4 Google account
that has access to the V4 MCC. Authorize → you should see the green
"✅ Conectado" page.

## 4. Run resync to populate accounts

Manual one-off (Cloud Scheduler will do this daily after Phase 1a):
```bash
gcloud run jobs execute v4-ads-mcp-resync --region=southamerica-east1 --wait
```

Verify accounts in Supabase via SQL editor:
```sql
SELECT customer_id, descriptive_name FROM google_ads_accounts WHERE is_active = true ORDER BY descriptive_name;
```
Expect ~29 rows.

## 5. Grant yourself access to all accounts

```bash
./.venv/Scripts/python.exe -m src.scripts.admin grant-all \
    --email wellinton@v4company.com
```

Expected: `Granted access to 29 new accounts (existing grants kept).`

## 6. Create an MCP session

```bash
./.venv/Scripts/python.exe -m src.scripts.admin create-session \
    --email wellinton@v4company.com \
    --label "Claude Desktop"
```

**Copy the printed `mcp_xxx...` token immediately — it won't be shown again.**

## 7. Configure Claude Desktop

Edit `~/AppData/Roaming/Claude/claude_desktop_config.json` (Windows) or
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "v4-ads": {
      "url": "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp",
      "headers": {
        "Authorization": "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

Restart Claude Desktop.

## 8. Verify in Claude

In a new chat:
> "List the available MCP tools."

Expected: Claude lists `list_my_accounts`.

> "Use list_my_accounts."

Expected: Claude returns ~29 accounts with names + currency + timezone.

## 9. Verify audit trail

```sql
SELECT occurred_at, manager_id, operation, target_count, status
FROM audit_log
ORDER BY occurred_at DESC
LIMIT 5;
```

Expect a row with `operation = 'list_my_accounts'`, `target_count = 29`, `status = 'success'`.

---

## Troubleshooting

- **OAuth callback says "Google didn't return a refresh_token"** — your Google account previously authorized this app and Google won't re-issue. Go to https://myaccount.google.com/permissions, revoke "V4 Ads MCP", retry.
- **Resync fails with "AUTHENTICATION_ERROR"** — the admin's refresh token expired or was revoked. Re-run step 3 (invite + OAuth) for the admin.
- **Resync fails with "no active OAuth connection"** — no admin has done OAuth yet; complete step 3 first.
- **Claude says "tool not found"** — restart Claude Desktop fully (not just close window). Check the Bearer token is exactly as printed (no leading/trailing spaces).

---

## Phase 2 — Testing read tools

After Phase 2 deploys, verify the 16 + 3 read tools work end-to-end via Codex/Claude Desktop. Use a current MCP session token (rotate if expired via `python -m src.scripts.admin create-session ...`).

### Pick a non-trivial customer_id

The 23 active V4 accounts are listed by `list_my_accounts`. Pick one with real recent activity for testing — e.g., 'Mestre da Obra - Cotia' (5894449831).

### Test prompts (paste into Claude/Codex)

1. **Account overview:**
   > "Use get_account_overview na conta 5894449831 ultimos 30 dias e mostra a comparacao com periodo anterior."

   Expected: numbers for impressions/clicks/cost/conv/ROAS, with current vs previous side-by-side.

2. **Budget pacing:**
   > "Quais campanhas da conta 5894449831 estao acima do projetado pro mes?"

   Expected: list of campaigns with daily_budget, MTD spend, projection, % over budget.

3. **Performance breakdown:**
   > "Top 5 campanhas por gasto na conta 5894449831, ultimos 7 dias."

   Expected: 5 campaigns ordered by cost.

4. **Tactical:**
   > "Quais search terms na conta 5894449831 gastaram mais sem converter nos ultimos 14 dias?"

   Expected: list of search terms with cost > 0 and conversions = 0.

5. **GAQL escape hatch:**
   > "Roda este GAQL na conta 5894449831: SELECT customer.descriptive_name, customer.currency_code FROM customer"

   Expected: 1 row with the descriptive_name + currency.

### Verify audit + rate limit

```sql
-- Sensitive reads (recommendations, run_gaql, conversion_actions) should be audited
SELECT operation, count(*) FROM audit_log
WHERE occurred_at > now() - interval '1 hour' AND action_type = 'read'
GROUP BY operation;

-- Rate counter should reflect today's usage
SELECT * FROM rate_counters WHERE date = current_date;
```

---

## Phase 3a — Testing core mutations

After Phase 3a deploys, verify the 10 mutation tools work end-to-end via Codex/Claude Desktop. **CAUTION:** these tools modify production Google Ads accounts. Use a safe test pattern: pause + immediately re-enable, or use a campaign with low/no budget.

### Available mutations

- `update_campaign_status`, `update_campaign_budget`, `update_campaign_bidding`
- `update_ad_group_status`, `update_ad_group_bid`
- `update_keyword_status`, `update_keyword_bid`
- `add_negative_keywords`
- `apply_recommendation`, `dismiss_recommendation`
- `apply_change` (utility — consume confirmation_token from any of the above)

### Test prompts

1. **Auto-apply path (low risk):**
   > "Use add_negative_keywords na conta 5894449831, campanha 22934537062, para adicionar 'free' como BROAD."

   Expected: `status: applied`, change visible in Google Ads UI Change History.

2. **Dry-run + apply path (budget):**
   > "Use update_campaign_budget na conta 5894449831, campanha 22934537062, novo orcamento R$ 110."

   Expected: `status: dry_run`, `confirmation_token: <8 chars>`, preview with current vs new vs delta_pct.

   Then:
   > "Use apply_change com token <token>"

   Expected: `status: applied`, change visible in Google Ads UI.

3. **Bulk dry-run path (status):**
   > "Pause as campanhas X, Y, Z, W, V, U na conta 5894449831." (6 campaigns -> dry-run)

   Expected: `status: dry_run`, single token covering all 6.

### Verify in Google Ads UI

1. Open https://ads.google.com → conta `5894449831` (Mestre da Obra - Cotia)
2. Tools & Settings → Change History
3. Each mutation should appear under your name (`wellinton.ribeiro@v4company.com`) with timestamp + before/after values

### Verify audit log

```sql
SELECT occurred_at, operation, target_count, status, google_request_id
FROM audit_log
WHERE action_type = 'mutate'
  AND occurred_at > now() - interval '1 hour'
ORDER BY occurred_at DESC;
```

Each successful mutation should have a `google_request_id` (proves the call hit Google's API).

### Rollback if needed

To undo a status change: re-run the same tool with the previous status. To undo a budget change: re-run with the previous amount. There is no atomic rollback yet — manual.
```
