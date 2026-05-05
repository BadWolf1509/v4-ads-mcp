# V4 Ads MCP — Frontend Redesign v2 Design

**Date:** 2026-05-05
**Scope:** Sub-project 1 of 4 (FE redesign only; multi-tenancy backend = sub-projects 2-4)
**Status:** Design — awaiting implementation plan

---

## 1. Context & Goals

The V4 Ads MCP web panel ships today as a functional admin tool: 9 pages, plain Jinja2 + V4 design tokens + HTMX, light theme, ~225 lines of CSS. It works. But:

- It feels like "default admin panel brutalism" — functional but lacking the brand identity expected of a digital marketing agency's internal tooling.
- Several scale-related UX problems exist today and worsen as the platform onboards multiple V4 unidades (3-5 unidades, 30-100 gestores within 12 months): access matrix breaks beyond ~10×30, audit table is too dense to navigate, no search/filter, no bulk actions.
- A real navigation bug: 3 of 4 admin pages have no UI link — they're only reachable by typing URLs.
- A real security/operational issue: any of V4's ~4000 employees with `@v4company.com` can complete OAuth and create a manager row, polluting the database (low-but-real harm — they can create MCP tokens but those have no account access; still operationally noisy).

**Primary goals (locked during brainstorming):**

- **B — V4 brand identity case study.** The panel becomes something V4 can show off as its own production-grade work. Tipografia rica, microinteractions, presence.
- **C — Operational scalability.** Patterns that work today (1 admin, 0-2 gestores) and continue working at 12-month target (3-5 unidades, 30-100 gestores total).

**De-prioritized (still considered, but lose trade-offs to B/C when they collide):**

- A — Pure speed (fewer clicks).
- D — Information density / "command center" feel.
- E — Audit depth (we still get most of this from the redesign anyway).

**Decisions locked during brainstorming:**

| Decision | Choice |
|---|---|
| Scale target (12 months) | Multi-unidade Brasil — 3-5 unidades, 10-20 gestores each |
| Sub-project scope | FE Redesign v2 only (this doc). Multi-tenancy backend = sub-projects 2-4 |
| Visual direction | **Hybrid** — Editorial in marketing surfaces (login, hero, empty states); Operational in data-heavy surfaces (audit, access matrix) |
| Stack | Plain Jinja2 + V4 design tokens + **Tailwind via CDN** + HTMX. No build step. |
| Mobile responsiveness | **Mobile-aware** — guarantees usable in mobile, including access matrix via different paradigm |
| Approach shape | **A — Audit-driven, faseado** (6 sequential PRs) |
| Auth Q7 (admin landing) | Keep shared shell; role-aware home; admin sub-nav; polished 403 |
| Auth Q8 (4000 employees) | Invite-only via allowlist (managers.status migration + OAuth callback decision tree) |
| Sitemap completeness | All routes ship with UI links (admin sub-nav resolves bug) + 6 new pages |

---

## 2. Information Architecture

### 2.1 Header navigation (visible to any authenticated user)

```
┌─────────────────────────────────────────────────────────────────────┐
│  [V4 Ads MCP]  Dashboard  Contas  Sessões  Audit  Help    [Admin]●  │
│                                              wellinton@... · Sair    │
└─────────────────────────────────────────────────────────────────────┘
```

- "Admin" button (red badge) appears only when `current_user.is_admin` is true. Clicking it lands on `/admin` (visão geral).
- On mobile (`<md`), nav collapses into hamburger menu opening a full-screen drawer with the same items + admin sub-items grouped.

### 2.2 Admin sub-nav (visible only on `/admin/*` routes)

```
┌─────────────────────────────────────────────────────────────────────┐
│  [V4 Ads MCP]  Dashboard  Contas  Sessões  Audit  Help    [Admin]●  │
│                                              wellinton@... · Sair    │
├─────────────────────────────────────────────────────────────────────┤
│  Visão geral · Managers · Convites [3] · Contas · Acessos · Audit   │
└─────────────────────────────────────────────────────────────────────┘
```

