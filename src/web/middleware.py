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

# External origins loaded by _base.html (verified 2026-05-28):
#   - https://cdn.tailwindcss.com  → script (Play CDN, needs 'unsafe-eval')
#   - https://unpkg.com            → script (htmx.org@2.0.3)
#   - https://fonts.bunny.net      → stylesheet (@import in v4-base.css) + font files
# No Google Fonts, no image CDNs. All other assets are self-hosted under /static/.
_CSP_REPORT_ONLY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.bunny.net; "
    "font-src 'self' https://fonts.bunny.net; "
    "img-src 'self' data:; "
    "connect-src 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set security headers on every response.

    CSP is Report-Only (not enforcing) so an overly-tight policy cannot break
    the UI. Promote to Content-Security-Policy once violations stabilise.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        resp = await call_next(request)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers.setdefault("Content-Security-Policy-Report-Only", _CSP_REPORT_ONLY)
        return resp


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """Reject unsafe-method requests whose Origin/Referer host != the request Host.

    Cookie-auth CSRF defense for same-origin browser apps. Comparing against the
    request's own Host header (not a hardcoded URL) is robust to multiple hostnames
    (e.g. Cloud Run's two service URLs).
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if request.method not in _SAFE_METHODS and not path.startswith(_CSRF_EXEMPT_PREFIXES):
            host = request.headers.get("host")
            source = request.headers.get("origin") or request.headers.get("referer")
            source_host = urlparse(source).netloc if source else None
            if not host or source_host != host:
                return JSONResponse({"detail": "CSRF: origem inválida"}, status_code=403)
        return await call_next(request)
