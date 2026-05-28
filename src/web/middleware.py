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
