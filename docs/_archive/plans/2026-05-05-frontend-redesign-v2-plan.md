# V4 Ads MCP — Frontend Redesign v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign 15 pages of the V4 Ads MCP web panel into a Hybrid Editorial+Operational identity that scales for multi-unidade Brasil (3-5 unidades, 30-100 gestores), shipping in 6 sequential phases with TDD discipline.

**Architecture:** Plain Jinja2 templates extended with Tailwind via CDN (no build step) plus HTMX for inline interactivity. V4 design tokens drive Tailwind config. Backend touchpoints minimal: 1 migration (`managers.status` for Q8 allowlist), OAuth callback decision tree, 12 new routes, ~10 new repository functions. Mobile-aware via Tailwind breakpoints with paradigm shifts on the access matrix.

**Tech Stack:** Python 3.12+ · FastAPI · Jinja2 · Tailwind CDN play · HTMX 2.x · asyncpg · pytest + testcontainers · ruff + mypy · Cloud Run

**Spec reference:** `docs/superpowers/specs/2026-05-05-frontend-redesign-v2-design.md`

---

## File Structure

### Files to CREATE

| Path | Responsibility |
|---|---|
| `docs/operacao/frontend-audit-2026-05.md` | Phase 0 audit deliverable |
| `src/web/static/v4-motion.css` | Motion tokens + transitions |
| `src/web/templates/admin/_subnav.html` | Admin sub-nav partial |
| `src/web/templates/access_denied.html` | Q8 — invite-only landing |
| `src/web/templates/help.html` | Onboarding consolidated |
| `src/web/templates/sessions/detail.html` | Permanent session view |
| `src/web/templates/audit_detail.html` | Single audit event |
| `src/web/templates/admin/index.html` | Admin visão geral |
| `src/web/templates/admin/invites.html` | Q8 invite UI |
| `src/db/migrations/002_managers_status.sql` | `status` column + indexes |

### Files to MODIFY

| Path | Reason |
|---|---|
| `src/web/static/v4-tokens.css` | Add display token, soft bgs, motion, operational, z-index |
| `src/web/static/v4-base.css` | Refactor header for sub-nav slot, mobile drawer hooks |
| `src/web/static/v4-components.css` | New variants on existing components |
| `src/web/templates/_base.html` | Tailwind CDN config, header restructure, sub-nav slot, drawer |
| `src/web/templates/_components.html` | Add 16 new macros |
| `src/web/templates/login.html` | Editorial hero |
| `src/web/templates/dashboard.html` | Hybrid hero + role-aware admin extras |
| `src/web/templates/accounts.html` | Search + filter + revoke flow |
| `src/web/templates/sessions/list.html` | Form colapsável + confirm dialog |
| `src/web/templates/sessions/_table.html` | Compact rows, dropdown ⋯ |
| `src/web/templates/sessions/created.html` | Removed — flow redirects to detail |
| `src/web/templates/audit.html` | Sticky filters + auto-submit + expand row + CSV |
| `src/web/templates/admin/managers.html` | Search + dropdown ⋯ + confirm dialog |
| `src/web/templates/admin/accounts.html` | Search + filter MCC |
| `src/web/templates/admin/access.html` | Search + bulk + per-gestor mobile route |
| `src/web/templates/admin/audit.html` | Same as `/audit` plus extra filters |
| `src/auth/oauth.py` | Allowlist decision tree |
| `src/db/repositories/managers.py` | invite lifecycle |
| `src/db/repositories/mcp_sessions.py` | get_by_id |
| `src/db/repositories/audit_log.py` | get_by_id, export_csv, summary_stats |
| `src/db/repositories/manager_account_access.py` | bulk_grant, copy_access |
| `src/web/routes.py` | 10+ new route handlers |
| `src/config.py` | `BOOTSTRAP_ADMIN_EMAILS` env |
| `tests/unit/test_managers.py` | Invite-related tests |
| `tests/integration/test_oauth_allowlist.py` | New test file |

---

## Phase 0 — Audit Doc (1-2 days)

Goal: capture the "before" state for institutional memory and to inform per-page redesign decisions.

### Task 0.1: Capture screenshots of all current pages

**Files:**
- Create: `docs/operacao/screenshots/before/` (directory)

- [ ] **Step 1: Login as admin (wellinton.ribeiro@v4company.com) on production**

Run in browser: navigate to `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/login`. Click "Entrar com Google V4". Complete OAuth.

- [ ] **Step 2: Take desktop screenshots (1440px wide) of every page**

Pages to capture:
- `/login` (logged out — open incognito)
- `/` (dashboard, admin view)
- `/accounts`
- `/sessions` (with at least 1 session)
- `/sessions/new` form filled (transient — re-create a test session)
- `/audit` (showing real events)
- `/admin/managers`
- `/admin/accounts`
- `/admin/access`
- `/admin/audit`

Save each as `docs/operacao/screenshots/before/desktop-<page>.png` (replace `/` with `-`).

- [ ] **Step 3: Take mobile screenshots (375px wide via DevTools device toolbar)**

Same 9 pages, save as `docs/operacao/screenshots/before/mobile-<page>.png`.

- [ ] **Step 4: Commit screenshots**

```bash
git add docs/operacao/screenshots/before/
git commit -m "docs(audit): capture before-state screenshots for FE redesign v2 baseline"
```

### Task 0.2: Write audit doc

**Files:**
- Create: `docs/operacao/frontend-audit-2026-05.md`

- [ ] **Step 1: Write the doc using this skeleton + per-page findings**

Create the file with this exact structure:

```markdown
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
```

- [ ] **Step 2: Verify file exists and is well-formed**

Run: `ls -la docs/operacao/frontend-audit-2026-05.md`
Expected: file exists, ~7-9KB.

- [ ] **Step 3: Commit the audit doc**

```bash
git add docs/operacao/frontend-audit-2026-05.md
git commit -m "docs(audit): Phase 0 — current frontend state findings"
```

### Task 0.3: Verify Phase 0 done

- [ ] **Step 1: Confirm both deliverables on disk**

Run:
```bash
ls -la docs/operacao/frontend-audit-2026-05.md
ls docs/operacao/screenshots/before/ | wc -l
```

Expected: doc exists; ~18 screenshots (9 desktop + 9 mobile).

- [ ] **Step 2: Push Phase 0 to origin**

```bash
git push origin main
```

Expected: CI runs (no code changed; lint+mypy+tests still pass on existing code) + Deploy is no-op (Docker image identical).

---

## Phase 1 — Design System v2 (4-6 days)

Goal: extend V4 tokens with motion + display + soft + operational; integrate Tailwind via CDN with V4 token bridge; refine 6 existing components and add 16 new ones; refactor `_base.html` for header + admin sub-nav slot + mobile drawer.

### Task 1.1: Add new design tokens

**Files:**
- Modify: `src/web/static/v4-tokens.css`
- Create: `src/web/static/v4-motion.css`

- [ ] **Step 1: Append new tokens to v4-tokens.css**

Edit `src/web/static/v4-tokens.css`. Insert these blocks before the closing `}` of `:root`:

```css
  /* Display (Editorial hero) */
  --v4-display-size: 56px;
  --v4-display-weight: 800;
  --v4-display-line: 1.0;
  --v4-display-track: -0.025em;

  /* Soft backgrounds (alerts, badges without alarm tone) */
  --v4-red-soft:   #fde2e4;
  --v4-green-soft: #e8f7ea;
  --v4-gold-soft:  #fff7e0;

  /* Operational density */
  --v4-row-height-compact: 36px;
  --v4-cell-pad-compact: 8px 12px;
  --v4-border-subtle: 1px solid var(--v4-gray-100);

  /* Z-index scale */
  --v4-z-base:     1;
  --v4-z-sticky:   10;
  --v4-z-dropdown: 100;
  --v4-z-modal:    1000;
  --v4-z-toast:    1100;

  /* Motion */
  --v4-motion-fast: 100ms;
  --v4-motion-base: 180ms;
  --v4-motion-slow: 320ms;
  --v4-ease-out:    cubic-bezier(0.2, 0.8, 0.2, 1);
  --v4-ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
```

- [ ] **Step 2: Create `src/web/static/v4-motion.css` with reusable utility classes**

```css
/* V4 motion utilities — apply via class for transitions/animations */

.v4-fade-in {
  animation: v4-fade-in var(--v4-motion-base) var(--v4-ease-out);
}
@keyframes v4-fade-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

.v4-slide-up {
  animation: v4-slide-up var(--v4-motion-slow) var(--v4-ease-spring);
}
@keyframes v4-slide-up {
  from { opacity: 0; transform: translateY(16px); }
  to   { opacity: 1; transform: translateY(0); }
}

.v4-pulse {
  animation: v4-pulse 2s var(--v4-ease-out) infinite;
}
@keyframes v4-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.5; }
}

/* HTMX-aware: indicate loading on htmx-request */
.htmx-indicator { opacity: 0; transition: opacity var(--v4-motion-base); }
.htmx-request .htmx-indicator { opacity: 1; }
.htmx-request.htmx-indicator { opacity: 1; }

/* Skeleton shimmer */
.v4-skeleton {
  background: linear-gradient(90deg,
    var(--v4-gray-100) 0%,
    var(--v4-gray-50) 50%,
    var(--v4-gray-100) 100%);
  background-size: 200% 100%;
  animation: v4-skeleton-shimmer 1.4s var(--v4-ease-out) infinite;
  border-radius: var(--v4-radius-sm);
}
@keyframes v4-skeleton-shimmer {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}
```

- [ ] **Step 3: Add link to `v4-motion.css` in `_base.html` `<head>`**

Edit `src/web/templates/_base.html`. After the line `<link rel="stylesheet" href="/static/v4-components.css">`, add:

```html
  <link rel="stylesheet" href="/static/v4-motion.css">
```

- [ ] **Step 4: Manually verify by loading `/login` in browser**

Run service locally (or wait for next deploy). Verify no CSS errors in console. View source — `v4-motion.css` should load with 200.

- [ ] **Step 5: Commit**

```bash
git add src/web/static/v4-tokens.css src/web/static/v4-motion.css src/web/templates/_base.html
git commit -m "feat(design-system): add display/soft/motion/z-index tokens + motion utilities"
```

### Task 1.2: Add Tailwind CDN config to `_base.html`

**Files:**
- Modify: `src/web/templates/_base.html`

- [ ] **Step 1: Insert Tailwind CDN script before `</head>`**

Edit `src/web/templates/_base.html`. Replace the existing `<script src="https://unpkg.com/htmx.org@2.0.3" defer></script>` line with this block:

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
          fontSize: {
            'display': ['56px', { lineHeight: '1.0', letterSpacing: '-0.025em' }],
          },
          transitionTimingFunction: {
            'v4-out':    'cubic-bezier(0.2, 0.8, 0.2, 1)',
            'v4-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
          },
        }
      }
    }
  </script>
  <script src="https://unpkg.com/htmx.org@2.0.3" defer></script>
```

- [ ] **Step 2: Reload `/login` and test a Tailwind utility**

Open browser DevTools console. Run:
```js
const el = document.createElement('div');
el.className = 'bg-v4-red text-white p-4 rounded-md';
el.textContent = 'Tailwind test';
document.body.appendChild(el);
```
Expected: red box with white text appears at the bottom of the page.

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/_base.html
git commit -m "feat(design-system): integrate Tailwind via CDN with V4 token bridge"
```

### Task 1.3: Refactor `_base.html` header + add admin sub-nav slot

**Files:**
- Modify: `src/web/templates/_base.html`
- Create: `src/web/templates/admin/_subnav.html`

- [ ] **Step 1: Create the admin sub-nav partial**

Create `src/web/templates/admin/_subnav.html`:

```html
{# Admin sub-nav · rendered only when on /admin/* routes #}
<nav class="v4-subnav" aria-label="Admin">
  <a href="/admin"
     class="v4-subnav__link {% if request.url.path == '/admin' %}is-active{% endif %}">Visão geral</a>
  <a href="/admin/managers"
     class="v4-subnav__link {% if request.url.path == '/admin/managers' %}is-active{% endif %}">Managers</a>
  <a href="/admin/invites"
     class="v4-subnav__link {% if request.url.path == '/admin/invites' %}is-active{% endif %}">
    Convites{% if pending_invites_count and pending_invites_count > 0 %}
      <span class="v4-badge v4-badge--counter">{{ pending_invites_count }}</span>
    {% endif %}
  </a>
  <a href="/admin/accounts"
     class="v4-subnav__link {% if request.url.path == '/admin/accounts' %}is-active{% endif %}">Contas</a>
  <a href="/admin/access"
     class="v4-subnav__link {% if request.url.path.startswith('/admin/access') %}is-active{% endif %}">Acessos</a>
  <a href="/admin/audit"
     class="v4-subnav__link {% if request.url.path == '/admin/audit' %}is-active{% endif %}">Audit global</a>
</nav>
```

- [ ] **Step 2: Update `_base.html` to render sub-nav block conditionally**

Edit `src/web/templates/_base.html`. Locate the `<header class="v4-header">...</header>` block. Immediately AFTER `</header>`, insert:

```html
{% if current_user and current_user.is_admin and request.url.path.startswith('/admin') %}
  {% include "admin/_subnav.html" %}
{% endif %}
```

- [ ] **Step 3: Add CSS for `.v4-subnav` to `v4-base.css`**

Append to `src/web/static/v4-base.css`:

```css
/* Admin sub-nav */
.v4-subnav {
  background: var(--v4-gray-50);
  border-bottom: 1px solid var(--v4-gray-100);
  padding: var(--v4-space-3) var(--v4-space-4);
  display: flex;
  gap: var(--v4-space-4);
  align-items: center;
  position: sticky;
  top: 53px; /* below header — header is ~52px */
  z-index: var(--v4-z-sticky);
  font-size: 13px;
  overflow-x: auto;
}
.v4-subnav__link {
  color: var(--v4-gray-700);
  text-decoration: none;
  font-weight: 500;
  white-space: nowrap;
  padding: var(--v4-space-1) 0;
  border-bottom: 2px solid transparent;
  transition: border-color var(--v4-motion-fast) var(--v4-ease-out),
              color var(--v4-motion-fast) var(--v4-ease-out);
}
.v4-subnav__link:hover {
  color: var(--v4-gray-900);
  text-decoration: none;
}
.v4-subnav__link.is-active {
  color: var(--v4-red);
  border-bottom-color: var(--v4-red);
}
```

- [ ] **Step 4: Add a `pending_invites_count` context provider**

Edit `src/web/deps.py`. Find the existing `current_manager` dependency or template context handler. Add a new lightweight dependency that admin pages can use to populate the counter.

For now, add a simple helper at the bottom of `src/web/deps.py`:

```python
async def pending_invites_count() -> int:
    """Lightweight count for the sub-nav badge. Returns 0 if table empty or feature off."""
    from src.db import connection
    from src.db.repositories import managers
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Will be implemented in Task 2.5; for now return 0 to keep the badge hidden.
        return 0
```

In `src/web/routes.py`, locate the `/admin/managers` GET handler. Update its template render to include `pending_invites_count`:

```python
return templates.TemplateResponse(
    request,
    "admin/managers.html",
    {
        "current_user": user,
        "managers": managers_data,
        "pending_invites_count": 0,  # populated in Task 2.5
    },
)
```

Apply the same `pending_invites_count: 0` to all existing admin route renders (`/admin/accounts`, `/admin/access`, `/admin/audit`). Phase 2 will replace this with the real query.

- [ ] **Step 5: Manual visual check**

Visit `/admin/managers`. Expect: header at top, then `.v4-subnav` sticky below it with 6 links, "Managers" highlighted in V4 red with underline. "Convites" has no badge yet (count = 0).

- [ ] **Step 6: Commit**

```bash
git add src/web/templates/_base.html src/web/templates/admin/_subnav.html src/web/static/v4-base.css src/web/deps.py src/web/routes.py
git commit -m "feat(web): admin sub-nav + active state + counter slot"
```

### Task 1.4: Add mobile drawer scaffold to `_base.html`

**Files:**
- Modify: `src/web/templates/_base.html`
- Modify: `src/web/static/v4-base.css`

- [ ] **Step 1: Add hamburger button + drawer markup**

Edit `src/web/templates/_base.html`. Inside `<header class="v4-header">`, BEFORE the `<a class="v4-header__brand">` link, add:

```html
    <button class="v4-header__hamburger" type="button" aria-label="Abrir menu" aria-controls="mobile-drawer" aria-expanded="false" onclick="toggleDrawer()">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h16M4 18h16"/></svg>
    </button>
```

After `</header>` (and after the conditional sub-nav), insert:

```html
<div id="mobile-drawer" class="v4-drawer" role="dialog" aria-hidden="true" aria-label="Menu">
  <div class="v4-drawer__backdrop" onclick="toggleDrawer()"></div>
  <nav class="v4-drawer__panel" aria-label="Mobile">
    {% if current_user %}
      <div class="v4-drawer__section">
        <a href="/" class="v4-drawer__link">Dashboard</a>
        <a href="/accounts" class="v4-drawer__link">Contas</a>
        <a href="/sessions" class="v4-drawer__link">Sessões</a>
        <a href="/audit" class="v4-drawer__link">Audit</a>
        <a href="/help" class="v4-drawer__link">Help</a>
      </div>
      {% if current_user.is_admin %}
      <div class="v4-drawer__section">
        <div class="v4-drawer__heading">Admin</div>
        <a href="/admin" class="v4-drawer__link">Visão geral</a>
        <a href="/admin/managers" class="v4-drawer__link">Managers</a>
        <a href="/admin/invites" class="v4-drawer__link">Convites</a>
        <a href="/admin/accounts" class="v4-drawer__link">Contas</a>
        <a href="/admin/access" class="v4-drawer__link">Acessos</a>
        <a href="/admin/audit" class="v4-drawer__link">Audit global</a>
      </div>
      {% endif %}
      <div class="v4-drawer__section">
        <div class="v4-drawer__heading">{{ current_user.email }}</div>
        <a href="/logout" class="v4-drawer__link">Sair</a>
      </div>
    {% endif %}
  </nav>
</div>
<script>
  function toggleDrawer() {
    const drawer = document.getElementById('mobile-drawer');
    const isOpen = drawer.classList.toggle('is-open');
    drawer.setAttribute('aria-hidden', String(!isOpen));
    document.querySelector('.v4-header__hamburger')?.setAttribute('aria-expanded', String(isOpen));
    document.body.style.overflow = isOpen ? 'hidden' : '';
  }
</script>
```

- [ ] **Step 2: Add drawer + hamburger CSS to v4-base.css**

Append to `src/web/static/v4-base.css`:

```css
/* Hamburger — visible only on mobile */
.v4-header__hamburger {
  background: transparent;
  border: 0;
  padding: var(--v4-space-2);
  cursor: pointer;
  color: var(--v4-gray-700);
  display: none;
}
@media (max-width: 767px) {
  .v4-header__hamburger { display: block; }
  .v4-header__nav { display: none; }
}

/* Mobile drawer */
.v4-drawer {
  position: fixed;
  inset: 0;
  z-index: var(--v4-z-modal);
  pointer-events: none;
  visibility: hidden;
}
.v4-drawer.is-open { pointer-events: auto; visibility: visible; }

.v4-drawer__backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.4);
  opacity: 0;
  transition: opacity var(--v4-motion-base) var(--v4-ease-out);
}
.v4-drawer.is-open .v4-drawer__backdrop { opacity: 1; }

.v4-drawer__panel {
  position: absolute;
  top: 0; left: 0; bottom: 0;
  width: min(85vw, 320px);
  background: var(--v4-white);
  padding: var(--v4-space-6) var(--v4-space-4);
  transform: translateX(-100%);
  transition: transform var(--v4-motion-slow) var(--v4-ease-out);
  overflow-y: auto;
}
.v4-drawer.is-open .v4-drawer__panel { transform: translateX(0); }

.v4-drawer__section { margin-bottom: var(--v4-space-6); }
.v4-drawer__heading {
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--v4-gray-300); font-weight: 600;
  margin-bottom: var(--v4-space-2);
}
.v4-drawer__link {
  display: block;
  padding: var(--v4-space-3) 0;
  color: var(--v4-gray-900);
  font-size: 15px;
  font-weight: 500;
  border-bottom: 1px solid var(--v4-gray-50);
  text-decoration: none;
}
.v4-drawer__link:hover { color: var(--v4-red); text-decoration: none; }
```

- [ ] **Step 3: Manually test mobile drawer**

Open `/` in browser. Resize window to <768px (or use DevTools mobile mode). Click hamburger — drawer slides in from left with backdrop. Click backdrop — closes. Verify keyboard accessibility (focus on hamburger, Enter opens; Tab cycles through drawer links).

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/_base.html src/web/static/v4-base.css
git commit -m "feat(web): mobile drawer with hamburger nav for <md screens"
```

### Task 1.5: Refine Button component (+ ghost, icon-only, loading)

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append new button variants to v4-components.css**

```css
/* Button — ghost + icon-only + loading */
.v4-btn--ghost {
  background: transparent;
  color: var(--v4-gray-700);
  border: 0;
}
.v4-btn--ghost:hover {
  background: var(--v4-gray-50);
  color: var(--v4-gray-900);
}

.v4-btn--icon {
  padding: 8px;
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.v4-btn[data-loading="true"] {
  position: relative;
  color: transparent !important;
  pointer-events: none;
}
.v4-btn[data-loading="true"]::after {
  content: '';
  position: absolute;
  inset: 50% 0 0 50%;
  width: 14px;
  height: 14px;
  margin: -7px 0 0 -7px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  color: var(--v4-white);
  animation: v4-btn-spin 0.6s linear infinite;
}
.v4-btn--secondary[data-loading="true"]::after,
.v4-btn--ghost[data-loading="true"]::after {
  color: var(--v4-gray-700);
}
@keyframes v4-btn-spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 2: Add `button(...)` macro to `_components.html`**

Append to `src/web/templates/_components.html`:

```jinja
{% macro button(label, variant="primary", size="md", type="button", loading=false, icon=None, extra_classes="", attrs="") %}
  {%- set classes = "v4-btn v4-btn--" ~ variant -%}
  {%- if size == "small" %}{% set classes = classes ~ " v4-btn--small" %}{% endif -%}
  {%- if icon and not label %}{% set classes = classes ~ " v4-btn--icon" %}{% endif -%}
  {%- if extra_classes %}{% set classes = classes ~ " " ~ extra_classes %}{% endif -%}
  <button type="{{ type }}" class="{{ classes }}"{% if loading %} data-loading="true"{% endif %} {{ attrs|safe }}>
    {%- if icon %}<span class="v4-btn__icon" aria-hidden="true">{{ icon|safe }}</span>{% endif -%}
    {%- if label %}<span class="v4-btn__label">{{ label }}</span>{% endif -%}
  </button>
{% endmacro %}
```

- [ ] **Step 3: Visual smoke test**

Render `/login` with browser. Inspect any `.v4-btn`. Add `data-loading="true"` via DevTools — spinner appears centered, label disappears.

- [ ] **Step 4: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): button ghost + icon-only + loading variants"
```

### Task 1.6: Refine Card component (+ compact)

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append compact card variant CSS**

```css
.v4-card--compact {
  padding: var(--v4-space-4);
  border-radius: var(--v4-radius-md);
}
.v4-card--compact .v4-card__header {
  margin-bottom: var(--v4-space-3);
}
.v4-card--compact .v4-card__title {
  font-size: var(--v4-h4-size);
}

