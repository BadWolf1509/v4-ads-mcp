# Infra setup — one-time manual steps

This document records the cloud-console actions performed once to bootstrap the project. Re-doing them is only necessary in disaster recovery or to provision a new environment.

## GitHub
- [x] Repo: `BadWolf1509/v4-ads-mcp` (private)
- [ ] Branch protection on `main`: require PR + passing CI (set after Task 11)

## GCP project
- [ ] Project created (TBD in Task 11)
- [ ] APIs enabled: Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Cloud Logging, Cloud Scheduler, Google Ads
- [ ] Workload Identity Federation pool/provider configured (Task 11)
- [ ] Secret Manager secrets created (Task 11)

## Supabase project
- [x] Project ref: `laiqtoisehgkwfxaezjl` (region São Paulo)
- [ ] DB password recorded (1Password under "v4-ads-mcp / supabase")
- [ ] Connection string saved in Secret Manager (Task 11)

## Google Ads
- [x] Developer token: `<set in Secret Manager — see 1Password "v4-ads-mcp / google-ads-dev-token">` (Test Account mode at MVP; submit Standard Access during Phase 1)