- Sticky below header on desktop.
- "Convites" has a counter badge showing pending invitations.
- Resolves the "3 of 4 admin pages have no UI link" bug present today.

### 2.3 Sitemap (post-redesign)

| Area | Routes | Notes |
|------|--------|-------|
| **Public** | `/login`, `/oauth/google/start`, `/oauth/google/callback`, `/logout`, `/access-denied` | `/access-denied` is NEW |
| **Gestor (auth)** | `/`, `/accounts`, `/sessions`, `/sessions/{id}`, `/audit`, `/audit/{id}`, `/help` | `/sessions/{id}`, `/audit/{id}`, `/help` are NEW |
| **Admin (auth + is_admin)** | `/admin`, `/admin/managers`, `/admin/invites`, `/admin/accounts`, `/admin/access`, `/admin/audit` | `/admin`, `/admin/invites` are NEW |

**Total: 15 user-facing pages** (9 redesigned + 6 new). Service routes (`/health`, `POST /mcp`, OAuth callbacks) unchanged.

### 2.4 Role-aware home (`/`)

- **Gestor sees:** Editorial hero "Bem-vindo, {first_name}." (V4 red on name) + sublabel with unidade context + 3 stat cards (contas, sessions, today's calls) + last 5 MCP calls + conditional "next steps" (only if there's a real gap, e.g., no OAuth connection yet).
- **Admin sees the above plus:** an "Operação V4 Ads MCP" card with: convites pendentes (count), quota usage today (e.g., 147/15k), erros últimas 24h, gestores ativos vs cadastrados.
- Same URL, same shell. The admin extras are an additive section, not a separate page.

### 2.5 Sessions detail flow

Today: `POST /sessions/new` → renders `created.html` (transient page); if you leave, you lose the snippets.

New flow:

```
POST /sessions/new
  → 302 redirect to GET /sessions/{id}?token_flash=true
    → Shows session details + token (one-time via flash session)
    → Token disappears on refresh; page remains accessible without token
  → GET /sessions/{id} (permanent)
    → Shows session details + reusable config snippets (Claude Desktop / Codex / Cursor)
    → Token never reappears (rotation = revoke + create new session)
```

This solves the "fechei a aba e perdi o snippet" problem present today.

---

## 3. Design System v2

### 3.1 Color tokens

**Existing (kept):**

```css
--v4-red:           #e50914;
--v4-red-medium:    #b20710;
--v4-red-dark:      #80050b;
--v4-red-darkest:   #400306;
--v4-white:         #ffffff;
--v4-gray-50:       #f5f5f5;
--v4-gray-100:      #e5e5e5;
--v4-gray-200:      #cccccc;
--v4-gray-300:      #b3b3b3;
--v4-gray-700:      #333333;
--v4-gray-800:      #262626;
--v4-gray-900:      #1a1a1a;
--v4-black:         #000000;
--v4-green:         #52cc5a;
--v4-gold:          #ffc02a;
```

**New (added in this redesign):**

```css
/* Soft backgrounds (alerts, badges, status hints without alarm tone) */
--v4-red-soft:      #fde2e4;
--v4-green-soft:    #e8f7ea;
--v4-gold-soft:     #fff7e0;
```

### 3.2 Typography

**Existing scale (kept):**

```css
--v4-h1-size: 36px; --v4-h1-weight: 800; --v4-h1-line: 1.1;
--v4-h2-size: 28px; --v4-h2-weight: 700; --v4-h2-line: 1.2;
--v4-h3-size: 20px; --v4-h3-weight: 600; --v4-h3-line: 1.3;
--v4-h4-size: 16px; --v4-h4-weight: 600; --v4-h4-line: 1.4;
--v4-body-size: 14px;
--v4-small-size: 12px;
```

**New (added):**

