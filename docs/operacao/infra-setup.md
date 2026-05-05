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

### Phase 2 — Read tools (2026-05-04)
- 16 curated read tools (visao geral, performance, tactical, client report) + 3 GAQL utilities (run_gaql, validate_gaql, list_gaql_resources) shipped.
- Total tools registered: 20 (incl. list_my_accounts from Phase 1a).
- Rate limit module enforces 15k ops/day per developer token (Basic Access). Warning at 80%, block at 100%.
- Audit log captures sensitive reads only (recommendations, run_gaql, conversion_actions).
- jsonschema input validation in MCP call_tool (defense in depth).
- 114 tests passing (unit + integration with testcontainers Postgres + mocked Google Ads SDK).
- E2E verified via Codex on conta `5894449831` (Mestre da Obra - Cotia):
  - `get_account_overview`: returned 30-day KPIs + previous-period comparison (impressions 8590 vs 8086, +6.2%; conversions 237 vs 197, +20.3%; CPA dropped from R$ 10.76 to R$ 10.04).
  - `get_budget_pacing`: returned 1 active campaign with daily_budget R$ 100, MTD spend R$ 213.92, projected R$ 1657.88 (53.5% of monthly budget).
  - `get_campaign_performance` (top 5, 7-day): returned the 1 active campaign with R$ 581.75 spend, 151 clicks, CTR 7.57%.
  - `get_search_terms_report` (14-day): returned 64 search terms without conversions totaling R$ 271.81, candidates for negative keywords identified by Codex.
  - `run_gaql` with custom GAQL: returned 1 row with descriptive_name "Mestre da Obra - Cotia", currency BRL.
- Codex performed intelligent analysis on top of the raw tool outputs (% deltas, negative keyword candidates, projection vs budget) — proving the gestor workflow value end-to-end.

### Phase 3a — Core mutations (2026-05-04 — code complete, E2E deferred to operations)
- 10 mutation tools shipped: 3 campaign (status/budget/bidding), 2 ad_group (status/bid), 2 keyword (status/bid), 1 negative_keywords, 2 recommendations.
- Plus `apply_change` utility tool to consume confirmation tokens.
- Total tools registered: 31 (20 from Phase 2 + 1 apply_change + 10 mutations).
- Governance: blast_radius classifier (auto vs confirm per spec §7.1), dry_run with 8-char alphanumeric tokens + 10-min TTL + session-scoped, audit_log captures every mutation with google_request_id.
- 162 tests passing (unit + integration with testcontainers + mocked Google Ads SDK).
- E2E approach: deferred to operations (gestores) doing real work — synthetic test mutations risk altering live accounts. Validation channel = audit_log table + Google Ads UI Change History. Test prompts in `phase-1a-bootstrap.md` Phase 3a section remain available for ad-hoc validation if needed.
- First-touch monitoring plan: track audit_log for the first week of operations use; flag any failures (status='error') for investigation.

### Phase 1b — Web panel (2026-05-05)
- 5 gestor pages (login, dashboard, accounts, sessions, audit) + 4 admin pages (managers, accounts, access matrix, audit) shipped.
- Authentication: unified Google OAuth (deviation from spec §5.1 which prescribed Supabase Auth + separate Google OAuth) — single flow with scopes {openid, email, profile, adwords} restricted to @v4company.com.
- Panel session: signed cookie `v4_panel_session` (24h TTL, httpOnly, Secure, SameSite=Lax). HMAC-signed with session_signing_key.
- First-ever login auto-promoted to admin (bootstrap path).
- Templates: Jinja2 + V4 design tokens (no JS framework, no build step). HTMX via CDN for inline interactions (revoke session, toggle access).
- Brand assets: official V4 SVG logo (`logo_v4_puro_round.svg`, 667 bytes vector-pure) replacing initial placeholder. Renders in header of every page + login hero. Reserve `logo_v4_puro_round_transparente.svg` (585 bytes) kept for future dark-mode/footer use.
- 203 tests passing (unit + integration with testcontainers).
- Existing CLI admin remains available as escape hatch.
- E2E verified by user on 2026-05-05 via 5 screenshots covering all gestor + admin pages in production:
  - Login flow worked end-to-end. Re-OAuth populated google_email = wellinton.ribeiro@v4company.com, fixing the "unknown" carryover from Phase 1a (which had only `adwords` scope).
  - Dashboard `/`: greeting "Bem-vindo, Wellinton Ribeiro!", ADMIN badge, "23 contas acessíveis", "1 sessão MCP ativa", Google connection card showing wellinton.ribeiro@v4company.com (Conectado em 05/05/2026 00:51).
  - `/accounts`: 2 OAuth connections rendered (new with-email ATIVA from 05/05 + legacy "unknown" ATIVA from 04/05) + table of 23 Google Ads accounts (CIDs 3237459217 → 9985020293, including "3 Lagoas Locações", "DR DÉRICK VINHAS", "Mestre da Obra - Cotia" etc.).
  - `/sessions`: 1 active "Claude Desktop" session listed (criada 04/05/2026 04:56, último uso 04/05/2026 14:14, expira 02/08/2026). Revoke button rendered.
  - `/audit`: 2 events captured — both `list_my_accounts` READ ops, status OK, target_count 23, durations 7ms + 6ms.
  - `/admin/managers`: 1 admin row (Wellinton Ribeiro, badge ADMIN, ATIVO, criado 04/05/2026, último acesso 04/05 14:14, marcado "(você)").
- Phase 1a known-limitation #1 (google_email="unknown" because OAuth used only `adwords` scope) is now resolved: new connections via panel use `{openid, email, profile, adwords}` and the email column populates correctly. Legacy "unknown" rows from Phase 1a remain visible until those connections are revoked + reauthorized — cosmetic only.
- Logo renders correctly across all pages including the login hero.
