"""M3: `list_gaql_resources(resource=...)` devolve selectable_with do GoogleAdsFieldService.

O fake do servico tem o formato real: `search_google_ads_fields(query=...)` devolve um
iteravel (pager) de objetos GoogleAdsField-like com `.name` e `.selectable_with`.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads import campos_gaql
from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools.list_gaql_resources import _SCHEMA, list_gaql_resources


@pytest.fixture(autouse=True)
def _ctx_e_cache():
    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    campos_gaql.limpar_cache()
    _GATE_TOOL.reset_mock(side_effect=True)
    _GATE_CAMPOS.reset_mock(side_effect=True)
    _BEFORE_CALL.reset_mock()
    _RECORD_ACTUAL.reset_mock()
    yield
    campos_gaql.limpar_cache()
    clear_current()


_GATE_TOOL = AsyncMock(return_value=None)
_GATE_CAMPOS = AsyncMock(return_value=None)
_BEFORE_CALL = AsyncMock()
_RECORD_ACTUAL = AsyncMock()
CID = "1234567890"


async def _run_reconnect(fn):
    return await fn(AsyncMock())


def _pool() -> MagicMock:
    conn = AsyncMock()
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=txn)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.acquire.return_value = cm
    return pool


def _client(servico: MagicMock) -> MagicMock:
    client = MagicMock()
    client.get_service.return_value = servico
    return client


def _servico_ok() -> MagicMock:
    servico = MagicMock()
    servico.search_google_ads_fields.return_value = iter(
        [
            SimpleNamespace(
                name="keyword_view",
                selectable_with=[
                    "segments.date",
                    "metrics.clicks",
                    "ad_group",
                    "campaign",
                    "segments.device",
                ],
            )
        ]
    )
    return servico


def _patches(servico: MagicMock, audit: AsyncMock | None = None):
    return (
        patch(
            "src.google_ads.campos_gaql.build_client_for_manager",
            AsyncMock(return_value=_client(servico)),
        ),
        patch("src.mcp.tools.list_gaql_resources.ensure_account_access", _GATE_TOOL),
        patch("src.google_ads.campos_gaql.ensure_account_access", _GATE_CAMPOS),
        patch("src.mcp.tools.list_gaql_resources.connection.run_with_reconnect", _run_reconnect),
        patch("src.mcp.tools.list_gaql_resources.before_call", _BEFORE_CALL),
        patch("src.mcp.tools.list_gaql_resources.record_actual", _RECORD_ACTUAL),
        patch(
            "src.mcp.tools.list_gaql_resources.audit_log.record",
            audit or AsyncMock(return_value=1),
        ),
        patch("src.mcp.tools.list_gaql_resources.connection.get_pool", return_value=_pool()),
    )


async def _rodar(servico, args, audit=None):
    ps = _patches(servico, audit)
    for p in ps:
        p.start()
    try:
        return await list_gaql_resources(args)
    finally:
        for p in ps:
            p.stop()


@pytest.mark.asyncio
async def test_com_resource_compativel_preenchido():
    servico = _servico_ok()
    r = await _rodar(servico, {"resource": "keyword_view", "customer_id": CID})
    assert r["compativel"] == {
        "segments": ["segments.date", "segments.device"],
        "metrics": ["metrics.clicks"],
        "resources_atribuidos": ["ad_group", "campaign"],
    }
    assert r["fonte"] == "GoogleAdsFieldService v25"
    assert r["compativel_motivo"] is None
    assert "resources" in r and "segments" in r
    q = servico.search_google_ads_fields.call_args.kwargs["query"]
    assert q == "SELECT name, selectable_with WHERE name = 'keyword_view'"


@pytest.mark.asyncio
async def test_falha_compativel_null_com_motivo():
    servico = MagicMock()
    servico.search_google_ads_fields.side_effect = RuntimeError("boom")
    audit = AsyncMock(return_value=1)
    r = await _rodar(servico, {"resource": "keyword_view", "customer_id": CID}, audit)
    assert r["compativel"] is None
    assert r["compativel_motivo"]
    assert r["resources"]  # catalogo estatico segue la
    assert audit.call_args.kwargs["status"] == "error"
    # falha nao e cacheada
    assert campos_gaql.do_cache("keyword_view") is None


@pytest.mark.asyncio
async def test_resource_desconhecido_null_com_motivo():
    servico = MagicMock()
    servico.search_google_ads_fields.return_value = iter([])
    r = await _rodar(servico, {"resource": "nao_existe", "customer_id": CID})
    assert r["compativel"] is None
    assert "nao conhece" in r["compativel_motivo"]


@pytest.mark.asyncio
async def test_sem_resource_resposta_identica():
    from src.google_ads.queries.meta import RESOURCES, SEGMENTS

    esperado = {
        "resources": [
            {"name": n, "description": m["description"], "fields": m["fields"]}
            for n, m in RESOURCES.items()
        ],
        "segments": SEGMENTS,
    }
    servico = MagicMock()
    r = await _rodar(servico, {})
    assert r == esperado
    servico.search_google_ads_fields.assert_not_called()


@pytest.mark.asyncio
async def test_cache_uma_chamada():
    servico = _servico_ok()
    audit = AsyncMock(return_value=1)
    ps = _patches(servico, audit)
    for p in ps:
        p.start()
    try:
        a = await list_gaql_resources({"resource": "keyword_view", "customer_id": CID})
        # miss: reserva de cota projeto + gestor, e reconcilia as duas
        assert _BEFORE_CALL.await_count == 2
        assert _RECORD_ACTUAL.await_count == 2
        servico.search_google_ads_fields.return_value = iter([])  # 2a chamada nao deve usar
        b = await list_gaql_resources({"resource": "keyword_view", "customer_id": CID})
    finally:
        for p in ps:
            p.stop()
    assert servico.search_google_ads_fields.call_count == 1
    assert a["compativel"] == b["compativel"] is not None
    audit.assert_awaited_once()  # cache hit nao audita
    # cache hit nao reserva nem reconcilia cota: continua em 2 (so o miss)
    assert _BEFORE_CALL.await_count == 2
    assert _RECORD_ACTUAL.await_count == 2


@pytest.mark.asyncio
async def test_audit_registra_customer_id_real():
    servico = _servico_ok()
    audit = AsyncMock(return_value=1)
    await _rodar(servico, {"resource": "keyword_view", "customer_id": CID}, audit)
    kw = audit.call_args.kwargs
    assert kw["customer_id"] == CID
    assert kw["operation"] == "list_gaql_resources"
    assert kw["action_type"] == "read"


def test_schema_resource_string_simples():
    prop = _SCHEMA["properties"]["resource"]
    assert prop == {"type": "string", "pattern": "^[a-z_]+$"}
    assert _SCHEMA["additionalProperties"] is False


@pytest.mark.asyncio
async def test_resource_com_injecao_recusado_no_modulo():
    with pytest.raises(ValueError):
        await campos_gaql.compatibilidade(
            "x' OR name != '", manager_id=uuid4(), customer_id=CID, session_id=uuid4()
        )


@pytest.mark.asyncio
async def test_resource_sem_customer_id_recusado_antes_de_client():
    servico = MagicMock()
    r = await _rodar(servico, {"resource": "keyword_view"})
    assert "customer_id" in r["error"]
    assert "compativel" not in r
    servico.search_google_ads_fields.assert_not_called()
    _GATE_TOOL.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_negado_recusa_sem_chamar_google():
    from src.google_ads.access import AccountAccessDeniedError

    _GATE_TOOL.side_effect = AccountAccessDeniedError("sem acesso")
    servico = _servico_ok()
    with pytest.raises(AccountAccessDeniedError):
        await _rodar(servico, {"resource": "keyword_view", "customer_id": CID})
    servico.search_google_ads_fields.assert_not_called()


@pytest.mark.asyncio
async def test_cache_hit_ainda_chama_o_gate():
    servico = _servico_ok()
    ps = _patches(servico)
    for p in ps:
        p.start()
    try:
        await list_gaql_resources({"resource": "keyword_view", "customer_id": CID})
        await list_gaql_resources({"resource": "keyword_view", "customer_id": CID})
    finally:
        for p in ps:
            p.stop()
    assert servico.search_google_ads_fields.call_count == 1
    assert _GATE_TOOL.await_count == 2
