"""Unit tests for the StarletteHTTPException handler in src/app.py.

CLAUDE.md: "preserve o branch 3xx (senão prende usuário não-autenticado)" — este
handler tem 3 branches (3xx redirect / mcp+oauth JSON / browser HTML) e um
regresso silencioso no primeiro (ex.: alguém "simplifica" o handler e passa a
sempre renderizar error.html) travaria todo login sem-cookie atrás de uma
página de erro em vez do redirect pra /login.

Usa a fixture `client` de tests/conftest.py (app com skip_db_init=True, sem DB
real) — httpx por padrão NÃO segue redirects, então response.status_code e
response.headers["location"] ficam intactos pra asserção.
"""

from httpx import AsyncClient


async def test_dependency_302_preserves_location_not_error_html(client: AsyncClient) -> None:
    """GET / sem cookie de sessão -> current_manager levanta HTTPException(302, Location=/login).

    O handler deve devolver um RedirectResponse (Location preservado), NÃO renderizar
    error.html — do contrário o usuário não-autenticado fica preso numa página de erro.
    """
    response = await client.get("/")
    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    # Confirma que NÃO é a página de erro (title amigável do error.html).
    assert "Algo deu errado" not in response.text
    assert "Não encontrado" not in response.text


async def test_404_under_mcp_prefix_is_json(client: AsyncClient) -> None:
    """404 sob /mcp/... (path não registrado) -> JSON, não HTML (cliente é MCP machine-consumer)."""
    response = await client.get("/mcp/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "detail" in body


async def test_404_under_oauth_prefix_is_json(client: AsyncClient) -> None:
    """404 sob /oauth/... -> JSON (mesmo tratamento machine-consumer que /mcp)."""
    response = await client.get("/oauth/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "detail" in body


async def test_404_on_normal_page_is_html_error_page(client: AsyncClient) -> None:
    """404 numa rota normal do painel (fora de /mcp e /oauth) -> error.html amigável em PT-BR."""
    response = await client.get("/this-page-does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "A página que você procura não existe ou foi movida." in response.text
    assert "Não encontrado" in response.text
