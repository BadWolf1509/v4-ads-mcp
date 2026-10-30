"""Audit do upload de conversoes conta as recusas (nao grava success com 100% recusado)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from tests.unit.test_run_conversion_upload import (
    _common_patches,
    _mock_client_with_partial_failure,
    _mock_client_with_success_response,
    _payload,
)


async def _roda(client, total: int):
    from src.google_ads.conversions import run_conversion_upload

    conversions = [
        {
            "gclid": f"Cj0_{i}",
            "conversion_date_time": "2026-05-17 14:30:00",
            "conversion_value_brl": 100.0,
        }
        for i in range(total)
    ]
    registro = AsyncMock(return_value=None)
    patches = _common_patches(client)
    for p in patches:
        p.start()
    try:
        with patch("src.google_ads.conversions.audit_log.record", registro):
            result = await run_conversion_upload(
                manager_id=uuid4(),
                session_id=uuid4(),
                customer_id="1234567890",
                operation_type="import_offline_conversions",
                payload=_payload(conversions=conversions),
                target_count=total,
                params_summary={"conversion_count": total},
            )
    finally:
        for p in patches:
            p.stop()
    return result, registro.await_args.kwargs


@pytest.mark.asyncio
async def test_100_de_100_recusadas_audit_error_e_resposta_com_falhas():
    result, kw = await _roda(_mock_client_with_partial_failure(0, 100), 100)
    assert kw["status"] == "error"
    assert kw["had_effect"] is False
    assert kw["params_summary"]["applied_count"] == 0
    assert kw["params_summary"]["failed_count"] == 100
    assert kw["params_summary"]["conversion_count"] == 100
    # o envelope NAO muda: segue com as falhas por linha
    assert result["status"] == "applied"
    assert result["applied_count"] == 0
    assert len(result["failures"]) == 100


@pytest.mark.asyncio
async def test_60_de_100_audit_success_com_contagens():
    result, kw = await _roda(_mock_client_with_partial_failure(60, 40), 100)
    assert kw["status"] == "success"
    assert kw["had_effect"] is True
    assert kw["params_summary"]["applied_count"] == 60
    assert kw["params_summary"]["failed_count"] == 40
    assert len(result["failures"]) == 40


@pytest.mark.asyncio
async def test_100_aceitas_had_effect_true():
    _, kw = await _roda(_mock_client_with_success_response(100), 100)
    assert kw["status"] == "success"
    assert kw["had_effect"] is True
    assert kw["params_summary"]["failed_count"] == 0