```css
--v4-display-size: 56px; /* used in /login hero, /access-denied title; -0.025em letter-spacing */
--v4-display-weight: 800;
--v4-display-line: 1.0;
```

**Font families (kept):** Montserrat (300-800) for sans · JetBrains Mono / Consolas for mono. Mono gets systematic use in Operational mode for IDs, timestamps, operation names.

### 3.3 Spacing, radii, shadows (kept as-is)

The existing `--v4-space-{1..16}`, `--v4-radius-{sm,md,lg,xl}`, and `--v4-shadow-{sm,card,modal}` scales are sound. No changes.

### 3.4 New tokens

```css
/* Motion */
--v4-motion-fast:   100ms;
--v4-motion-base:   180ms;
--v4-motion-slow:   320ms;
--v4-ease-out:      cubic-bezier(0.2, 0.8, 0.2, 1);
--v4-ease-spring:   cubic-bezier(0.34, 1.56, 0.64, 1);

/* Operational density */
--v4-row-height-compact: 36px;
--v4-cell-pad-compact:   8px 12px;
--v4-border-subtle:      1px solid var(--v4-gray-100);

/* Z-index scale */
--v4-z-base:        1;
--v4-z-sticky:      10;
--v4-z-dropdown:    100;
--v4-z-modal:       1000;
--v4-z-toast:       1100;
```

### 3.5 Tailwind CDN integration

`_base.html` adds:

```html
<script src="https://cdn.tailwindcss.com"></script>
<script>
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          'v4-red':   { DEFAULT: '#e50914', medium: '#b20710', dark: '#80050b', soft: '#fde2e4' },
          'v4-gray':  { 50: '#f5f5f5', 100: '#e5e5e5', 200: '#cccccc', 300: '#b3b3b3',
                        700: '#333333', 800: '#262626', 900: '#1a1a1a' },
          'v4-green': { DEFAULT: '#52cc5a', soft: '#e8f7ea' },
          'v4-gold':  { DEFAULT: '#ffc02a', soft: '#fff7e0' },
        },
        fontFamily: {
          sans: ['Montserrat', 'system-ui', 'sans-serif'],
          mono: ['JetBrains Mono', 'Consolas', 'monospace'],
        },
        fontSize: { 'display': ['56px', { lineHeight: '1.0', letterSpacing: '-0.025em' }] },
        transitionTimingFunction: {
          'v4-out':    'cubic-bezier(0.2, 0.8, 0.2, 1)',
          'v4-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
        },
      }
    }
  }
</script>
```

Component classes (`.v4-stat`, `.v4-table`, etc.) coexist. Refactor toward Tailwind utilities where readability isn't hurt; keep semantic classes where they communicate intent.

### 3.6 Component catalog

**6 existing components refined:**

| Component | Refinement |
|---|---|
| Button | + ghost variant, + icon-only variant, + loading state |
| Card | + compact variant |
| Badge | + counter variant (with number) |
| Alert | + success kind |
| Input/Select | + search input, + textarea, + checkbox, + radio |
| Form group + label | (no change, already solid) |

**16 new components:**

| Component | Purpose |
|---|---|
| Sparkline | Inline SVG 60×16, used in stat cards and audit trends |
| Pagination | Appears when >20 rows |
| Code block | `<pre>` with copy button + filename label |
| Empty state | Illustration + contextual CTA |
| Toast | Post-HTMX action feedback |
| Skeleton loader | While HTMX is loading |
| Confirm dialog | Replaces `onsubmit="return confirm()"` with accessible modal |
| Modal/dialog | Real implementation (CSS exists, never used) |
| Sub-nav | Sticky horizontal bar with counter badges |
| Breadcrumb | On detail pages (`/audit/{id}`, `/sessions/{id}`) |
| Mobile drawer | Hamburger nav |
| Dropdown menu | User menu, row actions (⋯) |
| Tooltip | Icon explanations |
| Expandable table row | Audit/admin tables — click row to expand inline detail |
| Sticky table header | For long tables |
| Compact table | Operational mode dense variant |

