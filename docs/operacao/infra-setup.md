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

### Phase FE Redesign v2 (2026-05-05) — code-complete in production
- 56 commits across 6 phases shipping a Hybrid Editorial+Operational identity per `docs/superpowers/specs/2026-05-05-frontend-redesign-v2-design.md` and `docs/superpowers/plans/2026-05-05-frontend-redesign-v2-plan.md`.
- Design system v2: Tailwind CDN integrated with V4 token bridge (`bg-v4-red`, `text-display`, `font-mono`, `transition-v4-out`); 22 components in `_components.html` (refined: button/card/badge/alert/inputs/form_group; new: sparkline, pagination, code_block, empty_state, toast, skeleton, confirm_dialog, modal, breadcrumb, dropdown, tooltip, expandable_row, sticky/compact tables); ~520 lines added to CSS; new `v4-motion.css`; 5 JS helpers in `_base.html` (toggleDrawer, showToast, openConfirm, v4DropdownToggle, v4ToggleRow).
- Auth/Q8: invite-only allowlist enforced. Migration `002_managers_status.sql` adds `status` (`invited`/`active`/`inactive`) + `invited_by` + `invited_at`. OAuth callback decision tree (pure `handle_callback_decision` + 8 unit tests). `BOOTSTRAP_ADMIN_EMAILS` env var (Cloud Run revision `00058+`). `/access-denied` page with 3 reason variants.
- 15 pages redesigned/created (9 redesigned + 6 new):
  - **Editorial:** `/login` (display 56 hero "V4 Ads MCP. IA + Google Ads."), `/access-denied`, `/help`.
  - **Hybrid hero:** `/` dashboard (Editorial hero + Operational stats + admin extras card), `/admin` (visão geral consolidada).
  - **Operational tables:** `/audit` (sticky filters + auto-submit + day grouping + expand row + CSV export), `/audit/{id}` detail, `/admin/audit` (+ status filter + gestor filter), `/admin/access` matrix v2 (search + bulk grant + copy access modals), `/admin/access/by-manager` + `/admin/access/{id}` (mobile per-gestor paradigm).
  - **List + form:** `/accounts`, `/sessions` (flow change: POST → 302 → `/sessions/{id}?token_flash=true`), `/sessions/{id}` permanent detail, `/admin/managers` (search + dropdown ⋯ + filters), `/admin/accounts` (search + MCC filter), `/admin/invites` (Q8 list + form).
- Sub-nav admin (Visão geral · Managers · Convites · Contas · Acessos · Audit global) with live-counter badge for pending invites.
- Mobile-aware: hamburger drawer below 768px; tables >3 cols become card list; access matrix has dedicated per-gestor route.
- Backend touchpoints: 1 migration, ~10 new repository functions (managers invite lifecycle, audit_log get_by_id/summary_stats/export_csv_rows, mcp_sessions.get_by_id, manager_account_access.bulk_grant/copy_access), 12+ new routes, allowlist OAuth flow.
- Tests: 101 unit + 8 OAuth allowlist + integration test updates (sessions flow + admin audit header). All CI green.
- E2E partially verified during deploy: smoke screenshot of `/admin/invites` showing form + sub-nav badge + Lucas Soares pending invite. Final visual regression sweep across all 15 pages deferred to operations during real onboarding (`docs/operacao/screenshots/after/` directory awaits captures).
- Out of scope (deferred to follow-up sub-projects per the spec): multi-tenancy backend (`unidades` table + 3-tier RBAC), multi-MCC OAuth, single→multi migration, dark mode opt-in.
