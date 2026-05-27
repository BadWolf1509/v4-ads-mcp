# V4 Ads MCP — Phase 1b: Web Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Self-service web panel for managers + admins. Replaces the CLI admin (`src/scripts/admin.py`) for routine ops: gestor logs in via Google V4, connects their Google Ads, creates MCP sessions, sees own audit. Admin manages account access + sees global audit.

**Architecture:** Server-rendered Jinja2 templates + plain CSS using V4 design tokens. **No JS framework, no build step.** HTMX (already loadable via CDN) for inline interactions like "revoke session" without full page reload. Authentication uses Google OAuth directly (the same client we already have) instead of Supabase Auth — restricted to `@v4company.com` emails on callback. Login produces a panel session cookie (signed JWT-like blob) AND saves the user's refresh_token for Google Ads access in the same flow.

**Spec deviation:** §5.1 originally specified Supabase Auth for panel login + separate Google OAuth for Google Ads access. We unify into one Google OAuth flow with `email + openid + profile + adwords` scopes. Justified because (a) every V4 user has @v4company.com Google account, (b) reuses existing OAuth infrastructure, (c) eliminates Supabase Auth as a moving part.

**Tech Stack:** Adds nothing new — Jinja2 already comes with FastAPI, HTMX is loaded via CDN, Montserrat via Bunny Fonts CDN. The design system is pure CSS.

**Reference spec:** `docs/superpowers/specs/2026-05-03-v4-ads-mcp-design.md` §8 (painel design).

**Definition of done (Phase 1b):**

