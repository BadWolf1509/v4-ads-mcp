"""Cliques reais nas confirmacoes do painel, com templates, estaticos e CSP de verdade.

Em 31/10 "Desativar" fechava a confirmacao sem enviar nada: o defeito morava entre
o HTML e a rota, onde nenhum teste que le arquivo ou chama rota alcanca.
"""

import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import Browser, ConsoleMessage, Page, sync_playwright

from src.web.middleware import SecurityHeadersMiddleware
from src.web.routes._shared import templates

_STATIC = Path(__file__).resolve().parents[2] / "src" / "web" / "static"
_ADMIN = SimpleNamespace(id="admin", email="admin@v4company.com", is_admin=True)
_GESTOR_ID = "00000000-0000-0000-0000-0000000000aa"
_CONVITE_ID = "00000000-0000-0000-0000-0000000000bb"


@dataclass
class Painel:
    url: str
    posts: list[tuple[str, str | None]] = field(default_factory=list)


@dataclass
class Aba:
    page: Page
    erros: list[str]


def _gestor() -> SimpleNamespace:
    return SimpleNamespace(
        id=_GESTOR_ID,
        email="gestor@v4company.com",
        full_name="Gestor",
        role="gestor",
        is_active=True,
        status="active",
        is_deactivated=False,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        last_seen_at=None,
    )


def _convite() -> SimpleNamespace:
    return SimpleNamespace(
        id=_CONVITE_ID,
        email="novo@v4company.com",
        full_name="Novo",
        role="gestor",
        invited_at=datetime(2026, 10, 1, tzinfo=UTC),
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        days_pending=1,
        onboarding_message="Bem-vindo",
    )


def _app(posts: list[tuple[str, str | None]]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    @app.get("/admin/managers")
    async def gestores(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "admin/managers.html",
            {"current_user": _ADMIN, "managers": [_gestor()], "pending_invites_count": 1},
        )

    @app.get("/admin/invites")
    async def convites(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "admin/invites.html",
            {"current_user": _ADMIN, "invites": [_convite()], "pending_invites_count": 1},
        )

    @app.post("/admin/managers/{gestor}/toggle-active")
    async def alternar(gestor: str, request: Request) -> Response:
        posts.append((request.url.path, request.headers.get("HX-Request")))
        return Response(status_code=204, headers={"HX-Redirect": "/admin/managers"})

    @app.post("/admin/invites/{convite}/cancel")
    async def cancelar(convite: str, request: Request) -> Response:
        posts.append((request.url.path, request.headers.get("HX-Request")))
        return Response(status_code=204, headers={"HX-Refresh": "true"})

    return app


@pytest.fixture
def painel() -> Iterator[Painel]:
    posts: list[tuple[str, str | None]] = []
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    porta = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_app(posts), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    limite = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < limite, "servidor de teste nao subiu"
        time.sleep(0.01)
    yield Painel(url=f"http://127.0.0.1:{porta}", posts=posts)
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def navegador() -> Iterator[Browser]:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def aba(navegador: Browser) -> Iterator[Aba]:
    page = navegador.new_page()
    # Fonte externa nao entra no teste; script externo reprova em
    # test_painel_so_carrega_script_da_propria_origem.
    page.route("https://fonts.bunny.net/**", lambda rota: rota.abort())
    erros: list[str] = []

    def registrar(msg: ConsoleMessage) -> None:
        if msg.type == "error" and "fonts.bunny.net" not in msg.location.get("url", ""):
            erros.append(msg.text)

    page.on("console", registrar)
    page.on("pageerror", lambda e: erros.append(str(e)))
    yield Aba(page=page, erros=erros)
    page.close()


def _confirma_e_espera_recarga(page: Page) -> None:
    page.evaluate("window.__antesDoPost = true")
    page.locator("#v4-confirm-dialog [data-confirm-ok]").click()
    page.wait_for_function("window.__antesDoPost === undefined")


def test_desativar_gestor_pelo_menu_envia_e_recarrega(painel: Painel, aba: Aba) -> None:
    aba.page.goto(f"{painel.url}/admin/managers")
    aba.page.locator(".v4-dropdown__trigger").click()
    aba.page.get_by_role("menuitem", name="Desativar").click()
    _confirma_e_espera_recarga(aba.page)
    assert painel.posts == [(f"/admin/managers/{_GESTOR_ID}/toggle-active", "true")]
    assert aba.erros == []


def test_cancelar_a_confirmacao_nao_envia(painel: Painel, aba: Aba) -> None:
    aba.page.goto(f"{painel.url}/admin/managers")
    aba.page.locator(".v4-dropdown__trigger").click()
    aba.page.get_by_role("menuitem", name="Desativar").click()
    aba.page.locator("[data-confirm-cancel]").click()
    assert not aba.page.locator("#v4-confirm-dialog").evaluate("d => d.open")
    assert painel.posts == []


def test_cancelar_convite_envia_e_recarrega(painel: Painel, aba: Aba) -> None:
    aba.page.goto(f"{painel.url}/admin/invites")
    aba.page.get_by_role("button", name="Cancelar", exact=True).click()
    _confirma_e_espera_recarga(aba.page)
    assert painel.posts == [(f"/admin/invites/{_CONVITE_ID}/cancel", "true")]
    assert aba.erros == []


def test_painel_so_carrega_script_da_propria_origem(painel: Painel, aba: Aba) -> None:
    scripts: list[str] = []
    aba.page.on(
        "request",
        lambda r: scripts.append(r.url) if r.resource_type == "script" else None,
    )
    aba.page.goto(f"{painel.url}/admin/managers")
    assert any("htmx" in s for s in scripts)
    assert all(s.startswith(painel.url) for s in scripts), scripts
    assert aba.page.evaluate("typeof htmx") == "object"
    assert aba.erros == []
