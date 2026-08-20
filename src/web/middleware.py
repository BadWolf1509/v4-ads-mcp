"""Security middlewares for the web panel."""

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
# Isento por ROTA, nao por prefixo. Dois casos, e so eles:
#   - /oauth/meta/data-deletion-callback: POST server-to-server da Meta, que valida
#     o proprio HMAC no signed_request;
#   - /mcp: auth por Bearer, nao por cookie.
# O prefixo `/oauth/` inteiro era largo demais. Os endpoints OAuth de verdade sao
# GET (start, callback) — metodo seguro, nunca checado —, mas `/oauth/meta/revoke` e
# `/oauth/meta/refresh-accounts` sao mutacoes do PAINEL autenticadas por cookie
# (Depends(current_manager)), disparadas por <form method="post"> em admin/index.html.
# Vivem ali por acidente de roteamento (o APIRouter tem prefix /oauth/meta) e ficavam
# de fora da unica checagem de origem que existe.
_CSRF_EXEMPT_PREFIXES = ("/oauth/meta/data-deletion-callback", "/mcp")

# Complete inventory of external origins the panel loads (verified 2026-05-29 via
# grep of templates + static; promoted from Report-Only to enforcing after smoke
# confirmed zero CSP violations in the browser console across all panel pages):
#   - https://unpkg.com            → script (htmx.org@2.0.3, SRI-pinned)
#   - https://fonts.bunny.net      → stylesheet + font files (loaded via <link
#                                     rel="preconnect"|"stylesheet"> in _base.html
#                                     head since 2026-07-04 — was @import in
#                                     v4-base.css; policy below is unchanged)
# No Google Fonts, no image CDNs. All other assets are self-hosted under /static/.
#
# 2026-08-11: o Tailwind deixou de ser CDN. O CSS passou a ser gerado offline
# (scripts/build_tailwind.py) e servido de /static, o que permitiu remover
# https://cdn.tailwindcss.com E o 'unsafe-eval' — este era exigido apenas pelo
# compilador em runtime do Play CDN.
#
# Em seguida, script-src perdeu o 'unsafe-inline': os 53 handlers de atributo
# (on*=/hx-on) e os 13 blocos <script> inline viraram listeners delegados em
# /static/v4-panel.js, acionados por data-v4-*. Guards em
# tests/unit/test_frontend_a11y_guards.py impedem a volta — sem eles, um
# handler inline novo falharia silenciosamente no browser.
#
# style-src perdeu o 'unsafe-inline' em seguida: os 28 atributos style= viraram
# classe (utilitario do Tailwind ou classe do design system) e o <style> que o
# htmx injetava pro .htmx-indicator foi desligado via
# <meta name="htmx-config" content='{"includeIndicatorStyles": false}'> — as
# mesmas regras ja existem em v4-motion.css.
#
# Escrita via CSSOM (el.style.x = y, setProperty) NAO e afetada por CSP —
# verificado empiricamente sob style-src 'none'. Por isso os filtros de tabela,
# o overflow do drawer e a medicao sticky seguem funcionando.
_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com; "
    "style-src 'self' https://fonts.bunny.net; "
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


class SelectiveGZipMiddleware(GZipMiddleware):
    """GZip em tudo, menos /mcp.

    Medido em producao 2026-08-11: os estaticos saiam sem compressao nenhuma
    (transferSize == decodedBodySize), 28,7 KB que gzipados viram ~7 KB.

    /mcp fica de fora porque e StreamableHTTPServerTransport (SSE): comprimir
    um corpo que fica aberto faz o gzip acumular bytes no buffer e atrasar ou
    quebrar a entrega dos eventos.
    """

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