All components ship as Jinja macros in `_components.html` (extending the existing `stat`, `badge`, `alert` macros).

### 3.7 Dark mode

**Posture:** Light theme is default and covers 100% of pages in MVP. Tokens are prepared for dark mode. Dark mode itself ships as a follow-up post-MVP, opt-in only on data-heavy pages (audit, access matrix), via toggle or `prefers-color-scheme`.

This redesign **does not block on dark mode**.

---

## 4. Editorial vs Operational Modes

### 4.1 Visual signature of each mode

| Attribute | Editorial | Operational |
|---|---|---|
| Type | Display 36-56 / 800, letter-spacing tight (-0.025em) | Body 12-14, Mono 12 in IDs/operations/timestamps |
| Spacing | 32-64px section paddings, single-column max-w 640-800px | 8-16px paddings, row 36px, multi-column full-width |
| Shape | rounded-full buttons, rounded-xl (16px) cards | rounded-md (8px), sharp badges (rounded-sm 4px) |
| Color | Light bg, V4 red as narrative accent (e.g., colored name in heading) | Subtle grays dominate, V4 red used in error/sparkline |
| Imagery | Generous whitespace, single hero element, possibly illustration | Dense data, sparklines, no imagery |

### 4.2 Mode assignment per page

| Page | Mode | Why |
|---|---|---|
| `/login` | Editorial | Marketing surface · first impression · zero data |
| `/access-denied` | Editorial | Clear message, human tone |
| `/help` | Editorial | Explanatory text, snippets in editorial frame |
| `/` (gestor + admin views) | Hybrid | Editorial hero + Operational stats/activity |
| `/accounts` | Hybrid | Editorial header + Operational tables |
| `/sessions` | Hybrid | Editorial header + Operational form/table |
| `/sessions/{id}` | Hybrid | Editorial detail header + Operational snippets |
| `/audit` | Operational | Dense table, filters, pagination · zero hero |
| `/audit/{id}` | Operational | Technical detail — JSON, IDs, error messages |
| `/admin` | Hybrid | Editorial header + Operational stats cards |
| `/admin/managers` | Operational | Table with row toggle actions |
| `/admin/invites` | Hybrid | Editorial-friendly form + Operational pending list |
| `/admin/accounts` | Operational | Pure table |
| `/admin/access` | Operational | Matrix is dense by design |
| `/admin/audit` | Operational | Same as `/audit` plus extra filters |

**Hybrid =** page header in Editorial (h1 + V4 red accent), body in Operational when content is tabular/dense.

**Counts:** 3 pure Editorial · 6 Hybrid · 6 pure Operational.

---

## 5. Mobile Strategy

### 5.1 Breakpoints (Tailwind defaults)

| Breakpoint | Min width | Behavior |
|---|---|---|
| (default) | 0-639px | Mobile · hamburger nav · stat grid 2-up · tables become card list |
| `sm` | 640px+ | Mobile L · stat grid 2-up · tables horizontal scroll |
| `md` | 768px+ | Tablet · header full · stat grid 4-up · tables full |
| `lg` | 1024px+ | Desktop · layout standard |
| `xl` | 1280px+ | Wide · access matrix uses full width without scroll |

### 5.2 Tables in mobile

**General rule:** tables with >3 columns become a "card list" at `<md`. Each row becomes a stacked card with: timestamp + operation/title + status badge + secondary metadata. Tap navigates to detail page if available.

Tables with ≤3 columns (e.g., short session list) remain tables with horizontal scroll if needed.

### 5.3 Access matrix paradigm switch

This is the largest mobile UX change.

**Desktop (`md+`):** Matrix preserved with new affordances:

