"""Test contextual hints in validate_gaql error messages (B2+B3 dogfood MO-JP).

B2: FROM change_event + LAST_30_DAYS rejection ("too old") -> hint about
    30-day inclusive window + suggest LAST_14_DAYS.
B3: segments.conversion_action + metrics.cost_micros conflict -> hint about
    splitting into 2 queries.

Task 1.3 (post reports.py 'reserved' refactor, commit 510cd9d): validate_gaql
ganhou rate-limit no mesmo padrao de run_report (before_call duplo global +
mgr:<uuid> em transacao externa; record_actual SO se reserved) + audit sempre
(sucesso, erro de validacao, e QuotaExhausted). Testes abaixo cobrem esse
envelope; os de cima (B2/B3) seguem testando so a funcao pura _augment_error_hint.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.mcp.context import McpRequestContext, clear_current, set_current
from src.mcp.tools.validate_gaql import _augment_error_hint

# ---------- B2: change_event 30-day window ----------


def test_b2_change_event_too_old_adds_hint():
    """FROM change_event + error mentioning 'too old' should append window hint."""
    query = (
        "SELECT change_event.change_date_time, change_event.user_email "
        "FROM change_event WHERE change_event.change_date_time DURING LAST_30_DAYS"
    )
    msg = (
        "Google Ads retornou: The requested start date is too old. It cannot be older than 30 days."
    )
    result = _augment_error_hint(query, msg)
    assert "change_event" in result.lower()
    assert "30 dias" in result or "30d" in result
    # Original message preserved
    assert "too old" in result.lower()


def test_b2_change_event_30_days_phrase_also_triggers():
    """Variant phrasing 'cannot be older than 30 days' should also trigger."""
    query = "SELECT change_event.change_date_time FROM change_event WHERE ... DURING LAST_30_DAYS"
    msg = "Erro: It cannot be older than 30 days."
    result = _augment_error_hint(query, msg)
    assert result != msg  # hint was appended
    assert "LAST_14_DAYS" in result or "14" in result


def test_b2_no_hint_when_query_doesnt_use_change_event():
    """Same 'too old' error on different resource shouldn't trigger change_event hint."""
    query = "SELECT campaign.id FROM campaign WHERE segments.date DURING LAST_30_DAYS"
    msg = "Google Ads retornou: The requested start date is too old."
    result = _augment_error_hint(query, msg)
    # No change_event-specific hint
    assert "change_event tem janela" not in result


def test_b2_no_hint_when_error_unrelated_to_window():
    """change_event query with unrelated error shouldn't get B2 hint."""
    query = "SELECT change_event.invalid_field FROM change_event"
    msg = "Field 'change_event.invalid_field' does not exist."
    result = _augment_error_hint(query, msg)
    assert "change_event tem janela" not in result


# ---------- B3: segments.conversion_action + metrics.cost_micros ----------


def test_b3_conversion_action_with_cost_micros_adds_hint():
    """Query selecting both segments.conversion_action and metrics.cost_micros should trigger hint."""
    query = (
        "SELECT segments.conversion_action, segments.conversion_action_name, "
        "metrics.conversions, metrics.cost_micros FROM campaign "
        "WHERE campaign.id IN (123)"
    )
    msg = (
        "Cannot select the following segments because at least one unsupported metric "
        "is found in SELECT or WHERE clause: 'segments.conversion_action' "
        "(unsupported metrics: 'cost_micros')."
    )
    result = _augment_error_hint(query, msg)
    assert "2 queries" in result.lower() or "duas queries" in result.lower()
    assert "cost_micros" in result.lower()
    # Original message preserved
    assert "unsupported metric" in result.lower()


def test_b3_conversion_action_name_variant_triggers():
    """segments.conversion_action_name variant should also trigger."""
    query = "SELECT segments.conversion_action_name, metrics.cost_micros FROM campaign WHERE ..."
    msg = "unsupported metrics: 'cost_micros'"
    result = _augment_error_hint(query, msg)
    assert result != msg


