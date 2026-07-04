"""Unit tests for run_offline_user_data_job dispatcher (Sprint 3b.28).

Pattern paralelo a tests/unit/test_run_conversion_upload.py (3b.26 +
retrofit ProtoFieldCapture commit e055ef7). Dispatcher faz 3 calls em
sequência: create_offline_user_data_job → add_offline_user_data_job_operations
→ run_offline_user_data_job.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tests.unit.fixtures.proto_capture import CapturedOp, make_capture_client


class _OneoofCapture(CapturedOp):
    """CapturedOp variant for OfflineUserDataJobOperation.

    Fixture limitation: CapturedOp.has() returns False when the stored value
    is itself a CapturedOp (proto sub-message). For the create/remove oneof
    field on OfflineUserDataJobOperation, we need has("create") / has("remove")
    to return True when the field is set (even if the value is a proto message).

    Workaround (inline, per task A4 spec): store a sentinel string "__SET__"
    instead of the raw CapturedOp when create/remove is assigned, preserving
    the oneof semantics for has() assertions.
    """

    _ONEOF_FIELDS = frozenset({"create", "remove"})

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith("_"):
            object.__setattr__(self, key, value)
        elif key in self._ONEOF_FIELDS:
            # Store sentinel so has() returns True (scalar, not CapturedOp)
            self._captured[key] = "__SET__"
        else:
            self._captured[key] = value


def _pool_with_transactable_conn() -> MagicMock:
    """conn.transaction() precisa ser um async CM real (F73 -- run_offline_user_data_job
    agora reserva/reconcilia dentro de `async with pool.acquire() as conn, conn.transaction():`)."""
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
    return mock_pool


def _make_capture_client_with_offline_user_data_job_service():
    """Extends make_capture_client com mocks pra OfflineUserDataJobService."""
    client = make_capture_client()

    service = MagicMock()
    service.create_offline_user_data_job = MagicMock(
        return_value=MagicMock(resource_name="customers/1163862076/offlineUserDataJobs/JOB123")
    )
    service.add_offline_user_data_job_operations = MagicMock(return_value=MagicMock())
    service.run_offline_user_data_job = MagicMock(return_value=MagicMock())

    _original_get_service = client.get_service

    def _get_service(name: str) -> MagicMock:
        if name == "OfflineUserDataJobService":
            return service
        return _original_get_service(name)

    client.get_service = _get_service

    # Override get_type so OfflineUserDataJobOperation uses _OneoofCapture
    _original_get_type = client.get_type

    def _get_type(name: str) -> CapturedOp:
        if name == "OfflineUserDataJobOperation":
            return _OneoofCapture()
        return _original_get_type(name)

    client.get_type = _get_type

    client.enums.OfflineUserDataJobTypeEnum.CUSTOMER_MATCH_USER_LIST = "CUSTOMER_MATCH_USER_LIST"
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    return client, service


@pytest.fixture
def fake_ctx():
    return {"manager_id": uuid4(), "session_id": uuid4(), "customer_id": "1163862076"}


@pytest.fixture(autouse=True)
def gov_mocks():
    """Neutraliza rate-limit + audit (tocam o DB) pros testes de proto-capture.

    Testes que asseguram o audit/rate-limit em si pedem esta fixture por nome
    pra acessar os mocks (record_actual, audit). Autouse porque TODO teste do
    dispatcher agora passa por before_call/record_actual/audit_log.record."""
    with (
        patch("src.google_ads.customer_match.before_call", AsyncMock()) as before,
        patch("src.google_ads.customer_match.record_actual", AsyncMock()) as rec_actual,
        patch("src.google_ads.customer_match.audit_log.record", AsyncMock(return_value=1)) as audit,
    ):
        yield {"before_call": before, "record_actual": rec_actual, "audit": audit}


@pytest.mark.asyncio
async def test_dispatcher_creates_job_with_customer_match_metadata(fake_ctx):
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    create_call = service.create_offline_user_data_job.call_args
    assert create_call.kwargs["customer_id"] == "1163862076"

    job_arg = create_call.kwargs["job"]
    assert job_arg.field("type_") == "CUSTOMER_MATCH_USER_LIST"
    assert (
        job_arg.field("customer_match_user_list_metadata.user_list")
        == "customers/1163862076/userLists/1234567890"
    )


@pytest.mark.asyncio
async def test_dispatcher_consent_lgpd_invariants_granted(fake_ctx):
    """V4 invariant: consent.ad_user_data + consent.ad_personalization GRANTED."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    job_arg = service.create_offline_user_data_job.call_args.kwargs["job"]
    assert job_arg.field("customer_match_user_list_metadata.consent.ad_user_data") == "GRANTED"
    assert (
        job_arg.field("customer_match_user_list_metadata.consent.ad_personalization") == "GRANTED"
    )


