# V4 Ads MCP — Frontend Audit (2026-05)

**Captured:** 2026-05-05
**Reviewer:** Wellinton + Claude
**Purpose:** Document the "before" state before FE Redesign v2. Decisions are in the design spec at `docs/superpowers/specs/2026-05-05-frontend-redesign-v2-design.md`.

## Cross-cutting findings

### Navigation
- 3 of 4 admin pages (`/admin/accounts`, `/admin/access`, `/admin/audit`) have no UI link — only reachable via URL or runbook.
- Header collapses badly in mobile (no hamburger).
- No breadcrumbs on detail-style pages (sessions/created.html is transient).

### Design system
- 225 lines of CSS in 3 files. Tokens are defined but inline `style="..."` attributes appear in nearly every template — design system is not enforced.
- No motion tokens (durations, easings).
- No empty state pattern — empty tables show "Nenhum X" centered, no illustration or CTA.
- No skeleton loaders — HTMX swaps are silent.
- Dark mode tokens prepared but not used.

### Auth / security
- OAuth callback auto-creates manager rows for any `@v4company.com` email — 4000 V4 employees can pollute the DB (low-risk but real operational concern).
- Generic 403 page on `/admin/*` denial — not branded.
- No `/access-denied` route.

### Audit & visibility
- Audit table truncates `error_message` to 40 chars with HTML `title` tooltip — frail, inaccessible.
- No detail page for individual audit events — `params_summary`, full error, `google_request_id` are not visible to the user.
- No CSV export.
- Filters require explicit "Filtrar" click instead of HTMX auto-submit.

### Tables
- Access matrix doesn't scale beyond ~10 gestores × 30 accounts before becoming unusable.
- No search inputs anywhere — finding a specific account/session/event requires Ctrl+F in browser.
- No pagination — all rows render at once.
- No bulk actions — granting access to 23 accounts for a new gestor = 23 individual clicks.

## Per-page findings

### `/login`
- Generic hero ("Conecte suas contas Google Ads ao Claude, Codex e outras IAs").
- No narrative product positioning.
- Logo at 64px, button generic.
- Missing: explainer of what comes after login (no preview, no FAQ link).

### `/` (dashboard)
- "Próximos passos" list always visible — even when all gaps are closed (cognitive noise).
- Stats are static counts — no trend, no "what happened today".
- No admin-specific operational view (admin sees the same as gestor).

### `/accounts`
- Two stacked tables (OAuth connections + Google Ads accounts) without clear hierarchy.
- "Unknown" OAuth from Phase 1a (no email scope) clutters the connections table.
- No search on the 23-account list (will be unusable at 100+).
- No filter by currency or test status.

### `/sessions`
- Form to create at top (always visible, no collapse).
- "Created" page (`sessions/created.html`) is transient — closing the tab loses the snippet permanently.
- "Revoke" uses `onsubmit="return confirm()"` — inaccessible to screen readers.
- No detail view for a session (URL, metadata, snippets reusable).

### `/audit`
- Filter form with explicit "Filtrar" button.
- Tabular layout, dense, no grouping by day/hour.
- Status shown only by color (problem for daltonism).
- Error messages truncated at 40 chars via `title` attribute (frail).
- No way to expand a row to see full params/error.
- No CSV export.

### `/admin/managers`
- Inline buttons "Promover/Despromover/Desativar" without confirm dialog beyond `onsubmit`.
- No search (will be unusable at 30+ managers).
- No filter by role/status.

### `/admin/accounts`
- Pure dump table — no search, no filter by MCC.
- No way to drill into account detail.

### `/admin/access`
- Matrix renders all gestores × accounts.
- Sticky header lateral but no top sticky.
- No search, no bulk actions.
- Email truncated at `@` — collisions possible.
- Mobile: nearly unusable (matrix scrolls in 2 axes on tiny screen).

### `/admin/audit`
- Same issues as `/audit`, plus filter UI duplicated (DRY violation).
- No "só erros" quick filter.

## Severity prioritization (will guide phase ordering)

- **High (Phase 4 priority):** access matrix scalability, audit table density, audit detail visibility.
- **High (Phase 2 priority):** Q8 invite-only enforcement, admin sub-nav.
- **Medium (Phase 3 priority):** brand identity in login + dashboard.
- **Low (Phase 5 priority):** list-page polish (accounts, sessions list, admin/managers, admin/accounts).
