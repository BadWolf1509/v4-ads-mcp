"""Unit tests for run_mutation's partial_failure mode + custom params_summary."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads.mutations import run_mutation


def _client_with_partial_failure(per_op_errors: list[str | None]):
    """Mock client whose .mutate() returns a response with the given per-op errors.

    per_op_errors[i] = None means op i succeeded; a string is the error message.
    """
    client = MagicMock()

    # Mock the mutate response
    responses = []
    for err in per_op_errors:
        r = MagicMock()
        if err:
            r.HasField = MagicMock(side_effect=lambda f, e=err: f == "partial_failure_error")
            r.partial_failure_error.message = err
        else:
            r.HasField = MagicMock(return_value=False)
            r.campaign_criterion_result.resource_name = f"customers/123/campaignCriteria/{id(r)}"
        responses.append(r)

    fake_response = MagicMock()
    fake_response.mutate_operation_responses = responses

    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    client.get_service = MagicMock(return_value=fake_service)
    client.get_type = MagicMock(
        return_value=MagicMock(
            mutate_operations=[],
            partial_failure_mode=MagicMock(),
        )
    )
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

    # Stub the DB hooks (before_call, record_actual, audit_log.record)
    with (
        patch.object(mutations.connection, "get_pool"),
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

    assert result["google_request_id"] == "req-pf"
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
        patch.object(mutations.connection, "get_pool"),
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
