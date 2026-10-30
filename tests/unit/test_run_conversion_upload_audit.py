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


def _client_results_vazio():
    client = _mock_client_with_partial_failure(0, 0)
    return client


@pytest.mark.asyncio
async def test_results_vazio_para_100_linhas_e_nao_medido():
    result, kw = await _roda(_client_results_vazio(), 100)
    assert kw["had_effect"] is None
    assert kw["status"] == "success"
    assert "applied_count" not in kw["params_summary"]
    assert "failed_count" not in kw["params_summary"]
    assert kw["params_summary"]["conversion_count"] == 100
    assert kw["error_message"] is None
    # o envelope ao gestor nao muda
    assert result["status"] == "applied"
    assert result["applied_count"] == 0
    assert result["failed_count"] == 0


@pytest.mark.asyncio
async def test_results_curto_e_nao_medido():
    _, kw = await _roda(_mock_client_with_partial_failure(30, 20), 100)
    assert kw["had_effect"] is None
    assert "applied_count" not in kw["params_summary"]
    assert "failed_count" not in kw["params_summary"]


@pytest.mark.asyncio
async def test_100_recusadas_grava_error_message_e_loga_status_do_audit():
    with patch("src.google_ads.conversions.log") as log:
        _, kw = await _roda(_mock_client_with_partial_failure(0, 100), 100)
    assert kw["status"] == "error"
    assert kw["error_message"] == "0 de 100 conversões aceitas"
    executado = [c for c in log.info.call_args_list if c.args[0] == "conversion_upload_executed"]
    assert len(executado) == 1
    assert executado[0].kwargs["status"] == "error"


@pytest.mark.asyncio
async def test_excecao_no_upload_had_effect_none():
    client = _mock_client_with_partial_failure(0, 0)
    client.get_service.return_value.upload_click_conversions.side_effect = RuntimeError("boom")
    result, kw = await _roda(client, 5)
    assert result["status"] == "error"
    assert kw["status"] == "error"
    assert kw["had_effect"] is None
    assert "applied_count" not in kw["params_summary"]
