"""`remove_asset_link` — always-CONFIRM, e o `resource_name` vem do `get_assets`.

O teste de acoplamento (classe F81) e o que impede as duas tools de estarem
certas sozinhas e erradas juntas.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

# Import de modulo no topo: e ele que dispara o @register_tool. Sem isto,
# `get_tool("remove_asset_link")` devolve None quando este arquivo roda sozinho.
from src.mcp.tools import remove_asset_link as mod
from src.mcp.tools._registry import get_tool


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


def test_tool_registrada_como_defer() -> None:
    t = get_tool("remove_asset_link")
    assert t is not None
    assert t.bucket == "defer"


def test_schema_aceita_o_resource_name_que_o_get_assets_devolve() -> None:
    """Acoplamento F81: o formato de um lado tem de ser aceito pelo outro."""
    t = get_tool("remove_asset_link")
    assert t is not None
    item = t.input_schema["properties"]["links"]["items"]
    assert set(item["required"]) == {"level", "resource_name"}
    assert set(item["properties"]["level"]["enum"]) == {"CUSTOMER", "CAMPAIGN", "AD_GROUP"}
    # o mesmo shape que get_assets emite em cada linha de `links`
    exemplo = {"level": "CAMPAIGN", "resource_name": "customers/1/campaignAssets/7~9~CALLOUT"}
    assert set(exemplo) >= set(item["required"])


def test_description_avisa_que_nao_remove_a_entidade() -> None:
    t = get_tool("remove_asset_link")
    assert t is not None
    assert "não remove o asset" in t.description.lower() or "nao remove o asset" in (
        t.description.lower()
    )


@pytest.mark.asyncio
async def test_devolve_preview_com_token_e_nunca_aplica_direto(monkeypatch) -> None:
    """Always-CONFIRM: nao ha caminho AUTO nesta tool."""

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        return "tok-123"

    class _FakeConn:
        async def __aenter__(self) -> Any:
            return self

        async def __aexit__(self, *a: Any) -> None:
            return None

    class _FakePool:
        def acquire(self) -> Any:
            return _FakeConn()

    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(mod, "create_pending", _create_pending)

    r = await mod.remove_asset_link(
        {
            "customer_id": "1234567890",
            "links": [
                {
                    "level": "CAMPAIGN",
                    "resource_name": "customers/1234567890/campaignAssets/7~9~CALLOUT",
                }
            ],
        }
    )
    # `preview_envelope` devolve status "dry_run" — verificado em
    # src/mcp/tools/_mutate_common.py. Se este teste falhar dizendo "preview",
    # o erro esta no teste, NAO no envelope: nao monte envelope a mao.
    assert r["status"] == "dry_run"
    assert r["confirmation_token"] == "tok-123"
    assert r["expires_in_minutes"] > 0, "TTL vem de DEFAULT_TTL_MINUTES"
    assert "applied_count" not in r


def test_classify_tem_branch_proprio_e_nao_cai_no_fallback() -> None:
    from src.governance.blast_radius import RiskLevel, classify

    r = classify(operation="remove_asset_link", params={"target_count": 3})
    assert r.level is RiskLevel.CONFIRM
    assert "unknown" not in r.reason.lower(), "caiu no fallback — falta o branch explicito"
    assert "3" in r.reason
