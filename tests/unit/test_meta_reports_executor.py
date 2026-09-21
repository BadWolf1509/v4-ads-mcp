"""Unit tests for run_meta_graph_get happy path + error path (Task 3.3+3.4).

O executor Meta (src/meta_ads/reports.py::run_meta_graph_get) tinha ZERO
testes cobrindo o caminho feliz e o caminho de erro do proprio Graph API call
antes desta task — só o hard-gate (test_meta_reports_gate.py) e o log de
negacao (test_meta_denial_log.py) eram cobertos.

F190/Task 3 (21/09): o transporte trocou do SDK facebook_business (mockado via
`build_meta_api`, que nem existe mais neste caminho) pra httpx com auth em
header. O fake daqui era um objeto minimo escrito a mao com `.json()`/
`.headers()` — motivado por NAO usar MagicMock cru (mesma razao pela qual
builder tests de proto usam make_capture_client, ver CLAUDE.md). Com
`httpx.MockTransport` a resposta que o handler devolve e um `httpx.Response`
DE VERDADE: o parsing de JSON/headers agora e real, nao um substituto — a
mesma motivação original, só que mais forte.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from src.meta_ads import reports
from src.meta_ads.client import MetaSystemUserTokenMissingError
from src.meta_ads.errors import MetaAdsFriendlyError


class _FakeAcquire:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def __aenter__(self) -> Any:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(self._conn)


def _patch_allowed_pool() -> _FakePool:
    """Pool fake — usado tanto pro hard-gate quanto pro audit_log.record."""
    return _FakePool(MagicMock())


def _cliente_httpx(handler: Any) -> httpx.AsyncClient:
    """Client httpx real, falando com um `MockTransport` — nao MagicMock cru."""
    transporte = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transporte, timeout=reports._TIMEOUT_GRAPH)


@pytest.mark.asyncio
async def test_run_meta_graph_get_happy_path_parses_and_audits() -> None:
    """Handler fake devolve data + BUC header + x-fb-trace-id.

    Assert: body parseado corretamente, requisicao foi pro edge certo com auth
    em header (nunca na URL — F82/F190), audit_log.record chamado com
    status=success + o trace-id certo, record_actual_meta chamado com o
    ad_account_id certo (kwarg, não mais lido de params — Task 3.4).
    """
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    fake_body = {"data": [{"campaign_id": "123", "spend": "10.5"}]}
    vistos: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vistos.append(request)
        return httpx.Response(
            200,
            json=fake_body,
            headers={
                "x-fb-trace-id": "trace-abc-123",
                "x-business-use-case-usage": '{"999": [{"call_count": 5}]}',
            },
        )

    mock_audit_record = AsyncMock(return_value=1)
    mock_record_actual_meta = AsyncMock()

    with (
        patch.object(reports.connection, "get_pool", return_value=fake_pool),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=_cliente_httpx(handler))),
        patch.object(reports.audit_log, "record", mock_audit_record),
        patch.object(reports, "record_actual_meta", mock_record_actual_meta),
    ):
        result = await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            ad_account_id="act_999",
            edge="/act_999/insights",
            params={"level": "campaign", "fields": "spend,campaign_id"},
            operation_name="meta_get_campaign_performance",
            audit_this_call=True,
            params_summary={"ad_account_id": "act_999", "level": "campaign"},
        )

    # Body parseado corretamente
    assert result == fake_body

    # Exatamente 1 requisicao, pro edge certo, com os params repassados
    # intactos e o token no HEADER — nunca na URL (F82/F190).
    assert len(vistos) == 1
    req = vistos[0]
    assert req.url.path == "/v22.0/act_999/insights"
    assert dict(req.url.params) == {"level": "campaign", "fields": "spend,campaign_id"}
    assert "access_token" not in str(req.url)
    assert req.headers.get("authorization", "").startswith("Bearer ")

    # audit_log.record: status success + trace-id do header
    mock_audit_record.assert_awaited_once()
    audit_kwargs = mock_audit_record.call_args.kwargs
    assert audit_kwargs["status"] == "success"
    assert audit_kwargs["manager_id"] == mid
    assert audit_kwargs["session_id"] == sid
    assert audit_kwargs["platform"] == "meta"
    assert audit_kwargs["provider_request_id"] == "trace-abc-123"
    assert audit_kwargs["target_count"] == 1  # len(body["data"])

    # record_actual_meta: ad_account_id vem do KWARG (não de params) — Task 3.4
    mock_record_actual_meta.assert_awaited_once()
    rate_kwargs = mock_record_actual_meta.call_args.kwargs
    assert rate_kwargs["ad_account_id"] == "act_999"
    assert rate_kwargs["buc_header"] == '{"999": [{"call_count": 5}]}'
    assert rate_kwargs["calls"] == 1


@pytest.mark.asyncio
async def test_run_meta_graph_get_records_buc_even_without_ad_account_id_in_params() -> None:
    """Task 3.4 regression: o dict `params` NÃO precisa mais conter ad_account_id
    pro rate counter BUC funcionar — o gravador usa o kwarg obrigatório. Antes
    (`if "ad_account_id" in params`), esta chamada teria SILENCIOSAMENTE pulado
    o rate counter; agora grava normalmente."""
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": []},
            headers={"x-business-use-case-usage": '{"111": [{"call_count": 3}]}'},
        )

    mock_record_actual_meta = AsyncMock()

    with (
        patch.object(reports.connection, "get_pool", return_value=fake_pool),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=_cliente_httpx(handler))),
        patch.object(reports, "record_actual_meta", mock_record_actual_meta),
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            ad_account_id="act_111",
            edge="/act_111/insights",
            # params SEM a chave ad_account_id (formato pós Task 3.4 de build_insights_call)
            params={"level": "campaign", "fields": "spend"},
            operation_name="meta_get_campaign_performance",
        )

    mock_record_actual_meta.assert_awaited_once()
    assert mock_record_actual_meta.call_args.kwargs["ad_account_id"] == "act_111"


@pytest.mark.asyncio
async def test_run_meta_graph_get_skips_rate_counter_when_buc_header_absent() -> None:
    """Resposta sem o header BUC (edge fora de /insights, por ex.) → record_actual_meta NÃO chamado."""
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    mock_record_actual_meta = AsyncMock()

    with (
        patch.object(reports.connection, "get_pool", return_value=fake_pool),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=_cliente_httpx(handler))),
        patch.object(reports, "record_actual_meta", mock_record_actual_meta),
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            ad_account_id="act_111",
            # F190/Task 4: era "/me/adaccounts" — edge que não contém a conta
            # gateada, par que só passava porque nada amarrava os dois (ver
            # test_edge_divergente_do_ad_account_gateado_e_recusado). O ponto
            # deste teste é a ausência do header BUC, não a forma do edge — o
            # handler acima não devolve o header independente de qual edge é.
            edge="/act_111/insights",
            params={},
            operation_name="meta_get_campaign_performance",
        )

    mock_record_actual_meta.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_meta_graph_get_error_path_maps_friendly_and_audits() -> None:
    """Falha de transporte → to_friendly_meta_error + audit_log.record status=error."""
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    mock_audit_record = AsyncMock(return_value=1)

    with (
        patch.object(reports.connection, "get_pool", return_value=fake_pool),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=_cliente_httpx(handler))),
        patch.object(reports.audit_log, "record", mock_audit_record),
        pytest.raises(MetaAdsFriendlyError) as excinfo,
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            ad_account_id="act_999",
            edge="/act_999/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
            audit_this_call=True,
            params_summary={"ad_account_id": "act_999"},
        )

    # RuntimeError genérico não é FacebookRequestError nem MetaGraphHTTPError →
    # to_friendly_meta_error cai no fallback "Erro inesperado: {e}".
    assert "Erro inesperado" in excinfo.value.message

    mock_audit_record.assert_awaited_once()
    audit_kwargs = mock_audit_record.call_args.kwargs
    assert audit_kwargs["status"] == "error"
    assert audit_kwargs["manager_id"] == mid
    assert audit_kwargs["session_id"] == sid
    assert audit_kwargs["platform"] == "meta"
    assert "Erro inesperado" in audit_kwargs["error_message"]


@pytest.mark.asyncio
async def test_run_meta_graph_get_error_path_without_audit_opt_in_skips_audit() -> None:
    """audit_this_call=False (default) no error path → audit_log.record NÃO chamado
    (diferente da negação de acesso, que sempre audita — este é erro de API, não
    security event)."""
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("boom")

    mock_audit_record = AsyncMock()

    with (
        patch.object(reports.connection, "get_pool", return_value=fake_pool),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch.object(reports.httpx, "AsyncClient", MagicMock(return_value=_cliente_httpx(handler))),
        patch.object(reports.audit_log, "record", mock_audit_record),
        pytest.raises(MetaAdsFriendlyError),
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            ad_account_id="act_999",
            edge="/act_999/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
            # audit_this_call não passado → default False
        )

    mock_audit_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_meta_graph_get_raises_when_system_user_token_missing() -> None:
    """F190/Task 6: `if not token: raise MetaSystemUserTokenMissingError` migrou
    de `build_meta_api` (Task 3) pro executor e ficou sem teste equivalente — o
    antigo cobria o construtor, que não existe mais neste caminho
    (`test_meta_client.py::test_build_meta_api_raises_when_system_user_token_empty`,
    removido na mesma task que apagou `build_meta_api` de `client.py`). Preserva
    a cobertura apontando pro executor real (`reports.py:218-223`), depois do
    hard-gate (`can_manager_access`) e da checagem edge/ad_account_id — as duas
    têm que passar pra este caminho ser exercitado, senão o teste provaria outra
    coisa.
    """
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    settings_sem_token = MagicMock()
    settings_sem_token.meta_system_user_token = ""

    with (
        patch.object(reports, "get_settings", MagicMock(return_value=settings_sem_token)),
        patch.object(reports.connection, "get_pool", return_value=fake_pool),
        patch.object(
            reports.manager_meta_account_access,
            "can_manager_access",
            AsyncMock(return_value=True),
        ),
        pytest.raises(MetaSystemUserTokenMissingError),
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            ad_account_id="act_999",
            edge="/act_999/insights",
            params={"level": "campaign"},
            operation_name="meta_get_campaign_performance",
        )
