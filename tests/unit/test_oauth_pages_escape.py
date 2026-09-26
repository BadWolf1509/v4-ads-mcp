from httpx import AsyncClient
from starlette.requests import Request

from src.auth.oauth import _error_page, _success_page


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/oauth/google/callback",
            "headers": [],
            "query_string": b"",
        }
    )


def test_error_page_escapes_html():
    resp = _error_page(_request(), "<script>alert(1)</script>", status=400)
    body = resp.body.decode()
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_success_page_escapes_email():
    resp = _success_page(_request(), "a@b.com<script>")
    assert "<script>" not in resp.body.decode()


def test_paginas_do_oauth_usam_o_css_do_painel_e_nao_style_inline():
    """F178: as duas paginas eram HTML montado em Python com `<style>` inline, que a
    CSP bloqueia — renderizavam sem CSS em producao. Como templates do painel, o
    estilo vem do mesmo Tailwind versionado do resto, e nao sobra `<style>` nenhum."""
    paginas = {
        "sucesso": _success_page(_request(), "gestor@v4company.com"),
        "erro": _error_page(_request(), "Troca do code falhou.", status=502),
    }
    for nome, resp in paginas.items():
        body = resp.body.decode()
        assert "<style" not in body, f"{nome}: <style> inline volta a ser bloqueado pela CSP"
        assert "/static/v4-tailwind.css?v=" in body, f"{nome}: sem o CSS versionado do painel"

    assert paginas["sucesso"].status_code == 200
    assert "Conectado" in paginas["sucesso"].body.decode()
    # O status de erro passa intacto — 502 de troca de code nao pode virar 200.
    assert paginas["erro"].status_code == 502
    assert "Troca do code falhou." in paginas["erro"].body.decode()


def test_pagina_de_sucesso_nao_manda_o_gestor_pro_fluxo_antigo():
    """O texto dizia que atribuir contas era "manual via CLI" e mandava pedir ao
    admin que criasse a sessao MCP. Hoje o admin libera contas pela matriz de
    acesso, e so o proprio gestor emite a sessao dele (`/sessions/new`)."""
    body = _success_page(_request(), "gestor@v4company.com").body.decode()
    assert "CLI" not in body
    assert 'href="/sessions"' in body


async def test_callback_de_verdade_renderiza_o_erro_com_o_css_do_painel(
    client: AsyncClient,
) -> None:
    """Pela pilha inteira — rota, middlewares, CSP, template —, sem banco: o ramo
    `error=` do callback devolve antes de qualquer consulta. O teste de integracao
    do fluxo cobre o resto, mas precisa de Docker; este roda no gate rapido."""
    resp = await client.get("/oauth/google/callback", params={"error": "access_denied"})

    assert resp.status_code == 400
    assert "<style" not in resp.text
    assert "/static/v4-tailwind.css?v=" in resp.text
    assert "access_denied" in resp.text
    # A pagina e servida sob a CSP que bloqueava o <style> — e ela continua estrita.
    csp = resp.headers["content-security-policy"]
    assert "style-src" in csp
    assert "unsafe-inline" not in csp
