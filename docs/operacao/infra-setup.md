# Infra setup — one-time manual steps

This document records the cloud-console actions performed once to bootstrap the project. Re-doing them is only necessary in disaster recovery or to provision a new environment.

## GitHub
- [x] Repo: `BadWolf1509/v4-ads-mcp` (private)
- [ ] Branch protection on `main`: require PR + passing CI (set after Task 11)

## GCP project
- [x] Project: `v4-ads-mcp-prod` (project number `518798891402`, billing `01286F-7A67A7-226F9E`)
- [x] APIs enabled: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Logging, Cloud Scheduler, IAM Credentials, STS, Google Ads
- [x] Service accounts: `v4-ads-mcp-runtime` (Cloud Run identity), `github-deployer` (CI deploys via Workload Identity Federation)
- [x] Workload Identity Federation pool `github-pool` + OIDC provider `github-provider` (restricted to repo `BadWolf1509/v4-ads-mcp`)
- [x] Secret Manager: 10 secrets created. Real values for `session-signing-key`, `aes-master-key`, `google-ads-developer-token`, `google-ads-login-customer-id`, `supabase-url`, `database-url`. Placeholders for OAuth + Supabase keys (Phase 1 fills in).
- [x] GitHub repo secrets: `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `GCP_PROJECT_ID`, `GCP_REGION`
- [x] Cloud Run Job `v4-ads-mcp-resync` created (entry: `python -m src.jobs.account_resync`)
- [x] Cloud Scheduler `v4-ads-mcp-resync-daily` (cron `0 7 * * *` UTC = 04:00 BRT)

## Supabase project
- [x] Project ref: `laiqtoisehgkwfxaezjl` (region São Paulo)
- [x] DB password recorded (1Password under "v4-ads-mcp / supabase")
- [x] Connection string in Secret Manager: `database-url` (uses Shared Pooler `aws-1-sa-east-1.pooler.supabase.com:5432`, IPv4)

## Google Ads
- [x] Developer token: `<set in Secret Manager — see 1Password "v4-ads-mcp / google-ads-dev-token">` (Test Account mode at MVP; submit Standard Access during Phase 1)
- [x] V4 MCC ID: `6436352492` (was previously misidentified as `7862230676` which is actually a child account "Mestre da Obra - João Pessoa")
- [x] OAuth Client created in GCP Console with redirect URI `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/oauth/google/callback`

## Phase sign-offs

### Phase 0 — Foundation (2026-05-03)
- Repo + tooling, Cloud Run service, /health and /mcp (no tools), CI/CD pipeline, Supabase migrations applied. All acceptance criteria met.

### Phase 1a — Auth backend + first MCP tool (2026-05-04)
- AES-GCM encryption for refresh tokens, MCP Bearer sessions, OAuth state HMAC, 6 DB repositories, Google Ads SDK client, MCP middleware, tool registry, `list_my_accounts` tool, OAuth Google flow, admin CLI, account_resync job + Cloud Scheduler.
- E2E verified: wellinton.ribeiro@v4company.com bootstrapped → OAuth flow completed → 23 V4 client accounts populated via resync → granted access → MCP session created → Codex CLI configured + connected → `list_my_accounts` returned all 23 accounts → audit_log captured 2 calls (6ms + 7ms duration each).
- Known limitations carried into Phase 1b:
  - Userinfo endpoint failed during OAuth (scope `adwords` alone doesn't include email); google_email is currently "unknown". Add `email` scope in Phase 1b.
  - Developer token still in Test mode (15k ops/day quota). Submit for Standard Access when quota becomes constraining.

### Phase 2 — Read tools (TBD - awaiting user E2E)
- 16 curated read tools (visao geral, performance, tactical, client report) + 3 GAQL utilities (run_gaql, validate_gaql, list_gaql_resources) shipped.
- Total tools registered: 20 (incl. list_my_accounts from Phase 1a).
- Rate limit module enforces 15k ops/day per developer token (Basic Access). Warning at 80%, block at 100%.
- Audit log captures sensitive reads only (recommendations, run_gaql, conversion_actions).
- jsonschema input validation in MCP call_tool (defense in depth).
- E2E pending — user runs the test prompts in `phase-1a-bootstrap.md` Phase 2 section. Once verified, replace this paragraph with the actual sign-off summary listing tools called + customer_ids tested.
