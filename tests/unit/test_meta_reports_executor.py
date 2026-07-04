"""Unit tests for run_meta_graph_get happy path + error path (Task 3.3+3.4).

O executor Meta (src/meta_ads/reports.py::run_meta_graph_get) tinha ZERO
testes cobrindo o caminho feliz e o caminho de erro do proprio Graph API call
antes desta task — só o hard-gate (test_meta_reports_gate.py) e o log de
negacao (test_meta_denial_log.py) eram cobertos.

Padrao de fake: um objeto minimo com .json() + .headers() reais (NAO MagicMock
cru) para que asserts sobre o parse do body/headers sejam significativos —
MagicMock aceitaria qualquer atributo e mascararia bugs de parsing (mesma
razao pela qual builder tests de proto usam make_capture_client em vez de
MagicMock, ver CLAUDE.md).

api.call(...) e mockado via patch("src.meta_ads.reports.build_meta_api", ...)
— o unico call site permitido pra build_meta_api e reports.py (F57-Meta).
"""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.meta_ads import reports
from src.meta_ads.errors import MetaAdsFriendlyError


@dataclass
class _FakeGraphResponse:
    """Fake FacebookResponse — só o que run_meta_graph_get consome.

    .json() e .headers() espelham a API real (facebook_business.api.FacebookResponse):
    json() faz json.loads no corpo, headers() devolve o dict cru.
    """

    _body: dict[str, Any]
    _headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        return self._body

    def headers(self) -> dict[str, str]:
        return self._headers


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


@pytest.mark.asyncio
async def test_run_meta_graph_get_happy_path_parses_and_audits() -> None:
    """Api fake devolve data + BUC header + x-fb-trace-id.

    Assert: body parseado corretamente, audit_log.record chamado com
    status=success + o trace-id certo, record_actual_meta chamado com o
    ad_account_id certo (kwarg, não mais lido de params — Task 3.4).
    """
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    fake_body = {"data": [{"campaign_id": "123", "spend": "10.5"}]}
    fake_response = _FakeGraphResponse(
        _body=fake_body,
        _headers={
            "x-fb-trace-id": "trace-abc-123",
            "x-business-use-case-usage": '{"999": [{"call_count": 5}]}',
        },
    )
    fake_api = MagicMock()
    fake_api.call = MagicMock(return_value=fake_response)

    mock_audit_record = AsyncMock(return_value=1)
    mock_record_actual_meta = AsyncMock()

    with (
        patch("src.meta_ads.reports.connection.get_pool", return_value=fake_pool),
        patch(
            "src.meta_ads.reports.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch("src.meta_ads.reports.build_meta_api", return_value=fake_api),
        patch("src.meta_ads.reports.audit_log.record", mock_audit_record),
        patch("src.meta_ads.reports.record_actual_meta", mock_record_actual_meta),
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

    # api.call recebeu o edge (sem barra inicial) + params repassados intactos
    fake_api.call.assert_called_once_with(
        "GET", ["act_999/insights"], params={"level": "campaign", "fields": "spend,campaign_id"}
    )

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

    fake_response = _FakeGraphResponse(
        _body={"data": []},
        _headers={"x-business-use-case-usage": '{"111": [{"call_count": 3}]}'},
    )
    fake_api = MagicMock()
    fake_api.call = MagicMock(return_value=fake_response)
    mock_record_actual_meta = AsyncMock()

    with (
        patch("src.meta_ads.reports.connection.get_pool", return_value=fake_pool),
        patch(
            "src.meta_ads.reports.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch("src.meta_ads.reports.build_meta_api", return_value=fake_api),
        patch("src.meta_ads.reports.record_actual_meta", mock_record_actual_meta),
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
    """Sem header BUC (edge não-insights, por ex.) → record_actual_meta NÃO chamado."""
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    fake_response = _FakeGraphResponse(_body={"data": []}, _headers={})
    fake_api = MagicMock()
    fake_api.call = MagicMock(return_value=fake_response)
    mock_record_actual_meta = AsyncMock()

    with (
        patch("src.meta_ads.reports.connection.get_pool", return_value=fake_pool),
        patch(
            "src.meta_ads.reports.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch("src.meta_ads.reports.build_meta_api", return_value=fake_api),
        patch("src.meta_ads.reports.record_actual_meta", mock_record_actual_meta),
    ):
        await reports.run_meta_graph_get(
            manager_id=mid,
            session_id=sid,
            ad_account_id="act_111",
            edge="/me/adaccounts",
            params={},
            operation_name="meta_list_my_ad_accounts",
        )

    mock_record_actual_meta.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_meta_graph_get_error_path_maps_friendly_and_audits() -> None:
    """api.call levanta → to_friendly_meta_error + audit_log.record status=error."""
    mid, sid = uuid4(), uuid4()
    fake_pool = _patch_allowed_pool()

    fake_api = MagicMock()
    fake_api.call = MagicMock(side_effect=RuntimeError("boom"))

    mock_audit_record = AsyncMock(return_value=1)

    with (
        patch("src.meta_ads.reports.connection.get_pool", return_value=fake_pool),
        patch(
            "src.meta_ads.reports.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch("src.meta_ads.reports.build_meta_api", return_value=fake_api),
        patch("src.meta_ads.reports.audit_log.record", mock_audit_record),
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

    # RuntimeError genérico não é FacebookRequestError → to_friendly_meta_error
    # cai no fallback "Erro inesperado: {e}".
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

    fake_api = MagicMock()
    fake_api.call = MagicMock(side_effect=RuntimeError("boom"))
    mock_audit_record = AsyncMock()

    with (
        patch("src.meta_ads.reports.connection.get_pool", return_value=fake_pool),
        patch(
            "src.meta_ads.reports.manager_meta_account_access.can_manager_access",
            AsyncMock(return_value=True),
        ),
        patch("src.meta_ads.reports.build_meta_api", return_value=fake_api),
        patch("src.meta_ads.reports.audit_log.record", mock_audit_record),
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