def test_b3_no_hint_when_only_segments_no_cost_micros():
    """Query with segments.conversion_action only (no cost_micros) shouldn't trigger B3."""
    query = "SELECT segments.conversion_action, metrics.conversions FROM campaign"
    msg = "Some other error."
    result = _augment_error_hint(query, msg)
    assert "2 queries" not in result.lower()


def test_b3_no_hint_when_only_cost_micros_no_segments():
    """Query with metrics.cost_micros only (no segments.conversion_action) shouldn't trigger."""
    query = "SELECT campaign.id, metrics.cost_micros FROM campaign"
    msg = "Some unrelated error."
    result = _augment_error_hint(query, msg)
    assert "2 queries" not in result.lower()


def test_b3_no_hint_when_error_unrelated():
    """Both fields present but error not about unsupported metric -> no hint."""
    query = "SELECT segments.conversion_action, metrics.cost_micros FROM campaign"
    msg = "Some random syntax error."
    result = _augment_error_hint(query, msg)
    assert "2 queries" not in result.lower()


# ---------- Cross-cutting ----------


def test_returns_original_message_when_no_pattern_matches():
    """Generic error on generic query should return original unchanged."""
    query = "SELECT campaign.id FROM campaign"
    msg = "Some random error."
    result = _augment_error_hint(query, msg)
    assert result == msg


def test_case_insensitive_query_detection():
    """Query patterns matched case-insensitively (handles SELECT/select, FROM/from)."""
    query = "select change_event.change_date_time from CHANGE_EVENT where ... during LAST_30_DAYS"
    msg = "The requested start date is too old."
    result = _augment_error_hint(query, msg)
    assert "change_event" in result.lower() and "30 dias" in result


def test_empty_query_returns_message_unchanged():
    result = _augment_error_hint("", "any error")
    assert result == "any error"


def test_empty_message_returns_empty():
    result = _augment_error_hint("SELECT campaign.id FROM campaign", "")
    assert result == ""


# ---------- Task 1.3: rate-limit (padrao 'reserved') + audit sempre ----------


@pytest.fixture
def bound_context():
    ctx = McpRequestContext(manager_id=uuid4(), session_id=uuid4())
    set_current(ctx)
    yield ctx
    clear_current()


def _pool_with_conn() -> tuple[MagicMock, AsyncMock]:
    """Mirrors test_run_report_quota_reserve.py's _pool_with_conn: pool.acquire()
    yields a fake conn whose .transaction() is a real async context manager."""
    fake_conn = AsyncMock()
    fake_txn_cm = MagicMock()
    fake_txn_cm.__aenter__ = AsyncMock(return_value=None)
    fake_txn_cm.__aexit__ = AsyncMock(return_value=None)
    fake_conn.transaction = MagicMock(return_value=fake_txn_cm)

    mock_pool = MagicMock()
    mock_acquire_cm = MagicMock()
    mock_acquire_cm.__aenter__ = AsyncMock(return_value=fake_conn)
    mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire_cm
    return mock_pool, fake_conn


def _common_patches(
    *, before_call_mock: AsyncMock, record_actual_mock: AsyncMock, audit_mock: AsyncMock
):
    mock_pool, _ = _pool_with_conn()
    return [
        patch("src.mcp.tools.validate_gaql.ensure_account_access", AsyncMock(return_value=None)),
        patch("src.mcp.tools.validate_gaql.before_call", before_call_mock),
        patch("src.mcp.tools.validate_gaql.record_actual", record_actual_mock),
        patch("src.mcp.tools.validate_gaql.audit_log.record", audit_mock),
        patch("src.mcp.tools.validate_gaql.connection.get_pool", return_value=mock_pool),
    ]


def _fake_client_valid() -> MagicMock:
    client = MagicMock()
    fake_service = MagicMock()
    fake_service.search = MagicMock(return_value=iter([]))
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(return_value=MagicMock())
    return client


