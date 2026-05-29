"""Security middlewares for the web panel."""

from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
# Exempt: OAuth callbacks (GET, or Meta data-deletion POST which validates its own
# HMAC signed_request) and the MCP endpoint (Bearer-token auth, not cookie).
_CSRF_EXEMPT_PREFIXES = ("/oauth/", "/mcp")

# Complete inventory of external origins the panel loads (verified 2026-05-29 via
# grep of templates + static; promoted from Report-Only to enforcing after smoke
# confirmed zero CSP violations in the browser console across all panel pages):
#   - https://cdn.tailwindcss.com  → script (Play CDN, needs 'unsafe-eval')
#   - https://unpkg.com            → script (htmx.org@2.0.3, SRI-pinned)
#   - https://fonts.bunny.net      → stylesheet (@import in v4-base.css) + font files
# No Google Fonts, no image CDNs. All other assets are self-hosted under /static/.
# Inline <script>/<style> blocks are covered by 'unsafe-inline'/'unsafe-eval'.
_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.bunny.net; "
    "font-src 'self' https://fonts.bunny.net; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set security headers on every response.

    CSP is enforced (not Report-Only): the policy was validated against the full
    external-origin inventory + browser-console smoke (zero violations) before
    promotion. If a new external resource is added, update _CSP_POLICY in the
    same commit or it will be blocked.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers.setdefault("Content-Security-Policy", _CSP_POLICY)
        return resp


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """Reject unsafe-method requests whose Origin/Referer host != the request Host.

    Cookie-auth CSRF defense (defense-in-depth on top of the SameSite=Lax session
    cookie, which already blocks the cookie on cross-site POSTs). Comparing against
    the request's own Host header (not a hardcoded URL) is robust to multiple
    hostnames (e.g. Cloud Run's two service URLs).

    Posture (OWASP "verifying origin with standard headers"): block ONLY when an
    Origin/Referer is present AND its host mismatches. A *missing* Origin/Referer is
    not evidence of CSRF — browsers always attach Origin to cross-site POSTs, so a
    real attack carries a (mismatched) Origin and is blocked; absence just means a
    non-browser client (curl, server-to-server, tests). Blocking absence would add
    no protection (SameSite=Lax already covers it) while breaking legitimate clients.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if request.method not in _SAFE_METHODS and not path.startswith(_CSRF_EXEMPT_PREFIXES):
            source = request.headers.get("origin") or request.headers.get("referer")
            if source is not None:
                host = request.headers.get("host")
                if urlparse(source).netloc != host:
                    return JSONResponse({"detail": "CSRF: origem inválida"}, status_code=403)
        return await call_next(request)
