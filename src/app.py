"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, RedirectResponse, Response

from src.config import get_settings
from src.db import connection
from src.logging import configure_logging
from src.mcp.server import mount_mcp
from src.web.middleware import CSRFOriginMiddleware, SecurityHeadersMiddleware

__version__ = "0.1.0"

log = structlog.get_logger(__name__)


def create_app(skip_db_init: bool = False) -> FastAPI:
    """Build the FastAPI app. Test code uses `skip_db_init=True`."""
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        json_output=settings.app_env != "development",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not skip_db_init:
            await connection.init_pool(settings.database_url)
            log.info("app_started", env=settings.app_env)
        yield
        if not skip_db_init:
            await connection.close_pool()
            log.info("app_stopped")

    app = FastAPI(
        title="V4 Ads MCP",
        version=__version__,
        lifespan=lifespan,
    )

    # NOTE: /healthz is intercepted by Google Front End on Cloud Run before
    # the request reaches the container (returns Google's 404 HTML page).
    # Use /health instead. Confirmed empirically on Cloud Run rev 00001.
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.add_middleware(CSRFOriginMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    mount_mcp(app)

    from src.auth.oauth import router as oauth_router

    app.include_router(oauth_router)

    from src.auth import meta_oauth as meta_oauth_module

    app.include_router(meta_oauth_module.router)

    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    from src.web.routes import router as web_router

    app.include_router(web_router)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
        # 3xx: preserve redirect (e.g. 302→/login from current_manager dep).
        if 300 <= exc.status_code < 400:
            location = (exc.headers or {}).get("Location", "/")
            return RedirectResponse(url=location, status_code=exc.status_code)

        # MCP + OAuth paths: JSON error (machine consumers).
        if request.url.path.startswith(("/mcp", "/oauth")):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

        # Browser panel: friendly error page.
        from src.web.routes import templates  # noqa: PLC0415

        # Starlette's default details are English ("Not Found", "Method Not Allowed",
        # "Internal Server Error"). Replace those generic strings with PT-BR; keep our
        # own custom PT-BR details (e.g. "Sessão não encontrada") untouched.
        generic_details = {"Not Found", "Method Not Allowed", "Internal Server Error", "Forbidden"}
        detail = exc.detail
        if exc.status_code == 404 and (not detail or detail in generic_details):
            message = "A página que você procura não existe ou foi movida."
        elif not detail or detail in generic_details:
            message = "Tente novamente em alguns segundos."
        else:
            message = str(detail)

        friendly: dict[str, str | int | None] = {
            "current_user": None,
            "title": "Não encontrado" if exc.status_code == 404 else "Algo deu errado",
            "message": message,
        }
        return templates.TemplateResponse(
            request,
            "error.html",
            friendly,
            status_code=exc.status_code,
        )

    return app


# Module-level instance for uvicorn / Buildpacks
app = create_app()
