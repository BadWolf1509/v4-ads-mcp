"""Unit tests for run_mutation's partial_failure mode + custom params_summary."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads.mutations import run_mutation


def _pool_with_transactable_conn() -> MagicMock:
    """conn.transaction() precisa ser um async CM real (F73 -- run_mutation agora
    reserva/reconcilia dentro de `async with pool.acquire() as conn, conn.transaction():`)."""
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


def _client_with_partial_failure(per_op_errors: list[str | None]):
    """Mock client whose .mutate() returns a response with the given per-op errors.

    per_op_errors[i] = None means op i succeeded; a string is the error message.
    Simulates the real API shape:
    - Top-level partial_failure_error.code is 0 if all OK, else non-zero
    - Top-level partial_failure_error.details contains a GoogleAdsFailure-like
      proto with per-op locations (we mock the unpack via index_to_error)
    - Each MutateOperationResponse has _pb.WhichOneof('response') returning
      a field name (success) or None (failure)
    """
    client = MagicMock()

    # Build per-op mock responses with realistic WhichOneof behavior
    responses = []
    for _idx, err in enumerate(per_op_errors):
        r = MagicMock()
        # _pb.WhichOneof returns field name on success, None on failure
        if err is None:
            r._pb.WhichOneof = MagicMock(return_value="campaign_criterion_result")
        else:
            r._pb.WhichOneof = MagicMock(return_value=None)
        responses.append(r)

    # Build top-level response
    fake_response = MagicMock()
    fake_response.mutate_operation_responses = responses

    # If any op failed, top-level partial_failure_error has non-zero code +
    # a single details entry we'll cause the unpack path to populate
    # error_by_index with the per_op_errors values.
    failed_indices = [i for i, e in enumerate(per_op_errors) if e is not None]
    if failed_indices:
        # Simulate a GoogleAdsFailure detail. The implementation duck-type-checks
        # for hasattr(raw, "type_url") and hasattr(raw, "Unpack") — MagicMock
        # satisfies both automatically. We just set type_url and stub Unpack.
        class _FakeError:
            def __init__(self, idx: int, msg: str) -> None:
                self.message = msg
                self.location = MagicMock()
                self.location.field_path_elements = [MagicMock(index=idx)]

        fake_errors = [
            _FakeError(i, per_op_errors[i])  # type: ignore[arg-type]
            for i in failed_indices
        ]

        def fake_unpack(target_pb: MagicMock) -> None:
            target_pb.errors = fake_errors

        raw_any = MagicMock()
        raw_any.type_url = "type.googleapis.com/google.ads.googleads.v20.errors.GoogleAdsFailure"
        raw_any.Unpack = fake_unpack

        # The proto-plus wrapper detail must expose _pb = raw_any
        fake_detail = MagicMock()
        fake_detail._pb = raw_any

        fake_response.partial_failure_error.code = 1  # Non-zero = errors present
        fake_response.partial_failure_error.details = [fake_detail]

        # client.get_type("GoogleAdsFailure") returns a stub whose _meta.pb()
        # returns a fresh MagicMock that fake_unpack will populate
        failure_type_stub = MagicMock()
        failure_type_stub._meta.pb = lambda: MagicMock(errors=[])
    else:
        fake_response.partial_failure_error.code = 0
        fake_response.partial_failure_error.details = []
        failure_type_stub = MagicMock()
        failure_type_stub._meta.pb = lambda: MagicMock(errors=[])

    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    client.get_service = MagicMock(return_value=fake_service)

    def get_type(name: str) -> MagicMock:
        if name == "GoogleAdsFailure":
            return failure_type_stub
        # Default: mutate request and operations stub
        return MagicMock(
            mutate_operations=[],
            partial_failure_mode=MagicMock(),
        )

    client.get_type = MagicMock(side_effect=get_type)
    client.enums.PartialFailureModeEnum.PARTIAL_FAILURE = "PARTIAL_FAILURE"
    return client


@pytest.mark.asyncio
async def test_run_mutation_partial_failure_returns_per_op_status(monkeypatch):
    """When partial_failure=True, returned dict includes per-op outcome list."""
    from src.google_ads import mutations

    monkeypatch.setattr(mutations, "import_all_builders", lambda: None)
    monkeypatch.setattr(
        mutations,
        "get_builder",
        lambda _op: lambda c, cid, p: [MagicMock(), MagicMock(), MagicMock()],
    )
    monkeypatch.setattr(
        mutations,
        "build_client_for_manager",
        AsyncMock(return_value=_client_with_partial_failure([None, "CRITERION_EXISTS", None])),
    )
    monkeypatch.setattr(mutations, "get_request_id", lambda: "req-pf")

    # Stub the DB hooks (before_call, record_actual, audit_log.record, access gate)
    with (
        patch.object(mutations.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock()),
    ):
        result = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="add_negatives_from_search_terms",
            payload={"negatives": [{}, {}, {}]},
            target_count=3,
            partial_failure=True,
        )

    assert result["provider_request_id"] == "req-pf"
    assert "partial_failures" in result
    assert len(result["partial_failures"]) == 3
    assert result["partial_failures"][0] == {"index": 0, "status": "added", "error": None}
    assert result["partial_failures"][1] == {
        "index": 1,
        "status": "failed",
        "error": "CRITERION_EXISTS",
    }
    assert result["partial_failures"][2] == {"index": 2, "status": "added", "error": None}
    assert result["applied_count"] == 2  # 2 added, 1 failed


@pytest.mark.asyncio
async def test_run_mutation_uses_custom_params_summary(monkeypatch):
    """When params_summary is provided, audit_log receives it instead of default {keys: ...}."""
    from src.google_ads import mutations

    custom = {"scopes_distribution": {"campaign": 2}, "match_types_distribution": {"EXACT": 2}}

    monkeypatch.setattr(mutations, "import_all_builders", lambda: None)
    monkeypatch.setattr(
        mutations,
        "get_builder",
        lambda _op: lambda c, cid, p: [MagicMock()],
    )
    monkeypatch.setattr(
        mutations,
        "build_client_for_manager",
        AsyncMock(return_value=_client_with_partial_failure([None])),
    )
    monkeypatch.setattr(mutations, "get_request_id", lambda: "req-cs")

    audit_mock = AsyncMock()
    with (
        patch.object(mutations.connection, "get_pool", return_value=_pool_with_transactable_conn()),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", audit_mock),
    ):
        await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="add_negatives_from_search_terms",
            payload={"negatives": [{}]},
            target_count=1,
            partial_failure=True,
            params_summary=custom,
        )

    # audit_log.record was called with params_summary=custom
    assert audit_mock.call_count == 1
    kwargs = audit_mock.call_args.kwargs
    assert kwargs["params_summary"] == custom
