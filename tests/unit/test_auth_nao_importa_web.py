"""F7: `src/auth` não depende de `src/web/routes`.

`oauth.py` importava `templates` de `src.web.routes._shared`, o que puxava o
pacote de rotas inteiro do painel para dentro da camada de autenticação. O
`templates` mora agora em `src.web.templating`, e o redirect_uri com https
forçado em `src.auth.urls.https_url_for`.
"""

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.auth import oauth
from src.auth.oauth import handle_callback_decision
from src.auth.urls import https_url_for

_AUTH_DIR = Path(__file__).resolve().parents[2] / "src" / "auth"
_PROIBIDO = "src.web.routes"


def _imports_proibidos(arquivo: Path) -> list[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    achados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes = [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes = [no.module] + [f"{no.module}.{a.name}" for a in no.names]
        else:
            continue
        for nome in nomes:
            if nome == _PROIBIDO or nome.startswith(_PROIBIDO + "."):
                achados.append(f"{arquivo.name}:{no.lineno} importa {nome}")
                break
    return achados


def test_auth_nao_importa_web_routes() -> None:
    arquivos = sorted(_AUTH_DIR.rglob("*.py"))
    assert arquivos, "nenhum arquivo em src/auth — o guard nao leu nada"
    achados = [a for arq in arquivos for a in _imports_proibidos(arq)]
    assert not achados, "src/auth nao pode importar src.web.routes:\n" + "\n".join(achados)


def test_https_url_for_forca_https_no_callback_do_oauth() -> None:
    """Cloud Run entrega HTTP ao container; o redirect_uri registrado no Google é https."""
    app = FastAPI()
    app.include_router(oauth.router)

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, str]:
        return {"url": https_url_for(request, "oauth_callback")}

    with TestClient(app, base_url="http://testserver") as c:
        assert c.get("/probe").json() == {"url": "https://testserver/oauth/google/callback"}


def test_https_url_for_preserva_https_e_path_params() -> None:
    app = FastAPI()

    @app.get("/status/{code}", name="status_probe")
    async def status_probe(code: str) -> None:
        return None

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, str]:
        return {"url": https_url_for(request, "status_probe", code="abc")}

    with TestClient(app, base_url="https://testserver") as c:
        assert c.get("/probe").json() == {"url": "https://testserver/status/abc"}


async def _decisao(email: str) -> tuple[str, str | None]:
    d = await handle_callback_decision(
        email=email,
        google_id="g",
        google_email=email,
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"status": "active", "is_active": True},
    )
    return d.kind, d.location


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("email", "esperado"),
    [
        # Medido no código pré-F7 (endswith "@v4company.com"): os dois casos do
        # brief dão o mesmo resultado que `is_allowed_email`.
        ("a@sub.v4company.com", ("redirect", "/access-denied?reason=domain")),
        ("a@V4Company.com", ("login", None)),
        # Divergência registrada: o endswith antigo aceitava dois "@"; o
        # `is_allowed_email` recusa (mais estrito, fail-closed).
        ("a@b@v4company.com", ("redirect", "/access-denied?reason=domain")),
    ],
)
async def test_callback_gate_de_dominio(email: str, esperado: tuple[str, str | None]) -> None:
    assert await _decisao(email) == esperado
