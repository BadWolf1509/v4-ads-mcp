"""Isenção de CSRF é por ROTA, nunca por prefixo (F106).

Prefixo herda tudo que um `APIRouter(prefix=…)` pendurar ali depois, sem
revisão. O teste tem DOIS lados de propósito: o que precisa ser isento continua
isento (senão o MCP quebra em produção), e o que não precisa não é.

Os casos de /mcp vêm do Step 1 medido (task-4-report.md): `create_app()`
registra um único `APIRoute` sob /mcp — `POST /mcp` (`mcp_endpoint`, definido
em `src/mcp/server.py:150` via `@app.post("/mcp")`), caminho literal, sem
nenhum `APIRouter(prefix=...)` por baixo e sem GET/DELETE (o transporte é
stateless — `mcp_session_id=None`, `stateless=True`). Não existe hoje nenhum
`/mcp/<algo>`. Por isso /mcp virou entrada literal no mesmo conjunto, não
prefixo — ver o motivo escrito em `src/web/middleware.py`.
"""

from __future__ import annotations

from src.web.middleware import _rota_isenta_de_csrf


def test_o_que_e_isento_continua_isento() -> None:
    """Isentar de menos quebra o transporte em produção."""
    assert _rota_isenta_de_csrf("/oauth/meta/data-deletion-callback")
    assert _rota_isenta_de_csrf("/mcp")


def test_caminho_pendurado_sob_o_prefixo_NAO_herda_a_isencao() -> None:  # noqa: N802
    """O coração do F106: um router novo sob o mesmo prefixo não vem junto."""
    assert not _rota_isenta_de_csrf("/oauth/meta/data-deletion-callback/admin")
    assert not _rota_isenta_de_csrf("/oauth/meta/data-deletion-callbackXYZ")
    # Medido no Step 1: nada vive sob /mcp além de /mcp. Um sub-caminho aqui
    # só pode existir por acidente (ou ataque) — nunca herda a isenção.
    assert not _rota_isenta_de_csrf("/mcp/session/123")
    assert not _rota_isenta_de_csrf("/mcpXYZ")


def test_rota_comum_do_painel_nao_e_isenta() -> None:
    """Controle positivo: sem ele, `return True` incondicional passaria verde."""
    assert not _rota_isenta_de_csrf("/admin/access/toggle")
    assert not _rota_isenta_de_csrf("/login")
