"""Unit tests for the remove_audience MCP tool."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from jsonschema import ValidationError, validate


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def _good_payload():
    return {
        "customer_id": "1163862076",
        "target_type": "ad_group",
        "target_id": "183008426336",
        "criterion_ids": ["52988066042"],
    }


# Schema-level tests (5)


def test_schema_rejects_missing_target_type():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    del bad["target_type"]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_invalid_target_type():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    bad["target_type"] = "removeall"
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_missing_target_id():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    del bad["target_id"]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_empty_criterion_ids():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    bad["criterion_ids"] = []
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


def test_schema_rejects_over_100_criterion_ids():
    from src.mcp.tools.remove_audience import _SCHEMA

    bad = _good_payload()
    bad["criterion_ids"] = [str(i) for i in range(101)]
    with pytest.raises(ValidationError):
        validate(bad, _SCHEMA)


# Classification + flow tests (3)


@pytest.mark.asyncio
async def test_classify_always_confirms_count_one():
    """1 criterion → CONFIRM (always)."""
    from src.mcp.tools.remove_audience import remove_audience

    with (
        patch(
            "src.mcp.tools.remove_audience.create_pending",
            AsyncMock(return_value="TOKEN001"),
        ),
        patch("src.mcp.tools.remove_audience.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await remove_audience(_good_payload())

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN001"
    assert "sempre confirma" in result["confirmation_reason"].lower()


@pytest.mark.asyncio
async def test_classify_always_confirms_bulk():
    """50 criteria → still CONFIRM (no AUTO branch)."""
    from src.mcp.tools.remove_audience import remove_audience

    with (
        patch(
            "src.mcp.tools.remove_audience.create_pending",
            AsyncMock(return_value="TOKEN050"),
        ),
        patch("src.mcp.tools.remove_audience.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        result = await remove_audience(
            {
                "customer_id": "1163862076",
                "target_type": "ad_group",
                "target_id": "183008426336",
                "criterion_ids": [str(100 + i) for i in range(50)],
            }
        )

    assert result["status"] == "dry_run"
    assert result["confirmation_token"] == "TOKEN050"


@pytest.mark.asyncio
async def test_confirm_path_payload_includes_partial_failure_flag():
    """Payload must include __partial_failure__: True so apply_change uses it."""
    from src.mcp.tools.remove_audience import remove_audience

    captured_payload: dict = {}

    async def fake_create_pending(*_args, **kwargs):
        captured_payload.update(kwargs["payload"])
        return "TOKEN_PF"

    with (
        patch(
            "src.mcp.tools.remove_audience.create_pending",
            AsyncMock(side_effect=fake_create_pending),
        ),
        patch("src.mcp.tools.remove_audience.connection") as conn_module,
    ):
        conn_module.get_pool.return_value.acquire.return_value.__aenter__ = AsyncMock(
            return_value=AsyncMock()
        )
        conn_module.get_pool.return_value.acquire.return_value.__aexit__ = AsyncMock(
            return_value=None
        )
        await remove_audience(_good_payload())

    assert captured_payload["__partial_failure__"] is True
    assert captured_payload["__target_count__"] == 1
    assert captured_payload["target_type"] == "ad_group"
    assert captured_payload["target_id"] == "183008426336"
    assert captured_payload["criterion_ids"] == ["52988066042"]


# R1-I5: o teste que existia aqui exercitava `_classify_partial` — codigo morto
# que ninguem chamava. Um teste verde sobre uma funcao sem chamador nao prova
# nada sobre o que a tool entrega; ele era, na verdade, o que fazia a promessa
# falsa da description parecer coberta. Saiu junto com a funcao.


# R1-I5: a description descreve o que a tool ENTREGA


def _description() -> str:
    """A description REGISTRADA — a que o cliente MCP ve, nao a docstring."""
    from src.mcp.tools._registry import get_tool, import_all_tools

    import_all_tools()
    tool = get_tool("remove_audience")
    assert tool is not None
    return tool.description


def test_description_nao_promete_status_por_linha_que_ninguem_produz() -> None:
    """R1-I5: `already_removed` per-row nunca aconteceu.

    `_classify_partial` era codigo morto — nenhum caminho o chamava, e o
    `apply_change` (por onde a resposta desta tool sai) e generico: ele nao
    conhece o vocabulario de dominio de tool nenhuma. A description anunciava
    "audit_log mostra 'already_removed' per-row", e o gestor planeja em cima
    disso: ele espera distinguir "ja estava removida" de "falhou". Description
    que mente e pior que description ausente.
    """
    assert "already_removed" not in _description()


def test_description_nomeia_a_chave_que_a_resposta_de_fato_traz() -> None:
    """O substituto honesto: `partial_failures`, que o apply_change devolve (R1-I1)."""
    assert "partial_failures" in _description()


def test_classify_partial_saiu_do_modulo() -> None:
    """Codigo morto que sustentava a promessa. Sem chamador, ele so validava a mentira."""
    from src.mcp.tools import remove_audience as mod

    assert not hasattr(mod, "_classify_partial")
    assert not hasattr(mod, "_ALREADY_REMOVED_PATTERNS")