- Two search inputs at top (search gestor + search account) — live HTMX filter.
- Sticky header (top + side, two-axis scroll without losing reference).
- Bulk actions toolbar: "Select all accounts for gestor X", "Copy access from gestor A to gestor B" (multiselect via shift+click).
- Toast confirmation on cell toggle.
- Empty state: "No gestores cadastrados. [Convide um]" linking to `/admin/invites`.

**Mobile (`<md`):** New paradigm — list per-gestor:

- Index lists gestores as cards: "maria@v4company.com (12 / 23 contas) →"
- Tap navigates to `/admin/access/{manager_id}` showing checkboxes vertically (one per account).
- Toggle "view by account" inverts the paradigm: list of accounts, tap shows checkboxes per gestor.

### 5.4 Modals & drawers

- At `<sm`: modals become full-screen drawers.
- Confirm dialogs use the modal component (accessible, escape-to-close, focus trap).

---

## 6. Page-by-page Briefs

### 6.1 Group A — Pure Editorial (3 pages)

**`/login`** (redesigned)

Hero: display 40-56px split across two lines, V4 red on the second:

```
V4 Ads MCP.
IA + Google Ads.
```

Sublabel narrative explaining the product (1-2 sentences), pill button "Entrar com Google V4" (black filled), small print noting access is invite-only with `@v4company.com`.

**`/access-denied`** (NEW)

Title: "Você ainda não tem acesso." Body: explanation that the panel is invite-only; user's email shown in a code block; CTA "Logout" (ghost button) so they can try a different account. Three reason variants via query string:

- `?reason=domain` — email domain isn't `@v4company.com`
- `?reason=not_invited` — email is `@v4company.com` but not in allowlist
- `?reason=deactivated` — email exists but `status=inactive`

**`/help`** (NEW)

Editorial frame with sections:

- "O que é o V4 Ads MCP" — short product explanation
- "Como configurar" — Claude Desktop, Codex CLI, Cursor (snippets reusable from `/sessions/{id}` but documented holistically here)
- "FAQ" — common issues, troubleshooting

### 6.2 Group B — Hybrid hero (2 pages)

**`/` (dashboard)**

Editorial hero: "Bem-vindo, {first_name}." with first name in V4 red. Sublabel: "V4 unidade · {unidade name} · ÚLTIMO ACESSO {timestamp}".

Operational below:

- 3-4 stat cards (contas, sessões, chamadas hoje, sessão MCP active state)
- "Últimas 5 chamadas" list (compact, mono operation names)
- Conditional "Próximos passos" — only if there's a real gap (no OAuth connection, no sessions, no account access). Disappears once everything is set.

**Admin extras:** an additional card "Operação V4 Ads MCP" with: convites pendentes (counter, link to `/admin/invites`), quota usage today (e.g., "147 / 15k"), erros últimas 24h (link to `/admin/audit?status=error`), gestores ativos vs cadastrados.

**`/admin`** (NEW visão geral)

Default landing for admins clicking "Admin" in nav. Editorial header "Operação · V4 Ads MCP" + Operational cards expanding the dashboard's admin block:

- Uso histórico (sparkline 30 dias of MCP calls)
- Top operations executed
- Top gestores by call volume
- Recente onboarding (últimos N gestores convidados/ativados)

### 6.3 Group C — List + form pages (5)

Common pattern: Editorial header (h1 + sublabel) → form/CTA block (when applicable) → Operational table with:

- Search input (always visible — client-side filter for ≤500 rows, server-side via HTMX otherwise)
- Filter chips (by status, type, etc.)
- Pagination (when >20 rows)
- Empty state with illustration + contextual CTA
- Mobile: tables >3 cols become card list; row inline actions become dropdown ⋯ menu

**Per-page specifics:**

