"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.config import get_settings
from src.db import connection
from src.logging import configure_logging
from src.mcp.server import mount_mcp

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

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    mount_mcp(app)
    return app


# Module-level instance for uvicorn / Buildpacks
app = create_app()