def _fake_client_invalid(error: Exception) -> MagicMock:
    client = MagicMock()
    fake_service = MagicMock()
    fake_service.search = MagicMock(side_effect=error)
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(return_value=MagicMock())
    return client


@pytest.mark.asyncio
async def test_validate_gaql_quota_exhausted_returns_friendly_error_and_skips_record_actual(
    bound_context,
):
    """QuotaExhausted no before_call (reserva) -> validate_gaql NAO propaga a
    excecao pro caller MCP; retorna erro amigavel no mesmo shape {valid, error}.
    record_actual nao deve ser chamado (sem reserva persistida)."""
    from src.governance.rate_limit import QuotaExhausted
    from src.mcp.tools.validate_gaql import validate_gaql

    before_call_mock = AsyncMock(side_effect=QuotaExhausted("quota diaria esgotada"))
    record_actual_mock = AsyncMock()
    audit_mock = AsyncMock(return_value=1)

    patches = _common_patches(
        before_call_mock=before_call_mock,
        record_actual_mock=record_actual_mock,
        audit_mock=audit_mock,
    )
    for p in patches:
        p.start()
    try:
        result = await validate_gaql(
            {
                "customer_id": "1234567890",
                "query": "SELECT customer.id FROM customer",
            }
        )
    finally:
        for p in patches:
            p.stop()

    assert result["valid"] is False
    assert "quota" in result["error"].lower()
    record_actual_mock.assert_not_awaited()
    audit_mock.assert_awaited_once()
    assert audit_mock.call_args.kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_validate_gaql_success_audits_with_query_and_valid_true_and_records_actual_twice(
    bound_context,
):
    """Sucesso: before_call 2x (global + mgr:<uuid>), record_actual 2x, e audit
    SEMPRE chamado com params_summary={'query':..., 'valid': True} status=success."""
    from src.config import get_settings
    from src.mcp.tools.validate_gaql import validate_gaql

    before_call_mock = AsyncMock()
    record_actual_mock = AsyncMock()
    audit_mock = AsyncMock(return_value=1)

    patches = _common_patches(
        before_call_mock=before_call_mock,
        record_actual_mock=record_actual_mock,
        audit_mock=audit_mock,
    )
    query = "SELECT customer.id FROM customer"
    for p in patches:
        p.start()
    try:
        with patch(
            "src.mcp.tools.validate_gaql.build_client_for_manager",
            AsyncMock(return_value=_fake_client_valid()),
        ):
            result = await validate_gaql({"customer_id": "1234567890", "query": query})
    finally:
        for p in patches:
            p.stop()

    assert result["valid"] is True

    settings = get_settings()
    manager_id = bound_context.manager_id
    assert before_call_mock.await_count == 2
    keys_called = {c.args[1] for c in before_call_mock.await_args_list}
    assert f"mgr:{manager_id}" in keys_called
    mgr_call = next(c for c in before_call_mock.await_args_list if c.args[1] == f"mgr:{manager_id}")
    assert mgr_call.kwargs["daily_limit"] == settings.manager_daily_quota

    assert record_actual_mock.await_count == 2

    audit_mock.assert_awaited_once()
    audit_kwargs = audit_mock.call_args.kwargs
    assert audit_kwargs["params_summary"] == {"query": query, "valid": True}
    assert audit_kwargs["status"] == "success"
    assert audit_kwargs["operation"] == "validate_gaql"