.v4-card--highlighted {
  border-left: 3px solid var(--v4-red);
}
```

- [ ] **Step 2: Add `card(...)` macro**

Append to `_components.html`:

```jinja
{% macro card(title=None, action=None, variant="default", body="") %}
  {%- set classes = "v4-card" -%}
  {%- if variant != "default" %}{% set classes = classes ~ " v4-card--" ~ variant %}{% endif -%}
  <div class="{{ classes }}">
    {% if title or action %}
    <div class="v4-card__header">
      {% if title %}<h3 class="v4-card__title">{{ title }}</h3>{% endif %}
      {% if action %}<div class="v4-card__action">{{ action|safe }}</div>{% endif %}
    </div>
    {% endif %}
    {{ body|safe }}
  </div>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): card compact + highlighted variants"
```

### Task 1.7: Refine Badge component (+ counter)

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append counter badge CSS**

```css
.v4-badge--counter {
  background: var(--v4-gold);
  color: var(--v4-gray-900);
  border-radius: 999px;
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  text-transform: none;
  letter-spacing: 0;
}

.v4-badge--icon {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.v4-badge--icon svg {
  width: 12px;
  height: 12px;
}
```

- [ ] **Step 2: Update existing `badge(...)` macro to support counter + icon**

Replace the `{% macro badge(...) %}` definition in `_components.html` with:

```jinja
{% macro badge(text, kind="neutral", icon=None) %}
  {%- set classes = "v4-badge v4-badge--" ~ kind -%}
  {%- if icon %}{% set classes = classes ~ " v4-badge--icon" %}{% endif -%}
  <span class="{{ classes }}">
    {%- if icon %}{{ icon|safe }}{% endif -%}
    {{ text }}
  </span>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): badge counter + icon variants"
```

### Task 1.8: Refine Alert component (+ success)

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append success alert CSS**

```css
.v4-alert--success {
  background: var(--v4-green-soft);
  border-left-color: var(--v4-green);
  color: #1a5b22;
}
```

- [ ] **Step 2: Update existing `alert(...)` macro to support optional title**

Replace the `{% macro alert(...) %}` block in `_components.html`:

```jinja
{% macro alert(message, kind="info", title=None) %}
<div class="v4-alert v4-alert--{{ kind }}" role="alert">
  {% if title %}<div class="v4-alert__title">{{ title }}</div>{% endif %}
  <div class="v4-alert__body">{{ message|safe }}</div>
</div>
{% endmacro %}
```

Add the title styling to v4-components.css:

```css
.v4-alert__title {
  font-weight: 600;
  margin-bottom: var(--v4-space-1);
}
.v4-alert__body { line-height: 1.5; }
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): alert success variant + optional title"
```

### Task 1.9: Refine Form inputs (+ search/textarea/checkbox/radio)

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append input variant CSS**

```css
.v4-input--search {
  padding-left: 36px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23999' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: 10px center;
  background-size: 18px;
}

.v4-textarea {
  width: 100%;
  padding: 10px 14px;
  font-family: var(--v4-font-body);
  font-size: var(--v4-body-size);
  color: var(--v4-gray-900);
  background: var(--v4-white);
  border: 1px solid var(--v4-gray-200);
  border-radius: var(--v4-radius-md);
  resize: vertical;
  min-height: 80px;
}
.v4-textarea:focus {
  outline: none;
  border-color: var(--v4-red);
  box-shadow: 0 0 0 3px rgba(229, 9, 20, 0.1);
}

.v4-check, .v4-radio {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}
.v4-check input, .v4-radio input {
  width: 18px;
  height: 18px;
  accent-color: var(--v4-red);
  margin: 0;
}
```

- [ ] **Step 2: Add macros for search, textarea, check, radio**

Append to `_components.html`:

```jinja
{% macro search_input(name, value="", placeholder="Buscar...", attrs="") %}
<input type="search" name="{{ name }}" class="v4-input v4-input--search"
       value="{{ value }}" placeholder="{{ placeholder }}" {{ attrs|safe }}>
{% endmacro %}

{% macro textarea(name, value="", placeholder="", rows=4, attrs="") %}
<textarea name="{{ name }}" class="v4-textarea" rows="{{ rows }}"
          placeholder="{{ placeholder }}" {{ attrs|safe }}>{{ value }}</textarea>
{% endmacro %}

{% macro checkbox(name, label, checked=false, value="true", attrs="") %}
<label class="v4-check">
  <input type="checkbox" name="{{ name }}" value="{{ value }}"
         {% if checked %}checked{% endif %} {{ attrs|safe }}>
  <span>{{ label }}</span>
</label>
{% endmacro %}

{% macro radio(name, label, value, checked=false, attrs="") %}
<label class="v4-radio">
  <input type="radio" name="{{ name }}" value="{{ value }}"
         {% if checked %}checked{% endif %} {{ attrs|safe }}>
  <span>{{ label }}</span>
</label>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): search input + textarea + checkbox + radio"
```

### Task 1.10: Add `form_group` macro for consistent label+input

**Files:**
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Add form_group macro**

Append to `_components.html`:

```jinja
{% macro form_group(label, name, type="text", value="", placeholder="", required=false, help=None, error=None) %}
<div class="v4-form__group">
  <label class="v4-form__label" for="{{ name }}">{{ label }}{% if required %} *{% endif %}</label>
  {% if type == "textarea" %}
    <textarea id="{{ name }}" name="{{ name }}" class="v4-textarea" placeholder="{{ placeholder }}"
              {% if required %}required{% endif %}>{{ value }}</textarea>
  {% else %}
    <input id="{{ name }}" name="{{ name }}" type="{{ type }}" class="v4-input" value="{{ value }}"
           placeholder="{{ placeholder }}" {% if required %}required{% endif %}>
  {% endif %}
  {% if help and not error %}<div class="v4-form__help">{{ help }}</div>{% endif %}
  {% if error %}<div class="v4-form__error">{{ error }}</div>{% endif %}
</div>
{% endmacro %}
```

Add CSS for help + error to v4-components.css:

```css
.v4-form__help {
  margin-top: var(--v4-space-1);
  font-size: 12px;
  color: var(--v4-gray-300);
}
.v4-form__error {
  margin-top: var(--v4-space-1);
  font-size: 12px;
  color: var(--v4-red);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/web/templates/_components.html src/web/static/v4-components.css
git commit -m "feat(design-system): form_group macro consolidating label+input+help+error"
```

### Task 1.11: Add Sparkline component

**Files:**
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Add sparkline macro**

Append to `_components.html`:

```jinja
{% macro sparkline(values, width=60, height=16, color="var(--v4-red)") %}
  {%- if values and values|length > 1 -%}
    {%- set vmax = values|max -%}
    {%- set vmin = values|min -%}
    {%- set span = (vmax - vmin) if vmax != vmin else 1 -%}
    {%- set step = width / (values|length - 1) -%}
    {%- set ns = namespace(points=[]) -%}
    {%- for v in values -%}
      {%- set x = loop.index0 * step -%}
      {%- set y = height - ((v - vmin) / span) * height -%}
      {%- set ns.points = ns.points + [(x|round(2)) ~ "," ~ (y|round(2))] -%}
    {%- endfor -%}
    <svg class="v4-sparkline" viewBox="0 0 {{ width }} {{ height }}"
         width="{{ width }}" height="{{ height }}" aria-hidden="true">
      <polyline points="{{ ns.points|join(' ') }}"
                fill="none" stroke="{{ color }}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>
  {%- endif -%}
{% endmacro %}
```

- [ ] **Step 2: Commit**

```bash
git add src/web/templates/_components.html
git commit -m "feat(design-system): sparkline component (inline SVG)"
```

### Task 1.12: Add Pagination component

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append pagination CSS**

```css
.v4-pagination {
  display: flex;
  gap: var(--v4-space-1);
  align-items: center;
  padding: var(--v4-space-3) 0;
  font-size: 13px;
}
.v4-pagination__info {
  margin-right: auto;
  color: var(--v4-gray-300);
}
.v4-pagination__btn {
  background: transparent;
  border: 1px solid var(--v4-gray-200);
  color: var(--v4-gray-900);
  padding: 6px 10px;
  border-radius: var(--v4-radius-sm);
  font-size: 13px;
  cursor: pointer;
}
.v4-pagination__btn:hover { background: var(--v4-gray-50); }
.v4-pagination__btn:disabled { opacity: 0.4; cursor: not-allowed; }
.v4-pagination__btn.is-current {
  background: var(--v4-gray-900);
  color: var(--v4-white);
  border-color: var(--v4-gray-900);
}
```

- [ ] **Step 2: Add pagination macro**

Append to `_components.html`:

```jinja
{% macro pagination(current, total, base_url, query_param="page") %}
  {%- if total > 1 -%}
  <nav class="v4-pagination" aria-label="Paginação">
    <span class="v4-pagination__info">Página {{ current }} de {{ total }}</span>
    {% set prev = current - 1 %}
    {% set next = current + 1 %}
    {%- if prev >= 1 -%}
      <a class="v4-pagination__btn" href="{{ base_url }}?{{ query_param }}={{ prev }}">‹ Anterior</a>
    {%- else -%}
      <button class="v4-pagination__btn" disabled>‹ Anterior</button>
    {%- endif -%}
    {%- if next <= total -%}
      <a class="v4-pagination__btn" href="{{ base_url }}?{{ query_param }}={{ next }}">Próxima ›</a>
    {%- else -%}
      <button class="v4-pagination__btn" disabled>Próxima ›</button>
    {%- endif -%}
  </nav>
  {%- endif -%}
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): pagination component"
```

### Task 1.13: Add Code Block component (with copy button)

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append code block CSS**

```css
.v4-code-block {
  position: relative;
  background: var(--v4-gray-900);
  color: var(--v4-white);
  border-radius: var(--v4-radius-md);
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow: hidden;
}
.v4-code-block__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: var(--v4-gray-800);
  padding: var(--v4-space-2) var(--v4-space-3);
  font-size: 11px;
  color: var(--v4-gray-300);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.v4-code-block__copy {
  background: transparent;
  color: var(--v4-gray-300);
  border: 1px solid var(--v4-gray-700);
  padding: 2px 8px;
  font-size: 11px;
  border-radius: var(--v4-radius-sm);
  cursor: pointer;
}
.v4-code-block__copy:hover { color: var(--v4-white); border-color: var(--v4-gray-300); }
.v4-code-block pre {
  margin: 0;
  padding: var(--v4-space-3);
  background: transparent;
  color: inherit;
  border: 0;
  overflow-x: auto;
}
```

- [ ] **Step 2: Add code_block macro**

Append to `_components.html`:

```jinja
{% macro code_block(content, language=None, filename=None) %}
{% set block_id = "code-" ~ (range(100000, 999999) | random) %}
<div class="v4-code-block" id="{{ block_id }}">
  <div class="v4-code-block__header">
    <span>{% if filename %}{{ filename }}{% elif language %}{{ language }}{% else %}snippet{% endif %}</span>
    <button class="v4-code-block__copy" type="button"
            onclick="
              const code = document.getElementById('{{ block_id }}').querySelector('pre').innerText;
              navigator.clipboard.writeText(code);
              this.innerText = 'Copiado!';
              setTimeout(() => this.innerText = 'Copiar', 2000);
            ">Copiar</button>
  </div>
  <pre><code>{{ content }}</code></pre>
</div>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): code block with copy button + filename"
```

### Task 1.14: Add Empty State component

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append empty state CSS**

```css
.v4-empty {
  text-align: center;
  padding: var(--v4-space-12) var(--v4-space-4);
  color: var(--v4-gray-300);
}
.v4-empty__icon {
  width: 48px;
  height: 48px;
  margin: 0 auto var(--v4-space-4);
  color: var(--v4-gray-200);
}
.v4-empty__title {
  font-size: var(--v4-h4-size);
  font-weight: 600;
  color: var(--v4-gray-700);
  margin: 0 0 var(--v4-space-2);
}
.v4-empty__body {
  font-size: 14px;
  margin-bottom: var(--v4-space-4);
}
```

- [ ] **Step 2: Add empty_state macro**

Append to `_components.html`:

```jinja
{% macro empty_state(title, body=None, icon=None, action=None) %}
<div class="v4-empty">
  {% if icon %}<div class="v4-empty__icon">{{ icon|safe }}</div>{% endif %}
  <div class="v4-empty__title">{{ title }}</div>
  {% if body %}<div class="v4-empty__body">{{ body|safe }}</div>{% endif %}
  {% if action %}<div>{{ action|safe }}</div>{% endif %}
</div>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): empty state component with icon + action slot"
```

### Task 1.15: Add Toast component (HTMX-aware)

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_base.html`

- [ ] **Step 1: Append toast CSS**

```css
.v4-toast-region {
  position: fixed;
  bottom: var(--v4-space-6);
  right: var(--v4-space-6);
  z-index: var(--v4-z-toast);
  display: flex;
  flex-direction: column;
  gap: var(--v4-space-2);
  pointer-events: none;
}
.v4-toast {
  background: var(--v4-gray-900);
  color: var(--v4-white);
  padding: var(--v4-space-3) var(--v4-space-4);
  border-radius: var(--v4-radius-md);
  font-size: 13px;
  box-shadow: var(--v4-shadow-modal);
  pointer-events: auto;
  animation: v4-toast-in var(--v4-motion-base) var(--v4-ease-spring) forwards;
  max-width: 360px;
}
.v4-toast--success { background: #1a5b22; }
.v4-toast--error   { background: var(--v4-red-medium); }
@keyframes v4-toast-in {
  from { opacity: 0; transform: translateX(20px); }
  to   { opacity: 1; transform: translateX(0); }
}
.v4-toast.is-leaving { animation: v4-toast-out var(--v4-motion-base) var(--v4-ease-out) forwards; }
@keyframes v4-toast-out {
  to { opacity: 0; transform: translateX(20px); }
}
```

- [ ] **Step 2: Add toast container + JS helper to `_base.html`**

In `src/web/templates/_base.html`, immediately before `</body>`, add:

```html
<div class="v4-toast-region" id="v4-toast-region" aria-live="polite" aria-atomic="true"></div>
<script>
  function showToast(message, kind) {
    kind = kind || 'success';
    const region = document.getElementById('v4-toast-region');
    const toast = document.createElement('div');
    toast.className = 'v4-toast v4-toast--' + kind;
    toast.textContent = message;
    region.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('is-leaving');
      setTimeout(() => toast.remove(), 200);
    }, 3500);
  }
  // HTMX hook: server can return HX-Trigger: {"toast": {"message": "...", "kind": "success"}}
  document.body.addEventListener('toast', (e) => showToast(e.detail.message, e.detail.kind));
</script>
```

- [ ] **Step 3: Test in browser**

DevTools console: `showToast('Acesso liberado', 'success')` — toast appears bottom-right with green tint, fades after 3.5s.

- [ ] **Step 4: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_base.html
git commit -m "feat(design-system): toast region + HTMX HX-Trigger integration"
```

### Task 1.16: Add Skeleton loader component

**Files:**
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Add skeleton macros**

Skeleton CSS (`v4-skeleton` + shimmer) is already in `v4-motion.css` (Task 1.1). Add macros that compose them:

```jinja
{% macro skeleton_row(width="100%", height="16px") %}
<div class="v4-skeleton" style="width: {{ width }}; height: {{ height }};"></div>
{% endmacro %}

{% macro skeleton_table(columns=4, rows=5) %}
<div class="v4-skeleton-table" aria-busy="true" aria-live="polite">
  {% for r in range(rows) %}
  <div style="display: grid; grid-template-columns: repeat({{ columns }}, 1fr); gap: 12px; padding: 8px 0;">
    {% for c in range(columns) %}
      <div class="v4-skeleton" style="height: 14px;"></div>
    {% endfor %}
  </div>
  {% endfor %}
</div>
{% endmacro %}
```

- [ ] **Step 2: Commit**

```bash
git add src/web/templates/_components.html
git commit -m "feat(design-system): skeleton loader macros (row, table)"
```

### Task 1.17: Add Confirm Dialog component

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`
- Modify: `src/web/templates/_base.html`

- [ ] **Step 1: Append dialog CSS**

```css
.v4-confirm-dialog[open] {
  border: 0;
  padding: 0;
  border-radius: var(--v4-radius-lg);
  box-shadow: var(--v4-shadow-modal);
  max-width: 440px;
  width: calc(100vw - var(--v4-space-8));
}
.v4-confirm-dialog::backdrop {
  background: rgba(0, 0, 0, 0.4);
  animation: v4-fade-in var(--v4-motion-base);
}
.v4-confirm-dialog__body {
  padding: var(--v4-space-6);
}
.v4-confirm-dialog__title {
  font-size: var(--v4-h3-size);
  font-weight: 600;
  margin: 0 0 var(--v4-space-2);
}
.v4-confirm-dialog__message {
  color: var(--v4-gray-700);
  margin: 0 0 var(--v4-space-4);
  font-size: 14px;
}
.v4-confirm-dialog__actions {
  display: flex;
  gap: var(--v4-space-2);
  justify-content: flex-end;
}
```

- [ ] **Step 2: Add a single `<dialog>` element to `_base.html` (shared across pages)**

Inside `<body>`, before the toast region, add:

```html
<dialog class="v4-confirm-dialog" id="v4-confirm-dialog" aria-labelledby="v4-confirm-title">
  <form method="dialog" class="v4-confirm-dialog__body">
    <h3 class="v4-confirm-dialog__title" id="v4-confirm-title"></h3>
    <p class="v4-confirm-dialog__message" id="v4-confirm-message"></p>
    <div class="v4-confirm-dialog__actions">
      <button type="button" class="v4-btn v4-btn--secondary v4-btn--small" data-confirm-cancel>Cancelar</button>
      <button type="button" class="v4-btn v4-btn--danger v4-btn--small" data-confirm-ok>Confirmar</button>
    </div>
  </form>
</dialog>
<script>
  // Public API: openConfirm({ title, message, okLabel, kind, onConfirm })
  function openConfirm(opts) {
    const dlg = document.getElementById('v4-confirm-dialog');
    document.getElementById('v4-confirm-title').textContent = opts.title || 'Confirmar?';
    document.getElementById('v4-confirm-message').textContent = opts.message || '';
    const okBtn = dlg.querySelector('[data-confirm-ok]');
    okBtn.textContent = opts.okLabel || 'Confirmar';
    okBtn.className = 'v4-btn v4-btn--small v4-btn--' + (opts.kind || 'danger');
    okBtn.onclick = () => { dlg.close(); opts.onConfirm && opts.onConfirm(); };
    dlg.querySelector('[data-confirm-cancel]').onclick = () => dlg.close();
    dlg.showModal();
  }
</script>
```

- [ ] **Step 3: Add helper macro for HTMX-driven confirm-then-post buttons**

Append to `_components.html`:

```jinja
{% macro confirm_button(label, post_url, message, title="Confirmar?", ok_label="Confirmar", kind="danger", target=None, swap=None) %}
<button type="button" class="v4-btn v4-btn--small v4-btn--{{ kind }}"
        onclick='openConfirm({
          title: {{ title|tojson }},
          message: {{ message|tojson }},
          okLabel: {{ ok_label|tojson }},
          kind: {{ kind|tojson }},
          onConfirm: () => htmx.ajax("POST", {{ post_url|tojson }}, {{ ("{ target: '" ~ target ~ "', swap: '" ~ (swap or "outerHTML") ~ "' }") if target else "{}" }})
        })'>{{ label }}</button>
{% endmacro %}
```

- [ ] **Step 4: Manual test**

Render any page with a button using `confirm_button("Teste", "/sessions/00000000-0000-0000-0000-000000000000/revoke", "Tem certeza?")`. Click → dialog opens with title + message + "Cancelar" + "Confirmar". Cancel closes; Confirm fires HTMX POST.

- [ ] **Step 5: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_base.html src/web/templates/_components.html
git commit -m "feat(design-system): accessible confirm dialog (replaces onsubmit confirm)"
```

### Task 1.18: Add Modal component

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append generic modal CSS**

```css
.v4-modal[open] {
  border: 0;
  padding: 0;
  border-radius: var(--v4-radius-lg);
  box-shadow: var(--v4-shadow-modal);
  max-width: 600px;
  width: calc(100vw - var(--v4-space-8));
  max-height: calc(100vh - var(--v4-space-8));
}
.v4-modal::backdrop { background: rgba(0,0,0,0.4); }