- **`/accounts`**: Two stacked cards — "Conexões Google" (with revoke for legacy "unknown" connections) + "Contas Google Ads" (search + filter by currency, virtual unidade-aware column).
- **`/sessions`**: Form to create at top (collapses on mobile); table below. "Revoke" button uses the new accessible confirm dialog (replaces `onsubmit="return confirm()"`).
- **`/admin/invites`** (NEW): Form "add gestor (email + optional name)" → creates `manager(status=invited)`. Pending list below with badge "aguardando primeiro login". Cancel button removes the row before login.
- **`/admin/managers`**: Today's inline buttons ("Promover/Despromover/Desativar") become a dropdown ⋯ menu with confirm dialog. Adds search + filter by role/status.
- **`/admin/accounts`**: Table with search + filter by MCC + "última sync" indicator.

### 6.4 Group D — Detail pages (2 NEW)

**`/sessions/{id}`** (NEW)

Breadcrumb "Sessões / {label}". Header with session label + status badge + "Criada {date} · expira {date}". Body has reusable config snippets (Claude Desktop, Codex CLI, Cursor, Claude Code) — same content as today's "created" page except the token is omitted (token shown only via flash on creation, never persisted in detail view). Warning alert: "Token nunca é exibido após criação. Pra rotacionar, revogue + crie nova sessão."

**`/audit/{id}`** (NEW)

Breadcrumb "Audit / {timestamp}". Header with operation name (mono) + status badge. Body shows: status, duração (ms), alvos (count + summary), `google_request_id`, full `params_summary`, full `error_message` (if any), context (manager, session label, IP). Replaces the current 40-char title-tooltip truncation.

### 6.5 Group E — Audit (2 pages)

Common Operational pattern:

- Sticky filter bar at top (not inside a card) — hora, status, tipo, conta, gestor (admin only).
- Auto-submit on filter change via HTMX (no separate "Filtrar" button).
- Expandable rows — click opens detail inline (alternative to navigating to `/audit/{id}`).
- Status with icon + color — OK ✓, ERRO ✗, NEGADO ⊘ (avoids color-only signaling for accessibility).
- Date/time grouped — sticky day headers ("Hoje", "Ontem", "04/05/2026").
- CSV export button at top right.

`/admin/audit` adds: "só erros" quick chip filter, filter by gestor, separate CSV export endpoint.

### 6.6 Group F — Access matrix (special case)

Detailed in §5.3. Summary:

- Desktop: matrix + 2 search inputs + bulk actions toolbar + sticky 2-axis headers + toast confirmation.
- Mobile: list per-gestor → tap → vertical checkboxes per account, with toggle to invert paradigm.
- Empty state links to `/admin/invites` if no gestores cadastrados.

---

## 7. Backend Touchpoints

The redesign deliberately keeps backend changes minimal. Multi-tenancy backend is sub-project 2 and out of scope here.

### 7.1 Migration: `002_managers_status.sql`

```sql
ALTER TABLE managers
  ADD COLUMN status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('invited', 'active', 'inactive'));

ALTER TABLE managers
  ADD COLUMN invited_by uuid REFERENCES managers(id),
  ADD COLUMN invited_at timestamptz;

CREATE INDEX idx_managers_status ON managers(status)
  WHERE status IN ('invited', 'inactive');
```

`is_active` is kept (deprecated in favor of `status`) to avoid breaking any existing query during migration. Cleanup can happen in a follow-up.

### 7.2 OAuth callback decision tree

```
callback receives (email, google_id, refresh_token):
│
├─ email does NOT end in @v4company.com
│  └─ redirect /access-denied?reason=domain
│
└─ email ends in @v4company.com
   ├─ exists row in managers WHERE email=email?
   │  ├─ yes, status='active'    → login OK · redirect /
   │  ├─ yes, status='invited'   → flip status='active' · login OK · redirect /
   │  ├─ yes, status='inactive'  → redirect /access-denied?reason=deactivated
   │  └─ does not exist:
   │     ├─ BOOTSTRAP_ADMIN_EMAILS contains email AND managers table is empty
   │     │   → create as admin · login OK
   │     └─ else → redirect /access-denied?reason=not_invited
```