@pytest.mark.asyncio
async def test_validate_gaql_invalid_query_still_audits_with_status_error(bound_context):
    """Query invalida (search levanta) -> resultado valid:False preservado (UX
    intacta) MAS o audit registra status='error' com valid:False + error_message."""
    from src.mcp.tools.validate_gaql import validate_gaql

    before_call_mock = AsyncMock()
    record_actual_mock = AsyncMock()
    audit_mock = AsyncMock(return_value=1)

    patches = _common_patches(
        before_call_mock=before_call_mock,
        record_actual_mock=record_actual_mock,
        audit_mock=audit_mock,
    )
    query = "SELECT bad FROM nothing"
    for p in patches:
        p.start()
    try:
        with patch(
            "src.mcp.tools.validate_gaql.build_client_for_manager",
            AsyncMock(return_value=_fake_client_invalid(Exception("Bad GAQL"))),
        ):
            result = await validate_gaql({"customer_id": "1234567890", "query": query})
    finally:
        for p in patches:
            p.stop()

    assert result["valid"] is False
    assert result["error"] is not None

    # Reserva foi feita e a chamada Google completou (mesmo com erro de validacao
    # de sintaxe) -> record_actual reconcilia normalmente (nao e QuotaExhausted).
    assert record_actual_mock.await_count == 2

    audit_mock.assert_awaited_once()
    audit_kwargs = audit_mock.call_args.kwargs
    assert audit_kwargs["params_summary"]["query"] == query
    assert audit_kwargs["params_summary"]["valid"] is False
    assert audit_kwargs["status"] == "error"
    assert audit_kwargs["error_message"] is not None


@pytest.mark.asyncio
async def test_validate_gaql_denied_by_gate_not_duplicated_by_own_audit(bound_context):
    """Hard-gate (ensure_account_access) ja audita 'denied' internamente --
    validate_gaql NAO deve chamar audit_log.record de novo quando o gate barra
    (evita duplicar o evento de negacao)."""
    from src.google_ads.access import AccountAccessDeniedError
    from src.mcp.tools.validate_gaql import validate_gaql

    audit_mock = AsyncMock(return_value=1)
    mock_pool, _ = _pool_with_conn()
    patches = [
        patch(
            "src.mcp.tools.validate_gaql.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("sem acesso")),
        ),
        patch("src.mcp.tools.validate_gaql.audit_log.record", audit_mock),
        patch("src.mcp.tools.validate_gaql.connection.get_pool", return_value=mock_pool),
    ]
    for p in patches:
        p.start()
    try:
        with pytest.raises(AccountAccessDeniedError):
            await validate_gaql(
                {"customer_id": "1234567890", "query": "SELECT customer.id FROM customer"}
            )
    finally:
        for p in patches:
            p.stop()

    audit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_validate_gaql_infra_failure_after_reserve_audits_error_and_reraises(
    bound_context,
):
    """build_client_for_manager (ou qualquer falha que NAO seja QuotaExhausted
    nem erro de validacao GAQL) apos a reserva -- audit registra status='error'
    (nao 'success'), record_actual reconcilia (actual_ops=0, devolve a reserva),
    e a excecao original propaga pro caller (nao vira {valid, error})."""
    from src.mcp.tools.validate_gaql import validate_gaql

    before_call_mock = AsyncMock()
    record_actual_mock = AsyncMock()
    audit_mock = AsyncMock(return_value=1)

    patches = _common_patches(
        before_call_mock=before_call_mock,
        record_actual_mock=record_actual_mock,
        audit_mock=audit_mock,
    )
    infra_error = RuntimeError("sem conexao OAuth pro gestor")
    for p in patches:
        p.start()
    try:
        with (
            patch(
                "src.mcp.tools.validate_gaql.build_client_for_manager",
                AsyncMock(side_effect=infra_error),
            ),
            pytest.raises(RuntimeError, match="sem conexao OAuth"),
        ):
            await validate_gaql(
                {"customer_id": "1234567890", "query": "SELECT customer.id FROM customer"}
            )
    finally:
        for p in patches:
            p.stop()

    # Reserva foi feita (before_call 2x) e reconciliada (record_actual 2x,
    # actual_ops=0 -- a chamada nunca chegou a rodar search()).
    assert before_call_mock.await_count == 2
    assert record_actual_mock.await_count == 2
    for c in record_actual_mock.await_args_list:
        assert c.kwargs["actual_ops"] == 0

    audit_mock.assert_awaited_once()
    audit_kwargs = audit_mock.call_args.kwargs
    assert audit_kwargs["status"] == "error"
    assert "sem conexao OAuth" in audit_kwargs["error_message"]
