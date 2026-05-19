"""Unit tests for validate_conversion_action_for_upload helper (Sprint 3b.26).

GAQL pre-flight: conversion_action exists + type=UPLOAD_CLICKS + status != REMOVED.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_validate_returns_none_when_action_exists_with_upload_clicks_type():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(
            return_value=[
                {
                    "conversion_action": {
                        "id": "987654321",
                        "type": "UPLOAD_CLICKS",
                        "status": "ENABLED",
                    }
                }
            ]
        ),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is None


@pytest.mark.asyncio
async def test_validate_returns_error_when_action_not_found():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(return_value=[]),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is not None
    assert "não existe" in result
    assert "987654321" in result
    assert "1234567890" in result


@pytest.mark.asyncio
async def test_validate_returns_error_when_type_is_webpage():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(
            return_value=[
                {
                    "conversion_action": {
                        "id": "987654321",
                        "type": "WEBPAGE",
                        "status": "ENABLED",
                    }
                }
            ]
        ),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is not None
    assert "UPLOAD_CLICKS" in result
    assert "WEBPAGE" in result


@pytest.mark.asyncio
async def test_validate_returns_error_when_action_is_removed():
    from src.google_ads.queries._common import validate_conversion_action_for_upload

    with patch(
        "src.google_ads.queries._common.run_report",
        AsyncMock(
            return_value=[
                {
                    "conversion_action": {
                        "id": "987654321",
                        "type": "UPLOAD_CLICKS",
                        "status": "REMOVED",
                    }
                }
            ]
        ),
    ):
        result = await validate_conversion_action_for_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            conversion_action_id="987654321",
        )

    assert result is not None
    assert "REMOVED" in result
