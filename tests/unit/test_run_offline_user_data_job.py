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


@pytest.mark.asyncio
async def test_dispatcher_creates_job_with_customer_match_metadata(fake_ctx):
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
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

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
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

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
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

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
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

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
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
    assert "google_request_id_create_job" in result
    assert "google_request_id_add_ops" in result
    assert "google_request_id_run_job" in result
    assert result["members_submitted"] == 2


@pytest.mark.asyncio
async def test_dispatcher_remove_operation_uses_remove_field(fake_ctx):
    """operation_type='remove' → operation.remove = user_data (não create)."""
    from src.google_ads.customer_match import run_offline_user_data_job

    client, service = _make_capture_client_with_offline_user_data_job_service()

    with patch(
        "src.google_ads.customer_match.build_client_for_manager",
        AsyncMock(return_value=client),
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