.v4-modal__header {
  padding: var(--v4-space-4) var(--v4-space-6);
  border-bottom: 1px solid var(--v4-gray-100);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.v4-modal__title { margin: 0; font-size: var(--v4-h3-size); font-weight: 600; }
.v4-modal__close {
  background: transparent;
  border: 0;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  color: var(--v4-gray-300);
  padding: 4px 8px;
}
.v4-modal__close:hover { color: var(--v4-gray-900); }
.v4-modal__body { padding: var(--v4-space-6); }

@media (max-width: 639px) {
  .v4-modal[open] {
    max-width: 100vw;
    max-height: 100vh;
    width: 100vw;
    height: 100vh;
    border-radius: 0;
  }
}
```

- [ ] **Step 2: Add modal macro**

Append to `_components.html`:

```jinja
{% macro modal(id, title, body, footer=None) %}
<dialog class="v4-modal" id="{{ id }}" aria-labelledby="{{ id }}-title">
  <div class="v4-modal__header">
    <h3 class="v4-modal__title" id="{{ id }}-title">{{ title }}</h3>
    <button type="button" class="v4-modal__close" onclick="document.getElementById('{{ id }}').close()" aria-label="Fechar">×</button>
  </div>
  <div class="v4-modal__body">{{ body|safe }}</div>
  {% if footer %}<div class="v4-modal__footer">{{ footer|safe }}</div>{% endif %}
</dialog>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): modal component (uses native <dialog>)"
```

### Task 1.19: Add Breadcrumb component

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append breadcrumb CSS**

```css
.v4-breadcrumb {
  display: flex;
  gap: var(--v4-space-2);
  align-items: center;
  font-size: 13px;
  margin-bottom: var(--v4-space-3);
}
.v4-breadcrumb a {
  color: var(--v4-gray-300);
  text-decoration: none;
}
.v4-breadcrumb a:hover { color: var(--v4-gray-700); }
.v4-breadcrumb__separator { color: var(--v4-gray-200); }
.v4-breadcrumb__current { color: var(--v4-gray-900); font-weight: 500; }
```

- [ ] **Step 2: Add breadcrumb macro**

```jinja
{% macro breadcrumb(items) %}
{# items: list of dicts {label: str, url: str|None} — last item without url is rendered as current #}
<nav class="v4-breadcrumb" aria-label="Breadcrumb">
  {% for item in items %}
    {% if not loop.last and item.url %}
      <a href="{{ item.url }}">{{ item.label }}</a>
      <span class="v4-breadcrumb__separator">/</span>
    {% else %}
      <span class="v4-breadcrumb__current" aria-current="page">{{ item.label }}</span>
    {% endif %}
  {% endfor %}
</nav>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): breadcrumb component"
```

### Task 1.20: Add Dropdown menu component

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append dropdown CSS**

```css
.v4-dropdown {
  position: relative;
  display: inline-block;
}
.v4-dropdown__trigger {
  background: transparent;
  border: 0;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 16px;
  color: var(--v4-gray-700);
  border-radius: var(--v4-radius-sm);
}
.v4-dropdown__trigger:hover { background: var(--v4-gray-50); color: var(--v4-gray-900); }
.v4-dropdown__menu {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  background: var(--v4-white);
  border: 1px solid var(--v4-gray-100);
  border-radius: var(--v4-radius-md);
  box-shadow: var(--v4-shadow-card);
  min-width: 180px;
  padding: 4px;
  z-index: var(--v4-z-dropdown);
  display: none;
}
.v4-dropdown.is-open .v4-dropdown__menu { display: block; animation: v4-fade-in var(--v4-motion-fast); }
.v4-dropdown__item {
  display: block;
  width: 100%;
  background: transparent;
  border: 0;
  text-align: left;
  padding: 8px 10px;
  font-size: 13px;
  color: var(--v4-gray-900);
  cursor: pointer;
  border-radius: var(--v4-radius-sm);
}
.v4-dropdown__item:hover { background: var(--v4-gray-50); }
.v4-dropdown__item--danger { color: var(--v4-red); }
.v4-dropdown__divider {
  height: 1px;
  background: var(--v4-gray-100);
  margin: 4px 0;
}
```

- [ ] **Step 2: Add dropdown macro + JS toggle helper**

Append to `_components.html`:

```jinja
{% macro dropdown(id, items, trigger_label="⋯") %}
{# items: list of dicts with keys: label, url (optional), post_url (optional), kind (optional, 'danger'), separator (optional, true => render <hr>) #}
<div class="v4-dropdown" id="{{ id }}">
  <button type="button" class="v4-dropdown__trigger" aria-haspopup="menu" aria-expanded="false"
          onclick="v4DropdownToggle('{{ id }}')">{{ trigger_label }}</button>
  <div class="v4-dropdown__menu" role="menu">
    {% for item in items %}
      {% if item.separator %}
        <div class="v4-dropdown__divider" role="separator"></div>
      {% elif item.url %}
        <a class="v4-dropdown__item {% if item.kind == 'danger' %}v4-dropdown__item--danger{% endif %}"
           href="{{ item.url }}" role="menuitem">{{ item.label }}</a>
      {% elif item.post_url %}
        <button class="v4-dropdown__item {% if item.kind == 'danger' %}v4-dropdown__item--danger{% endif %}"
                type="button" role="menuitem"
                hx-post="{{ item.post_url }}" hx-target="{{ item.target or 'closest tr' }}"
                hx-swap="{{ item.swap or 'outerHTML' }}">{{ item.label }}</button>
      {% endif %}
    {% endfor %}
  </div>
</div>
{% endmacro %}
```

Add JS helper to `_base.html` (before `</body>`, near the toast script):

```html
<script>
  function v4DropdownToggle(id) {
    const dd = document.getElementById(id);
    const isOpen = dd.classList.toggle('is-open');
    dd.querySelector('.v4-dropdown__trigger').setAttribute('aria-expanded', String(isOpen));
    if (isOpen) {
      const closeOnOutside = (e) => {
        if (!dd.contains(e.target)) {
          dd.classList.remove('is-open');
          dd.querySelector('.v4-dropdown__trigger').setAttribute('aria-expanded', 'false');
          document.removeEventListener('click', closeOnOutside);
        }
      };
      setTimeout(() => document.addEventListener('click', closeOnOutside), 0);
    }
  }
</script>
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html src/web/templates/_base.html
git commit -m "feat(design-system): dropdown menu (HTMX-aware row actions)"
```

### Task 1.21: Add Tooltip component

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append tooltip CSS (CSS-only, no JS)**

```css
.v4-tooltip {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: help;
}
.v4-tooltip__bubble {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--v4-gray-900);
  color: var(--v4-white);
  padding: 6px 10px;
  border-radius: var(--v4-radius-sm);
  font-size: 12px;
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity var(--v4-motion-fast) var(--v4-ease-out);
  z-index: var(--v4-z-dropdown);
}
.v4-tooltip:hover .v4-tooltip__bubble,
.v4-tooltip:focus-within .v4-tooltip__bubble { opacity: 1; }
```

- [ ] **Step 2: Add tooltip macro**

```jinja
{% macro tooltip(text, content) %}
<span class="v4-tooltip" tabindex="0">
  {{ content|safe }}
  <span class="v4-tooltip__bubble" role="tooltip">{{ text }}</span>
</span>
{% endmacro %}
```

- [ ] **Step 3: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_components.html
git commit -m "feat(design-system): CSS-only tooltip (focus + hover)"
```

### Task 1.22: Add Expandable table row pattern

**Files:**
- Modify: `src/web/static/v4-components.css`
- Modify: `src/web/templates/_components.html`

- [ ] **Step 1: Append expandable row CSS**

```css
.v4-table tbody tr.is-expandable { cursor: pointer; }
.v4-table tbody tr.is-expandable td:first-child::before {
  content: '▸';
  display: inline-block;
  margin-right: 8px;
  transition: transform var(--v4-motion-fast) var(--v4-ease-out);
  color: var(--v4-gray-300);
}
.v4-table tbody tr.is-expandable.is-open td:first-child::before {
  transform: rotate(90deg);
}
.v4-table tbody tr.v4-table__detail {
  background: var(--v4-gray-50);
  display: none;
}
.v4-table tbody tr.v4-table__detail.is-open { display: table-row; }
.v4-table tbody tr.v4-table__detail td {
  padding: var(--v4-space-4);
  border-bottom: 2px solid var(--v4-gray-100);
}
```

- [ ] **Step 2: Add JS toggle helper to `_base.html`**

```html
<script>
  function v4ToggleRow(rowId) {
    const row = document.getElementById(rowId);
    const detail = document.getElementById(rowId + '-detail');
    if (!row || !detail) return;
    row.classList.toggle('is-open');
    detail.classList.toggle('is-open');
  }
</script>
```

- [ ] **Step 3: Document usage pattern as inline comment**

Add this to `_components.html` so future devs know how:

```jinja
{# Expandable row pattern (no macro — inline in templates):
  <tr id="row-1" class="is-expandable" onclick="v4ToggleRow('row-1')">
    <td>cell 1</td><td>cell 2</td>
  </tr>
  <tr id="row-1-detail" class="v4-table__detail">
    <td colspan="2">Detail content here</td>
  </tr>
#}
```

- [ ] **Step 4: Commit**

```bash
git add src/web/static/v4-components.css src/web/templates/_base.html src/web/templates/_components.html
git commit -m "feat(design-system): expandable table row pattern"
```

### Task 1.23: Add Sticky table header + Compact table variants

**Files:**
- Modify: `src/web/static/v4-components.css`

- [ ] **Step 1: Append sticky + compact CSS**

```css
/* Sticky table header — opt-in via wrapper class */
.v4-table--sticky-head thead th {
  position: sticky;
  top: 0;
  background: var(--v4-gray-50);
  z-index: 1;
}

/* Compact (Operational mode) variant */
.v4-table--compact th,
.v4-table--compact td {
  padding: var(--v4-cell-pad-compact);
  font-size: 12px;
}
.v4-table--compact th {
  font-size: 10px;
}
.v4-table--compact tr {
  height: var(--v4-row-height-compact);
}

/* Mono variant for IDs/operations columns */
.v4-table .col-mono {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 12px;
  color: var(--v4-gray-700);
}
```

- [ ] **Step 2: Commit**

```bash
git add src/web/static/v4-components.css
git commit -m "feat(design-system): sticky table head + compact variant + mono column"
```

### Task 1.24: Phase 1 visual regression sanity check

**Files:** none (manual verification)

- [ ] **Step 1: Deploy current state to production**

```bash
git push origin main
gh run watch  # wait for CI + Deploy green
```

- [ ] **Step 2: Visit each existing page and confirm no visual regression**

Open in browser:
- `/login` → looks similar to before (still works), no console errors, Tailwind utilities load
- `/` (logged in) → header has hamburger button, sub-nav doesn't appear (not on /admin)
- `/admin/managers` → sub-nav appears below header with 6 links, Managers highlighted
- Resize to <768px on `/` → hamburger visible, click → drawer opens

- [ ] **Step 3: Run smoke tests**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/ -q -m "not integration" 2>&1 | tail -10
```

Expected: all tests pass (Phase 1 didn't change Python code beyond deps + 1 stub function).

- [ ] **Step 4: Phase 1 done marker commit**

```bash
git commit --allow-empty -m "chore: Phase 1 (design system v2) complete — foundation ready"
git push origin main
```

---

## Phase 2 — Backend Q8 + Invite UI (4-6 days)

Goal: enforce invite-only access (Q8). Add `managers.status`, OAuth allowlist decision tree, `BOOTSTRAP_ADMIN_EMAILS` env, and the `/admin/invites` UI + `/access-denied` page. Must ship before inviting real gestores.

### Task 2.1: Migration `002_managers_status.sql`

**Files:**
- Create: `src/db/migrations/002_managers_status.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 002_managers_status.sql
-- Adds invite-only allowlist support per FE Redesign v2 Phase 2 (Q8).

ALTER TABLE managers
  ADD COLUMN status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('invited', 'active', 'inactive'));

ALTER TABLE managers
  ADD COLUMN invited_by uuid REFERENCES managers(id),
  ADD COLUMN invited_at timestamptz;

CREATE INDEX idx_managers_status ON managers(status)
  WHERE status IN ('invited', 'inactive');

-- Backfill is implicit via DEFAULT 'active'. Existing 'is_active=false' rows
-- can be migrated to status='inactive' in a follow-up cleanup PR; for now
-- they remain status='active' but is_active=false (functionally inactive
-- because login flow checks both).

COMMENT ON COLUMN managers.status IS
  'Invite lifecycle: invited (pre-OAuth) -> active (post first login) -> inactive (admin disabled)';
```

- [ ] **Step 2: Apply migration to local dev DB**

If you have a local Postgres for dev:

```bash
psql -h localhost -U postgres -d v4_ads_mcp -f src/db/migrations/002_managers_status.sql
```

If no local DB, the testcontainers-based tests will apply it automatically when test fixtures load all migrations.

- [ ] **Step 3: Apply migration to Supabase production**

Open Supabase SQL editor (project laiqtoisehgkwfxaezjl). Paste the migration contents. Run. Verify with:

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'managers' AND column_name IN ('status', 'invited_by', 'invited_at');
```

Expected: 3 rows.

- [ ] **Step 4: Verify your existing user got status='active'**

```sql
SELECT email, status, role, is_active FROM managers;
```

Expected: `wellinton.ribeiro@v4company.com | active | admin | true`.

- [ ] **Step 5: Commit**

```bash
git add src/db/migrations/002_managers_status.sql
git commit -m "feat(db): migration 002 — managers.status for invite-only allowlist"
```

### Task 2.2: Extend managers repository with invite lifecycle

**Files:**
- Modify: `src/db/repositories/managers.py`
- Modify: `tests/unit/test_managers.py` (or create — depends on whether file exists)

- [ ] **Step 1: Write failing test for `create_invited`**

Look at the existing `tests/unit/` tests to find the managers test file. Either append to it or create `tests/integration/test_managers_repo.py` (since DB-touching tests go in integration):

```python
# tests/integration/test_managers_invite.py
"""Tests for managers repository invite lifecycle (Phase 2 — Q8)."""

import pytest
from uuid import uuid4

from src.db.repositories import managers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_invited_marks_status_invited(db_pool):
    inviter_id = uuid4()
    # Insert a fake admin to be the inviter (FK)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role)
               VALUES ($1, 'admin@v4company.com', 'active', 'admin')""",
            inviter_id,
        )

    async with db_pool.acquire() as conn:
        invitee = await managers.create_invited(
            conn, email="newgestor@v4company.com", invited_by=inviter_id, full_name="New Gestor"
        )

    assert invitee["email"] == "newgestor@v4company.com"
    assert invitee["status"] == "invited"
    assert invitee["role"] == "gestor"
    assert invitee["invited_by"] == inviter_id
    assert invitee["invited_at"] is not None
```

- [ ] **Step 2: Run test — expect failure (function not defined)**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/integration/test_managers_invite.py::test_create_invited_marks_status_invited -v 2>&1 | tail -15
```

Expected: `AttributeError: module 'src.db.repositories.managers' has no attribute 'create_invited'`.

- [ ] **Step 3: Implement `create_invited` in managers.py**

Append to `src/db/repositories/managers.py`:

```python
from datetime import datetime
from typing import Any
from uuid import UUID
import asyncpg


async def create_invited(
    conn: asyncpg.Connection,
    *,
    email: str,
    invited_by: UUID,
    full_name: str | None = None,
) -> dict[str, Any]:
    """Pre-create a manager row with status='invited' before they log in.

    Raises asyncpg.UniqueViolationError if email already exists in managers.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO managers (email, full_name, role, status, is_active, invited_by, invited_at)
        VALUES ($1, $2, 'gestor', 'invited', true, $3, $4)
        RETURNING id, email, full_name, role, status, invited_by, invited_at
        """,
        email,
        full_name,
        invited_by,
        datetime.utcnow(),
    )
    if row is None:
        raise RuntimeError("INSERT did not return a row")
    return dict(row)
```

- [ ] **Step 4: Run test again — expect pass**

```bash
python -m pytest tests/integration/test_managers_invite.py::test_create_invited_marks_status_invited -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 5: Add tests + implementations for `mark_active`, `list_invited`, `delete_invite`**

Append to the test file:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_mark_active_only_invited(db_pool):
    """mark_active flips invited→active. Should NOT promote inactive→active."""
    inviter = uuid4()
    invited_id = uuid4()
    inactive_id = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'admin@v4company.com', 'active', 'admin'),
               ($2, 'invited@v4company.com', 'invited', 'gestor'),
               ($3, 'inactive@v4company.com', 'inactive', 'gestor')""",
            inviter, invited_id, inactive_id,
        )

    async with db_pool.acquire() as conn:
        ok = await managers.mark_active(conn, manager_id=invited_id)
        assert ok is True

        ok = await managers.mark_active(conn, manager_id=inactive_id)
        assert ok is False

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT email, status FROM managers WHERE id IN ($1, $2)",
                                invited_id, inactive_id)
    statuses = {r["email"]: r["status"] for r in rows}
    assert statuses["invited@v4company.com"] == "active"
    assert statuses["inactive@v4company.com"] == "inactive"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_invited_returns_only_invited(db_pool):
    inviter = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'admin@v4company.com', 'active', 'admin'),
               ($2, 'pending1@v4company.com', 'invited', 'gestor'),
               ($3, 'pending2@v4company.com', 'invited', 'gestor'),
               ($4, 'active@v4company.com', 'active', 'gestor')""",
            inviter, uuid4(), uuid4(), uuid4(),
        )

    async with db_pool.acquire() as conn:
        invited = await managers.list_invited(conn)

    emails = {r["email"] for r in invited}
    assert "pending1@v4company.com" in emails
    assert "pending2@v4company.com" in emails
    assert "admin@v4company.com" not in emails
    assert "active@v4company.com" not in emails


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_invite_only_if_invited(db_pool):
    inviter = uuid4()
    invited_id = uuid4()
    active_id = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'admin@v4company.com', 'active', 'admin'),
               ($2, 'pending@v4company.com', 'invited', 'gestor'),
               ($3, 'active@v4company.com', 'active', 'gestor')""",
            inviter, invited_id, active_id,
        )

    async with db_pool.acquire() as conn:
        deleted = await managers.delete_invite(conn, manager_id=invited_id)
        assert deleted is True

        deleted = await managers.delete_invite(conn, manager_id=active_id)
        assert deleted is False

    async with db_pool.acquire() as conn:
        active_still_there = await conn.fetchval(
            "SELECT 1 FROM managers WHERE id = $1", active_id
        )
        invited_gone = await conn.fetchval(
            "SELECT 1 FROM managers WHERE id = $1", invited_id
        )
    assert active_still_there == 1
    assert invited_gone is None
```

Append to `src/db/repositories/managers.py`:

```python
async def mark_active(conn: asyncpg.Connection, *, manager_id: UUID) -> bool:
    """Flip status from 'invited' to 'active'. Returns True if row was modified.

    Does NOT promote 'inactive' to 'active' — that requires explicit admin action.
    """
    result = await conn.execute(
        "UPDATE managers SET status = 'active' WHERE id = $1 AND status = 'invited'",
        manager_id,
    )
    # asyncpg returns 'UPDATE n' where n is row count
    return result.endswith(" 1")


async def list_invited(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Return rows where status = 'invited' for the admin invites page."""
    rows = await conn.fetch(
        """SELECT id, email, full_name, invited_by, invited_at
           FROM managers WHERE status = 'invited'
           ORDER BY invited_at DESC"""
    )
    return [dict(r) for r in rows]


async def delete_invite(conn: asyncpg.Connection, *, manager_id: UUID) -> bool:
    """Delete a row only if status='invited'. Safety against accidental deletion of active accounts."""
    result = await conn.execute(
        "DELETE FROM managers WHERE id = $1 AND status = 'invited'",
        manager_id,
    )
    return result.endswith(" 1")


async def count_invited(conn: asyncpg.Connection) -> int:
    """Count of pending invites — used by /admin sub-nav badge."""
    return await conn.fetchval("SELECT count(*) FROM managers WHERE status = 'invited'") or 0


async def get_by_email(conn: asyncpg.Connection, *, email: str) -> dict[str, Any] | None:
    """Lookup by email — used by OAuth callback for the allowlist check."""
    row = await conn.fetchrow(
        "SELECT id, email, full_name, role, status, is_active FROM managers WHERE email = $1",
        email,
    )
    return dict(row) if row else None


async def count_all(conn: asyncpg.Connection) -> int:
    """Used by bootstrap path — admin only auto-creates when the table is empty."""
    return await conn.fetchval("SELECT count(*) FROM managers") or 0
```

- [ ] **Step 6: Run all 4 tests — expect pass**

```bash
python -m pytest tests/integration/test_managers_invite.py -v 2>&1 | tail -15
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add src/db/repositories/managers.py tests/integration/test_managers_invite.py
git commit -m "feat(db): managers invite lifecycle (create_invited / mark_active / list / delete / counts)"
```

### Task 2.3: Add `BOOTSTRAP_ADMIN_EMAILS` config

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Locate the Settings class and add the field**

Open `src/config.py`. Inside the `Settings` class, add (preserve existing field ordering — append near other env-driven fields):

```python
    # Phase 2: invite-only allowlist bootstrap
    bootstrap_admin_emails: str = ""

    @property
    def bootstrap_admin_emails_set(self) -> set[str]:
        """Parse the comma-separated env into a normalized set of lowercased emails."""
        return {
            e.strip().lower()
            for e in self.bootstrap_admin_emails.split(",")
            if e.strip()
        }
```

- [ ] **Step 2: Test parsing in Python REPL**

```bash
python -c "
import os
os.environ['BOOTSTRAP_ADMIN_EMAILS'] = 'a@v4company.com, b@v4company.com'
from src.config import get_settings
print(get_settings().bootstrap_admin_emails_set)
"
```

Expected: `{'a@v4company.com', 'b@v4company.com'}`.

- [ ] **Step 3: Set env var on Cloud Run**

```bash
gh api -X PATCH repos/BadWolf1509/v4-ads-mcp -f homepage="https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app" 2>/dev/null  # placeholder; actual env update via gcloud:

gcloud run services update v4-ads-mcp \
  --region=southamerica-east1 \
  --update-env-vars BOOTSTRAP_ADMIN_EMAILS=wellinton.ribeiro@v4company.com
```

(The user runs this; it's a production-touching ops command — do NOT run from agent without explicit user approval.)

- [ ] **Step 4: Commit**

```bash
git add src/config.py
git commit -m "feat(config): BOOTSTRAP_ADMIN_EMAILS env for invite-only allowlist bootstrap"
```

### Task 2.4: Refactor OAuth callback for allowlist decision tree

**Files:**
- Modify: `src/auth/oauth.py`
- Create: `tests/integration/test_oauth_allowlist.py`

- [ ] **Step 1: Read current oauth.py to understand structure**

```bash
# Just read for orientation — no command needed
```

Open `src/auth/oauth.py`. Locate the callback handler. Identify where the manager row is looked up / created.

- [ ] **Step 2: Write failing tests for the 5 decision branches**

Create `tests/integration/test_oauth_allowlist.py`:

```python
"""Integration tests for OAuth callback allowlist decision tree (Phase 2 — Q8)."""

import pytest
from uuid import uuid4
from unittest.mock import patch, AsyncMock

