"""A3: tools Meta devolvem `denied` na negação e não vazam erro interno."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools import meta_get_entities as modulo
from src.mcp.tools._meta_common import meta_erro
from src.meta_ads.client import MetaAccessDeniedError
from src.meta_ads.errors import MetaAdsFriendlyError


@pytest.fixture(autouse=True)
def _ctx() -> Iterator[None]:
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def test_negacao_vira_denied() -> None:
    assert meta_erro(MetaAccessDeniedError("sem grant")) == {
        "status": "denied",
        "error_message": "sem grant",
    }


def test_friendly_mantem_mensagem() -> None:
    r = meta_erro(MetaAdsFriendlyError(message="token expirado", retryable=False))
    assert r == {"status": "error", "error_message": "token expirado"}


def test_erro_interno_sobe() -> None:
    exc = RuntimeError("asyncpg: senha")
    with pytest.raises(RuntimeError) as info:
        meta_erro(exc)
    assert info.value is exc


@pytest.mark.asyncio
async def test_tool_meta_negada_devolve_denied() -> None:
    with (
        patch.object(modulo, "exigir_brl", AsyncMock(return_value=None)),
        patch.object(
            modulo, "listar_entidades", AsyncMock(side_effect=MetaAccessDeniedError("sem grant"))
        ),
    ):
        r = await modulo.meta_get_entities({"ad_account_id": "act_1", "level": "campaign"})
    assert r["status"] == "denied"
    assert r["error_message"] == "sem grant"


def test_nenhuma_tool_meta_usa_meta_error_message() -> None:
    pasta = Path(__file__).resolve().parents[2] / "src" / "mcp" / "tools"
    usam = [p.name for p in pasta.glob("*.py") if "meta_error_message" in p.read_text("utf-8")]
    assert usam == []


@pytest.mark.asyncio
async def test_token_ausente_chega_ao_gestor_como_error() -> None:
    from src.meta_ads.client import MetaSystemUserTokenMissingError

    msg = "Token do system user Meta não configurado. O admin precisa subir o secret."
    exc = MetaSystemUserTokenMissingError(msg)
    assert isinstance(exc, MetaAdsFriendlyError)
    assert exc.message == msg and exc.retryable is False
    with (
        patch.object(modulo, "exigir_brl", AsyncMock(return_value=None)),
        patch.object(modulo, "listar_entidades", AsyncMock(side_effect=exc)),
    ):
        r = await modulo.meta_get_entities({"ad_account_id": "act_1", "level": "campaign"})
    assert r == {"status": "error", "error_message": msg}
