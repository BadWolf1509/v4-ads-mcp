"""`remove_asset_link` — always-CONFIRM, e o `resource_name` vem do `get_assets`.

O teste de acoplamento (classe F81) e o que impede as duas tools de estarem
certas sozinhas e erradas juntas.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from jsonschema import validate

# Import de modulo no topo: e ele que dispara o @register_tool. Sem isto,
# `get_tool("remove_asset_link")` devolve None quando este arquivo roda sozinho.
from src.google_ads.queries.assets import (
    parse_ad_group_asset_row,
    parse_campaign_asset_row,
    parse_customer_asset_row,
)
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
    """Acoplamento F81: o formato de um lado tem de ser aceito pelo outro.

    Fix round 1: a versao anterior validava contra um literal `exemplo`
    copiado a mao — as duas tools so concordavam porque a mesma string tinha
    sido digitada duas vezes. Este teste roda as linhas pelos parsers REAIS
    de `src/google_ads/queries/assets.py` (as tres camadas) e valida a saida
    contra o schema real de `remove_asset_link`, entao ele pega drift de
    qualquer lado: campo renomeado ou literal de level trocado.
    """
    t = get_tool("remove_asset_link")
    assert t is not None
    item = t.input_schema["properties"]["links"]["items"]
    assert set(item["required"]) == {"level", "resource_name"}
    assert set(item["properties"]["level"]["enum"]) == {"CUSTOMER", "CAMPAIGN", "AD_GROUP"}

    row_customer = SimpleNamespace(
        customer_asset=SimpleNamespace(
            resource_name="customers/1/customerAssets/9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="X"),
    )
    row_campaign = SimpleNamespace(
        campaign_asset=SimpleNamespace(
            resource_name="customers/1/campaignAssets/7~9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="X"),
        campaign=SimpleNamespace(id=7, name="JPA"),
    )
    row_ad_group = SimpleNamespace(
        ad_group_asset=SimpleNamespace(
            resource_name="customers/1/adGroupAssets/5~9~CALLOUT",
            field_type=SimpleNamespace(name="CALLOUT"),
            status=SimpleNamespace(name="ENABLED"),
            primary_status=SimpleNamespace(name="ELIGIBLE"),
            primary_status_reasons=[],
        ),
        asset=SimpleNamespace(id=9, name="X"),
        campaign=SimpleNamespace(id=7, name="JPA"),
        ad_group=SimpleNamespace(id=5, name="AG-1"),
    )

    for parser, row in (
        (parse_customer_asset_row, row_customer),
        (parse_campaign_asset_row, row_campaign),
        (parse_ad_group_asset_row, row_ad_group),
    ):
        emitido = parser(row)
        exemplo = {"level": emitido["level"], "resource_name": emitido["resource_name"]}
        validate(exemplo, item)


def test_description_avisa_que_nao_remove_a_entidade() -> None:
    t = get_tool("remove_asset_link")
    assert t is not None
    assert "não remove o asset" in t.description.lower() or "nao remove o asset" in (
        t.description.lower()
    )


@pytest.mark.asyncio
async def test_devolve_preview_com_token_e_nunca_aplica_direto(monkeypatch) -> None:
    """Always-CONFIRM: nao ha caminho AUTO nesta tool.

    Fix round 1: o fake de `create_pending` agora CAPTURA os kwargs em vez de
    descarta-los. `operation_type` e a UNICA coisa que roteia esta tool pro
    builder certo (`build_remove_asset_link`, Task 4) — errado, o dispatch
    iria pro builder errado (ex: `remove_audience`, de onde este arquivo foi
    adaptado) e nenhuma asserção anterior notaria.
    """
    capturado: dict[str, Any] = {}

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        capturado.update(kwargs)
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

    links = [
        {
            "level": "CAMPAIGN",
            "resource_name": "customers/1234567890/campaignAssets/7~9~CALLOUT",
        }
    ]
    r = await mod.remove_asset_link({"customer_id": "1234567890", "links": links})
    # `preview_envelope` devolve status "dry_run" — verificado em
    # src/mcp/tools/_mutate_common.py. Se este teste falhar dizendo "preview",
    # o erro esta no teste, NAO no envelope: nao monte envelope a mao.
    assert r["status"] == "dry_run"
    assert r["confirmation_token"] == "tok-123"
    assert r["expires_in_minutes"] > 0, "TTL vem de DEFAULT_TTL_MINUTES"
    assert "applied_count" not in r

    # operation_type e a chave de roteamento: errar aqui despacha pro builder
    # errado sem que nenhuma asserção de envelope acima note a diferença.
    assert capturado["operation_type"] == "remove_asset_link"
    assert capturado["payload"]["links"] == links
    assert capturado["payload"]["__partial_failure__"] is True
    assert capturado["customer_id"] == "1234567890"


def test_classify_tem_branch_proprio_e_nao_cai_no_fallback() -> None:
    from src.governance.blast_radius import RiskLevel, classify

    r = classify(operation="remove_asset_link", params={"target_count": 3})
    assert r.level is RiskLevel.CONFIRM
    assert "unknown" not in r.reason.lower(), "caiu no fallback — falta o branch explicito"
    assert "3" in r.reason


def _boom_get_pool() -> Any:
    """Pre-flight tem que barrar ANTES de tocar o banco — se isto for chamado,
    o par invalido escapou do pre-flight e chegou a mintar token."""
    raise AssertionError("nao deveria mintar token com par level/resource_name invalido")


@pytest.mark.asyncio
async def test_rejeita_level_incompativel_com_resource_name(monkeypatch) -> None:
    """`level` escolhe o campo da operacao no builder; `resource_name` e'
    copiado verbatim. Um par que nao bate monta uma operacao valida que o
    Google rejeita POR OPERACAO — com `__partial_failure__: True` isso nunca
    levanta, e `apply_change` descarta `partial_failures`, entao o gestor veria
    status: "applied" com applied_count: 0 e nenhum motivo. O pre-flight tem
    que barrar antes de mintar o token."""
    monkeypatch.setattr(mod.connection, "get_pool", _boom_get_pool)
    links = [
        {
            "level": "CUSTOMER",
            "resource_name": "customers/1234567890/campaignAssets/7~9~CALLOUT",
        }
    ]
    r = await mod.remove_asset_link({"customer_id": "1234567890", "links": links})
    assert r["status"] == "error"
    assert r["operation"] == "remove_asset_link"
    assert "links[0]" in r["error_message"]
    assert "CUSTOMER" in r["error_message"]
    assert "customers/1234567890/campaignAssets/7~9~CALLOUT" in r["error_message"]


@pytest.mark.asyncio
async def test_rejeita_resource_name_de_outra_conta(monkeypatch) -> None:
    """resource_name com customer_id diferente do argumento — mesma familia do
    mismatch de level, mas no segmento de conta em vez do de nivel."""
    monkeypatch.setattr(mod.connection, "get_pool", _boom_get_pool)
    links = [
        {
            "level": "CAMPAIGN",
            "resource_name": "customers/9999999999/campaignAssets/7~9~CALLOUT",
        }
    ]
    r = await mod.remove_asset_link({"customer_id": "1234567890", "links": links})
    assert r["status"] == "error"
    assert "links[0]" in r["error_message"]
    assert "1234567890" in r["error_message"]
    assert "9999999999" in r["error_message"]


@pytest.mark.asyncio
async def test_segundo_link_invalido_e_apontado_pelo_indice(monkeypatch) -> None:
    """O primeiro link e' valido; so o segundo (indice 1) tem o mismatch — a
    mensagem tem que apontar o indice certo, nao só "algum link esta errado"."""
    monkeypatch.setattr(mod.connection, "get_pool", _boom_get_pool)
    links = [
        {"level": "CAMPAIGN", "resource_name": "customers/1234567890/campaignAssets/7~9~CALLOUT"},
        {"level": "AD_GROUP", "resource_name": "customers/1234567890/campaignAssets/7~9~CALLOUT"},
    ]
    r = await mod.remove_asset_link({"customer_id": "1234567890", "links": links})
    assert r["status"] == "error"
    assert "links[1]" in r["error_message"]
    assert "links[0]" not in r["error_message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("nivel", "resource_name"),
    [
        ("CUSTOMER", "customers/1234567890/customerAssets/9~CALLOUT"),
        ("CAMPAIGN", "customers/1234567890/campaignAssets/7~9~CALLOUT"),
        ("AD_GROUP", "customers/1234567890/adGroupAssets/5~9~CALLOUT"),
    ],
)
async def test_par_correto_ainda_minta_token_em_cada_nivel(
    monkeypatch, nivel: str, resource_name: str
) -> None:
    """Guard de regressao: o pre-flight novo nao pode bloquear o caminho feliz
    em NENHUM dos tres niveis."""

    async def _create_pending(conn: Any, **kwargs: Any) -> str:
        return "tok-ok"

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
            "links": [{"level": nivel, "resource_name": resource_name}],
        }
    )
    assert r["status"] == "dry_run"
    assert r["confirmation_token"] == "tok-ok"
