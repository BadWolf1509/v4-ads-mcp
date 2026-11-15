"""Fixtures compartilhadas dos testes de unidade."""

from collections.abc import Iterator
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
def ctx_mcp() -> Iterator[McpRequestContext]:
    """Contexto MCP com gestor e sessao aleatorios, limpo no teardown.

    NAO e autouse de proposito: ha teste que depende da AUSENCIA de contexto
    (`get_current()` levantando). Quem precisa pede por parametro ou declara
    `pytestmark = pytest.mark.usefixtures("ctx_mcp")` no arquivo.
    """
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()
