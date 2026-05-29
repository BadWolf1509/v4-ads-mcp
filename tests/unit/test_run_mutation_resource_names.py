"""Unit tests for run_mutation resource_names extraction (Sprint 3b.15 F13)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _fake_op_resp_with_resource(field_name: str, resource_name: str) -> MagicMock:
    """Create a mock op_resp where WhichOneof returns field_name and
    getattr returns object with resource_name set."""
    pb = MagicMock()
    pb.WhichOneof.return_value = field_name
    setattr(pb, field_name, SimpleNamespace(resource_name=resource_name))
    op_resp = MagicMock()
    op_resp._pb = pb
    return op_resp


def _fake_op_resp_failed() -> MagicMock:
    """Failed op: WhichOneof returns None (no result oneof set)."""
    pb = MagicMock()
    pb.WhichOneof.return_value = None
    op_resp = MagicMock()
    op_resp._pb = pb
    return op_resp


def _setup_run_mutation_mocks(monkeypatch, fake_response):
    """Helper: mock the heavy dependencies so run_mutation focuses on response parsing."""
    from src.google_ads import mutations

    fake_client = MagicMock()
    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type.return_value = MagicMock(
        mutate_operations=[],
    )

    monkeypatch.setattr(
        mutations,
        "build_client_for_manager",
        AsyncMock(return_value=fake_client),
    )
    monkeypatch.setattr(
        mutations,
        "get_builder",
        lambda op_type: lambda c, cid, p: [MagicMock()],
    )
    monkeypatch.setattr(
        mutations,
        "get_request_id",
        lambda: "fake-req-id",
    )
    monkeypatch.setattr(
        mutations,
        "reset_request_id",
        lambda: None,
    )

    with (
        patch.object(mutations.connection, "get_pool"),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
    ):
        yield


@pytest.mark.asyncio
async def test_extracts_resource_names_for_successful_ops(monkeypatch):
    """3 ops all successful → 3 resource_names extracted."""
    from src.google_ads.mutations import run_mutation

    fake_response = MagicMock()
    fake_response.mutate_operation_responses = [
        _fake_op_resp_with_resource("ad_group_result", "customers/X/adGroups/1"),
        _fake_op_resp_with_resource("ad_group_result", "customers/X/adGroups/2"),
        _fake_op_resp_with_resource("ad_group_result", "customers/X/adGroups/3"),
    ]
    fake_response.partial_failure_error = SimpleNamespace(code=0, details=[])

    from src.google_ads import mutations

    with (
        patch.object(
            mutations,
            "build_client_for_manager",
            AsyncMock(return_value=_make_client(fake_response)),
        ),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch.object(mutations.connection, "get_pool"),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
    ):
        result = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="create_ad_group",
            payload={"ad_groups": [{}], "__target_count__": 3},
            target_count=3,
        )

    assert "resource_names" in result
    assert result["resource_names"] == [
        "customers/X/adGroups/1",
        "customers/X/adGroups/2",
        "customers/X/adGroups/3",
    ]


@pytest.mark.asyncio
async def test_returns_none_for_failed_ops_in_partial_failure(monkeypatch):
    """1 success + 1 failed in partial_failure → [str, None]."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    fake_response = MagicMock()
    fake_response.mutate_operation_responses = [
        _fake_op_resp_with_resource("ad_group_criterion_result", "customers/X/adGroupCriteria/1"),
        _fake_op_resp_failed(),
    ]
    fake_response.partial_failure_error = SimpleNamespace(code=1, details=[])

    with (
        patch.object(
            mutations,
            "build_client_for_manager",
            AsyncMock(return_value=_make_client(fake_response)),
        ),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch.object(mutations.connection, "get_pool"),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
    ):
        result = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="add_keywords",
            payload={
                "ad_group_id": "1",
                "keywords": [{}, {}],
                "__target_count__": 2,
                "__partial_failure__": True,
            },
            target_count=2,
            partial_failure=True,
        )

    assert "resource_names" in result
    assert result["resource_names"] == [
        "customers/X/adGroupCriteria/1",
        None,
    ]


@pytest.mark.asyncio
async def test_handles_missing_mutate_operation_responses_field(monkeypatch):
    """If response lacks the field (SDK version drift) → empty list."""
    from src.google_ads import mutations
    from src.google_ads.mutations import run_mutation

    # spec=["partial_failure_error"] means MagicMock will raise AttributeError
    # for any attribute NOT in that list — simulating a response object that
    # genuinely lacks mutate_operation_responses.
    fake_response = MagicMock(spec=["partial_failure_error"])
    fake_response.partial_failure_error = SimpleNamespace(code=0, details=[])

    with (
        patch.object(
            mutations,
            "build_client_for_manager",
            AsyncMock(return_value=_make_client(fake_response)),
        ),
        patch.object(mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock()]),
        patch.object(mutations, "get_request_id", lambda: "fake-req-id"),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch.object(mutations.connection, "get_pool"),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch.object(mutations, "before_call", AsyncMock()),
        patch.object(mutations, "record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
    ):
        result = await run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="update_keyword_status",
            payload={"__target_count__": 1},
            target_count=1,
        )

    assert "resource_names" in result
    assert result["resource_names"] == []


def _make_client(fake_response) -> MagicMock:
    """Build a minimal mock SDK client with the given mutate response."""
    client = MagicMock()
    fake_service = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    client.get_service = MagicMock(return_value=fake_service)
    failure_stub = MagicMock()
    failure_stub._meta.pb = lambda: MagicMock(errors=[])
    client.get_type = MagicMock(
        side_effect=lambda name: (
            failure_stub if name == "GoogleAdsFailure" else MagicMock(mutate_operations=[])
        )
    )
    return client
