"""Unit tests for run_conversion_upload + _parse_upload_response (Sprint 3b.26).

Dispatcher tests use MagicMock client (NOT proto_capture — ConversionUploadService
is a service method call, not proto-plus message capture pattern).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _payload(conversions=None, conversion_action_id="987654321"):
    """Build a valid payload (post-validation)."""
    base_conversions = conversions or [
        {
            "gclid": "Cj0KCQjwTEST_001",
            "conversion_date_time": "2026-05-17 14:30:00",
            "conversion_value_brl": 100.0,
        }
    ]
    return {
        "customer_id": "1234567890",
        "conversion_action_id": conversion_action_id,
        "conversions": base_conversions,
        "__target_count__": len(base_conversions),
        "__params_summary__": {"conversion_count": len(base_conversions)},
    }


def _mock_client_with_success_response(num_conversions: int) -> MagicMock:
    """Mock SDK client returning UploadClickConversionsResponse with N successes."""
    client = MagicMock()
    client.get_type = MagicMock(side_effect=lambda name: MagicMock())
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    response = MagicMock()
    results = []
    for i in range(num_conversions):
        r = MagicMock()
        r.conversion_action = "customers/1234567890/conversionActions/987654321"
        r.gclid = f"Cj0KCQjwTEST_{i:03d}"
        r.conversion_date_time = "2026-05-17 14:30:00-03:00"
        results.append(r)
    response.results = results

    pfe = MagicMock()
    pfe.code = 0
    pfe.details = []
    response.partial_failure_error = pfe

    service = MagicMock()
    service.upload_click_conversions = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=service)
    return client


def _mock_client_with_partial_failure(success_count: int, failure_count: int) -> MagicMock:
    """Mock client returning N successes + M failed rows (empty result.conversion_action)."""
    client = MagicMock()
    client.get_type = MagicMock(side_effect=lambda name: MagicMock())
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    response = MagicMock()
    results = []
    for _ in range(success_count):
        r = MagicMock()
        r.conversion_action = "customers/1234567890/conversionActions/987654321"
        results.append(r)
    for _ in range(failure_count):
        r = MagicMock()
        r.conversion_action = ""  # Empty = failed
        results.append(r)
    response.results = results

    pfe = MagicMock()
    pfe.code = 1
    pfe.details = []
    response.partial_failure_error = pfe

    service = MagicMock()
    service.upload_click_conversions = MagicMock(return_value=response)
    client.get_service = MagicMock(return_value=service)
    return client


def _common_patches(client, request_id="req-001"):
    """Common patch context for run_conversion_upload tests.

    Patches match REAL signatures:
    - before_call(conn, token_id, *, estimated_ops) — positional conn + token_id
    - record_actual(conn, token_id, *, actual_ops, estimated_ops) — positional conn + token_id
    - audit_log.record(conn, *, ...) — the real function name is 'record', not 'insert_row'
    """
    mock_pool = MagicMock()
    mock_acquire_cm = MagicMock()
    mock_acquire_cm.__aenter__ = AsyncMock(return_value=AsyncMock())
    mock_acquire_cm.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire_cm

    return [
        patch(
            "src.google_ads.conversions.build_client_for_manager", AsyncMock(return_value=client)
        ),
        patch("src.google_ads.conversions.before_call", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.record_actual", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.audit_log.record", AsyncMock(return_value=None)),
        patch("src.google_ads.conversions.get_request_id", return_value=request_id),
        patch("src.google_ads.conversions.reset_request_id", return_value=None),
        patch("src.google_ads.conversions.connection.get_pool", return_value=mock_pool),
    ]


# ============================================================================
# Request construction tests
# ============================================================================


@pytest.mark.asyncio
async def test_upload_constructs_request_with_correct_customer_id_and_partial_failure_true():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)

    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    service = client.get_service.return_value
    assert service.upload_click_conversions.called
    request = service.upload_click_conversions.call_args[1]["request"]
    assert request.customer_id == "1234567890"
    assert request.partial_failure is True
    # F42 (Sprint 3b.26.1): debug_enabled removed from v24 UploadClickConversionsRequest;
    # builder no longer sets it. Previously asserted False.


@pytest.mark.asyncio
async def test_upload_sets_currency_brl_per_v4_invariant():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    assert len(captured) == 1
    assert captured[0].currency_code == "BRL"


@pytest.mark.asyncio
async def test_upload_appends_minus_03_timezone_per_v4_invariant():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    assert captured[0].conversion_date_time == "2026-05-17 14:30:00-03:00"


@pytest.mark.asyncio
async def test_upload_sets_consent_granted_per_v4_invariant_lgpd():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    assert captured[0].consent.ad_user_data == "GRANTED"


@pytest.mark.asyncio
async def test_upload_sets_conversion_action_resource_path_correctly():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversion_action_id="987654321"),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    expected = "customers/1234567890/conversionActions/987654321"
    assert captured[0].conversion_action == expected


@pytest.mark.asyncio
async def test_upload_includes_order_id_when_present():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(1)
    captured = []

    def capture_get_type(name):
        m = MagicMock()
        if name == "ClickConversion":
            captured.append(m)
        return m

    client.get_type = MagicMock(side_effect=capture_get_type)

    conversions = [
        {
            "gclid": "Cj0KCQjwTEST",
            "conversion_date_time": "2026-05-17 14:30:00",
            "conversion_value_brl": 100.0,
            "order_id": "crm-12345",
        }
    ]

    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversions=conversions),
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()

    assert captured[0].order_id == "crm-12345"


# ============================================================================
# Response parsing tests
# ============================================================================


@pytest.mark.asyncio
async def test_parse_response_counts_applied_correctly_all_success():
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_success_response(5)

    patches = _common_patches(client, request_id="req-005")
    for p in patches:
        p.start()
    try:
        conversions = [
            {
                "gclid": f"Cj0_{i}",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
            for i in range(5)
        ]
        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversions=conversions),
            target_count=5,
            params_summary={"conversion_count": 5},
        )
    finally:
        for p in patches:
            p.stop()

    assert result["status"] == "applied"
    assert result["applied_count"] == 5
    assert result["failed_count"] == 0
    assert result["failures"] == []
    assert result["google_request_id"] == "req-005"


@pytest.mark.asyncio
async def test_parse_response_extracts_failures_with_row_index():
    """When 3 of 5 results have empty conversion_action, failures list has 2 entries."""
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_partial_failure(success_count=3, failure_count=2)

    patches = _common_patches(client, request_id="req-partial")
    for p in patches:
        p.start()
    try:
        conversions = [
            {
                "gclid": f"Cj0_{i}",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
            for i in range(5)
        ]
        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversions=conversions),
            target_count=5,
            params_summary={"conversion_count": 5},
        )
    finally:
        for p in patches:
            p.stop()

    assert result["applied_count"] == 3
    assert result["failed_count"] == 2
    assert len(result["failures"]) == 2
    assert result["failures"][0]["row_index"] == 3
    assert result["failures"][1]["row_index"] == 4
    assert result["failures"][0]["gclid"] == "Cj0_3"
    assert result["failures"][1]["gclid"] == "Cj0_4"


@pytest.mark.asyncio
async def test_parse_response_handles_all_failed():
    """When all 3 results are failed, applied_count=0 and failures has 3 entries."""
    from src.google_ads.conversions import run_conversion_upload

    client = _mock_client_with_partial_failure(success_count=0, failure_count=3)

    patches = _common_patches(client, request_id="req-all-fail")
    for p in patches:
        p.start()
    try:
        conversions = [
            {
                "gclid": f"Cj0_{i}",
                "conversion_date_time": "2026-05-17 14:30:00",
                "conversion_value_brl": 100.0,
            }
            for i in range(3)
        ]
        result = await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=_payload(conversions=conversions),
            target_count=3,
            params_summary={"conversion_count": 3},
        )
    finally:
        for p in patches:
            p.stop()

    assert result["applied_count"] == 0
    assert result["failed_count"] == 3
    assert len(result["failures"]) == 3


# F42 (Sprint 3b.26.1): test_upload_request_debug_enabled_false removed —
# UploadClickConversionsRequest.debug_enabled doesn't exist in v24 SDK.
# Builder no longer sets it. Smoke T7 caught the AttributeError pré-fix.