Replaces today's auto-create-on-first-login. Pre-existence in `managers` table (via admin invite) is now required.

### 7.3 New routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/access-denied` | Editorial 403 page; `?reason=domain\|not_invited\|deactivated` |
| GET | `/help` | Onboarding consolidated |
| GET | `/sessions/{id}` | Permanent session detail with reusable snippets |
| GET | `/audit/{id}` | Single audit event detail |
| GET | `/audit/export.csv` | Export current filter as CSV (gestor scope) |
| GET | `/admin` | Admin overview (operação V4 Ads MCP) |
| GET | `/admin/invites` | Pending invites list + add form |
| POST | `/admin/invites/new` | Create `manager(status=invited)` |
| POST | `/admin/invites/{id}/cancel` | Delete the invited row before login |
| POST | `/admin/access/bulk-grant` | `{manager_id, customer_ids[]}` |
| POST | `/admin/access/bulk-copy` | `{from_manager_id, to_manager_id}` |
| GET | `/admin/audit/export.csv` | Global audit CSV export |

### 7.4 Repository functions added

| Repository | Function |
|---|---|
| `managers` | `create_invited(email, full_name?, invited_by)` |
| `managers` | `mark_active(manager_id)` |
| `managers` | `list_invited()` |
| `managers` | `delete_invite(manager_id)` (only if `status='invited'`) |
| `mcp_sessions` | `get_by_id(session_id, manager_id)` (with auth check) |
| `audit_log` | `get_by_id(audit_id, manager_id?)` (gestor: own only; admin: any) |
| `audit_log` | `export_csv(filters)` (streaming response) |
| `audit_log` | `summary_stats(window=24h)` |
| `manager_account_access` | `bulk_grant(manager_id, customer_ids[])` |
| `manager_account_access` | `copy_access(from_manager_id, to_manager_id)` |

### 7.5 Config

New environment variable: `BOOTSTRAP_ADMIN_EMAILS` — comma-separated list. Set in Cloud Run env (not a secret; allowlist only). Triggers auto-create-as-admin only when `managers` table is empty.

### 7.6 Tests added

**Unit (~6):**

- `test_create_invited_marks_status`
- `test_mark_active_only_invited`
- `test_delete_invite_only_if_invited`
- `test_bulk_grant_idempotent`
- `test_copy_access_replaces_destination`
- `test_summary_stats_24h_window`

**Integration (~5):**

- `test_oauth_rejects_not_invited`
- `test_oauth_promotes_invited_to_active`
- `test_oauth_bootstrap_email_when_table_empty`
- `test_oauth_bootstrap_ignored_when_table_populated`
- `test_invite_ui_admin_only`

### 7.7 Existing user impact

The current admin (`wellinton.ribeiro@v4company.com`) has `is_active=true, role='admin'`. Migration adds `status='active'` via DEFAULT. Login continues to work via the "yes, status='active'" branch. Active MCP session remains valid. **Zero user action required.**

---

## 8. Implementation Phases

Approach A — audit-driven, faseado. 6 sequential PRs, each independently mergeable and shippable.

| Phase | Deliverable | Days |
|---|---|---|
| **0** | Audit doc — `docs/operacao/frontend-audit-2026-05.md`. Maps current per-page issues with screenshots, prioritizes findings, captures "before" state for institutional memory. Zero code. | 1-2 |
| **1** | Design system v2. Tailwind CDN config + extended tokens · 6 components refined + 16 new · `_base.html` refactor with new header + admin sub-nav scaffold + mobile drawer. Visually similar to today, but the foundation is set. | 4-6 |
| **2** | Backend Q8 + Invite UI. Migration `002_managers_status` · OAuth allowlist · `BOOTSTRAP_ADMIN_EMAILS` env · routes `/admin/invites`, `/access-denied` (functional, polish in Phase 3) · 11 new tests. **Must ship before inviting real gestores.** | 4-6 |
| **3** | Editorial + Hybrid hero pages. `/login` (hero IA + Google Ads) · `/help` · `/access-denied` polished · `/` dashboard with role-aware extras · `/admin` overview. The "case visual da agência" begins here. | 4-5 |
| **4** | Operational tables. `/audit` (sticky filters, auto-submit, expand row, CSV export, day grouping) · `/audit/{id}` · `/admin/audit` · `/admin/access` matrix with search + bulk + per-gestor mobile paradigm. Heaviest UX gain. | 6-9 |
| **5** | List + detail + final polish. `/accounts` · `/sessions` · `/sessions/{id}` · `/admin/managers` · `/admin/accounts` · `/admin/invites` polish · final visual regression check. | 4-6 |