1. wellinton.ribeiro@v4company.com opens `https://v4-ads-mcp-jf26mmrgqa-rj.a.run.app/` in browser, clicks "Entrar com Google V4", authorizes Google → lands on dashboard.
2. From dashboard, can navigate to: accounts (Google connections), sessions (Bearer tokens), audit (own log).
3. Can create a new MCP session via UI; token is shown once with copy-paste snippets for Claude Desktop/Code/Codex/Cursor.
4. Can revoke an existing session inline (HTMX).
5. As admin, can navigate to /admin/managers (list/promote), /admin/access (matrix manager × account), /admin/audit (global), /admin/accounts (list synced).
6. A non-`@v4company.com` user trying to login gets a clean error page.
7. Visual: looks like V4 (red `#e50914` accents, Montserrat font, V4 symbol logo on header, light theme).
8. CLI admin still works (we don't remove it — it stays as the disaster-recovery escape hatch).
9. All 162+ existing tests still pass; new tests cover ~15 unit tests (auth helpers, snippet generation) + 8 integration tests (each route returns 200 with expected content for the right user role).

---

## File structure

```
src/
├── auth/
│   ├── oauth.py                       # MODIFY — add email scope, unify panel+ads flow
│   ├── panel_session.py               # NEW — signed cookie for panel auth
│   └── domain_check.py                # NEW — @v4company.com restriction
├── web/                               # NEW PACKAGE (placeholder existed in plan, now realized)
│   ├── __init__.py
│   ├── routes.py                      # FastAPI routes for all panel pages
│   ├── deps.py                        # current_manager / require_admin dependencies
│   ├── templates/
│   │   ├── _base.html                 # layout + header (V4 logo) + nav
│   │   ├── _components.html           # Jinja2 macros (button, badge, card, table_row)
│   │   ├── login.html
│   │   ├── error.html
│   │   ├── dashboard.html
│   │   ├── accounts.html
│   │   ├── sessions/
│   │   │   ├── list.html
│   │   │   └── created.html           # "token shown once" page with snippets
│   │   ├── audit.html
│   │   └── admin/
│   │       ├── managers.html
│   │       ├── accounts.html
│   │       ├── access.html
│   │       └── audit.html
│   └── static/
│       ├── v4-tokens.css              # CSS variables (colors, fonts, spacings)
│       ├── v4-base.css                # reset, typography base, body styles
│       ├── v4-components.css          # button, input, table, card, badge classes
│       └── logo/v4-symbol.svg
├── app.py                             # MODIFY — mount web router, serve /static
└── mcp/server.py                      # NO CHANGE

tests/
├── unit/
│   ├── test_panel_session.py          # cookie sign/verify, expiration
│   └── test_domain_check.py
└── integration/
    └── test_web_panel.py              # 8 route tests with httpx + cookie helper
```

---

## Manual prerequisites

- [x] OAuth Client in GCP allows `email`, `profile`, `openid`, `adwords` scopes (the consent screen needs these enabled — verify in GCP Console; should already be set if Phase 1a was complete).
- Re-add the `email` scope to the OAuth client allowlist if it's not already there. Browse: https://console.cloud.google.com/apis/credentials/consent → Edit App → Scopes → Add `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `openid` (in addition to `.../auth/adwords` already present).

---

## Task 1: Update OAuth flow to include email + openid scopes (carry-over from Phase 1a)

**Files:**
- Modify: `src/auth/oauth.py` to extend `GOOGLE_ADWORDS_SCOPE` -> `_SCOPES` list including email, profile, openid, plus the existing adwords. Update `oauth_start` to request the full scope list and `oauth_callback` to parse the email from userinfo correctly.
- Create: `src/auth/domain_check.py` — small module to validate @v4company.com.
- Modify: `tests/integration/test_oauth_flow.py` to assert the new scopes are in the redirect.
- Create: `tests/unit/test_domain_check.py`.

### Step 1: Implement `src/auth/domain_check.py`

EXACT content:

```python
"""Restrict panel access to @v4company.com emails."""

ALLOWED_DOMAIN = "v4company.com"


def is_allowed_email(email: str | None) -> bool:
    """Return True if email belongs to the allowed corporate domain."""
    if not email:
        return False
    parts = email.lower().strip().split("@")
    if len(parts) != 2:
        return False
    _, domain = parts
    return domain == ALLOWED_DOMAIN
```

### Step 2: Implement `tests/unit/test_domain_check.py`

```python
"""Domain check tests."""
import pytest

from src.auth.domain_check import is_allowed_email


@pytest.mark.parametrize("email,expected", [
    ("wellinton.ribeiro@v4company.com", True),
    ("admin@v4company.com", True),
    ("WELLINTON@V4COMPANY.COM", True),  # case-insensitive
    ("attacker@gmail.com", False),
    ("attacker@v4company.com.malicious.com", False),
    ("malicious.v4company.com@gmail.com", False),
    ("", False),
    (None, False),
    ("nodomain", False),
    ("two@signs@v4company.com", False),
])
def test_is_allowed_email(email, expected):
    assert is_allowed_email(email) is expected
```

### Step 3: Modify `src/auth/oauth.py`

Find `GOOGLE_ADWORDS_SCOPE = "..."` line. Replace with a list:

```python
GOOGLE_ADWORDS_SCOPE = "https://www.googleapis.com/auth/adwords"
GOOGLE_PROFILE_SCOPE = "https://www.googleapis.com/auth/userinfo.profile"
GOOGLE_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
GOOGLE_OPENID_SCOPE = "openid"

_REQUIRED_SCOPES = [
    GOOGLE_OPENID_SCOPE,
    GOOGLE_EMAIL_SCOPE,
    GOOGLE_PROFILE_SCOPE,
    GOOGLE_ADWORDS_SCOPE,
]
```

Find the `oauth_start` function. Update the params dict's `"scope"` key from `GOOGLE_ADWORDS_SCOPE` to `" ".join(_REQUIRED_SCOPES)`.

Find the `oauth_callback` function — the userinfo call should now succeed (because we asked for email scope). Verify the email + reject if not @v4company.com:

```python
# At the end of the userinfo block, after google_email is parsed:
from src.auth.domain_check import is_allowed_email
if not is_allowed_email(google_email):
    return _error_page(
        f"Conta {google_email} nao autorizada — apenas @v4company.com.",
        status=403,
    )
```

### Step 4: Update `tests/integration/test_oauth_flow.py`

Find `test_start_redirects_to_google` — extend the assertions to confirm the new scopes are present:

```python
    qs = parse_qs(urlparse(location).query)
    scope_str = qs["scope"][0]
    assert "adwords" in scope_str
    assert "userinfo.email" in scope_str
    assert "openid" in scope_str
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
```

The other tests (`test_callback_persists_encrypted_refresh_token` etc) need their userinfo mock to return a `@v4company.com` email so the new domain check doesn't reject them. Find the line `respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(...)` and change `manager@gmail.com` to `manager@v4company.com`.

Add 1 new test for the domain rejection:

```python
@pytest.mark.integration
@respx.mock
async def test_callback_rejects_non_v4_email(client: AsyncClient) -> None:
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="d@v4.com", full_name=None)
    state = sign_state({"manager_id": str(mid)}, _SIGNING_KEY)

    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=Response(200, json={
            "access_token": "ya29.fake",
            "refresh_token": "1//06fake",
            "expires_in": 3600,
            "scope": " ".join([
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/adwords",
            ]),
            "token_type": "Bearer",
        })
    )
    respx.get("https://www.googleapis.com/oauth2/v2/userinfo").mock(
        return_value=Response(200, json={"email": "attacker@gmail.com"}),
    )

    response = await client.get(
        f"/oauth/google/callback?code=fake&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert "v4company.com" in response.text
```

### Step 5: Run tests + commit

```bash
cd "/d/HUB ads MCP"
./.venv/Scripts/python.exe -m pytest tests/unit/test_domain_check.py tests/integration/test_oauth_flow.py -v
./.venv/Scripts/python.exe -m mypy src/auth/
./.venv/Scripts/python.exe -m ruff check src/auth/ tests/unit/test_domain_check.py
./.venv/Scripts/python.exe -m ruff format --check src/auth/ tests/unit/test_domain_check.py

git add src/auth/oauth.py src/auth/domain_check.py tests/unit/test_domain_check.py tests/integration/test_oauth_flow.py
git commit -m "feat(auth): unify panel login + Google Ads OAuth (add email + openid scopes)

OAuth flow now requests {openid, email, profile, adwords} so we get
the user's email back from userinfo (was 'unknown' before). Callback
rejects with 403 if email not @v4company.com — defense in depth on
top of GCP OAuth consent screen restrictions."
git push
```

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 2: Panel session module (signed cookie) — TDD

**Files:**
- Create: `src/auth/panel_session.py`
- Create: `tests/unit/test_panel_session.py`

The panel session is a signed cookie containing `{manager_id, email, exp}`. We sign with `session_signing_key` (already in Settings). 24-hour TTL by default; user can re-login any time.

### Step 1: Write failing test `tests/unit/test_panel_session.py`

EXACT content:

```python
"""Panel session cookie tests."""
import time

import pytest

from src.auth.panel_session import (
    InvalidPanelSessionError,
    PanelSession,
    sign_panel_session,
    verify_panel_session,
)


_SIGNING_KEY = "x" * 32


def test_round_trip_recovers_payload():
    cookie = sign_panel_session(
        manager_id="abc123", email="t@v4company.com", signing_key=_SIGNING_KEY,
    )
    s = verify_panel_session(cookie, _SIGNING_KEY)
    assert isinstance(s, PanelSession)
    assert s.manager_id == "abc123"
    assert s.email == "t@v4company.com"


def test_tampered_cookie_rejected():
    cookie = sign_panel_session(
        manager_id="abc", email="t@v4company.com", signing_key=_SIGNING_KEY,
    )
    tampered = cookie[:-1] + ("X" if cookie[-1] != "X" else "Y")
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(tampered, _SIGNING_KEY)


def test_wrong_key_rejected():
    cookie = sign_panel_session(
        manager_id="abc", email="t@v4company.com", signing_key=_SIGNING_KEY,
    )
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session(cookie, "y" * 32)


def test_expired_cookie_rejected():
    fake_now = time.time() - (25 * 60 * 60)  # 25 hours ago
    cookie = sign_panel_session(
        manager_id="abc", email="t@v4company.com", signing_key=_SIGNING_KEY,
        issued_at=fake_now,
    )
    with pytest.raises(InvalidPanelSessionError, match="expired"):
        verify_panel_session(cookie, _SIGNING_KEY)


def test_within_ttl_accepted():
    fake_now = time.time() - (12 * 60 * 60)  # 12 hours ago
    cookie = sign_panel_session(
        manager_id="abc", email="t@v4company.com", signing_key=_SIGNING_KEY,
        issued_at=fake_now,
    )
    s = verify_panel_session(cookie, _SIGNING_KEY)
    assert s.manager_id == "abc"


def test_garbage_input_rejected():
    with pytest.raises(InvalidPanelSessionError):
        verify_panel_session("not-a-real-cookie", _SIGNING_KEY)
```

### Step 2: Implement `src/auth/panel_session.py`

EXACT content (mirrors oauth_state pattern but with 24h TTL):

```python
"""Panel session cookie — signed, time-bounded.

Format: base64url(payload_json) + "." + base64url(hmac_sha256(payload_json))

Payload: {manager_id, email, iat}. 24-hour TTL.

Used as the value of an httpOnly Secure SameSite=Lax cookie called
'v4_panel_session'. Verified on every panel route via Depends.
"""
import base64
import hmac
import json
import time
from dataclasses import dataclass
from hashlib import sha256

PANEL_SESSION_TTL_SECONDS = 24 * 60 * 60  # 24 hours
PANEL_SESSION_COOKIE_NAME = "v4_panel_session"


class InvalidPanelSessionError(Exception):
    """Raised when the cookie is missing/expired/tampered."""


@dataclass(slots=True, frozen=True)
class PanelSession:
    manager_id: str
    email: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def sign_panel_session(
    *,
    manager_id: str,
    email: str,
    signing_key: str,
    issued_at: float | None = None,
) -> str:
    """Build a signed cookie value."""
    payload = {
        "manager_id": manager_id,
        "email": email,
        "iat": int(issued_at if issued_at is not None else time.time()),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tag = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    return f"{_b64url(body)}.{_b64url(tag)}"


def verify_panel_session(cookie: str, signing_key: str) -> PanelSession:
    """Verify HMAC + TTL, return the decoded PanelSession. Raises on failure."""
    try:
        body_b64, tag_b64 = cookie.split(".", 1)
        body = _b64url_decode(body_b64)
        tag = _b64url_decode(tag_b64)
    except (ValueError, base64.binascii.Error) as e:
        raise InvalidPanelSessionError("Malformed cookie") from e

    expected = hmac.new(signing_key.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise InvalidPanelSessionError("HMAC mismatch")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise InvalidPanelSessionError("Bad JSON") from e

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise InvalidPanelSessionError("Missing iat")
    if (time.time() - iat) > PANEL_SESSION_TTL_SECONDS:
        raise InvalidPanelSessionError("Cookie expired")

    return PanelSession(
        manager_id=payload.get("manager_id", ""),
        email=payload.get("email", ""),
    )
```

### Step 3: Run tests + commit

```bash
./.venv/Scripts/python.exe -m pytest tests/unit/test_panel_session.py -v
./.venv/Scripts/python.exe -m mypy src/auth/panel_session.py
./.venv/Scripts/python.exe -m ruff check src/auth/panel_session.py tests/unit/test_panel_session.py
./.venv/Scripts/python.exe -m ruff format --check src/auth/panel_session.py tests/unit/test_panel_session.py
./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3

git add src/auth/panel_session.py tests/unit/test_panel_session.py
git commit -m "feat(auth): panel_session signed cookie helper

24-hour TTL signed cookie analogous to oauth_state but for panel
sessions. Used by web/routes.py to gate access to gestor + admin
pages."
git push
```

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 3: V4 design system (CSS tokens + base + components) + logo + base template

**Files:**
- Create: `src/web/__init__.py` (empty)
- Create: `src/web/static/v4-tokens.css`
- Create: `src/web/static/v4-base.css`
- Create: `src/web/static/v4-components.css`
- Create: `src/web/static/logo/v4-symbol.svg` (the V4 red square symbol — see brand book)
- Create: `src/web/templates/_base.html`
- Create: `src/web/templates/_components.html` (Jinja2 macros)
- Modify: `src/app.py` to mount static files + register Jinja2 environment

### Step 1: Implement `src/web/static/v4-tokens.css`

EXACT content (derived from brand.v4company.com):

```css
/* V4 Company Design Tokens */
:root {
  /* PRIMARY — Vermelho V4 (#e50914) */
  --v4-red:           #e50914;
  --v4-red-medium:    #b20710;
  --v4-red-dark:      #80050b;
  --v4-red-darkest:   #400306;

  /* NEUTRALS — Light */
  --v4-white:         #ffffff;
  --v4-gray-50:       #f5f5f5;
  --v4-gray-100:      #e5e5e5;
  --v4-gray-200:      #cccccc;
  --v4-gray-300:      #b3b3b3;

  /* NEUTRALS — Dark */
  --v4-gray-700:      #333333;
  --v4-gray-800:      #262626;
  --v4-gray-900:      #1a1a1a;
  --v4-black:         #000000;

  /* SECONDARY — Status */
  --v4-green:         #52cc5a;
  --v4-gold:          #ffc02a;

  /* TYPOGRAPHY (Montserrat — Bunny Fonts CDN) */
  --v4-font-primary:  'Montserrat', system-ui, -apple-system, sans-serif;
  --v4-font-body:     'Montserrat', system-ui, -apple-system, sans-serif;

  /* Hierarchy from V4 brand book */
  --v4-h1-size: 36px;   /* scaled down from book's 72px for web ergonomics */
  --v4-h1-weight: 800;
  --v4-h1-line: 1.1;

  --v4-h2-size: 28px;
  --v4-h2-weight: 700;
  --v4-h2-line: 1.2;

  --v4-h3-size: 20px;
  --v4-h3-weight: 600;
  --v4-h3-line: 1.3;

  --v4-h4-size: 16px;
  --v4-h4-weight: 600;
  --v4-h4-line: 1.4;

  --v4-body-size: 14px;
  --v4-body-weight: 400;
  --v4-body-line: 1.5;

  --v4-small-size: 12px;
  --v4-small-line: 1.4;

  /* SPACING */
  --v4-space-1: 4px;
  --v4-space-2: 8px;
  --v4-space-3: 12px;
  --v4-space-4: 16px;
  --v4-space-6: 24px;
  --v4-space-8: 32px;
  --v4-space-12: 48px;
  --v4-space-16: 64px;

  /* RADII */
  --v4-radius-sm: 4px;
  --v4-radius-md: 8px;
  --v4-radius-lg: 12px;
  --v4-radius-xl: 16px;

  /* SHADOWS */
  --v4-shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --v4-shadow-card: 0 1px 3px rgba(0, 0, 0, 0.1), 0 1px 2px rgba(0, 0, 0, 0.06);
  --v4-shadow-modal: 0 10px 25px rgba(0, 0, 0, 0.15);
}
```

### Step 2: Implement `src/web/static/v4-base.css`

EXACT content:

```css
/* V4 base styles — light theme, Montserrat */
@import url('https://fonts.bunny.net/css?family=montserrat:300,400,500,600,700,800&display=swap');

* {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  font-family: var(--v4-font-body);
  font-size: var(--v4-body-size);
  line-height: var(--v4-body-line);
  color: var(--v4-gray-900);
  background: var(--v4-white);
}

h1 {
  font-size: var(--v4-h1-size);
  font-weight: var(--v4-h1-weight);
  line-height: var(--v4-h1-line);
  margin: 0 0 var(--v4-space-4);
}

h2 {
  font-size: var(--v4-h2-size);
  font-weight: var(--v4-h2-weight);
  line-height: var(--v4-h2-line);
  margin: 0 0 var(--v4-space-3);
}

h3 {
  font-size: var(--v4-h3-size);
  font-weight: var(--v4-h3-weight);
  line-height: var(--v4-h3-line);
  margin: 0 0 var(--v4-space-2);
}

h4 {
  font-size: var(--v4-h4-size);
  font-weight: var(--v4-h4-weight);
  line-height: var(--v4-h4-line);
  margin: 0 0 var(--v4-space-2);
}

p {
  margin: 0 0 var(--v4-space-3);
}

a {
  color: var(--v4-red);
  text-decoration: none;
}

a:hover {
  color: var(--v4-red-medium);
  text-decoration: underline;
}

code, pre {
  font-family: 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
  background: var(--v4-gray-50);
  padding: 2px 6px;
  border-radius: var(--v4-radius-sm);
}

pre {
  padding: var(--v4-space-4);
  overflow-x: auto;
  border: 1px solid var(--v4-gray-100);
}

main {
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--v4-space-6) var(--v4-space-4);
}

/* Header — V4 logo + nav */
.v4-header {
  background: var(--v4-white);
  border-bottom: 1px solid var(--v4-gray-100);
  padding: var(--v4-space-3) var(--v4-space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 10;
}

.v4-header__brand {
  display: flex;
  align-items: center;
  gap: var(--v4-space-3);
  text-decoration: none;
  color: var(--v4-gray-900);
}

.v4-header__brand:hover {
  color: var(--v4-gray-900);
  text-decoration: none;
}

.v4-header__logo {
  height: 32px;
  width: auto;
}

.v4-header__title {
  font-weight: 700;
  font-size: 16px;
  letter-spacing: -0.01em;
}

.v4-header__nav {
  display: flex;
  gap: var(--v4-space-4);
}

.v4-header__nav a {
  color: var(--v4-gray-700);
  font-weight: 500;
}

.v4-header__nav a:hover {
  color: var(--v4-red);
}

.v4-header__user {
  display: flex;
  align-items: center;
  gap: var(--v4-space-3);
  font-size: 13px;
  color: var(--v4-gray-700);
}

.v4-header__user a.logout {
  font-size: 12px;
  color: var(--v4-gray-700);
}

/* Footer */
.v4-footer {
  border-top: 1px solid var(--v4-gray-100);
  padding: var(--v4-space-6) var(--v4-space-4);
  margin-top: var(--v4-space-12);
  text-align: center;
  font-size: var(--v4-small-size);
  color: var(--v4-gray-300);
}
```

### Step 3: Implement `src/web/static/v4-components.css`

EXACT content:

```css
/* V4 component classes */

/* Buttons */
.v4-btn {
  display: inline-block;
  padding: 10px 20px;
  font-family: var(--v4-font-primary);
  font-size: var(--v4-body-size);
  font-weight: 600;
  line-height: 1.4;
  border: none;
  border-radius: var(--v4-radius-md);
  cursor: pointer;
  text-decoration: none;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.v4-btn--primary {
  background: var(--v4-red);
  color: var(--v4-white);
}

.v4-btn--primary:hover {
  background: var(--v4-red-medium);
  color: var(--v4-white);
  text-decoration: none;
}

.v4-btn--secondary {
  background: transparent;
  color: var(--v4-gray-900);
  border: 1px solid var(--v4-gray-200);
}

.v4-btn--secondary:hover {
  background: var(--v4-gray-50);
  border-color: var(--v4-gray-300);
}

.v4-btn--danger {
  background: var(--v4-white);
  color: var(--v4-red);
  border: 1px solid var(--v4-red);
}

.v4-btn--danger:hover {
  background: var(--v4-red);
  color: var(--v4-white);
}

.v4-btn--small {
  padding: 6px 12px;
  font-size: 13px;
}

.v4-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Cards */
.v4-card {
  background: var(--v4-white);
  border: 1px solid var(--v4-gray-100);
  border-radius: var(--v4-radius-lg);
  padding: var(--v4-space-6);
  box-shadow: var(--v4-shadow-card);
  margin-bottom: var(--v4-space-4);
}

.v4-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--v4-space-4);
}

.v4-card__title {
  margin: 0;
  font-size: var(--v4-h3-size);
}

/* Badges */
.v4-badge {
  display: inline-block;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  border-radius: var(--v4-radius-sm);
  letter-spacing: 0.05em;
}

.v4-badge--success { background: rgba(82, 204, 90, 0.15); color: #2e7e3a; }
.v4-badge--warning { background: rgba(255, 192, 42, 0.15); color: #a07700; }
.v4-badge--error { background: rgba(229, 9, 20, 0.1); color: var(--v4-red-medium); }
.v4-badge--neutral { background: var(--v4-gray-100); color: var(--v4-gray-700); }

/* Tables */
.v4-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: var(--v4-space-4);
}

.v4-table th, .v4-table td {
  text-align: left;
  padding: var(--v4-space-3) var(--v4-space-4);
  border-bottom: 1px solid var(--v4-gray-100);
}

.v4-table th {
  font-weight: 600;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--v4-gray-700);
  background: var(--v4-gray-50);
}

.v4-table tbody tr:hover {
  background: var(--v4-gray-50);
}

/* Forms */
.v4-input, .v4-select {
  width: 100%;
  padding: 10px 14px;
  font-family: var(--v4-font-body);
  font-size: var(--v4-body-size);
  color: var(--v4-gray-900);
  background: var(--v4-white);
  border: 1px solid var(--v4-gray-200);
  border-radius: var(--v4-radius-md);
}

.v4-input:focus, .v4-select:focus {
  outline: none;
  border-color: var(--v4-red);
  box-shadow: 0 0 0 3px rgba(229, 9, 20, 0.1);
}

.v4-form__group {
  margin-bottom: var(--v4-space-4);
}

.v4-form__label {
  display: block;
  margin-bottom: var(--v4-space-1);
  font-weight: 500;
  font-size: 13px;
  color: var(--v4-gray-700);
}

/* Alert / inline message */
.v4-alert {
  padding: var(--v4-space-3) var(--v4-space-4);
  border-radius: var(--v4-radius-md);
  margin-bottom: var(--v4-space-4);
  border-left: 4px solid;
  font-size: 13px;
}

.v4-alert--info { background: rgba(82, 204, 90, 0.05); border-left-color: var(--v4-green); }
.v4-alert--warning { background: rgba(255, 192, 42, 0.08); border-left-color: var(--v4-gold); }
.v4-alert--error { background: rgba(229, 9, 20, 0.05); border-left-color: var(--v4-red); }

.v4-alert--copyable code {
  user-select: all;
  display: block;
  margin-top: var(--v4-space-2);
  word-break: break-all;
  background: var(--v4-gray-900);
  color: var(--v4-white);
  padding: var(--v4-space-2);
}

/* Stat cards */
.v4-stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--v4-space-4);
  margin-bottom: var(--v4-space-6);
}

.v4-stat {
  background: var(--v4-white);
  border: 1px solid var(--v4-gray-100);
  border-radius: var(--v4-radius-lg);
  padding: var(--v4-space-4);
}

.v4-stat__label {
  font-size: 12px;
  color: var(--v4-gray-700);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--v4-space-2);
}

.v4-stat__value {
  font-size: 28px;
  font-weight: 700;
  color: var(--v4-gray-900);
}

.v4-stat__sublabel {
  font-size: 12px;
  color: var(--v4-gray-300);
  margin-top: 4px;
}

/* Dialog (modal-ish, not used yet but reserved) */
.v4-dialog {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.v4-dialog__panel {
  background: var(--v4-white);
  border-radius: var(--v4-radius-lg);
  padding: var(--v4-space-6);
  max-width: 500px;
  width: 100%;
  margin: 0 var(--v4-space-4);
  box-shadow: var(--v4-shadow-modal);
}
```

### Step 4: V4 logo SVG

Create `src/web/static/logo/v4-symbol.svg` with this content (simple V4 red square — replace with the official asset later if you have it):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <rect width="64" height="64" rx="8" fill="#E50914"/>
  <path d="M14 16 L24 48 L32 48 L42 16 L34 16 L28 38 L22 16 Z" fill="white"/>
  <path d="M44 16 L44 32 L52 32 L52 48 L60 48 L60 16 Z" fill="white"/>
</svg>
```

### Step 5: Implement `src/web/templates/_base.html`

EXACT content:

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}V4 Ads MCP{% endblock %}</title>
  <link rel="stylesheet" href="/static/v4-tokens.css">
  <link rel="stylesheet" href="/static/v4-base.css">
  <link rel="stylesheet" href="/static/v4-components.css">
  <link rel="icon" type="image/svg+xml" href="/static/logo/v4-symbol.svg">
  <script src="https://unpkg.com/htmx.org@2.0.3" defer></script>
</head>
<body>
  <header class="v4-header">
    <a class="v4-header__brand" href="/">
      <img src="/static/logo/v4-symbol.svg" class="v4-header__logo" alt="V4">
      <span class="v4-header__title">Ads MCP</span>
    </a>

    {% if current_user %}
    <nav class="v4-header__nav">
      <a href="/">Dashboard</a>
      <a href="/accounts">Contas</a>
      <a href="/sessions">Sessoes MCP</a>
      <a href="/audit">Audit</a>
      {% if current_user.is_admin %}
      <a href="/admin/managers">Admin</a>
      {% endif %}
    </nav>
    <div class="v4-header__user">
      <span>{{ current_user.email }}</span>
      <a class="logout" href="/logout">Sair</a>
    </div>
    {% endif %}
  </header>

  <main>
    {% block content %}{% endblock %}
  </main>

  <footer class="v4-footer">
    V4 Ads MCP — interno V4 Company
  </footer>
</body>
</html>
```

### Step 6: Implement `src/web/templates/_components.html` (Jinja2 macros)

EXACT content:

```html
{% macro stat(label, value, sublabel=None) %}
<div class="v4-stat">
  <div class="v4-stat__label">{{ label }}</div>
  <div class="v4-stat__value">{{ value }}</div>
  {% if sublabel %}<div class="v4-stat__sublabel">{{ sublabel }}</div>{% endif %}
</div>
{% endmacro %}

{% macro badge(text, kind="neutral") %}
<span class="v4-badge v4-badge--{{ kind }}">{{ text }}</span>
{% endmacro %}

{% macro alert(message, kind="info") %}
<div class="v4-alert v4-alert--{{ kind }}">{{ message }}</div>
{% endmacro %}
```

### Step 7: Modify `src/app.py`

Read it. Add `from fastapi.staticfiles import StaticFiles` at top, then in `create_app()` after `mount_mcp(app)` and oauth_router inclusion, add:

```python
    from pathlib import Path

    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from src.web.routes import router as web_router
    app.include_router(web_router)
```

(`web_router` doesn't exist yet — Tasks 4-6 create it. Until then, the import will fail on app boot. To avoid breaking things, wrap in try/except or defer the import to after Task 4.)

Actually, simpler: skip the `web_router` include in this task. Just mount /static so we can preview the CSS via direct URL like /static/v4-base.css. Add the web_router include at the end of Task 4.

Final modification:

```python
    from pathlib import Path

    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
```

### Step 8: Smoke test + commit

```bash
cd "/d/HUB ads MCP"
mkdir -p src/web/static/logo src/web/templates
# (already created the files above)
ls src/web/static/
ls src/web/templates/

# Verify imports still work
./.venv/Scripts/python.exe -c "from src.app import create_app; app = create_app(skip_db_init=True); print('OK', [r.path for r in app.routes][:5])"

./.venv/Scripts/python.exe -m pytest tests/ --tb=line | tail -3

git add src/web/ src/app.py
git commit -m "feat(web): V4 design tokens + base + components CSS + base template

CSS variables for V4 brand (#e50914 red, Montserrat font, light
theme), base typography, component classes (buttons, cards, badges,
tables, forms, alerts, stats), V4 logo symbol SVG.

Base Jinja2 template with V4 header (logo + nav), footer, HTMX
loaded via CDN. _components.html exposes Jinja macros for stat,
badge, alert.

src/app.py mounts /static. web router will be added in next task."
git push
```

## Report

Status, list files created, pytest tail, mypy/ruff, git head.

---

## Task 4: Login + landing pages + panel session middleware

**Files:**
- Create: `src/web/__init__.py` (empty if not yet)
- Create: `src/web/deps.py` — `current_manager` dependency reads cookie
- Create: `src/web/routes.py` — `/login`, `/logout`, `/` (dashboard), `/auth/callback` (re-uses oauth_callback but issues a panel cookie)
- Create: `src/web/templates/login.html`
- Create: `src/web/templates/dashboard.html`
- Create: `src/web/templates/error.html`
- Modify: `src/auth/oauth.py` — `oauth_callback` now also sets the panel session cookie + redirects to `/` instead of returning HTML
- Modify: `src/app.py` to include the web router
- Create: `tests/integration/test_web_panel_login.py`

**Subagent dispatches**: this task is large enough that the implementer may need careful guidance. Dispatch with detailed instructions including all file contents.

The login page renders a single button "Entrar com Google V4" that links to `/oauth/google/start?invite=<token>` where the invite is generated from a DEFAULT manager_id (or uses a special flow without invite — let's use a "self-onboarding" branch).

Key change: `/oauth/google/start` for **panel login** doesn't require an invite (anyone with @v4company.com can self-onboard). The callback creates the manager record if it doesn't exist, or finds the existing one by email.

Add a query param `mode=panel_login` to `/oauth/google/start` to distinguish from CLI invite-based flow. The callback branches on the mode param (carried in the state) — if `mode=panel_login`, find-or-create the manager by email; otherwise (mode=invite), use the invited manager_id.

Implementation specifics:
- `/oauth/google/start?mode=panel_login` (no invite required) — encodes `mode=panel_login` in state
- `/oauth/google/start?invite=<sig>` (existing) — encodes `manager_id` in state
- Callback: if state has `mode=panel_login`, lookup manager by email (from userinfo) → create if missing → upsert refresh_token → set panel cookie → redirect to `/`. If state has `manager_id`, use the existing logic.

The `/` route renders dashboard. Header shows logged-in email + admin status. Dashboard shows quick stats: number of accessible accounts, number of MCP sessions active, today's quota usage.

Tasks for the implementer:
1. Add panel_session helpers
2. Modify oauth_start to accept mode param
3. Modify oauth_callback to branch on mode
4. Add `current_manager` dependency in `src/web/deps.py`
5. Add `/login`, `/logout`, `/` routes
6. Templates: login.html, dashboard.html, error.html
7. Tests for login/logout/dashboard

## Report

Status, pytest tail, mypy/ruff, git head, deviations.

---

## Task 5: Sessions page (create / list / revoke MCP Bearer tokens)

**Files:**
- Modify: `src/web/routes.py` — add `/sessions`, `/sessions/new`, `/sessions/<id>/revoke`
- Create: `src/web/templates/sessions/list.html`, `src/web/templates/sessions/created.html`
- Tests: integration tests for the 3 routes

The "created" page is the one-time token reveal screen with copy-paste snippets for Claude Desktop, Claude Code, Codex CLI, Cursor (same content as the CLI's create-session output, but as HTML with copy buttons).

Revoke uses HTMX for inline action (no full page reload).

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 6: Accounts page (Google OAuth connections)

**Files:**
- Modify: `src/web/routes.py` — add `/accounts`, `/accounts/connect`, `/accounts/<id>/revoke`
- Create: `src/web/templates/accounts.html`
- Tests

`/accounts/connect` redirects to `/oauth/google/start?mode=panel_login` (re-do the flow to get a fresh refresh_token if user wants to reconnect a different Google account).

The page lists active OAuth connections (showing Google email + connected_at + scopes) and each one has a "Revogar" button.

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 7: Audit page (manager's own log)

**Files:**
- Modify: `src/web/routes.py` — add `/audit`
- Create: `src/web/templates/audit.html`
- Tests

`/audit` shows the manager's own audit_log entries from the last 30 days, paginated. Filters: action_type (read|mutate|all), customer_id (dropdown of accessible accounts), date range.

Each row shows: timestamp, operation, customer (with name from google_ads_accounts), target_count, status, duration_ms.

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 8: Admin pages (managers + access matrix + accounts list + admin audit)

**Files:**
- Modify: `src/web/routes.py` — add `/admin/*` routes with `require_admin` dependency
- Create: 4 templates in `src/web/templates/admin/`
- Tests

Pages:
- `/admin/managers` — list all managers (email, role, is_active, last_seen). Actions: toggle is_active, toggle role (gestor↔admin).
- `/admin/access` — matrix of (manager × account) checkboxes. Toggle a checkbox grants/revokes access (HTMX inline).
- `/admin/accounts` — list synced google_ads_accounts. Show last-synced timestamp, link to trigger manual resync.
- `/admin/audit` — global audit log with filter by manager + customer.

## Report

Status, pytest tail, mypy/ruff, git head.

---

## Task 9: E2E + sign-off

**Files:**
- Modify: `docs/operacao/phase-1a-bootstrap.md` — append Phase 1b testing section
- Modify: `docs/operacao/infra-setup.md` — append Phase 1b sign-off scaffold

Test prompts for the user:
1. **Login flow:** Open the panel URL in incognito browser. Click "Entrar com Google V4". Authorize a `@v4company.com` Google account. Land on dashboard.
2. **Self-onboarding:** From dashboard, navigate to /accounts. The Google connection from login is already there (refresh_token saved).
3. **Create session:** /sessions → "Nova sessao". Token is shown once with snippets. Copy snippet, configure Claude Desktop, verify connection works.
4. **Revoke session:** Back in /sessions, click "Revogar" on a session. Verify it disappears (HTMX) and that future MCP calls with that token return 401.
5. **Audit:** /audit shows the recent calls.
6. **Admin pages:** /admin/managers, /admin/access — verify all 23 V4 accounts are listed and checkboxes work.
7. **Domain rejection:** Try logging in with a `@gmail.com` account → should be rejected with the V4-only error page.

Update `docs/operacao/infra-setup.md` with Phase 1b sign-off summary.

## Report

Status, sign-off commit hash, list of pages tested.

---

## Self-review notes

**Spec coverage:**
- §8 painel completo (5 telas gestor + 5 telas admin) — Tasks 4-8
- §5.1 Fluxo A (Supabase Auth) — DEVIATED to unified Google OAuth (Task 1) — documented
- §5.1 Fluxo B (OAuth Google) — Task 1 (extended with email scope)
- §8.4 Acessibilidade (contraste 2.25:1, focus visível) — Task 3 CSS

**Out of scope for Phase 1b (deferred):**
- Audit log roll-up cron — Phase 4
- Custom domain — Phase 4
- Admin /admin/quota dashboard — defer (audit + accounts gives enough visibility)

**Type/name consistency:**
- `current_manager` dependency consistent across all panel routes
- `require_admin` dependency used in all admin routes
- Cookie name `v4_panel_session` consistent
- Path patterns: `/admin/*` for admin only, others for any logged-in manager

**Risk register:**
- Cookie security: must be httpOnly + Secure (HTTPS) + SameSite=Lax. Set in routes.py.
- CSRF: forms that mutate state (revoke session, grant access) should include CSRF token. Simple impl: HMAC of `{manager_id, action, ts}` posted with the form.
- Session hijacking: cookie is signed with our key — can't be forged. TTL is 24h.