@pytest.mark.asyncio
async def test_dispatcher_add_operations_partial_failure_true(fake_ctx):
    """V4 invariant: enable_partial_failure=True na add_operations request."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    add_call = service.add_offline_user_data_job_operations.call_args
    request_arg = add_call.kwargs["request"]
    assert request_arg.field("enable_partial_failure") is True
    assert request_arg.field("resource_name") == "customers/1163862076/offlineUserDataJobs/JOB123"


@pytest.mark.asyncio
async def test_dispatcher_user_data_uses_hashed_email_field(fake_ctx):
    """UserData.user_identifiers[].hashed_email é setado quando email no member."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc123hash"}],
        )

    add_call = service.add_offline_user_data_job_operations.call_args
    operations = add_call.kwargs["request"].field("operations")
    assert len(operations) == 1


@pytest.mark.asyncio
async def test_dispatcher_returns_job_resource_name_and_three_request_ids(fake_ctx):
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        result = await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc"}, {"hashed_phone_number": "xyz"}],
        )

    assert result["job_resource_name"] == "customers/1163862076/offlineUserDataJobs/JOB123"
    assert "provider_request_id_create_job" in result
    assert "provider_request_id_add_ops" in result
    assert "provider_request_id_run_job" in result
    assert result["members_submitted"] == 2


@pytest.mark.asyncio
async def test_dispatcher_remove_operation_uses_remove_field(fake_ctx):
    """operation_type='remove' → operation.remove = user_data (não create)."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="remove",
            hashed_members=[{"hashed_email": "abc123"}],
        )

    add_call = service.add_offline_user_data_job_operations.call_args
    operations = add_call.kwargs["request"].field("operations")
    op_zero = operations[0]
    assert op_zero.has("remove") is True
    assert op_zero.has("create") is False


@pytest.mark.asyncio
async def test_dispatcher_records_audit_and_rate_limit_on_success(fake_ctx, gov_mocks):
    """F71: sucesso grava audit_log (mutate) SEM PII + reconcilia o rate counter."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, _ = _make_capture_client_with_offline_user_data_job_service()

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc"}, {"hashed_phone_number": "xyz"}],
        )

    # F73: record_actual agora reconcilia 2 chaves (global + mgr:<uuid> cap por
    # gestor) -- antes era 1x so pra chave global.
    assert gov_mocks["record_actual"].await_count == 2
    reconciled_keys = {c.args[1] for c in gov_mocks["record_actual"].await_args_list}
    assert f"mgr:{fake_ctx['manager_id']}" in reconciled_keys
    gov_mocks["audit"].assert_awaited_once()
    kwargs = gov_mocks["audit"].call_args.kwargs
    assert kwargs["action_type"] == "mutate"
    assert kwargs["operation"] == "upload_customer_match_list"
    assert kwargs["status"] == "success"
    assert kwargs["target_count"] == 2
    # params_summary carrega só metadados — NUNCA os hashes (PII)
    ps = kwargs["params_summary"]
    assert ps == {"user_list_id": "1234567890", "operation": "add", "member_count": 2}
    assert "abc" not in str(ps) and "xyz" not in str(ps)


@pytest.mark.asyncio
async def test_dispatcher_audits_and_raises_on_api_error(fake_ctx, gov_mocks):
    """F71: erro numa das 3 chamadas grava audit (status=error) E levanta friendly
    (apply_change espera dict de sucesso; o raise vira envelope PT-BR pro cliente)."""
    from src.google_ads.customer_match import run_offline_user_data_job
    from src.google_ads.errors import GoogleAdsFriendlyError

    client, service = _make_capture_client_with_offline_user_data_job_service()
    service.create_offline_user_data_job = MagicMock(side_effect=RuntimeError("boom da API"))

    with (
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=_pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
        pytest.raises(GoogleAdsFriendlyError),
    ):
        await run_offline_user_data_job(
            manager_id=fake_ctx["manager_id"],
            session_id=fake_ctx["session_id"],
            customer_id=fake_ctx["customer_id"],
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc"}],
        )

    gov_mocks["audit"].assert_awaited_once()
    assert gov_mocks["audit"].call_args.kwargs["status"] == "error"
    # rate counter reconciliado com actual_ops=0 (reserva liberada)
    assert gov_mocks["record_actual"].call_args.kwargs["actual_ops"] == 0