**Total: 23-34 working days · ~5 weeks for a solo dev.**

### 8.1 Dependencies

- Phase 1 unblocks Phases 3-5 (design system is foundation).
- Phase 2 is independent — can ship before or after Editorial pages, but must be live before inviting real gestores.
- Phases 3-5 are parallelizable in principle but sequential is more predictable for solo dev.
- Phase 0 is optional but recommended (preserves "before" state).

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Tailwind CDN play has limitations vs full | Build escape hatch ready: if blocked, migrate to compiled Tailwind CLI (Phase 1 validates the constraint early) |
| Migration 002 breaks something | DEFAULT='active' preserves all current behavior; DROP COLUMN reverts trivially; test on Supabase staging first |
| `BOOTSTRAP_ADMIN_EMAILS` misconfigured blocks recovery | Document recovery via direct SQL on Supabase in `infra-setup.md` runbook |
| Solo dev burns out on Phase 4 (longest) | Allow splitting Phase 4 into sub-PRs (audit tables first, access matrix second); pause between phases is fine |
| Operations feedback invalidates design during build | Phase 1-2 ship early; let operations test the foundation while Phase 3+ is built; adjust based on real usage |
| Tailwind CDN performance | ~300KB CDN load. Acceptable for internal tool. If it ever feels slow, switch to compiled Tailwind. |

---

## 10. Definition of Done

The redesign is "done" when:

- All 15 pages are redesigned and live in production.
- Q8 allowlist is active — V4's 4000 employees can no longer auto-register.
- The 3 admin pages that today are URL-only have UI links via the admin sub-nav.
- Test suite is green (ruff + mypy + pytest unit + integration via testcontainers).
- Mobile-aware behavior works: tables become card lists, access matrix uses per-gestor paradigm, hamburger nav.
- Design system is documented (token comments in `v4-tokens.css`; component examples in `v4-components.css`).
- One admin other than the original creator can navigate the panel without needing a runbook.

---

## 11. Out of Scope

The following are explicitly NOT part of this redesign. Each is a future sub-project (separate brainstorm + spec + plan):

- **Sub-project 2 — Multi-tenancy backend.** `unidades` table; manager↔unidade vínculo; account↔unidade vínculo; 3-tier RBAC (super-admin / unidade-admin / gestor); permission middleware. UI in this redesign anticipates these (header can show "V4 unidade Maceió", filter by unidade in tables) but the backend can hardcode a single string until sub-project 2 ships.
- **Sub-project 3 — Multi-MCC OAuth + resync.** Each unidade gets its own OAuth connection and MCC. Resync job iterates per unidade. Login customer ID dynamic in the SDK.
- **Sub-project 4 — Migration single → multi.** Backfill: create a default unidade and link existing accounts/managers to it; admin endpoint to create new unidades; validation that everything continues working post-migration.

This redesign also explicitly defers:

- **Dark mode.** Tokens are prepared; implementation ships post-MVP, opt-in only on data-heavy pages.
- **Real-time features.** No WebSockets or SSE. HTMX swaps are sufficient.
- **Deeper accessibility than WCAG AA baseline.** AAA, screen reader optimization, etc., are nice-to-haves.

---

*End of design document.*
