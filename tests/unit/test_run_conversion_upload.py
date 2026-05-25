"""Unit tests for run_conversion_upload + _parse_upload_response (Sprint 3b.26).

Dispatcher split:
- Tests asserting ClickConversion *field assignments* (currency_code, gclid, etc.)
  use make_capture_client (ProtoFieldCapture). MagicMock silently accepted
  removed fields — this is what hid F42 (debug_enabled removed in v24 SDK) for
  one deploy cycle. See mcp-tool-quality-reviewer recommendation 2026-05-19.
- Tests asserting on the service-call boundary (request.customer_id,
  request.partial_failure) or only on response parsing stay MagicMock, because
  they work at the service object level, not proto-plus message field level.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from tests.unit.fixtures.proto_capture import CapturedOp, make_capture_client


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


def _capture_client_with_success_response(
    num_conversions: int,
) -> tuple[MagicMock, list[CapturedOp]]:
    """ProtoFieldCapture client for ClickConversion field assertion tests.

    Returns (client, click_convs) where click_convs accumulates each
    CapturedOp instance created by client.get_type("ClickConversion").

    WHY ProtoFieldCapture instead of MagicMock:
    MagicMock.debug_enabled = False silently passed tests even after the field
    was removed from the SDK (Sprint 3b.26 F42 — 1 deploy cycle blind). CapturedOp
    uses __setattr__ recording, not MagicMock attribute sinks, so an accidentally-
    set removed field shows up in the op dict rather than disappearing quietly.
    The real guard is ProtoFieldCapture in future dispatcher tests (3b.28+).
    """
    client = make_capture_client()
    # ConsentStatusEnum is not set by make_capture_client (it covers mutation
    # enums, not upload service enums). Assign the scalar directly so the builder
    # receives "GRANTED" and the test can assert on it.
    client.enums.ConsentStatusEnum.GRANTED = "GRANTED"

    click_convs: list[CapturedOp] = []

    # Wrap get_type to record every ClickConversion instance the builder creates.
    def _tracking_get_type(name: str) -> CapturedOp:
        op = CapturedOp()
        if name == "ClickConversion":
            click_convs.append(op)
        return op

    client.get_type = _tracking_get_type

    # Wire up ConversionUploadService so the dispatcher can call
    # service.upload_click_conversions(request=...) and get a usable response.
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

    upload_service = MagicMock()
    upload_service.upload_click_conversions = MagicMock(return_value=response)

    # Override get_service for ConversionUploadService specifically; keep
    # make_capture_client's routing for everything else.
    _original_get_service = client.get_service

    def _get_service(name: str) -> Any:
        if name == "ConversionUploadService":
            return upload_service
        return _original_get_service(name)

    client.get_service = _get_service

    return client, click_convs


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
    """ProtoFieldCapture: asserts ClickConversion.currency_code = 'BRL' (V4 invariant).

    Uses make_capture_client so an accidental field removal would raise at test
    time instead of silently passing (F42-recurrence mitigation).
    """
    from src.google_ads.conversions import run_conversion_upload

    client, click_convs = _capture_client_with_success_response(1)

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

    assert len(click_convs) == 1
    assert click_convs[0].field("currency_code") == "BRL"


@pytest.mark.asyncio
async def test_upload_appends_minus_03_timezone_per_v4_invariant():
    """ProtoFieldCapture: asserts conversion_date_time gets -03:00 BRT suffix (V4 invariant)."""
    from src.google_ads.conversions import run_conversion_upload

    client, click_convs = _capture_client_with_success_response(1)

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

    assert click_convs[0].field("conversion_date_time") == "2026-05-17 14:30:00-03:00"


@pytest.mark.asyncio
async def test_upload_sets_consent_granted_per_v4_invariant_lgpd():
    """ProtoFieldCapture: asserts consent.ad_user_data = GRANTED (LGPD V4 invariant).

    Nested field accessed via op.field('consent.ad_user_data') — CapturedOp
    traverses the _SubCapture chain for nested proto messages.
    """
    from src.google_ads.conversions import run_conversion_upload

    client, click_convs = _capture_client_with_success_response(1)

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

    assert click_convs[0].field("consent.ad_user_data") == "GRANTED"


@pytest.mark.asyncio
async def test_upload_sets_conversion_action_resource_path_correctly():
    """ProtoFieldCapture: asserts conversion_action uses correct resource path format."""
    from src.google_ads.conversions import run_conversion_upload

    client, click_convs = _capture_client_with_success_response(1)

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
    assert click_convs[0].field("conversion_action") == expected


@pytest.mark.asyncio
async def test_upload_includes_order_id_when_present():
    """ProtoFieldCapture: asserts order_id is set when provided in payload."""
    from src.google_ads.conversions import run_conversion_upload

    client, click_convs = _capture_client_with_success_response(1)

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

    assert click_convs[0].field("order_id") == "crm-12345"


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
    assert result["provider_request_id"] == "req-005"


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
