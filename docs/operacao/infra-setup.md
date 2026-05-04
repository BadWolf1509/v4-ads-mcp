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
