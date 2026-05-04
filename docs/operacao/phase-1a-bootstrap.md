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