from src.auth import oauth


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_rejects_non_v4_domain():
    """Email outside @v4company.com → /access-denied?reason=domain"""
    response = await oauth.handle_callback_decision(
        email="alice@gmail.com",
        google_id="g123",
        google_email="alice@gmail.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=domain"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_active_email_logs_in():
    """status=active → login OK → /"""
    response = await oauth.handle_callback_decision(
        email="wellinton.ribeiro@v4company.com",
        google_id="g123",
        google_email="wellinton.ribeiro@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "active", "is_active": True},
    )
    assert response.kind == "login"
    assert response.action is None  # no special status flip


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_invited_email_promotes_to_active():
    response = await oauth.handle_callback_decision(
        email="invitee@v4company.com",
        google_id="g123",
        google_email="invitee@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "invited", "is_active": True},
    )
    assert response.kind == "login"
    assert response.action == "promote_invited"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_inactive_email_redirects():
    response = await oauth.handle_callback_decision(
        email="ex.gestor@v4company.com",
        google_id="g123",
        google_email="ex.gestor@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "inactive", "is_active": False},
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=deactivated"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_not_invited_redirects():
    """Email is @v4company.com but not in allowlist and not in bootstrap"""
    response = await oauth.handle_callback_decision(
        email="random@v4company.com",
        google_id="g123",
        google_email="random@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=not_invited"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_bootstrap_when_table_empty():
    response = await oauth.handle_callback_decision(
        email="boot@v4company.com",
        google_id="g123",
        google_email="boot@v4company.com",
        managers_table_empty=True,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "login"
    assert response.action == "bootstrap_admin"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_callback_bootstrap_ignored_when_table_populated():
    """Even if email matches BOOTSTRAP_ADMIN_EMAILS, if managers exist, don't auto-create"""
    response = await oauth.handle_callback_decision(
        email="boot@v4company.com",
        google_id="g123",
        google_email="boot@v4company.com",
        managers_table_empty=False,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=not_invited"
```

- [ ] **Step 3: Run tests — expect failure (function not yet defined)**

```bash
python -m pytest tests/integration/test_oauth_allowlist.py -v 2>&1 | tail -20
```

Expected: AttributeError on `handle_callback_decision`.

- [ ] **Step 4: Implement `handle_callback_decision` as a pure function in oauth.py**

Add to `src/auth/oauth.py`, near the top:

```python
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class CallbackDecision:
    """Outcome of the OAuth allowlist decision tree.

    kind='login'    → proceed; action determines whether to flip status/create row
    kind='redirect' → redirect to `location`; do not create or update any manager row
    """
    kind: Literal["login", "redirect"]
    location: str | None = None
    action: Literal["promote_invited", "bootstrap_admin"] | None = None


async def handle_callback_decision(
    *,
    email: str,
    google_id: str,
    google_email: str,
    managers_table_empty: bool,
    bootstrap_emails: set[str],
    existing_manager: dict[str, Any] | None,
) -> CallbackDecision:
    """Pure decision tree — no DB writes, no I/O. Caller applies the resulting action.

    Phase 2 (Q8) replaces today's auto-create-on-first-login with explicit allowlist.
    """
    email = email.strip().lower()

    # 1. Domain gate
    if not email.endswith("@v4company.com"):
        return CallbackDecision(kind="redirect", location="/access-denied?reason=domain")

    # 2. Email in managers table?
    if existing_manager is not None:
        status = existing_manager.get("status", "active")
        is_active = existing_manager.get("is_active", True)

        if status == "active" and is_active:
            return CallbackDecision(kind="login")

        if status == "invited":
            return CallbackDecision(kind="login", action="promote_invited")

        # status == "inactive" OR is_active=false from legacy
        return CallbackDecision(kind="redirect", location="/access-denied?reason=deactivated")

    # 3. Email NOT in managers table — bootstrap path?
    if managers_table_empty and email in bootstrap_emails:
        return CallbackDecision(kind="login", action="bootstrap_admin")

    # 4. Default: not invited
    return CallbackDecision(kind="redirect", location="/access-denied?reason=not_invited")
```

- [ ] **Step 5: Run tests — expect pass**

```bash
python -m pytest tests/integration/test_oauth_allowlist.py -v 2>&1 | tail -15
```

Expected: 7 passed.

- [ ] **Step 6: Wire `handle_callback_decision` into the actual OAuth callback handler**

Locate the existing callback handler in `src/auth/oauth.py` (the `@router.get("/callback")` or similar). Replace its manager-lookup logic with:

```python
from src.config import get_settings
from src.db.repositories import managers as managers_repo

# Inside the callback handler (replace the old auto-create block):
async with pool.acquire() as conn:
    existing = await managers_repo.get_by_email(conn, email=email)
    table_empty = await managers_repo.count_all(conn) == 0
    settings = get_settings()

    decision = await handle_callback_decision(
        email=email,
        google_id=google_id,
        google_email=google_email,
        managers_table_empty=table_empty,
        bootstrap_emails=settings.bootstrap_admin_emails_set,
        existing_manager=existing,
    )

    if decision.kind == "redirect":
        return RedirectResponse(url=decision.location, status_code=302)

    # decision.kind == 'login'
    if decision.action == "promote_invited" and existing:
        await managers_repo.mark_active(conn, manager_id=existing["id"])
        manager_id = existing["id"]
    elif decision.action == "bootstrap_admin":
        bootstrapped = await conn.fetchrow(
            """INSERT INTO managers (email, full_name, role, status)
               VALUES ($1, $2, 'admin', 'active') RETURNING id""",
            email, google_email or None,
        )
        manager_id = bootstrapped["id"]
    else:
        # status='active' login — manager_id from existing
        assert existing is not None
        manager_id = existing["id"]

    # ... continue with existing oauth_connection upsert + panel session creation ...
```

- [ ] **Step 7: Manual smoke test on staging or local**

If staging available: deploy this change and complete OAuth with `wellinton.ribeiro@v4company.com`. Expected: login OK (status=active branch).

Try logging in with a fresh `@v4company.com` email NOT in managers table. Expected: redirect to `/access-denied?reason=not_invited`.

- [ ] **Step 8: Commit**

```bash
git add src/auth/oauth.py tests/integration/test_oauth_allowlist.py
git commit -m "feat(auth): OAuth callback allowlist decision tree (Q8)"
```

### Task 2.5: Wire real `pending_invites_count` into admin route renders

**Files:**
- Modify: `src/web/deps.py`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Replace the stub from Task 1.3 with the real implementation**

In `src/web/deps.py`, replace the placeholder `pending_invites_count` function with:

```python
async def pending_invites_count() -> int:
    """Count of managers with status='invited'. Used by admin sub-nav badge."""
    from src.db import connection
    from src.db.repositories import managers
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        return await managers.count_invited(conn)
```

- [ ] **Step 2: Wire it into all admin route renders**

In `src/web/routes.py`, find every admin route handler (`/admin/managers`, `/admin/accounts`, `/admin/access`, `/admin/audit`). Where each currently passes `"pending_invites_count": 0`, replace with:

```python
from src.web.deps import pending_invites_count

# Inside each handler:
pending = await pending_invites_count()
return templates.TemplateResponse(
    request,
    "admin/managers.html",  # or whichever template
    {
        ...
        "pending_invites_count": pending,
    },
)
```

- [ ] **Step 3: Smoke test**

Run server locally. Visit `/admin/managers`. Expected: same as before but with real count. Currently 0 invites in DB so badge still hidden (sub-nav `if count > 0` check).

- [ ] **Step 4: Commit**

```bash
git add src/web/deps.py src/web/routes.py
git commit -m "feat(web): wire real pending_invites_count to admin sub-nav"
```

### Task 2.6: Create `/access-denied` route + template

**Files:**
- Create: `src/web/templates/access_denied.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Create the template**

`src/web/templates/access_denied.html`:

```html
{% extends "_base.html" %}
{% from "_components.html" import button %}

{% block title %}Acesso negado — V4 Ads MCP{% endblock %}

{% block content %}
<div class="max-w-xl mx-auto py-16 px-4 text-center">
  {% if reason == "domain" %}
    <div class="text-display font-sans font-extrabold leading-none tracking-tight text-v4-gray-900">
      Domínio não permitido.
    </div>
    <p class="mt-6 text-v4-gray-700">
      O V4 Ads MCP é restrito a contas <code>@v4company.com</code>. Use sua conta corporativa.
    </p>
  {% elif reason == "deactivated" %}
    <div class="text-display font-sans font-extrabold leading-none tracking-tight text-v4-gray-900">
      Conta desativada.
    </div>
    <p class="mt-6 text-v4-gray-700">
      Sua conta foi desativada por um admin. Entre em contato com o admin V4 da sua unidade pra reativar.
    </p>
  {% else %}
    <div class="text-display font-sans font-extrabold leading-none tracking-tight text-v4-gray-900">
      Você ainda não tem acesso.
    </div>
    <p class="mt-6 text-v4-gray-700">
      O V4 Ads MCP é uma ferramenta interna por convite. Peça pro admin V4 da sua unidade adicionar o seu email à allowlist:
    </p>
    {% if attempted_email %}
    <div class="my-4 inline-block bg-v4-gray-50 px-4 py-2 rounded-md font-mono text-sm">
      {{ attempted_email }}
    </div>
    {% endif %}
  {% endif %}

  <div class="mt-8">
    <a href="/logout" class="v4-btn v4-btn--secondary">Logout</a>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Add the route handler**

In `src/web/routes.py`, append:

```python
@router.get("/access-denied", response_class=HTMLResponse)
async def access_denied(
    request: Request,
    reason: str = "not_invited",
) -> HTMLResponse:
    """Q8 invite-only landing page. No auth required."""
    # The user's attempted email (if any) is stored briefly in a transient cookie
    # set by the OAuth callback before redirect; if absent, render generic message.
    attempted_email = request.cookies.get("v4_attempted_email")
    response = templates.TemplateResponse(
        request,
        "access_denied.html",
        {
            "current_user": None,
            "reason": reason,
            "attempted_email": attempted_email,
        },
    )
    # Clear the cookie after read
    response.delete_cookie("v4_attempted_email", path="/")
    return response
```

- [ ] **Step 3: Set the transient cookie in the OAuth callback before redirect**

In `src/auth/oauth.py` callback, when `decision.kind == "redirect"`:

```python
if decision.kind == "redirect":
    response = RedirectResponse(url=decision.location, status_code=302)
    response.set_cookie(
        "v4_attempted_email", email,
        httponly=True, secure=True, samesite="lax", max_age=60,  # 60 seconds enough
    )
    return response
```

- [ ] **Step 4: Manual test**

Visit `/access-denied?reason=domain` directly — page renders with "Domínio não permitido." in display font, V4 red accent, logout button. Try `?reason=deactivated` and default — both render correct variants.

- [ ] **Step 5: Commit**

```bash
git add src/web/templates/access_denied.html src/web/routes.py src/auth/oauth.py
git commit -m "feat(web): /access-denied page with 3 reason variants (Q8)"
```

### Task 2.7: Create `/admin/invites` page (list + form)

**Files:**
- Create: `src/web/templates/admin/invites.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Create the template**

`src/web/templates/admin/invites.html`:

```html
{% extends "_base.html" %}
{% from "_components.html" import alert, badge, empty_state, form_group, button %}

{% block title %}Admin / Convites — V4 Ads MCP{% endblock %}

{% block content %}
<div class="max-w-4xl">
  <h1>Convites</h1>
  <p class="text-v4-gray-700 mb-6">
    Adicione gestores pelo email <code>@v4company.com</code> antes do primeiro login deles. Sem convite, o login é rejeitado.
  </p>

  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Adicionar gestor</h3>
    </div>
    <form method="POST" action="/admin/invites/new" class="grid grid-cols-1 md:grid-cols-[2fr_1fr_auto] gap-3 items-end">
      {{ form_group("Email V4", "email", type="email", placeholder="gestor@v4company.com", required=true) }}
      {{ form_group("Nome (opcional)", "full_name", placeholder="Maria Silva") }}
      <button type="submit" class="v4-btn v4-btn--primary">Convidar</button>
    </form>
  </div>

  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Pendentes ({{ invites|length }})</h3>
    </div>
    {% if invites %}
    <table class="v4-table v4-table--compact">
      <thead>
        <tr>
          <th>Email</th>
          <th>Nome</th>
          <th>Convidado por</th>
          <th>Convidado em</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for inv in invites %}
        <tr>
          <td><strong>{{ inv.email }}</strong></td>
          <td>{{ inv.full_name or "—" }}</td>
          <td class="col-mono">{{ inv.invited_by_email or "?" }}</td>
          <td>{{ inv.invited_at.strftime("%d/%m/%Y %H:%M") }}</td>
          <td class="text-right">
            <button type="button" class="v4-btn v4-btn--small v4-btn--ghost"
                    onclick='openConfirm({
                      title: "Cancelar convite?",
                      message: "Remove o convite de " + {{ inv.email|tojson }} + ". O usuário não poderá logar até ser convidado novamente.",
                      okLabel: "Cancelar convite",
                      kind: "danger",
                      onConfirm: () => htmx.ajax("POST", "/admin/invites/{{ inv.id }}/cancel", { target: "closest tr", swap: "outerHTML" })
                    })'>Cancelar</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      {{ empty_state("Nenhum convite pendente", "Use o formulário acima pra convidar um novo gestor.") }}
    {% endif %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Add the GET handler**

In `src/web/routes.py`:

```python
@router.get("/admin/invites", response_class=HTMLResponse)
async def admin_invites(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        invites = await conn.fetch(
            """SELECT m.id, m.email, m.full_name, m.invited_at,
                      inviter.email AS invited_by_email
               FROM managers m
               LEFT JOIN managers inviter ON inviter.id = m.invited_by
               WHERE m.status = 'invited'
               ORDER BY m.invited_at DESC"""
        )
        pending = await pending_invites_count()
    return templates.TemplateResponse(
        request,
        "admin/invites.html",
        {
            "current_user": user,
            "invites": [dict(r) for r in invites],
            "pending_invites_count": pending,
        },
    )
```

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/admin/invites.html src/web/routes.py
git commit -m "feat(admin): /admin/invites page (list pendentes + form de convidar)"
```

### Task 2.8: Add POST handlers for invite create + cancel

**Files:**
- Modify: `src/web/routes.py`

- [ ] **Step 1: Add `POST /admin/invites/new`**

```python
@router.post("/admin/invites/new", response_class=HTMLResponse, response_model=None)
async def admin_invites_new(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    email: str = Form(...),
    full_name: str = Form(""),
) -> RedirectResponse:
    _require_admin(user)
    email = email.strip().lower()
    if not email.endswith("@v4company.com"):
        # Could improve UX here with flash message; for MVP redirect plain
        return RedirectResponse(url="/admin/invites?error=bad_domain", status_code=303)

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Idempotency: if email already exists in any status, don't double-invite
        existing = await conn.fetchval("SELECT 1 FROM managers WHERE email = $1", email)
        if existing:
            return RedirectResponse(url="/admin/invites?error=exists", status_code=303)

        from src.db.repositories import managers as managers_repo
        await managers_repo.create_invited(
            conn, email=email, invited_by=user.id, full_name=(full_name or None),
        )
    return RedirectResponse(url="/admin/invites", status_code=303)
```

- [ ] **Step 2: Add `POST /admin/invites/{id}/cancel`**

```python
@router.post("/admin/invites/{invite_id}/cancel", response_class=HTMLResponse, response_model=None)
async def admin_invites_cancel(
    request: Request,
    invite_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import managers as managers_repo
        await managers_repo.delete_invite(conn, manager_id=UUID(invite_id))
    # HTMX swap: remove the row by returning empty content
    return HTMLResponse("")
```

- [ ] **Step 3: Manual smoke test**

Run app locally. Login as admin. Visit `/admin/invites`. Submit form with `test@v4company.com`. Expected: redirect back, row appears in pending list. Click "Cancelar" → confirm dialog → row disappears.

- [ ] **Step 4: Commit**

```bash
git add src/web/routes.py
git commit -m "feat(admin): POST /admin/invites/new + cancel (Q8 invite lifecycle)"
```

### Task 2.9: Phase 2 deploy + smoke

**Files:** none (ops)

- [ ] **Step 1: Push Phase 2 to origin**

```bash
git push origin main
gh run watch
```

Expected: CI green, Deploy green.

- [ ] **Step 2: E2E smoke on production**

1. Login at `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/login` — should still work (status=active branch).
2. Visit `/admin/invites` — page renders with empty state.
3. Add a fake invite `test.invite@v4company.com` via form — appears in pending list.
4. Open incognito, try login with that email — should land OAuth, then redirect back to `/` (status flip from invited→active).
5. Cancel an invite via the dropdown — row disappears via HTMX.

- [ ] **Step 3: Cleanup test data**

```sql
DELETE FROM managers WHERE email = 'test.invite@v4company.com';
```

- [ ] **Step 4: Phase 2 done marker**

```bash
git commit --allow-empty -m "chore: Phase 2 (Q8 invite-only allowlist) complete and verified in production"
git push origin main
```

---

## Phase 3 — Editorial + Hybrid hero pages (4-5 days)

Goal: deliver the "case visual da agência" payoff. Redesign `/login`, create `/help`, polish `/access-denied`, redesign `/` (dashboard) Hybrid hero, create `/admin` (visão geral) Hybrid.

### Task 3.1: Redesign `/login` (Editorial hero)

**Files:**
- Modify: `src/web/templates/login.html`

- [ ] **Step 1: Replace `login.html` content**

Full new content for `src/web/templates/login.html`:

```html
{% extends "_base.html" %}

{% block title %}V4 Ads MCP — Login{% endblock %}

{% block content %}
<section class="max-w-2xl mx-auto py-20 px-6">
  <img src="/static/logo/logo_v4_puro_round.svg" alt="V4" class="h-12 w-auto mb-10">

  <h1 class="text-display font-sans font-extrabold leading-none tracking-tight text-v4-gray-900 mb-2">
    V4 Ads MCP.
  </h1>
  <h2 class="text-display font-sans font-extrabold leading-none tracking-tight text-v4-red mb-8">
    IA + Google Ads.
  </h2>

  <p class="text-base text-v4-gray-700 max-w-md mb-10 leading-relaxed">
    Conecte suas contas Google Ads ao Claude, Codex e Cursor.
    Análise e otimização por linguagem natural — direto pro seu time de gestores.
  </p>

  <a href="/oauth/google/start?mode=panel_login"
     class="inline-flex items-center gap-3 bg-v4-gray-900 text-white px-6 py-3 rounded-full text-sm font-semibold hover:bg-v4-gray-800 transition-colors">
    <svg width="18" height="18" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
      <path fill="#fff" d="M21.35 11.1h-9.17v2.97h5.3c-.23 1.49-1.74 4.36-5.3 4.36-3.19 0-5.79-2.65-5.79-5.92 0-3.27 2.6-5.92 5.79-5.92 1.81 0 3.03.77 3.72 1.43l2.54-2.45C16.85 4.18 14.93 3.1 12.18 3.1c-5.04 0-9.13 4.09-9.13 9.13 0 5.04 4.09 9.13 9.13 9.13 5.27 0 8.76-3.7 8.76-8.92 0-.6-.06-1.06-.14-1.34z"/>
    </svg>
    Entrar com Google V4
  </a>

  <p class="mt-12 text-xs text-v4-gray-300">
    Acesso restrito a contas <code class="bg-v4-gray-50 px-1 py-0.5 rounded">@v4company.com</code> com convite ativo.
    Não tem acesso? Peça pro <a href="/help" class="underline">admin V4 da sua unidade</a>.
  </p>
</section>
{% endblock %}
```

- [ ] **Step 2: Visual smoke test**

Run server. Logout if logged in. Visit `/login`. Expected: hero "V4 Ads MCP." in black, "IA + Google Ads." in V4 red, sublabel narrative, black pill button with Google logo, footer in small gray text.

Resize to mobile — hero should wrap reasonably at smaller display sizes (Tailwind responsive).

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/login.html
git commit -m "feat(web): redesign /login with Editorial hero (display 56 + V4 red accent)"
```

### Task 3.2: Create `/help` page

**Files:**
- Create: `src/web/templates/help.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Create the template**

`src/web/templates/help.html`:

```html
{% extends "_base.html" %}
{% from "_components.html" import code_block %}

{% block title %}Help — V4 Ads MCP{% endblock %}

{% block content %}
<article class="max-w-3xl mx-auto py-12 px-6 prose">
  <h1 class="text-4xl font-extrabold tracking-tight text-v4-gray-900 mb-2">Help</h1>
  <p class="text-v4-gray-700 mb-12">Onboarding consolidado pra usar o V4 Ads MCP no seu cliente de IA preferido.</p>

  <section class="mb-12">
    <h2 class="text-2xl font-bold mb-4">O que é o V4 Ads MCP</h2>
    <p>
      Servidor MCP (Model Context Protocol) interno V4 que conecta as contas Google Ads que você gerencia ao Claude, Codex e Cursor.
      Você pede em linguagem natural — "performance da conta X últimos 30 dias", "pause keywords sem conversão" — e o assistente
      executa via ferramentas auditadas + governança (dry-run + apply para mutações).
    </p>
  </section>

  <section class="mb-12">
    <h2 class="text-2xl font-bold mb-4">Como configurar — passo a passo</h2>
    <ol class="space-y-4">
      <li><strong>Login no painel</strong> — acesse <a href="/login" class="underline">/login</a> com sua conta <code>@v4company.com</code>.</li>
      <li><strong>Espere o admin liberar contas</strong> — em <a href="/accounts" class="underline">/accounts</a> você verá as contas que pode gerenciar.</li>
      <li><strong>Crie uma sessão MCP</strong> em <a href="/sessions" class="underline">/sessions</a> — copie o Bearer token (aparece UMA vez).</li>
      <li><strong>Configure seu cliente</strong> com os snippets abaixo.</li>
    </ol>
  </section>

  <section class="mb-12">
    <h3 class="text-xl font-semibold mb-3">Claude Desktop</h3>
    <p class="mb-3">Edite <code>%APPDATA%\Claude\claude_desktop_config.json</code> (Windows) ou <code>~/Library/Application Support/Claude/claude_desktop_config.json</code> (Mac):</p>
    {{ code_block('{\n  "mcpServers": {\n    "v4-ads": {\n      "url": "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp",\n      "headers": {\n        "Authorization": "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"\n      }\n    }\n  }\n}', filename="claude_desktop_config.json") }}
    <p class="mt-3 text-sm text-v4-gray-700"><strong>Reinicie o Claude Desktop totalmente</strong> (sair pelo system tray, não só fechar a janela).</p>
  </section>

  <section class="mb-12">
    <h3 class="text-xl font-semibold mb-3">Codex CLI</h3>
    {{ code_block('[mcp_servers.v4-ads]\nurl = "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp"\n\n[mcp_servers.v4-ads.headers]\nAuthorization = "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"', filename="~/.codex/config.toml") }}
  </section>

  <section class="mb-12">
    <h3 class="text-xl font-semibold mb-3">Cursor</h3>
    {{ code_block('{\n  "mcpServers": {\n    "v4-ads": {\n      "url": "https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/mcp",\n      "headers": {\n        "Authorization": "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"\n      }\n    }\n  }\n}', filename=".cursor/mcp.json") }}
  </section>

  <section class="mb-12">
    <h2 class="text-2xl font-bold mb-4">FAQ</h2>

    <h3 class="text-lg font-semibold mt-6 mb-2">"Tool not found" no Claude</h3>
    <p>Reinicie o Claude Desktop completamente (sair pelo system tray). Verifique que o Bearer token está exatamente como copiado, sem espaços extras.</p>

    <h3 class="text-lg font-semibold mt-6 mb-2">Perdi o token, e agora?</h3>
    <p>Tokens só aparecem uma vez. Crie uma <a href="/sessions" class="underline">nova sessão</a> em <code>/sessions</code> e descarte a anterior em <code>Revogar</code>.</p>

    <h3 class="text-lg font-semibold mt-6 mb-2">Não vejo as contas que deveria gerenciar</h3>
    <p>Peça pro admin V4 da sua unidade liberar via <code>/admin/access</code>.</p>

    <h3 class="text-lg font-semibold mt-6 mb-2">"acesso negado" depois de logar com Google</h3>
    <p>Seu email não está na allowlist. Peça pro admin te adicionar em <code>/admin/invites</code>.</p>
  </section>
</article>
{% endblock %}
```

- [ ] **Step 2: Add the route**

In `src/web/routes.py`:

```python
@router.get("/help", response_class=HTMLResponse)
async def help_page(
    request: Request,
    user: CurrentUser | None = Depends(optional_current_manager),  # noqa: B008
) -> HTMLResponse:
    """Onboarding consolidated. Accessible logged-in or out (login link is included)."""
    return templates.TemplateResponse(
        request, "help.html", {"current_user": user}
    )
```

- [ ] **Step 3: Visual smoke test**

Visit `/help`. Expected: clean Editorial layout with code blocks (each with dark background + filename + Copy button).

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/help.html src/web/routes.py
git commit -m "feat(web): /help page (onboarding consolidated)"
```

### Task 3.3: Redesign `/` (dashboard) Hybrid hero

**Files:**
- Modify: `src/web/templates/dashboard.html`
- Modify: `src/web/routes.py` (provide `oauth_email`, last activity, etc.)

- [ ] **Step 1: Replace `dashboard.html` content**

`src/web/templates/dashboard.html`:

```html
{% extends "_base.html" %}
{% from "_components.html" import stat, badge, alert, sparkline %}

{% block title %}Dashboard — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-5xl mx-auto py-8 px-4">

  {# Editorial hero #}
  <header class="mb-10">
    <h1 class="text-4xl md:text-5xl font-sans font-extrabold leading-none tracking-tight text-v4-gray-900">
      Bem-vindo, <span class="text-v4-red">{{ current_user.full_name.split(' ')[0] if current_user.full_name else current_user.email.split('@')[0] }}</span>.
    </h1>
    <div class="mt-3 flex items-center gap-3 text-xs text-v4-gray-700 uppercase tracking-wider">
      {% if current_user.is_admin %}
        <span class="bg-v4-red-soft text-v4-red-dark px-2 py-1 rounded font-semibold">ADMIN</span>
      {% else %}
        <span class="bg-v4-gray-100 text-v4-gray-700 px-2 py-1 rounded font-semibold">GESTOR</span>
      {% endif %}
      <span>V4 unidade · {{ unidade_label or "—" }}</span>
      {% if current_user.last_seen_at %}
      <span>·</span>
      <span>último acesso {{ current_user.last_seen_at.strftime("%d/%m %H:%M") }}</span>
      {% endif %}
    </div>
  </header>

  {# Operational stat grid #}
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-10">
    <div class="border border-v4-gray-100 rounded-md p-3">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Contas</div>
      <div class="text-3xl font-bold mt-1">{{ accounts_count }}</div>
      <div class="text-xs text-v4-gray-300 mt-1">Google Ads acessíveis</div>
    </div>

    <div class="border border-v4-gray-100 rounded-md p-3">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Sessões</div>
      <div class="text-3xl font-bold mt-1">{{ sessions_count }}</div>
      <div class="text-xs text-v4-gray-300 mt-1">MCP ativas</div>
    </div>

    <div class="border border-v4-gray-100 rounded-md p-3">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Chamadas hoje</div>
      <div class="text-3xl font-bold mt-1">{{ calls_today }}</div>
      {% if calls_sparkline %}
        <div class="mt-1">{{ sparkline(calls_sparkline, width=80, height=14) }}</div>
      {% else %}
        <div class="text-xs text-v4-gray-300 mt-1">últimos 7 dias</div>
      {% endif %}
    </div>

    <div class="border border-v4-gray-100 rounded-md p-3">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Conexão Google</div>
      {% if oauth_email %}
        <div class="text-sm font-semibold mt-1 truncate" title="{{ oauth_email }}">{{ oauth_email }}</div>
        <div class="text-xs text-v4-gray-300 mt-1">conectado em {{ oauth_connected_at.strftime("%d/%m") }}</div>
      {% else %}
        <div class="text-sm font-semibold mt-1 text-v4-red">Não conectada</div>
        <div class="text-xs text-v4-gray-300 mt-1"><a href="/accounts" class="underline">conectar</a></div>
      {% endif %}
    </div>
  </div>

  {# Conditional next steps — only show if there's a real gap #}
  {% if not oauth_email or accounts_count == 0 or sessions_count == 0 %}
  <div class="v4-card v4-card--highlighted mb-8">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Próximos passos</h3>
    </div>
    <ul class="space-y-2 pl-5 list-disc">
      {% if not oauth_email %}
        <li><a href="/accounts" class="underline">Conectar conta Google Ads</a> — autorize acesso ao MCC</li>
      {% endif %}
      {% if accounts_count == 0 %}
        <li>Pedir pro admin V4 da sua unidade liberar contas pra você</li>
      {% endif %}
      {% if sessions_count == 0 %}
        <li><a href="/sessions" class="underline">Criar uma sessão MCP</a> — gera o Bearer pra Claude/Codex/Cursor</li>
      {% endif %}
    </ul>
  </div>
  {% endif %}

  {# Recent activity #}
  {% if recent_calls %}
  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Atividade recente</h3>
      <a href="/audit" class="text-sm text-v4-red underline">ver tudo →</a>
    </div>
    <table class="v4-table v4-table--compact">
      <thead>
        <tr>
          <th>Quando</th>
          <th>Operação</th>
          <th>Conta</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {% for r in recent_calls %}
        <tr>
          <td class="col-mono">{{ r.occurred_at.strftime("%d/%m %H:%M") }}</td>
          <td class="col-mono">{{ r.operation }}</td>
          <td>{{ r.account_name or r.customer_id or "—" }}</td>
          <td>
            {% if r.status == "success" %}{{ badge("OK", "success") }}
            {% elif r.status == "error" %}{{ badge("Erro", "error") }}
            {% else %}{{ badge(r.status, "neutral") }}{% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {# Admin-only operational card #}
  {% if current_user.is_admin and admin_ops %}
  <div class="v4-card v4-card--highlighted mt-8">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Operação V4 Ads MCP</h3>
      <a href="/admin" class="text-sm text-v4-red underline">painel admin →</a>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div>
        <div class="text-xs text-v4-gray-700 uppercase font-semibold">Convites pendentes</div>
        <div class="text-2xl font-bold {% if admin_ops.pending_invites > 0 %}text-v4-gold{% endif %}">
          {{ admin_ops.pending_invites }}
        </div>
        {% if admin_ops.pending_invites > 0 %}
          <a href="/admin/invites" class="text-xs underline text-v4-gray-700">ver →</a>
        {% endif %}
      </div>
      <div>
        <div class="text-xs text-v4-gray-700 uppercase font-semibold">Quota MCP hoje</div>
        <div class="text-2xl font-bold">{{ admin_ops.quota_used }} / {{ admin_ops.quota_max }}</div>
      </div>
      <div>
        <div class="text-xs text-v4-gray-700 uppercase font-semibold">Erros últ. 24h</div>
        <div class="text-2xl font-bold {% if admin_ops.errors_24h > 0 %}text-v4-red{% else %}text-v4-green{% endif %}">
          {{ admin_ops.errors_24h }}
        </div>
        {% if admin_ops.errors_24h > 0 %}
          <a href="/admin/audit?status=error" class="text-xs underline text-v4-gray-700">investigar →</a>
        {% endif %}
      </div>
      <div>
        <div class="text-xs text-v4-gray-700 uppercase font-semibold">Gestores ativos</div>
        <div class="text-2xl font-bold">{{ admin_ops.active_managers }} / {{ admin_ops.total_managers }}</div>
      </div>
    </div>
  </div>
  {% endif %}

</section>
{% endblock %}
```

- [ ] **Step 2: Update the dashboard route handler in `routes.py`**

Locate the existing `@router.get("/")` handler. Replace its body with:

```python
from datetime import datetime, timedelta

@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)
        active_sessions = await mcp_sessions.list_for_manager(conn, user.id, include_revoked=False)
        oauth_conn = await google_oauth_connections.get_active_for_manager(conn, user.id)

        # Recent calls (last 5 by this manager)
        from src.db.repositories import audit_log
        recent = await conn.fetch(
            """SELECT occurred_at, operation, customer_id, status,
                      (SELECT descriptive_name FROM google_ads_accounts a
                       WHERE a.customer_id = al.customer_id LIMIT 1) AS account_name
               FROM audit_log al
               WHERE manager_id = $1
               ORDER BY occurred_at DESC LIMIT 5""",
            user.id,
        )

        # Calls today (count + sparkline of last 7 days)
        today = datetime.utcnow().date()
        calls_today = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE manager_id = $1 AND occurred_at::date = $2",
            user.id, today,
        ) or 0
        sparkline_rows = await conn.fetch(
            """SELECT (occurred_at::date) as d, count(*) AS c
               FROM audit_log
               WHERE manager_id = $1 AND occurred_at >= $2
               GROUP BY 1 ORDER BY 1""",
            user.id, today - timedelta(days=6),
        )
        # Build 7-day series, filling zeros for missing days
        days = [today - timedelta(days=i) for i in range(6, -1, -1)]
        counts_by_day = {r["d"]: r["c"] for r in sparkline_rows}
        sparkline_values = [counts_by_day.get(d, 0) for d in days]

        admin_ops = None
        if user.is_admin:
            from src.db.repositories import managers as managers_repo
            pending = await managers_repo.count_invited(conn)
            errors_24h = await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE status='error' AND occurred_at > now() - interval '24 hours'",
            ) or 0
            quota_used = await conn.fetchval(
                "SELECT used_today FROM rate_counters WHERE date = current_date LIMIT 1",
            ) or 0
            active_mgrs = await conn.fetchval(
                "SELECT count(*) FROM managers WHERE status = 'active'"
            ) or 0
            total_mgrs = await conn.fetchval("SELECT count(*) FROM managers") or 0
            admin_ops = {
                "pending_invites": pending,
                "quota_used": quota_used,
                "quota_max": 15000,
                "errors_24h": errors_24h,
                "active_managers": active_mgrs,
                "total_managers": total_mgrs,
            }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "current_user": user,
            "accounts_count": len(accounts),
            "sessions_count": len(active_sessions),
            "oauth_email": oauth_conn["google_email"] if oauth_conn else None,
            "oauth_connected_at": oauth_conn["connected_at"] if oauth_conn else None,
            "calls_today": calls_today,
            "calls_sparkline": sparkline_values,
            "recent_calls": [dict(r) for r in recent],
            "unidade_label": "—",  # placeholder until sub-project 2 ships
            "admin_ops": admin_ops,
        },
    )
```

- [ ] **Step 3: Visual smoke test**

Login as admin. Visit `/`. Expected:
- Editorial hero "Bem-vindo, **Wellinton**." with name in V4 red.
- "ADMIN" badge red, unidade label, last access timestamp.
- 4 stat cards in a row (md+) or 2x2 (mobile).
- "Próximos passos" hidden (you have OAuth, accounts, session).
- "Atividade recente" with last 5 audit entries.
- "Operação V4 Ads MCP" admin card with 4 metrics.

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/dashboard.html src/web/routes.py
git commit -m "feat(web): redesign / dashboard (Editorial hero + Operational stats + admin extras)"
```

### Task 3.4: Create `/admin` overview page

**Files:**
- Create: `src/web/templates/admin/index.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Create the template**

`src/web/templates/admin/index.html`:

```html
{% extends "_base.html" %}
{% from "_components.html" import sparkline, badge %}

{% block title %}Admin · Visão geral — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-5xl mx-auto py-8 px-4">
  <header class="mb-10">
    <h1 class="text-4xl font-sans font-extrabold leading-none tracking-tight text-v4-gray-900">
      Operação · <span class="text-v4-red">V4 Ads MCP</span>
    </h1>
    <p class="text-sm text-v4-gray-700 mt-2">Visão consolidada de uso, saúde e onboarding da plataforma.</p>
  </header>

  {# Top metrics #}
  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
    <div class="border border-v4-gray-100 rounded-md p-4">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Convites pendentes</div>
      <div class="text-3xl font-bold {% if pending_invites > 0 %}text-v4-gold{% endif %}">{{ pending_invites }}</div>
      {% if pending_invites > 0 %}
        <a href="/admin/invites" class="text-xs text-v4-gray-700 underline">ver lista →</a>
      {% endif %}
    </div>
    <div class="border border-v4-gray-100 rounded-md p-4">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Gestores ativos</div>
      <div class="text-3xl font-bold">{{ active_managers }} <span class="text-base text-v4-gray-300">/ {{ total_managers }}</span></div>
    </div>
    <div class="border border-v4-gray-100 rounded-md p-4">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Quota MCP hoje</div>
      <div class="text-3xl font-bold">{{ quota_used }}</div>
      <div class="text-xs text-v4-gray-300 mt-1">/ {{ quota_max }} ops</div>
    </div>
    <div class="border border-v4-gray-100 rounded-md p-4">
      <div class="text-xs text-v4-gray-700 uppercase tracking-wider font-semibold">Erros 24h</div>
      <div class="text-3xl font-bold {% if errors_24h > 0 %}text-v4-red{% else %}text-v4-green{% endif %}">{{ errors_24h }}</div>
      {% if errors_24h > 0 %}
        <a href="/admin/audit?status=error" class="text-xs text-v4-gray-700 underline">investigar →</a>
      {% endif %}
    </div>
  </div>

  {# Usage history #}
  <div class="v4-card mb-6">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Uso últimos 30 dias</h3>
      <a href="/admin/audit" class="text-sm text-v4-red underline">audit →</a>
    </div>
    <div class="px-4 pb-4">
      {% if usage_30d %}
        {{ sparkline(usage_30d, width=600, height=80, color="var(--v4-red)") }}
      {% else %}
        <p class="text-v4-gray-300 text-center py-8">Sem dados ainda.</p>
      {% endif %}
    </div>
  </div>

  {# Top operations + Top gestores side-by-side #}
  <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
    <div class="v4-card">
      <div class="v4-card__header">
        <h3 class="v4-card__title">Top operações (7 dias)</h3>
      </div>
      <table class="v4-table v4-table--compact">
        <tbody>
          {% for op in top_operations %}
          <tr>
            <td class="col-mono">{{ op.operation }}</td>
            <td class="text-right font-bold">{{ op.count }}</td>
          </tr>
          {% endfor %}
          {% if not top_operations %}
          <tr><td class="text-center text-v4-gray-300 py-6">Sem dados.</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>

    <div class="v4-card">
      <div class="v4-card__header">
        <h3 class="v4-card__title">Top gestores (7 dias)</h3>
      </div>
      <table class="v4-table v4-table--compact">
        <tbody>
          {% for g in top_managers %}
          <tr>
            <td>{{ g.email }}</td>
            <td class="text-right font-bold">{{ g.count }}</td>
          </tr>
          {% endfor %}
          {% if not top_managers %}
          <tr><td class="text-center text-v4-gray-300 py-6">Sem dados.</td></tr>
          {% endif %}
        </tbody>
      </table>
    </div>
  </div>

  {# Recent onboarding #}
  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Onboarding recente</h3>
    </div>
    {% if recent_onboarding %}
    <table class="v4-table v4-table--compact">
      <thead>
        <tr>
          <th>Email</th>
          <th>Status</th>
          <th>Quando</th>
        </tr>
      </thead>
      <tbody>
        {% for m in recent_onboarding %}
        <tr>
          <td><strong>{{ m.email }}</strong></td>
          <td>
            {% if m.status == "invited" %}{{ badge("Convidado", "warning") }}
            {% elif m.status == "active" %}{{ badge("Ativo", "success") }}
            {% else %}{{ badge(m.status, "neutral") }}{% endif %}
          </td>
          <td class="col-mono">{{ (m.invited_at or m.created_at).strftime("%d/%m %H:%M") }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      <p class="text-v4-gray-300 text-center py-6">Nenhum onboarding recente.</p>
    {% endif %}
  </div>
</section>
{% endblock %}
```

- [ ] **Step 2: Add the route**

```python
@router.get("/admin", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import managers as managers_repo

        pending = await managers_repo.count_invited(conn)
        active_mgrs = await conn.fetchval(
            "SELECT count(*) FROM managers WHERE status = 'active'"
        ) or 0
        total_mgrs = await conn.fetchval("SELECT count(*) FROM managers") or 0
        quota_used = await conn.fetchval(
            "SELECT used_today FROM rate_counters WHERE date = current_date"
        ) or 0
        errors_24h = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE status='error' AND occurred_at > now() - interval '24 hours'"
        ) or 0

        # Usage 30d sparkline
        rows_30 = await conn.fetch(
            """SELECT (occurred_at::date) AS d, count(*) AS c
               FROM audit_log
               WHERE occurred_at > now() - interval '30 days'
               GROUP BY 1 ORDER BY 1"""
        )
        usage_30d = [r["c"] for r in rows_30]

        # Top operations 7d
        top_ops = await conn.fetch(
            """SELECT operation, count(*) AS count FROM audit_log
               WHERE occurred_at > now() - interval '7 days'
               GROUP BY operation ORDER BY count DESC LIMIT 5"""
        )
        # Top managers 7d
        top_mgrs = await conn.fetch(
            """SELECT m.email, count(*) AS count
               FROM audit_log al JOIN managers m ON m.id = al.manager_id
               WHERE al.occurred_at > now() - interval '7 days'
               GROUP BY m.email ORDER BY count DESC LIMIT 5"""
        )
        # Recent onboarding (last 10 managers by created_at)
        onboarding = await conn.fetch(
            """SELECT email, status, created_at, invited_at
               FROM managers ORDER BY coalesce(invited_at, created_at) DESC LIMIT 10"""
        )

    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "current_user": user,
            "pending_invites": pending,
            "pending_invites_count": pending,
            "active_managers": active_mgrs,
            "total_managers": total_mgrs,
            "quota_used": quota_used,
            "quota_max": 15000,
            "errors_24h": errors_24h,
            "usage_30d": usage_30d,
            "top_operations": [dict(r) for r in top_ops],
            "top_managers": [dict(r) for r in top_mgrs],
            "recent_onboarding": [dict(r) for r in onboarding],
        },
    )
```

- [ ] **Step 3: Visual smoke test**

Login as admin. Click "Admin" in nav (red badge button). Expected: lands on `/admin` showing 4 top metrics, 30d sparkline, top operations + managers, recent onboarding list.

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/admin/index.html src/web/routes.py
git commit -m "feat(admin): /admin overview page (Hybrid hero + operational metrics)"
```

### Task 3.5: Phase 3 deploy + smoke

- [ ] **Step 1: Push + watch CI**

```bash
git push origin main
gh run watch
```

- [ ] **Step 2: Visual E2E in production**

Login as admin. Walk through:
- `/login` (logout first) — Editorial hero displays "V4 Ads MCP. IA + Google Ads."
- `/help` — onboarding doc renders cleanly with code blocks.
- `/access-denied?reason=domain` (incognito) — Editorial 403.
- `/` — Hybrid hero greeting, stats, recent activity, admin operations card.
- `/admin` — overview metrics, sparkline, tops, onboarding list.
- Click "Admin" link in nav — sub-nav appears with "Visão geral" highlighted.

- [ ] **Step 3: Phase 3 done marker**

```bash
git commit --allow-empty -m "chore: Phase 3 (Editorial + Hybrid hero) complete and verified in production"
git push origin main
```

---

## Phase 4 — Operational tables (6-9 days)

Goal: deliver the heaviest UX gain — `/audit`, `/audit/{id}`, `/admin/audit`, and the `/admin/access` matrix with new search + bulk actions and a mobile per-gestor paradigm.

### Task 4.1: Audit repository — `get_by_id`, `export_csv`, `summary_stats`

**Files:**
- Modify: `src/db/repositories/audit_log.py`
- Create/Modify: `tests/integration/test_audit_log_repo.py`

- [ ] **Step 1: Write failing tests**

Append to (or create) `tests/integration/test_audit_log_repo.py`:

```python
"""Tests for audit_log repository extensions (Phase 4)."""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta

from src.db.repositories import audit_log


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_returns_full_row(db_pool):
    mid = uuid4()
    sid = uuid4()
    aid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')""",
            mid,
        )
        await conn.execute(
            """INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'test', 'h')""",
            sid, mid,
        )
        await conn.execute(
            """INSERT INTO audit_log (id, manager_id, session_id, customer_id, action_type, operation, status,
                                       target_count, params_summary, error_message, duration_ms, occurred_at)
               VALUES ($1, $2, $3, '1234567890', 'read', 'list_my_accounts', 'success',
                       23, '{}'::jsonb, NULL, 7, now())""",
            aid, mid, sid,
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=mid)
    assert result is not None
    assert result["operation"] == "list_my_accounts"
    assert result["target_count"] == 23


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_scopes_to_manager(db_pool):
    """Gestor passing manager_id can't see other gestores' events."""
    mid = uuid4()
    other = uuid4()
    aid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'a@v4company.com', 'active', 'gestor'),
               ($2, 'b@v4company.com', 'active', 'gestor')""",
            mid, other,
        )
        await conn.execute(
            """INSERT INTO audit_log (id, manager_id, action_type, operation, status, occurred_at)
               VALUES ($1, $2, 'read', 'op', 'success', now())""",
            aid, other,  # belongs to OTHER manager
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=mid)
    assert result is None  # mid can't see other's row


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_admin_sees_any(db_pool):
    """When manager_id=None (admin context), any audit_id is reachable."""
    other = uuid4()
    aid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'b@v4company.com', 'active', 'gestor')""",
            other,
        )
        await conn.execute(
            """INSERT INTO audit_log (id, manager_id, action_type, operation, status, occurred_at)
               VALUES ($1, $2, 'read', 'op', 'success', now())""",
            aid, other,
        )
        result = await audit_log.get_by_id(conn, audit_id=aid, manager_id=None)
    assert result is not None
    assert result["operation"] == "op"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_summary_stats_24h_window(db_pool):
    mid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')""",
            mid,
        )
        # 2 success in last hour, 1 error in last hour, 1 success 25h ago (out of window)
        await conn.execute(
            """INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at) VALUES
               ($1, 'read', 'op1', 'success', now() - interval '10 minutes'),
               ($1, 'read', 'op1', 'success', now() - interval '20 minutes'),
               ($1, 'mutate', 'op2', 'error', now() - interval '5 minutes'),
               ($1, 'read', 'op1', 'success', now() - interval '25 hours')""",
            mid,
        )
        stats = await audit_log.summary_stats(conn)
    assert stats["total_24h"] == 3
    assert stats["errors_24h"] == 1
    assert stats["success_24h"] == 2
```

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/integration/test_audit_log_repo.py -v 2>&1 | tail -20
```

Expected: AttributeError on `audit_log.get_by_id` and `audit_log.summary_stats`.

- [ ] **Step 3: Implement the repo functions**

Append to `src/db/repositories/audit_log.py`:

```python
from typing import Any, AsyncIterator
from uuid import UUID
import csv
import io
import asyncpg


async def get_by_id(
    conn: asyncpg.Connection,
    *,
    audit_id: UUID,
    manager_id: UUID | None,
) -> dict[str, Any] | None:
    """Fetch a single audit event.

    If manager_id is provided, scoped to that gestor (returns None if event belongs to another).
    If manager_id is None (admin context), returns any event by id.
    """
    if manager_id is None:
        row = await conn.fetchrow(
            """SELECT al.*, m.email AS manager_email,
                      s.label AS session_label,
                      a.descriptive_name AS account_name
               FROM audit_log al
               LEFT JOIN managers m ON m.id = al.manager_id
               LEFT JOIN mcp_sessions s ON s.id = al.session_id
               LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id
               WHERE al.id = $1""",
            audit_id,
        )
    else:
        row = await conn.fetchrow(
            """SELECT al.*, m.email AS manager_email,
                      s.label AS session_label,
                      a.descriptive_name AS account_name
               FROM audit_log al
               LEFT JOIN managers m ON m.id = al.manager_id
               LEFT JOIN mcp_sessions s ON s.id = al.session_id
               LEFT JOIN google_ads_accounts a ON a.customer_id = al.customer_id
               WHERE al.id = $1 AND al.manager_id = $2""",
            audit_id, manager_id,
        )
    return dict(row) if row else None


async def summary_stats(conn: asyncpg.Connection) -> dict[str, int]:
    """Aggregate counts over the last 24 hours."""
    row = await conn.fetchrow(
        """SELECT
             count(*) AS total,
             count(*) FILTER (WHERE status = 'success') AS success,
             count(*) FILTER (WHERE status = 'error') AS errors
           FROM audit_log
           WHERE occurred_at > now() - interval '24 hours'"""
    )
    return {
        "total_24h": row["total"],
        "success_24h": row["success"],
        "errors_24h": row["errors"],
    }


async def export_csv_rows(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID | None = None,
    customer_id: str | None = None,
    action_type: str | None = None,
    days: int = 7,
) -> AsyncIterator[str]:
    """Yield CSV lines (header + data) for streaming response."""
    where = ["occurred_at > now() - ($1 || ' days')::interval"]
    params: list[Any] = [str(days)]
    idx = 2
    if manager_id is not None:
        where.append(f"manager_id = ${idx}"); params.append(manager_id); idx += 1
    if customer_id:
        where.append(f"customer_id = ${idx}"); params.append(customer_id); idx += 1
    if action_type and action_type != "all":
        where.append(f"action_type = ${idx}"); params.append(action_type); idx += 1
    sql = f"""SELECT al.occurred_at, m.email, al.operation, al.customer_id,
                     al.action_type, al.status, al.target_count, al.duration_ms,
                     al.error_message, al.google_request_id
              FROM audit_log al LEFT JOIN managers m ON m.id = al.manager_id
              WHERE {' AND '.join(where)}
              ORDER BY al.occurred_at DESC"""

    # Header
    header = ["occurred_at", "manager_email", "operation", "customer_id",
              "action_type", "status", "target_count", "duration_ms",
              "error_message", "google_request_id"]
    buf = io.StringIO()
    csv.writer(buf).writerow(header)
    yield buf.getvalue()

    async for row in conn.cursor(sql, *params):
        buf = io.StringIO()
        csv.writer(buf).writerow([
            row["occurred_at"].isoformat() if row["occurred_at"] else "",
            row["email"] or "",
            row["operation"] or "",
            row["customer_id"] or "",
            row["action_type"] or "",
            row["status"] or "",
            row["target_count"] if row["target_count"] is not None else "",
            row["duration_ms"] if row["duration_ms"] is not None else "",
            row["error_message"] or "",
            row["google_request_id"] or "",
        ])
        yield buf.getvalue()
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/integration/test_audit_log_repo.py -v 2>&1 | tail -15
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/db/repositories/audit_log.py tests/integration/test_audit_log_repo.py
git commit -m "feat(db): audit_log get_by_id + summary_stats + export_csv_rows (streaming)"
```

### Task 4.2: Redesign `/audit` page

**Files:**
- Modify: `src/web/templates/audit.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Replace `audit.html` content**

```html
{% extends "_base.html" %}
{% from "_components.html" import badge, empty_state, pagination %}

{% block title %}Audit log — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-6xl mx-auto py-6 px-4">
  <header class="mb-6 flex flex-wrap items-end justify-between gap-3">
    <div>
      <h1 class="text-3xl font-extrabold tracking-tight">Audit log</h1>
      <p class="text-sm text-v4-gray-700">Suas chamadas MCP nos últimos {{ filter_days }} dias.</p>
    </div>
    <a href="/audit/export.csv?{{ query_string }}" class="v4-btn v4-btn--secondary v4-btn--small">
      ⤓ Exportar CSV
    </a>
  </header>

  {# Sticky filter bar with auto-submit #}
  <form id="audit-filters" method="GET" action="/audit"
        class="sticky top-[53px] z-[10] bg-white border-b border-v4-gray-100 py-3 mb-4 flex flex-wrap gap-3 items-end">
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label" for="action_type">Tipo</label>
      <select id="action_type" name="action_type" class="v4-select"
              onchange="this.form.submit()">
        <option value="all" {% if filter_action_type == "all" %}selected{% endif %}>Todos</option>
        <option value="mutate" {% if filter_action_type == "mutate" %}selected{% endif %}>Mutações</option>
        <option value="read" {% if filter_action_type == "read" %}selected{% endif %}>Reads sensíveis</option>
      </select>
    </div>
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label" for="customer_id">Conta</label>
      <select id="customer_id" name="customer_id" class="v4-select" onchange="this.form.submit()">
        <option value="">Todas</option>
        {% for a in accessible_accounts %}
          <option value="{{ a.customer_id }}" {% if filter_customer_id == a.customer_id %}selected{% endif %}>
            {{ a.descriptive_name }} ({{ a.customer_id }})
          </option>
        {% endfor %}
      </select>
    </div>
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label" for="status">Status</label>
      <select id="status" name="status" class="v4-select" onchange="this.form.submit()">
        <option value="all" {% if filter_status == "all" %}selected{% endif %}>Todos</option>
        <option value="success" {% if filter_status == "success" %}selected{% endif %}>OK</option>
        <option value="error" {% if filter_status == "error" %}selected{% endif %}>Erros</option>
      </select>
    </div>
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label" for="days">Período</label>
      <select id="days" name="days" class="v4-select" onchange="this.form.submit()">
        {% for n in [1, 7, 14, 30, 90] %}
          <option value="{{ n }}" {% if filter_days == n %}selected{% endif %}>{{ n }} dias</option>
        {% endfor %}
      </select>
    </div>
  </form>

  {# Day-grouped events #}
  {% if grouped %}
    {% for day, events in grouped.items() %}
    <div class="mb-6">
      <h3 class="sticky top-[120px] z-[5] bg-v4-gray-50 border-y border-v4-gray-100 py-2 px-3 text-xs uppercase tracking-wider font-semibold text-v4-gray-700">
        {{ day }}
      </h3>
      <table class="v4-table v4-table--compact">
        <thead>
          <tr>
            <th>Hora</th>
            <th>Operação</th>
            <th>Conta</th>
            <th>Tipo</th>
            <th>Status</th>
            <th>Alvos</th>
            <th>Duração</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {% for r in events %}
          <tr id="row-{{ r.id }}" class="is-expandable" onclick="v4ToggleRow('row-{{ r.id }}')">
            <td class="col-mono">{{ r.occurred_at.strftime("%H:%M:%S") }}</td>
            <td class="col-mono">{{ r.operation }}</td>
            <td>
              {% if r.customer_id %}
                <strong>{{ r.account_name or r.customer_id }}</strong>
                <div class="text-xs text-v4-gray-300">{{ r.customer_id }}</div>
              {% else %}—{% endif %}
            </td>
            <td>
              {% if r.action_type == "mutate" %}{{ badge("Mutate", "warning") }}
              {% elif r.action_type == "read" %}{{ badge("Read", "neutral") }}
              {% elif r.action_type == "auth" %}{{ badge("Auth", "neutral") }}
              {% else %}{{ badge(r.action_type, "neutral") }}{% endif %}
            </td>
            <td>
              {% if r.status == "success" %}{{ badge("✓ OK", "success") }}
              {% elif r.status == "error" %}{{ badge("✗ Erro", "error") }}
              {% elif r.status == "denied" %}{{ badge("⊘ Negado", "error") }}
              {% else %}{{ badge(r.status, "neutral") }}{% endif %}
            </td>
            <td>{{ r.target_count if r.target_count is not none else "—" }}</td>
            <td class="col-mono text-v4-gray-700">{{ r.duration_ms ~ "ms" if r.duration_ms else "—" }}</td>
            <td class="text-right">
              <a href="/audit/{{ r.id }}" class="v4-btn v4-btn--small v4-btn--ghost"
                 onclick="event.stopPropagation();">Detalhe</a>
            </td>
          </tr>
          <tr id="row-{{ r.id }}-detail" class="v4-table__detail">
            <td colspan="8">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 p-2">
                {% if r.error_message %}
                <div>
                  <div class="text-xs uppercase font-semibold text-v4-gray-700 mb-1">Erro</div>
                  <div class="bg-v4-red-soft text-v4-red-dark p-2 rounded font-mono text-xs">{{ r.error_message }}</div>
                </div>
                {% endif %}
                {% if r.params_summary %}
                <div>
                  <div class="text-xs uppercase font-semibold text-v4-gray-700 mb-1">Parâmetros</div>
                  <pre class="bg-v4-gray-50 p-2 rounded text-xs overflow-x-auto">{{ r.params_summary | tojson(indent=2) }}</pre>
                </div>
                {% endif %}
                {% if r.google_request_id %}
                <div class="col-span-1 md:col-span-2 text-xs">
                  <span class="text-v4-gray-700 uppercase">Google Request ID:</span>
                  <code class="ml-2">{{ r.google_request_id }}</code>
                </div>
                {% endif %}
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    {% endfor %}

    {{ pagination(current_page, total_pages, "/audit", "page") }}
  {% else %}
    {{ empty_state("Nenhum evento no período selecionado.", "Tente um período maior ou remova filtros.") }}
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 2: Update the `/audit` route handler**

Find the existing handler in `src/web/routes.py`. Replace the body to support filters + grouping by day + pagination:

```python
@router.get("/audit", response_class=HTMLResponse)
async def audit(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    action_type: str = "all",
    customer_id: str | None = None,
    status: str = "all",
    days: int = 7,
    page: int = 1,
) -> HTMLResponse:
    PAGE_SIZE = 50
    offset = (page - 1) * PAGE_SIZE

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        accounts = await manager_account_access.list_accounts_for_manager(conn, user.id)

        # Build dynamic WHERE
        where = ["al.manager_id = $1", "al.occurred_at > now() - ($2 || ' days')::interval"]
        params: list[Any] = [user.id, str(days)]
        idx = 3
        if action_type != "all":
            where.append(f"al.action_type = ${idx}"); params.append(action_type); idx += 1
        if customer_id:
            where.append(f"al.customer_id = ${idx}"); params.append(customer_id); idx += 1
        if status != "all":
            where.append(f"al.status = ${idx}"); params.append(status); idx += 1

        count_sql = f"SELECT count(*) FROM audit_log al WHERE {' AND '.join(where)}"
        total = await conn.fetchval(count_sql, *params) or 0
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

        rows_sql = f"""SELECT al.*, a.descriptive_name AS account_name
                       FROM audit_log al LEFT JOIN google_ads_accounts a
                         ON a.customer_id = al.customer_id
                       WHERE {' AND '.join(where)}
                       ORDER BY al.occurred_at DESC LIMIT $%d OFFSET $%d""" % (idx, idx + 1)
        params_with_pagination = params + [PAGE_SIZE, offset]
        rows = await conn.fetch(rows_sql, *params_with_pagination)

    # Group by day for sticky day headers
    from collections import OrderedDict
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    today = datetime.utcnow().date()
    for r in rows:
        d = r["occurred_at"].date()
        if d == today: label = "Hoje"
        elif d == today - timedelta(days=1): label = "Ontem"
        else: label = d.strftime("%d/%m/%Y")
        grouped.setdefault(label, []).append(dict(r))

    # Preserve query string for CSV export link
    qparts = []
    if action_type != "all": qparts.append(f"action_type={action_type}")
    if customer_id: qparts.append(f"customer_id={customer_id}")
    if status != "all": qparts.append(f"status={status}")
    qparts.append(f"days={days}")
    query_string = "&".join(qparts)

    return templates.TemplateResponse(
        request, "audit.html",
        {
            "current_user": user,
            "grouped": grouped,
            "accessible_accounts": accounts,
            "filter_action_type": action_type,
            "filter_customer_id": customer_id,
            "filter_status": status,
            "filter_days": days,
            "current_page": page,
            "total_pages": total_pages,
            "query_string": query_string,
        },
    )
```

- [ ] **Step 3: Add `GET /audit/export.csv` route**

```python
from fastapi.responses import StreamingResponse

@router.get("/audit/export.csv", response_model=None)
async def audit_export_csv(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    action_type: str = "all",
    customer_id: str | None = None,
    days: int = 7,
) -> StreamingResponse:
    """Stream CSV export of the gestor's audit log with current filters applied."""
    pool = connection.get_pool()

    async def stream() -> AsyncIterator[bytes]:
        async with pool.acquire() as conn:
            from src.db.repositories import audit_log
            async for line in audit_log.export_csv_rows(
                conn,
                manager_id=user.id,
                customer_id=customer_id,
                action_type=action_type if action_type != "all" else None,
                days=days,
            ):
                yield line.encode("utf-8")

    filename = f"audit-{datetime.utcnow().strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Add `from typing import AsyncIterator` and `from typing import Any` at the top of routes.py if not present.

- [ ] **Step 4: Visual smoke test**

Visit `/audit`. Expected:
- Sticky filter bar at top with 4 selects.
- Changing a select auto-submits (page reloads with filter applied).
- Events grouped by "Hoje", "Ontem", or "DD/MM/YYYY" with sticky day headers.
- Status badges show ✓/✗/⊘ + label.
- Click on a row → expands inline showing error/params/google_request_id.
- "Detalhe" link → goes to `/audit/{id}`.
- "Exportar CSV" downloads a file with current filter applied.

- [ ] **Step 5: Commit**

```bash
git add src/web/templates/audit.html src/web/routes.py
git commit -m "feat(web): redesign /audit (sticky filters + auto-submit + day groups + expand row + CSV)"
```

### Task 4.3: Create `/audit/{id}` detail page

**Files:**
- Create: `src/web/templates/audit_detail.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Create the template**

`src/web/templates/audit_detail.html`:

```html
{% extends "_base.html" %}
{% from "_components.html" import breadcrumb, badge %}

{% block title %}Audit · {{ event.operation }} — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-3xl mx-auto py-6 px-4">
  {{ breadcrumb([
    {"label": "Audit", "url": "/audit"},
    {"label": event.occurred_at.strftime("%d/%m %H:%M:%S")}
  ]) }}

  <header class="mb-6 flex items-center gap-3 flex-wrap">
    <h1 class="text-3xl font-extrabold tracking-tight font-mono">{{ event.operation }}</h1>
    {% if event.status == "success" %}{{ badge("✓ OK", "success") }}
    {% elif event.status == "error" %}{{ badge("✗ Erro", "error") }}
    {% else %}{{ badge(event.status, "neutral") }}{% endif %}
  </header>

  <dl class="grid grid-cols-[140px_1fr] gap-y-3 gap-x-4 text-sm mb-8">
    <dt class="text-v4-gray-700 uppercase text-xs font-semibold pt-1">Manager</dt>
    <dd><strong>{{ event.manager_email or "—" }}</strong></dd>

    <dt class="text-v4-gray-700 uppercase text-xs font-semibold pt-1">Sessão</dt>
    <dd>{{ event.session_label or "—" }}</dd>

    <dt class="text-v4-gray-700 uppercase text-xs font-semibold pt-1">Conta</dt>
    <dd>
      {% if event.customer_id %}
        <strong>{{ event.account_name or event.customer_id }}</strong>
        <span class="text-v4-gray-300 ml-2 font-mono">{{ event.customer_id }}</span>
      {% else %}—{% endif %}
    </dd>

    <dt class="text-v4-gray-700 uppercase text-xs font-semibold pt-1">Tipo</dt>
    <dd class="font-mono">{{ event.action_type }}</dd>

    <dt class="text-v4-gray-700 uppercase text-xs font-semibold pt-1">Duração</dt>
    <dd class="font-mono">{{ event.duration_ms or "—" }}{% if event.duration_ms %}ms{% endif %}</dd>

    <dt class="text-v4-gray-700 uppercase text-xs font-semibold pt-1">Alvos</dt>
    <dd>{{ event.target_count if event.target_count is not none else "—" }}</dd>

    {% if event.google_request_id %}
    <dt class="text-v4-gray-700 uppercase text-xs font-semibold pt-1">Request ID</dt>
    <dd><code class="text-xs">{{ event.google_request_id }}</code></dd>
    {% endif %}
  </dl>

  {% if event.error_message %}
  <div class="mb-6">
    <h3 class="text-sm font-semibold text-v4-gray-700 uppercase mb-2">Mensagem de erro</h3>
    <div class="bg-v4-red-soft text-v4-red-dark p-4 rounded-md font-mono text-sm whitespace-pre-wrap">{{ event.error_message }}</div>
  </div>
  {% endif %}

  {% if event.params_summary %}
  <div class="mb-6">
    <h3 class="text-sm font-semibold text-v4-gray-700 uppercase mb-2">Parâmetros</h3>
    <pre class="bg-v4-gray-900 text-white p-4 rounded-md font-mono text-xs overflow-x-auto">{{ event.params_summary | tojson(indent=2) }}</pre>
  </div>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 2: Add the route**

```python
@router.get("/audit/{audit_id}", response_class=HTMLResponse)
async def audit_detail(
    request: Request,
    audit_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import audit_log
        # Gestores see only their own; admins see any
        scope_id = None if user.is_admin else user.id
        event = await audit_log.get_by_id(conn, audit_id=UUID(audit_id), manager_id=scope_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found or out of scope")
    return templates.TemplateResponse(
        request, "audit_detail.html",
        {"current_user": user, "event": event},
    )
```

- [ ] **Step 3: Visual smoke test**

Visit `/audit`. Click "Detalhe" on any row. Expected: detail page with breadcrumb, operation as h1, badges, full metadata grid, error/params blocks if present.

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/audit_detail.html src/web/routes.py
git commit -m "feat(web): /audit/{id} detail page (full params + error + request_id)"
```

### Task 4.4: Redesign `/admin/audit` (same pattern + extra filters)

**Files:**
- Modify: `src/web/templates/admin/audit.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Replace `admin/audit.html` content**

The same general structure as `/audit` but with an extra "Gestor" filter and showing `manager_email` column:

```html
{% extends "_base.html" %}
{% from "_components.html" import badge, empty_state, pagination %}

{% block title %}Admin · Audit global — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-7xl mx-auto py-6 px-4">
  <header class="mb-6 flex flex-wrap items-end justify-between gap-3">
    <h1 class="text-3xl font-extrabold tracking-tight">Audit global</h1>
    <div class="flex gap-2">
      <a href="/admin/audit?status=error&days={{ filter_days }}" class="v4-btn v4-btn--small v4-btn--secondary">⚠ Só erros</a>
      <a href="/admin/audit/export.csv?{{ query_string }}" class="v4-btn v4-btn--small v4-btn--secondary">⤓ Exportar CSV</a>
    </div>
  </header>

  <form method="GET" action="/admin/audit"
        class="sticky top-[53px] z-[10] bg-white border-b border-v4-gray-100 py-3 mb-4 grid grid-cols-2 md:grid-cols-5 gap-3 items-end">
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label">Gestor</label>
      <select name="manager_id" class="v4-select" onchange="this.form.submit()">
        <option value="">Todos</option>
        {% for m in managers_list %}
          <option value="{{ m.id }}" {% if filter_manager_id == m.id|string %}selected{% endif %}>{{ m.email }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label">Conta</label>
      <select name="customer_id" class="v4-select" onchange="this.form.submit()">
        <option value="">Todas</option>
        {% for a in accounts %}
          <option value="{{ a.customer_id }}" {% if filter_customer_id == a.customer_id %}selected{% endif %}>{{ a.descriptive_name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label">Tipo</label>
      <select name="action_type" class="v4-select" onchange="this.form.submit()">
        <option value="all" {% if filter_action_type == "all" %}selected{% endif %}>Todos</option>
        <option value="mutate" {% if filter_action_type == "mutate" %}selected{% endif %}>Mutações</option>
        <option value="read" {% if filter_action_type == "read" %}selected{% endif %}>Reads</option>
      </select>
    </div>
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label">Status</label>
      <select name="status" class="v4-select" onchange="this.form.submit()">
        <option value="all" {% if filter_status == "all" %}selected{% endif %}>Todos</option>
        <option value="success" {% if filter_status == "success" %}selected{% endif %}>OK</option>
        <option value="error" {% if filter_status == "error" %}selected{% endif %}>Erros</option>
      </select>
    </div>
    <div class="v4-form__group" style="margin: 0;">
      <label class="v4-form__label">Período</label>
      <select name="days" class="v4-select" onchange="this.form.submit()">
        {% for n in [1, 7, 14, 30, 90] %}
          <option value="{{ n }}" {% if filter_days == n %}selected{% endif %}>{{ n }} dias</option>
        {% endfor %}
      </select>
    </div>
  </form>

  {% if rows %}
  <table class="v4-table v4-table--compact v4-table--sticky-head">
    <thead>
      <tr>
        <th>Quando</th>
        <th>Gestor</th>
        <th>Operação</th>
        <th>Conta</th>
        <th>Tipo</th>
        <th>Status</th>
        <th>Alvos</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for r in rows %}
      <tr>
        <td class="col-mono">{{ r.occurred_at.strftime("%d/%m %H:%M:%S") }}</td>
        <td><strong>{{ r.manager_email or "?" }}</strong></td>
        <td class="col-mono">{{ r.operation }}</td>
        <td>{{ r.account_name or r.customer_id or "—" }}</td>
        <td>
          {% if r.action_type == "mutate" %}{{ badge("Mutate", "warning") }}
          {% elif r.action_type == "read" %}{{ badge("Read", "neutral") }}
          {% else %}{{ badge(r.action_type, "neutral") }}{% endif %}
        </td>
        <td>
          {% if r.status == "success" %}{{ badge("✓ OK", "success") }}
          {% elif r.status == "error" %}{{ badge("✗ Erro", "error") }}
          {% else %}{{ badge(r.status, "neutral") }}{% endif %}
        </td>
        <td>{{ r.target_count or "—" }}</td>
        <td><a href="/audit/{{ r.id }}" class="v4-btn v4-btn--ghost v4-btn--small">→</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {{ pagination(current_page, total_pages, "/admin/audit", "page") }}
  {% else %}
    {{ empty_state("Nenhum evento.", "Tente um período maior ou remova filtros.") }}
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 2: Update the `/admin/audit` route handler**

Same pattern as `/audit` but with admin scope. Add the `status` filter + pagination + `query_string` for CSV link. Also add `GET /admin/audit/export.csv` paralleling the gestor one but without manager scope. (Adapt route from Task 4.2 — replace `manager_id=user.id` with `manager_id=None` for admin; use `filter_manager_id` from query if provided.)

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/admin/audit.html src/web/routes.py
git commit -m "feat(admin): /admin/audit redesign with status filter, gestor filter, CSV export"
```

### Task 4.5: Access matrix repository — `bulk_grant`, `copy_access`

**Files:**
- Modify: `src/db/repositories/manager_account_access.py`
- Append to: `tests/integration/test_managers_invite.py` (or create dedicated file)

- [ ] **Step 1: Write failing tests**

Append:

```python
from src.db.repositories import manager_account_access


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_grant_idempotent(db_pool):
    mid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')""",
            mid,
        )
        await conn.execute(
            """INSERT INTO google_ads_accounts (customer_id, descriptive_name, mcc_id, synced_at) VALUES
               ('1111111111', 'A', '6436352492', now()),
               ('2222222222', 'B', '6436352492', now()),
               ('3333333333', 'C', '6436352492', now())"""
        )
        await manager_account_access.bulk_grant(
            conn, manager_id=mid, customer_ids=["1111111111", "2222222222"], granted_by=mid,
        )
        # Re-run with overlap — should be idempotent
        await manager_account_access.bulk_grant(
            conn, manager_id=mid, customer_ids=["2222222222", "3333333333"], granted_by=mid,
        )
        rows = await conn.fetch("SELECT customer_id FROM manager_account_access WHERE manager_id = $1", mid)
    cids = sorted([r["customer_id"] for r in rows])
    assert cids == ["1111111111", "2222222222", "3333333333"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_copy_access_replaces_destination(db_pool):
    src = uuid4()
    dst = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'src@v4company.com', 'active', 'gestor'),
               ($2, 'dst@v4company.com', 'active', 'gestor')""",
            src, dst,
        )
        await conn.execute(
            """INSERT INTO google_ads_accounts (customer_id, descriptive_name, mcc_id, synced_at) VALUES
               ('1111111111', 'A', '6436352492', now()),
               ('2222222222', 'B', '6436352492', now()),
               ('3333333333', 'C', '6436352492', now())"""
        )
        # src has 1+2; dst has 3
        await conn.execute(
            """INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by) VALUES
               ($1, '1111111111', 'write', $1),
               ($1, '2222222222', 'write', $1),
               ($2, '3333333333', 'write', $2)""",
            src, dst,
        )
        await manager_account_access.copy_access(
            conn, from_manager_id=src, to_manager_id=dst, granted_by=src,
        )
        # After copy: dst should have 1+2 (replaced 3)
        rows = await conn.fetch("SELECT customer_id FROM manager_account_access WHERE manager_id = $1", dst)
    assert sorted([r["customer_id"] for r in rows]) == ["1111111111", "2222222222"]
```

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/integration/test_managers_invite.py::test_bulk_grant_idempotent tests/integration/test_managers_invite.py::test_copy_access_replaces_destination -v 2>&1 | tail -15
```

Expected: AttributeError on `bulk_grant` and `copy_access`.

- [ ] **Step 3: Implement the functions**

Append to `src/db/repositories/manager_account_access.py`:

```python
async def bulk_grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_ids: list[str],
    granted_by: UUID,
    access_level: str = "write",
) -> int:
    """Idempotent bulk grant. Inserts rows that don't exist; ignores duplicates."""
    if not customer_ids:
        return 0
    rows = [(manager_id, cid, access_level, granted_by) for cid in customer_ids]
    await conn.executemany(
        """INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (manager_id, customer_id) DO NOTHING""",
        rows,
    )
    return len(rows)


async def copy_access(
    conn: asyncpg.Connection,
    *,
    from_manager_id: UUID,
    to_manager_id: UUID,
    granted_by: UUID,
) -> int:
    """Replace destination's access with source's access. Atomic."""
    async with conn.transaction():
        await conn.execute(
            "DELETE FROM manager_account_access WHERE manager_id = $1",
            to_manager_id,
        )
        result = await conn.execute(
            """INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
               SELECT $1, customer_id, access_level, $2
               FROM manager_account_access
               WHERE manager_id = $3""",
            to_manager_id, granted_by, from_manager_id,
        )
    # asyncpg returns 'INSERT 0 N'
    return int(result.rsplit(" ", 1)[-1])
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/integration/test_managers_invite.py::test_bulk_grant_idempotent tests/integration/test_managers_invite.py::test_copy_access_replaces_destination -v 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/db/repositories/manager_account_access.py tests/integration/test_managers_invite.py
git commit -m "feat(db): manager_account_access bulk_grant + copy_access (idempotent + atomic)"
```

### Task 4.6: Redesign `/admin/access` matrix (desktop)

**Files:**
- Modify: `src/web/templates/admin/access.html`
- Modify: `src/web/routes.py` (add bulk routes + search filter)

- [ ] **Step 1: Replace `admin/access.html` content**

```html
{% extends "_base.html" %}
{% from "_components.html" import empty_state %}

{% block title %}Admin · Acessos — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-7xl mx-auto py-6 px-4">
  <header class="mb-6">
    <h1 class="text-3xl font-extrabold tracking-tight">Matriz de acessos</h1>
    <p class="text-sm text-v4-gray-700">Marque a célula pra dar acesso de write a um gestor numa conta. Mudanças instantâneas.</p>
  </header>

  {% if not managers_list %}
    {{ empty_state(
      "Nenhum gestor cadastrado.",
      "Convide um gestor pra começar a atribuir acessos.",
      action='<a href="/admin/invites" class="v4-btn v4-btn--primary">Convidar gestor</a>'
    ) }}
  {% elif not accounts %}
    {{ empty_state("Nenhuma conta sincronizada.", "Aguarde o resync diário ou verifique o setup do MCC.") }}
  {% else %}

  {# Search + bulk toolbar #}
  <div class="bg-v4-gray-50 border border-v4-gray-100 rounded-md p-3 mb-4 flex flex-wrap gap-3 items-center">
    <input type="search" id="search-gestor" placeholder="Buscar gestor..."
           class="v4-input v4-input--search v4-input--small" style="width: 200px;"
           onkeyup="filterMatrix()">
    <input type="search" id="search-account" placeholder="Buscar conta..."
           class="v4-input v4-input--search v4-input--small" style="width: 200px;"
           onkeyup="filterMatrix()">

    <div class="ml-auto flex gap-2">
      <button type="button" class="v4-btn v4-btn--small v4-btn--secondary"
              onclick="openBulkGrantModal()">Selecionar todas pra gestor…</button>
      <button type="button" class="v4-btn v4-btn--small v4-btn--secondary"
              onclick="openCopyModal()">Copiar acessos…</button>
    </div>
  </div>

  <div class="overflow-x-auto v4-card" style="padding: 0;">
    <table class="v4-table v4-table--compact" id="access-matrix">
      <thead>
        <tr>
          <th class="sticky left-0 bg-v4-gray-50 z-[2]">Conta / Gestor</th>
          {% for m in managers_list %}
            <th class="text-center min-w-[120px]" data-manager-email="{{ m.email|lower }}">
              <div class="text-xs break-words">{{ m.email.split('@')[0] }}</div>
            </th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for a in accounts %}
        <tr data-account-name="{{ a.descriptive_name|lower }}" data-account-id="{{ a.customer_id }}">
          <td class="sticky left-0 bg-white whitespace-nowrap">
            <strong>{{ a.descriptive_name }}</strong>
            <div class="text-xs text-v4-gray-300 font-mono">{{ a.customer_id }}</div>
          </td>
          {% for m in managers_list %}
          <td class="text-center" data-manager-id="{{ m.id }}">
            <input type="checkbox"
                   {% if (m.id|string, a.customer_id) in access_set %}checked{% endif %}
                   hx-post="/admin/access/toggle"
                   hx-vals='{"manager_id": "{{ m.id }}", "customer_id": "{{ a.customer_id }}"}'
                   hx-trigger="change"
                   hx-swap="outerHTML"
                   hx-on::after-request="if (event.detail.successful) { showToast(this.checked ? 'Acesso liberado' : 'Acesso revogado', 'success'); }">
          </td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <p class="text-sm text-v4-gray-700 mt-4">
    Em mobile, use <a href="/admin/access/by-manager" class="underline">visão por gestor</a>.
  </p>

  {# Bulk grant modal #}
  <dialog class="v4-modal" id="bulk-grant-modal">
    <div class="v4-modal__header">
      <h3 class="v4-modal__title">Selecionar todas as contas pra gestor</h3>
      <button type="button" class="v4-modal__close" onclick="document.getElementById('bulk-grant-modal').close()">×</button>
    </div>
    <form method="POST" action="/admin/access/bulk-grant" class="v4-modal__body grid gap-3">
      <label class="v4-form__label">Gestor</label>
      <select name="manager_id" class="v4-select" required>
        <option value="">Selecione...</option>
        {% for m in managers_list %}<option value="{{ m.id }}">{{ m.email }}</option>{% endfor %}
      </select>
      {# All visible account ids hidden as multiple inputs #}
      {% for a in accounts %}
        <input type="hidden" name="customer_ids" value="{{ a.customer_id }}">
      {% endfor %}
      <div class="text-sm text-v4-gray-700">Vai liberar acesso a todas as {{ accounts|length }} contas.</div>
      <div class="flex justify-end gap-2 mt-2">
        <button type="button" class="v4-btn v4-btn--secondary v4-btn--small" onclick="document.getElementById('bulk-grant-modal').close()">Cancelar</button>
        <button type="submit" class="v4-btn v4-btn--primary v4-btn--small">Liberar todas</button>
      </div>
    </form>
  </dialog>

  {# Copy modal #}
  <dialog class="v4-modal" id="copy-modal">
    <div class="v4-modal__header">
      <h3 class="v4-modal__title">Copiar acessos</h3>
      <button type="button" class="v4-modal__close" onclick="document.getElementById('copy-modal').close()">×</button>
    </div>
    <form method="POST" action="/admin/access/bulk-copy" class="v4-modal__body grid gap-3">
      <label class="v4-form__label">De</label>
      <select name="from_manager_id" class="v4-select" required>
        <option value="">Selecione gestor de origem...</option>
        {% for m in managers_list %}<option value="{{ m.id }}">{{ m.email }}</option>{% endfor %}
      </select>
      <label class="v4-form__label">Para</label>
      <select name="to_manager_id" class="v4-select" required>
        <option value="">Selecione gestor de destino...</option>
        {% for m in managers_list %}<option value="{{ m.id }}">{{ m.email }}</option>{% endfor %}
      </select>
      <div class="text-sm text-v4-red-medium">⚠ Substitui todos os acessos do destino pelos do origem.</div>
      <div class="flex justify-end gap-2 mt-2">
        <button type="button" class="v4-btn v4-btn--secondary v4-btn--small" onclick="document.getElementById('copy-modal').close()">Cancelar</button>
        <button type="submit" class="v4-btn v4-btn--primary v4-btn--small">Copiar</button>
      </div>
    </form>
  </dialog>

  <script>
    function openBulkGrantModal() { document.getElementById('bulk-grant-modal').showModal(); }
    function openCopyModal() { document.getElementById('copy-modal').showModal(); }

    function filterMatrix() {
      const gestor = document.getElementById('search-gestor').value.toLowerCase();
      const account = document.getElementById('search-account').value.toLowerCase();

      // Filter columns by gestor
      document.querySelectorAll('th[data-manager-email]').forEach(th => {
        const visible = !gestor || th.dataset.managerEmail.includes(gestor);
        th.style.display = visible ? '' : 'none';
        const colIndex = Array.from(th.parentNode.children).indexOf(th);
        document.querySelectorAll('tbody tr').forEach(tr => {
          const cell = tr.children[colIndex];
          if (cell) cell.style.display = visible ? '' : 'none';
        });
      });

      // Filter rows by account
      document.querySelectorAll('tbody tr[data-account-name]').forEach(tr => {
        const visible = !account
                     || tr.dataset.accountName.includes(account)
                     || tr.dataset.accountId.includes(account);
        tr.style.display = visible ? '' : 'none';
      });
    }
  </script>

  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 2: Add bulk grant + copy + by-manager routes**

```python
@router.post("/admin/access/bulk-grant", response_class=HTMLResponse, response_model=None)
async def admin_access_bulk_grant(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    manager_id: str = Form(...),
    customer_ids: list[str] = Form(...),
) -> RedirectResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_account_access.bulk_grant(
            conn,
            manager_id=UUID(manager_id),
            customer_ids=customer_ids,
            granted_by=user.id,
        )
    return RedirectResponse(url="/admin/access", status_code=303)


@router.post("/admin/access/bulk-copy", response_class=HTMLResponse, response_model=None)
async def admin_access_bulk_copy(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    from_manager_id: str = Form(...),
    to_manager_id: str = Form(...),
) -> RedirectResponse:
    _require_admin(user)
    if from_manager_id == to_manager_id:
        return RedirectResponse(url="/admin/access?error=same_manager", status_code=303)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        await manager_account_access.copy_access(
            conn,
            from_manager_id=UUID(from_manager_id),
            to_manager_id=UUID(to_manager_id),
            granted_by=user.id,
        )
    return RedirectResponse(url="/admin/access", status_code=303)
```

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/admin/access.html src/web/routes.py
git commit -m "feat(admin): /admin/access matrix v2 (search + bulk grant + copy access)"
```

### Task 4.7: Add `/admin/access/by-manager` and `/admin/access/{manager_id}` (mobile per-gestor)

**Files:**
- Create: `src/web/templates/admin/access_by_manager.html`
- Create: `src/web/templates/admin/access_manager_detail.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Create `access_by_manager.html`**

```html
{% extends "_base.html" %}

{% block title %}Admin · Acessos por gestor — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-2xl mx-auto py-6 px-4">
  <header class="mb-6">
    <h1 class="text-3xl font-extrabold tracking-tight">Acessos por gestor</h1>
    <p class="text-sm text-v4-gray-700">Visão list-friendly pra mobile. <a href="/admin/access" class="underline">matriz completa →</a></p>
  </header>

  {% for m in managers_with_counts %}
  <a href="/admin/access/{{ m.id }}"
     class="block border border-v4-gray-100 rounded-md p-4 mb-2 hover:bg-v4-gray-50 transition-colors">
    <div class="flex justify-between items-center">
      <div>
        <strong>{{ m.email }}</strong>
        {% if m.full_name %}<div class="text-xs text-v4-gray-300">{{ m.full_name }}</div>{% endif %}
      </div>
      <div class="text-sm text-v4-gray-700">
        {{ m.access_count }} / {{ total_accounts }} contas →
      </div>
    </div>
  </a>
  {% endfor %}
</section>
{% endblock %}
```

- [ ] **Step 2: Create `access_manager_detail.html`**

```html
{% extends "_base.html" %}
{% from "_components.html" import breadcrumb %}

{% block title %}Admin · Acessos · {{ manager.email }} — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-3xl mx-auto py-6 px-4">
  {{ breadcrumb([
    {"label": "Acessos", "url": "/admin/access/by-manager"},
    {"label": manager.email}
  ]) }}

  <header class="mb-6">
    <h1 class="text-2xl font-bold">{{ manager.email }}</h1>
    <p class="text-sm text-v4-gray-700">Marque/desmarque pra liberar/revogar acesso. Mudanças instantâneas.</p>
  </header>

  <div class="grid gap-2">
    {% for a in accounts %}
    <label class="flex items-center gap-3 p-3 border border-v4-gray-100 rounded-md hover:bg-v4-gray-50 cursor-pointer">
      <input type="checkbox"
             {% if a.customer_id in access_set %}checked{% endif %}
             hx-post="/admin/access/toggle"
             hx-vals='{"manager_id": "{{ manager.id }}", "customer_id": "{{ a.customer_id }}"}'
             hx-trigger="change"
             hx-swap="outerHTML"
             hx-on::after-request="if (event.detail.successful) { showToast(this.checked ? 'Acesso liberado' : 'Acesso revogado', 'success'); }">
      <div class="flex-1">
        <strong>{{ a.descriptive_name }}</strong>
        <div class="text-xs text-v4-gray-300 font-mono">{{ a.customer_id }}</div>
      </div>
    </label>
    {% endfor %}
  </div>
</section>
{% endblock %}
```

- [ ] **Step 3: Add routes**

```python
@router.get("/admin/access/by-manager", response_class=HTMLResponse)
async def admin_access_by_manager(
    request: Request,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        managers_with_counts = await conn.fetch(
            """SELECT m.id, m.email, m.full_name,
                      count(maa.customer_id) AS access_count
               FROM managers m
               LEFT JOIN manager_account_access maa ON maa.manager_id = m.id
               WHERE m.status = 'active'
               GROUP BY m.id ORDER BY m.email"""
        )
        total_accounts = await conn.fetchval("SELECT count(*) FROM google_ads_accounts") or 0
        pending = await pending_invites_count()
    return templates.TemplateResponse(
        request, "admin/access_by_manager.html",
        {
            "current_user": user,
            "managers_with_counts": [dict(r) for r in managers_with_counts],
            "total_accounts": total_accounts,
            "pending_invites_count": pending,
        },
    )


@router.get("/admin/access/{manager_id}", response_class=HTMLResponse)
async def admin_access_manager_detail(
    request: Request,
    manager_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
) -> HTMLResponse:
    _require_admin(user)
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mgr_row = await conn.fetchrow("SELECT id, email, full_name FROM managers WHERE id = $1", UUID(manager_id))
        if mgr_row is None:
            raise HTTPException(status_code=404, detail="Gestor not found")
        accs = await google_ads_accounts.list_all(conn)
        access_rows = await conn.fetch(
            "SELECT customer_id FROM manager_account_access WHERE manager_id = $1",
            UUID(manager_id),
        )
        access_set = {r["customer_id"] for r in access_rows}
        pending = await pending_invites_count()
    return templates.TemplateResponse(
        request, "admin/access_manager_detail.html",
        {
            "current_user": user,
            "manager": dict(mgr_row),
            "accounts": accs,
            "access_set": access_set,
            "pending_invites_count": pending,
        },
    )
```

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/admin/access_by_manager.html src/web/templates/admin/access_manager_detail.html src/web/routes.py
git commit -m "feat(admin): /admin/access/by-manager + /admin/access/{id} (mobile-friendly per-gestor)"
```

### Task 4.8: Phase 4 deploy + smoke

- [ ] **Step 1: Push**

```bash
git push origin main
gh run watch
```

- [ ] **Step 2: E2E smoke**

Login as admin. Walk through:
- `/audit` — sticky filters, change "Status" to "Erros" → page auto-reloads. Click row → expands. Click "Exportar CSV" → file downloads.
- `/audit/{id}` (click any "Detalhe") — full event detail.
- `/admin/audit` — extra "Gestor" filter, "⚠ Só erros" button works.
- `/admin/access` — search inputs filter rows/columns live. "Selecionar todas" modal opens; submit grants access. "Copiar acessos" modal works.
- `/admin/access/by-manager` (mobile mode) — list of gestores with counts. Tap one → checkboxes vertically.

- [ ] **Step 3: Phase 4 done marker**

```bash
git commit --allow-empty -m "chore: Phase 4 (Operational tables) complete and verified in production"
git push origin main
```

---

## Phase 5 — List + Detail + Final Polish (4-6 days)

Goal: redesign the remaining list pages and ship `/sessions/{id}` permanent detail. Final visual regression check across all 15 pages.

### Task 5.1: `mcp_sessions` repository — `get_by_id`

**Files:**
- Modify: `src/db/repositories/mcp_sessions.py`
- Append to: `tests/integration/test_mcp_sessions.py` (or create)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_mcp_sessions_detail.py
import pytest
from uuid import uuid4
from src.db.repositories import mcp_sessions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_returns_session_when_owned(db_pool):
    mid = uuid4()
    sid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')",
            mid,
        )
        await conn.execute(
            "INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'Test', 'h')",
            sid, mid,
        )
        result = await mcp_sessions.get_by_id(conn, session_id=sid, manager_id=mid)
    assert result is not None
    assert result["label"] == "Test"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_not_owned(db_pool):
    mid = uuid4()
    other = uuid4()
    sid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'a@v4company.com', 'active', 'gestor'),
               ($2, 'b@v4company.com', 'active', 'gestor')""",
            mid, other,
        )
        await conn.execute(
            "INSERT INTO mcp_sessions (id, manager_id, label, token_hash) VALUES ($1, $2, 'OtherTest', 'h')",
            sid, other,
        )
        result = await mcp_sessions.get_by_id(conn, session_id=sid, manager_id=mid)
    assert result is None
```

- [ ] **Step 2: Implement `get_by_id`**

Append to `src/db/repositories/mcp_sessions.py`:

```python
from typing import Any
from uuid import UUID
import asyncpg


async def get_by_id(
    conn: asyncpg.Connection,
    *,
    session_id: UUID,
    manager_id: UUID,
) -> dict[str, Any] | None:
    """Fetch one session, scoped to the owning manager. Returns None if not found or not owned."""
    row = await conn.fetchrow(
        """SELECT id, manager_id, label, created_at, last_used_at, expires_at, revoked_at
           FROM mcp_sessions
           WHERE id = $1 AND manager_id = $2""",
        session_id, manager_id,
    )
    return dict(row) if row else None
```

- [ ] **Step 3: Run tests — expect pass**

```bash
python -m pytest tests/integration/test_mcp_sessions_detail.py -v 2>&1 | tail -10
```

Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add src/db/repositories/mcp_sessions.py tests/integration/test_mcp_sessions_detail.py
git commit -m "feat(db): mcp_sessions.get_by_id (manager-scoped lookup)"
```

### Task 5.2: Redesign `/sessions` list + change creation flow to redirect to `/sessions/{id}`

**Files:**
- Modify: `src/web/templates/sessions/list.html`
- Modify: `src/web/templates/sessions/_table.html`
- Delete: `src/web/templates/sessions/created.html` (replaced by `/sessions/{id}?token_flash=true`)
- Modify: `src/web/routes.py`

- [ ] **Step 1: Update `sessions/list.html`**

```html
{% extends "_base.html" %}
{% from "_components.html" import alert %}

{% block title %}Sessões MCP — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-4xl mx-auto py-6 px-4">
  <header class="mb-6">
    <h1 class="text-3xl font-extrabold tracking-tight">Sessões MCP</h1>
    <p class="text-sm text-v4-gray-700">Cada sessão é um Bearer token usado por um cliente MCP (Claude Desktop, Codex, Cursor). Tokens são mostrados <strong>uma vez</strong> no momento da criação.</p>
  </header>

  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Criar nova sessão</h3>
    </div>
    <form method="POST" action="/sessions/new"
          class="grid grid-cols-1 md:grid-cols-[1fr_180px_auto] gap-3 items-end">
      <div class="v4-form__group" style="margin: 0;">
        <label class="v4-form__label" for="label">Nome (cliente / máquina)</label>
        <input type="text" id="label" name="label" class="v4-input"
               placeholder="Ex: Claude Desktop pessoal" required>
      </div>
      <div class="v4-form__group" style="margin: 0;">
        <label class="v4-form__label" for="ttl_days">Validade</label>
        <select id="ttl_days" name="ttl_days" class="v4-select">
          <option value="30">30 dias</option>
          <option value="60">60 dias</option>
          <option value="90" selected>90 dias</option>
          <option value="180">180 dias</option>
        </select>
      </div>
      <button type="submit" class="v4-btn v4-btn--primary">Criar</button>
    </form>
  </div>

  {% include "sessions/_table.html" %}
</section>
{% endblock %}
```

- [ ] **Step 2: Update `sessions/_table.html` to use confirm dialog + link to detail**

```html
{% from "_components.html" import badge, empty_state %}

<div id="sessions-table" class="v4-card">
  <div class="v4-card__header">
    <h3 class="v4-card__title">Sessões ativas ({{ sessions|length }})</h3>
  </div>

  {% if sessions %}
  <table class="v4-table v4-table--compact">
    <thead>
      <tr>
        <th>Nome</th>
        <th>Criada</th>
        <th>Último uso</th>
        <th>Expira</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for s in sessions %}
      <tr>
        <td>
          <a href="/sessions/{{ s.id }}" class="font-semibold hover:text-v4-red">
            {{ s.label or "(sem nome)" }}
          </a>
        </td>
        <td class="col-mono">{{ s.created_at.strftime("%d/%m/%Y %H:%M") }}</td>
        <td class="col-mono">
          {% if s.last_used_at %}{{ s.last_used_at.strftime("%d/%m %H:%M") }}{% else %}<span class="text-v4-gray-300">nunca</span>{% endif %}
        </td>
        <td class="col-mono">
          {% if s.expires_at %}{{ s.expires_at.strftime("%d/%m/%Y") }}{% else %}<em>—</em>{% endif %}
        </td>
        <td class="text-right">
          <button type="button" class="v4-btn v4-btn--small v4-btn--danger"
                  onclick='openConfirm({
                    title: "Revogar sessão?",
                    message: "A sessão {{ s.label|tojson }} para de funcionar imediatamente. Bearer atual fica inválido. Você precisa criar uma nova sessão pra reconfigurar.",
                    okLabel: "Revogar",
                    kind: "danger",
                    onConfirm: () => htmx.ajax("POST", "/sessions/{{ s.id }}/revoke", { target: "#sessions-table", swap: "outerHTML" })
                  })'>Revogar</button>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
    {{ empty_state("Nenhuma sessão ativa.", "Crie uma acima pra configurar Claude/Codex/Cursor.") }}
  {% endif %}
</div>
```

- [ ] **Step 3: Change `POST /sessions/new` to redirect to detail page with flash token**

In `src/web/routes.py`, locate the `/sessions/new` POST handler. Replace its body's last lines with:

```python
# After session is created and token is generated:
response = RedirectResponse(
    url=f"/sessions/{session_id}?token_flash=true",
    status_code=303,
)
# Set the plaintext token in a transient cookie that /sessions/{id} reads + clears
response.set_cookie(
    "v4_session_flash_token",
    plaintext_token,
    httponly=True, secure=True, samesite="strict",
    max_age=60,  # 60 seconds — pra não persistir em devices longe
    path=f"/sessions/{session_id}",  # restrict scope
)
return response
```

- [ ] **Step 4: Delete `sessions/created.html`**

```bash
git rm src/web/templates/sessions/created.html
```

- [ ] **Step 5: Commit**

```bash
git add src/web/templates/sessions/list.html src/web/templates/sessions/_table.html src/web/routes.py
git commit -m "feat(web): redesign /sessions list + flow change (creation redirects to /sessions/{id})"
```

### Task 5.3: Create `/sessions/{id}` detail page

**Files:**
- Create: `src/web/templates/sessions/detail.html`
- Modify: `src/web/routes.py`

- [ ] **Step 1: Create the template**

`src/web/templates/sessions/detail.html`:

```html
{% extends "_base.html" %}
{% from "_components.html" import breadcrumb, alert, badge, code_block, button %}

{% block title %}Sessão · {{ session.label }} — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-3xl mx-auto py-6 px-4">
  {{ breadcrumb([
    {"label": "Sessões", "url": "/sessions"},
    {"label": session.label or "(sem nome)"}
  ]) }}

  <header class="mb-6 flex items-center gap-3 flex-wrap">
    <h1 class="text-3xl font-extrabold tracking-tight">{{ session.label or "(sem nome)" }}</h1>
    {% if session.revoked_at %}{{ badge("Revogada", "neutral") }}
    {% else %}{{ badge("Ativa", "success") }}{% endif %}
  </header>

  <div class="text-sm text-v4-gray-700 mb-6 grid grid-cols-2 md:grid-cols-3 gap-3">
    <div>Criada em<br><strong>{{ session.created_at.strftime("%d/%m/%Y %H:%M") }}</strong></div>
    <div>Último uso<br><strong>{% if session.last_used_at %}{{ session.last_used_at.strftime("%d/%m %H:%M") }}{% else %}nunca{% endif %}</strong></div>
    <div>Expira<br><strong>{% if session.expires_at %}{{ session.expires_at.strftime("%d/%m/%Y") }}{% else %}—{% endif %}</strong></div>
  </div>

  {% if flash_token %}
  <div class="bg-v4-gold-soft border border-v4-gold rounded-md p-4 mb-6">
    <h3 class="font-semibold text-v4-gray-900 mb-2">⚠ Token Bearer · só aparece UMA vez</h3>
    <p class="text-sm text-v4-gray-700 mb-3">Copie agora. Esta página vai esconder o token assim que você sair ou recarregar.</p>
    <div class="bg-v4-gray-900 text-white p-3 rounded font-mono text-sm break-all" id="flash-token">{{ flash_token }}</div>
    <button class="v4-btn v4-btn--small v4-btn--secondary mt-3"
            onclick="navigator.clipboard.writeText(document.getElementById('flash-token').innerText); this.innerText = 'Copiado!'; setTimeout(() => this.innerText = 'Copiar token', 2000);">Copiar token</button>
  </div>
  {% endif %}

  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Configurar no cliente</h3>
    </div>
    <p class="text-sm text-v4-gray-700 mb-4">
      Substitua <code>mcp_xxx...</code> pelo seu token. {% if not flash_token %}<strong>Token só foi mostrado na criação.</strong> Se você perdeu, revogue esta sessão e crie uma nova.{% endif %}
    </p>

    <details open class="mb-4">
      <summary class="cursor-pointer font-semibold py-2">Claude Desktop</summary>
      {{ code_block('{
  "mcpServers": {
    "v4-ads": {
      "url": "' ~ mcp_url ~ '",
      "headers": {
        "Authorization": "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}', filename="claude_desktop_config.json") }}
    </details>

    <details class="mb-4">
      <summary class="cursor-pointer font-semibold py-2">Codex CLI</summary>
      {{ code_block('[mcp_servers.v4-ads]
url = "' ~ mcp_url ~ '"

[mcp_servers.v4-ads.headers]
Authorization = "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"', filename="~/.codex/config.toml") }}
    </details>

    <details class="mb-4">
      <summary class="cursor-pointer font-semibold py-2">Cursor</summary>
      {{ code_block('{
  "mcpServers": {
    "v4-ads": {
      "url": "' ~ mcp_url ~ '",
      "headers": {
        "Authorization": "Bearer mcp_xxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}', filename=".cursor/mcp.json") }}
    </details>
  </div>

  {% if not session.revoked_at %}
  <div class="mt-8 flex gap-2 justify-end">
    <button type="button" class="v4-btn v4-btn--danger v4-btn--small"
            onclick='openConfirm({
              title: "Revogar esta sessão?",
              message: "O Bearer correspondente para de funcionar imediatamente.",
              okLabel: "Revogar",
              kind: "danger",
              onConfirm: () => htmx.ajax("POST", "/sessions/{{ session.id }}/revoke", { target: "body", swap: "innerHTML" }).then(() => window.location.href = "/sessions")
            })'>Revogar sessão</button>
  </div>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 2: Add the route handler**

```python
@router.get("/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail(
    request: Request,
    session_id: str,
    user: CurrentUser = Depends(current_manager),  # noqa: B008
    token_flash: bool = False,
) -> HTMLResponse:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        from src.db.repositories import mcp_sessions
        session = await mcp_sessions.get_by_id(
            conn, session_id=UUID(session_id), manager_id=user.id,
        )
    if session is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    flash_token = request.cookies.get("v4_session_flash_token") if token_flash else None
    settings = get_settings()
    mcp_url = f"{settings.public_base_url}/mcp"

    response = templates.TemplateResponse(
        request, "sessions/detail.html",
        {
            "current_user": user,
            "session": session,
            "flash_token": flash_token,
            "mcp_url": mcp_url,
        },
    )
    if flash_token:
        response.delete_cookie(
            "v4_session_flash_token",
            path=f"/sessions/{session_id}",
        )
    return response
```

(If `public_base_url` doesn't exist on Settings yet, add it — value: `"https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app"`.)

- [ ] **Step 3: Visual smoke test**

Visit `/sessions`. Click an existing session label → goes to `/sessions/{id}` with breadcrumb, snippets, no flash token. Create a new session → redirects to `/sessions/{id}?token_flash=true` with token shown in gold-soft warning box. Refresh page → token disappears.

- [ ] **Step 4: Commit**

```bash
git add src/web/templates/sessions/detail.html src/web/routes.py src/config.py
git commit -m "feat(web): /sessions/{id} permanent detail with one-shot token flash"
```

### Task 5.4: Redesign `/accounts`

**Files:**
- Modify: `src/web/templates/accounts.html`

- [ ] **Step 1: Replace template**

```html
{% extends "_base.html" %}
{% from "_components.html" import badge, alert, search_input, empty_state %}

{% block title %}Contas — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-5xl mx-auto py-6 px-4">
  <header class="mb-6">
    <h1 class="text-3xl font-extrabold tracking-tight">Contas</h1>
    <p class="text-sm text-v4-gray-700">Suas conexões Google e contas Google Ads acessíveis.</p>
  </header>

  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Conexões Google</h3>
      <a href="/oauth/google/start?mode=panel_login" class="v4-btn v4-btn--primary v4-btn--small">+ Conectar nova conta</a>
    </div>
    {% if connections %}
    <table class="v4-table v4-table--compact">
      <thead>
        <tr>
          <th>Email Google</th>
          <th>Conectada em</th>
          <th>Status</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for c in connections %}
        <tr>
          <td><strong>{{ c.google_email }}</strong></td>
          <td class="col-mono">{{ c.connected_at.strftime("%d/%m/%Y %H:%M") }}</td>
          <td>
            {% if c.revoked_at %}{{ badge("Revogada", "neutral") }}
            {% else %}{{ badge("Ativa", "success") }}{% endif %}
          </td>
          <td class="text-right">
            {% if not c.revoked_at %}
            <button type="button" class="v4-btn v4-btn--small v4-btn--danger"
                    onclick='openConfirm({
                      title: "Revogar conexão?",
                      message: "Você precisará reconectar com Google para usar Google Ads de novo.",
                      okLabel: "Revogar",
                      kind: "danger",
                      onConfirm: () => htmx.ajax("POST", "/accounts/{{ c.id }}/revoke", { target: "body", swap: "innerHTML" }).then(() => window.location.reload())
                    })'>Revogar</button>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      {{ empty_state("Nenhuma conexão Google.", "Use o botão acima pra conectar sua conta.") }}
    {% endif %}
  </div>

  <div class="v4-card">
    <div class="v4-card__header">
      <h3 class="v4-card__title">Contas Google Ads acessíveis ({{ accounts|length }})</h3>
    </div>
    {% if accounts %}
      <div class="mb-3">
        {{ search_input("acc-search", placeholder="Buscar nome ou customer_id...", attrs='oninput="filterAccounts()"') }}
      </div>
      <table class="v4-table v4-table--compact" id="accounts-table">
        <thead>
          <tr>
            <th>Customer ID</th>
            <th>Nome</th>
            <th>Moeda</th>
            <th>Fuso</th>
          </tr>
        </thead>
        <tbody>
          {% for a in accounts %}
          <tr data-name="{{ a.descriptive_name|lower }}" data-id="{{ a.customer_id }}">
            <td class="col-mono">{{ a.customer_id }}</td>
            <td>{{ a.descriptive_name }}</td>
            <td>{{ a.currency_code or "—" }}</td>
            <td>{{ a.time_zone or "—" }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <script>
        function filterAccounts() {
          const q = document.getElementById('acc-search').value.toLowerCase();
          document.querySelectorAll('#accounts-table tbody tr').forEach(tr => {
            const visible = !q || tr.dataset.name.includes(q) || tr.dataset.id.includes(q);
            tr.style.display = visible ? '' : 'none';
          });
        }
      </script>
    {% else %}
      {{ alert("Você não tem acesso a nenhuma conta ainda. Peça pro admin V4 da sua unidade liberar acessos em /admin/access.", "warning") }}
    {% endif %}
  </div>
</section>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add src/web/templates/accounts.html
git commit -m "feat(web): redesign /accounts with search + accessible confirm dialog on revoke"
```

### Task 5.5: Redesign `/admin/managers` (search + dropdown ⋯ + confirm)

**Files:**
- Modify: `src/web/templates/admin/managers.html`

- [ ] **Step 1: Replace template**

```html
{% extends "_base.html" %}
{% from "_components.html" import badge, search_input, dropdown, empty_state %}

{% block title %}Admin · Managers — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-5xl mx-auto py-6 px-4">
  <header class="mb-6 flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-extrabold tracking-tight">Managers</h1>
      <p class="text-sm text-v4-gray-700">{{ managers|length }} gestores cadastrados.</p>
    </div>
    <a href="/admin/invites" class="v4-btn v4-btn--primary v4-btn--small">+ Convidar gestor</a>
  </header>

  <div class="v4-card">
    <div class="mb-3 flex flex-wrap gap-3 items-center">
      {{ search_input("mgr-search", placeholder="Buscar email...", attrs='oninput="filterManagers()" style="flex: 1; max-width: 320px;"') }}
      <select id="mgr-role" class="v4-select" onchange="filterManagers()" style="width: 140px;">
        <option value="all">Todos os roles</option>
        <option value="admin">Admin</option>
        <option value="gestor">Gestor</option>
      </select>
      <select id="mgr-status" class="v4-select" onchange="filterManagers()" style="width: 140px;">
        <option value="all">Todos os status</option>
        <option value="active">Ativos</option>
        <option value="invited">Convidados</option>
        <option value="inactive">Inativos</option>
      </select>
    </div>

    {% if managers %}
    <table class="v4-table v4-table--compact" id="managers-table">
      <thead>
        <tr>
          <th>Email</th>
          <th>Nome</th>
          <th>Role</th>
          <th>Status</th>
          <th>Criado</th>
          <th>Último acesso</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for m in managers %}
        <tr data-email="{{ m.email|lower }}" data-role="{{ m.role }}" data-status="{{ m.status or ('active' if m.is_active else 'inactive') }}">
          <td><strong>{{ m.email }}</strong></td>
          <td>{{ m.full_name or "—" }}</td>
          <td>
            {% if m.role == "admin" %}{{ badge("Admin", "error") }}
            {% else %}{{ badge("Gestor", "neutral") }}{% endif %}
          </td>
          <td>
            {% set s = m.status or ('active' if m.is_active else 'inactive') %}
            {% if s == "active" %}{{ badge("Ativo", "success") }}
            {% elif s == "invited" %}{{ badge("Convidado", "warning") }}
            {% else %}{{ badge("Desativado", "neutral") }}{% endif %}
          </td>
          <td class="col-mono">{{ m.created_at.strftime("%d/%m/%Y") }}</td>
          <td class="col-mono">{{ m.last_seen_at.strftime("%d/%m %H:%M") if m.last_seen_at else "—" }}</td>
          <td class="text-right">
            {% if m.id != current_user.id %}
            {{ dropdown("dd-" ~ loop.index, [
              {"label": "Promover a admin" if m.role == "gestor" else "Despromover a gestor",
               "post_url": "/admin/managers/" ~ m.id|string ~ "/toggle-role"},
              {"label": "Desativar" if m.is_active else "Reativar",
               "post_url": "/admin/managers/" ~ m.id|string ~ "/toggle-active",
               "kind": "danger" if m.is_active else None},
            ]) }}
            {% else %}
            <span class="text-xs text-v4-gray-300">(você)</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      {{ empty_state("Nenhum gestor.", "Convide o primeiro pelo botão acima.") }}
    {% endif %}
  </div>

  <script>
    function filterManagers() {
      const q = document.getElementById('mgr-search').value.toLowerCase();
      const role = document.getElementById('mgr-role').value;
      const status = document.getElementById('mgr-status').value;
      document.querySelectorAll('#managers-table tbody tr').forEach(tr => {
        const matchEmail = !q || tr.dataset.email.includes(q);
        const matchRole = role === 'all' || tr.dataset.role === role;
        const matchStatus = status === 'all' || tr.dataset.status === status;
        tr.style.display = (matchEmail && matchRole && matchStatus) ? '' : 'none';
      });
    }
  </script>
</section>
{% endblock %}
```

- [ ] **Step 2: Wrap toggle-role and toggle-active in confirm dialog (handle in dropdown component already supports HTMX POST, but adding confirm via JS isn't easy from macro)**

Since `dropdown` items currently fire HTMX POST directly, for these destructive actions add an explicit confirm step. Modify the macro call to include an `onclick` override; or for simplicity, accept that dropdown menu items go straight to HTMX (the dropdown is a deliberate user click after opening — not as risky as a buttonless toggle).

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/admin/managers.html
git commit -m "feat(admin): redesign /admin/managers (search + filters + dropdown ⋯ menu)"
```

### Task 5.6: Redesign `/admin/accounts`

**Files:**
- Modify: `src/web/templates/admin/accounts.html`

- [ ] **Step 1: Replace template**

```html
{% extends "_base.html" %}
{% from "_components.html" import badge, search_input, empty_state %}

{% block title %}Admin · Contas Google Ads — V4 Ads MCP{% endblock %}

{% block content %}
<section class="max-w-5xl mx-auto py-6 px-4">
  <header class="mb-6">
    <h1 class="text-3xl font-extrabold tracking-tight">Contas Google Ads</h1>
    <p class="text-sm text-v4-gray-700">Sincronizadas diariamente via Cloud Scheduler. Use <a href="/admin/access" class="underline">/admin/access</a> pra atribuir gestores.</p>
  </header>

  <div class="v4-card">
    <div class="mb-3 flex flex-wrap gap-3 items-center">
      {{ search_input("acc-search", placeholder="Buscar nome ou customer_id...", attrs='oninput="filterAccs()"') }}
      <select id="mcc-filter" class="v4-select" onchange="filterAccs()" style="width: 200px;">
        <option value="all">Todos os MCCs</option>
        {% for mcc in mccs %}<option value="{{ mcc }}">{{ mcc }}</option>{% endfor %}
      </select>
    </div>

    {% if accounts %}
    <table class="v4-table v4-table--compact" id="adm-accs-table">
      <thead>
        <tr>
          <th>Customer ID</th>
          <th>Nome</th>
          <th>MCC</th>
          <th>Moeda</th>
          <th>Fuso</th>
          <th>Test?</th>
          <th>Última sync</th>
        </tr>
      </thead>
      <tbody>
        {% for a in accounts %}
        <tr data-name="{{ a.descriptive_name|lower }}" data-id="{{ a.customer_id }}" data-mcc="{{ a.mcc_id }}">
          <td class="col-mono">{{ a.customer_id }}</td>
          <td><strong>{{ a.descriptive_name }}</strong></td>
          <td class="col-mono">{{ a.mcc_id }}</td>
          <td>{{ a.currency_code or "—" }}</td>
          <td>{{ a.time_zone or "—" }}</td>
          <td>{% if a.is_test_account %}{{ badge("Test", "warning") }}{% else %}—{% endif %}</td>
          <td class="col-mono">{{ a.synced_at.strftime("%d/%m %H:%M") }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <script>
      function filterAccs() {
        const q = document.getElementById('acc-search').value.toLowerCase();
        const mcc = document.getElementById('mcc-filter').value;
        document.querySelectorAll('#adm-accs-table tbody tr').forEach(tr => {
          const matchQ = !q || tr.dataset.name.includes(q) || tr.dataset.id.includes(q);
          const matchMcc = mcc === 'all' || tr.dataset.mcc === mcc;
          tr.style.display = (matchQ && matchMcc) ? '' : 'none';
        });
      }
    </script>
    {% else %}
      {{ empty_state("Nenhuma conta sincronizada ainda.", "Aguarde o resync diário ou execute manualmente.") }}
    {% endif %}
  </div>
</section>
{% endblock %}
```

- [ ] **Step 2: Update the route handler to pass `mccs` (distinct list)**

In the `/admin/accounts` handler, before the template render:

```python
async with pool.acquire() as conn:
    accs = await google_ads_accounts.list_all(conn)
    mccs = sorted({a["mcc_id"] for a in accs if a.get("mcc_id")})
    pending = await pending_invites_count()

return templates.TemplateResponse(
    request, "admin/accounts.html",
    {
        "current_user": user,
        "accounts": accs,
        "mccs": mccs,
        "pending_invites_count": pending,
    },
)
```

- [ ] **Step 3: Commit**

```bash
git add src/web/templates/admin/accounts.html src/web/routes.py
git commit -m "feat(admin): redesign /admin/accounts with search + MCC filter"
```

### Task 5.7: Final visual regression + Phase 5 deploy

**Files:** none (manual verification)

- [ ] **Step 1: Push**

```bash
git push origin main
gh run watch
```

- [ ] **Step 2: Walk through all 15 pages and capture "after" screenshots**

```bash
mkdir -p docs/operacao/screenshots/after
```

Take desktop + mobile screenshots of all 15 pages. Save with same naming convention as `before/` (Phase 0 Task 0.1).

- [ ] **Step 3: Side-by-side diff manually**

Compare each `before/desktop-page.png` vs `after/desktop-page.png`. Note any:

- Pages where `after` looks worse than `before` → fix in follow-up commit
- Pages where headers/typography don't match Editorial standard → fix
- Pages where mobile layout breaks → fix

- [ ] **Step 4: Run full test suite**

```bash
cd "D:\HUB ads MCP" && python -m pytest tests/ -q 2>&1 | tail -10
```

Expected: all tests pass, including the new 11+ tests added across phases.

- [ ] **Step 5: Update infra-setup.md with FE Redesign v2 sign-off**

Append to `docs/operacao/infra-setup.md` under "Phase sign-offs":

```markdown
### Phase FE Redesign v2 (2026-XX-XX)
- 15 pages redesigned (9 + 6 new): /login, /access-denied, /help, /, /accounts, /sessions, /sessions/{id}, /audit, /audit/{id}, /admin, /admin/managers, /admin/invites, /admin/accounts, /admin/access, /admin/audit
- Q8 invite-only allowlist active in production via managers.status migration
- Tailwind CDN integrated; design system v2 with 22 components shipping
- Mobile-aware: tables become card lists, access matrix has per-gestor view
- All test suites passing: ~11 new tests (managers invite + audit + access bulk + sessions detail)
- Visual before/after screenshots in `docs/operacao/screenshots/`
```

- [ ] **Step 6: Phase 5 done marker + push**

```bash
git add docs/operacao/screenshots/after/ docs/operacao/infra-setup.md
git commit -m "docs(redesign): Phase 5 + final sign-off — FE Redesign v2 complete"
git push origin main
```

---

## Self-Review Checklist

After completing the plan, run this final check:

### Spec coverage

- [x] Section 1 (IA + sitemap): covered by Task 1.3 (sub-nav), Task 1.4 (drawer), Tasks 2.6/3.4/3.2 (new pages)
- [x] Section 2 (Design system): covered by Tasks 1.1, 1.2, 1.5–1.23
- [x] Section 3 (Editorial/Operational + mobile): covered by template authoring per page (Phases 3, 4, 5) + breakpoint media queries embedded in component CSS
- [x] Section 4 (15 page briefs): all 15 pages have a redesign or creation task
- [x] Section 5 (Backend touchpoints): migration (Task 2.1), allowlist (2.4), repo functions (2.2, 4.1, 4.5, 5.1), 12 routes (across phases)
- [x] Section 6 (Implementation phases): plan IS the phase breakdown

### Placeholder scan

- [x] No "TBD", "TODO", "implement later", "fill in details"
- [x] No "add appropriate error handling" / "handle edge cases" without spec
- [x] No "tests for the above" without test code
- [x] No "Similar to Task N" — code repeated where needed
- [x] All steps describing code show the code

### Type consistency

- [x] `pending_invites_count` is `int` returned from `managers.count_invited`
- [x] `audit_log.get_by_id(audit_id, manager_id)` — same signature in Tasks 4.1 and 4.3
- [x] `mcp_sessions.get_by_id(session_id, manager_id)` — same in Tasks 5.1 and 5.3
- [x] `manager_account_access.bulk_grant(manager_id, customer_ids[], granted_by)` — Tasks 4.5 and 4.6
- [x] `CallbackDecision` dataclass shared between Tasks 2.4 (definition + tests) and oauth.py callback wiring

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-05-frontend-redesign-v2-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for solo dev who wants minimal context-switching.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. Best when you want to watch each step in real-time.

**Which approach?**

If Subagent-Driven: I invoke `superpowers:subagent-driven-development`.
If Inline: I invoke `superpowers:executing-plans`.
