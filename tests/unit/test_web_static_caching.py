"""Entrega de assets: compressao + cache (sem DB, sem testcontainers).

Medido em producao 2026-08-11 como ausentes — transferSize == decodedBodySize
nos quatro CSS (sem compressao) e nenhum Cache-Control, so etag, entao toda
navegacao revalidava todos os assets.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.web.middleware import SelectiveGZipMiddleware
from src.web.static_files import CachedStaticFiles, asset_version

_STATIC = Path(__file__).resolve().parents[2] / "src" / "web" / "static"


def _app() -> FastAPI:
    a = FastAPI()
    a.add_middleware(SelectiveGZipMiddleware, minimum_size=100)
    a.mount("/static", CachedStaticFiles(directory=str(_STATIC)), name="static")

    @a.get("/pagina")
    async def pagina() -> dict[str, str]:
        return {"corpo": "conteudo compressivel " * 40}

    @a.post("/mcp")
    async def mcp() -> dict[str, str]:
        return {"stream": "evento sse " * 40}

    return a


@pytest.mark.asyncio
async def test_static_tem_cache_control_imutavel() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/static/v4-tokens.css")
    assert r.status_code == 200
    cache = r.headers["cache-control"]
    assert "immutable" in cache
    assert "max-age=31536000" in cache


@pytest.mark.asyncio
async def test_resposta_comum_e_comprimida() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.get("/pagina", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"


@pytest.mark.asyncio
async def test_mcp_nunca_e_comprimido() -> None:
    """/mcp e StreamableHTTPServerTransport (SSE) — gzip com buffering quebra o stream."""
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://t") as c:
        r = await c.post("/mcp", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") != "gzip"


def test_asset_version_muda_por_revisao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("K_REVISION", "v4-ads-mcp-00042-abc")
    assert asset_version() == "v4-ads-mcp-00042-abc"
    monkeypatch.delenv("K_REVISION")
    assert asset_version() == "dev"
