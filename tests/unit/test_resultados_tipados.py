"""C4: as chaves que cada executor do Google devolve == as chaves do TypedDict.

Guard do contrato em `src/google_ads/resultados.py`: campo novo no `return` sem
o tipo (ou o contrario) deixa o mypy cego, porque os consumidores leem por
`Mapping[str, Any]`. Usa os fakes dos testes `test_run_*` existentes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.google_ads.resultados import (
    ResultadoCustomerMatch,
    ResultadoMutacao,
    ResultadoRecomendacao,
    ResultadoUploadAplicado,
    ResultadoUploadErro,
)
from tests.unit import test_mutations_partial_failure as t_mut
from tests.unit import test_run_conversion_upload as t_conv
from tests.unit import test_run_offline_user_data_job as t_cm


@pytest.mark.asyncio
async def test_chaves_do_resultado_bate_com_o_tipo_mutacao(monkeypatch):
    from src.google_ads import mutations

    monkeypatch.setattr(mutations, "import_all_builders", lambda: None)
    monkeypatch.setattr(
        mutations, "get_builder", lambda _op: lambda c, cid, p: [MagicMock(), MagicMock()]
    )
    monkeypatch.setattr(
        mutations,
        "build_client_for_manager",
        AsyncMock(return_value=t_mut._client_with_partial_failure([None, "X"])),
    )
    monkeypatch.setattr(mutations, "get_request_id", lambda: "req")
    with (
        patch.object(
            mutations.connection, "get_pool", return_value=t_mut._pool_with_transactable_conn()
        ),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch("src.governance.reserva.before_call", AsyncMock()),
        patch("src.governance.reserva.record_actual", AsyncMock()),
        patch.object(mutations.audit_log, "record", AsyncMock()),
    ):
        result = await mutations.run_mutation(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="add_negatives_from_search_terms",
            payload={"negatives": [{}, {}]},
            target_count=2,
            partial_failure=True,
        )
    assert set(result) == set(ResultadoMutacao.__annotations__)


@pytest.mark.asyncio
async def test_chaves_do_resultado_bate_com_o_tipo_recomendacao():
    from src.google_ads import mutations
    from tests.unit import test_run_recommendation_action_happy_path as t_rec

    with (
        patch.object(mutations, "connection") as mock_connection,
        patch.object(
            mutations.connection, "run_with_reconnect", t_rec._run_with_reconnect, create=True
        ),
        patch.object(mutations, "ensure_account_access", AsyncMock()),
        patch("src.governance.reserva.before_call", AsyncMock()),
        patch("src.governance.reserva.record_actual", AsyncMock()),
        patch.object(mutations, "build_client_for_manager", AsyncMock(return_value=MagicMock())),
        patch.object(mutations, "get_request_id", lambda: "req"),
        patch.object(mutations, "reset_request_id", lambda: None),
        patch(
            "src.google_ads.mutates.recommendations.execute_apply_recommendation",
            MagicMock(return_value=MagicMock()),
        ),
        patch.object(mutations.audit_log, "record", AsyncMock(return_value=1)),
    ):
        mock_connection.get_pool.return_value = t_rec._mock_pool()
        result = await mutations.run_recommendation_action(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="apply_recommendation",
            payload={"recommendation_resource_name": "customers/1234567890/recommendations/1"},
        )
    assert set(result) == set(ResultadoRecomendacao.__annotations__)


async def _upload(client, payload):
    from src.google_ads.conversions import run_conversion_upload

    patches = t_conv._common_patches(client)
    for p in patches:
        p.start()
    try:
        return await run_conversion_upload(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1234567890",
            operation_type="import_offline_conversions",
            payload=payload,
            target_count=1,
            params_summary={"conversion_count": 1},
        )
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_chaves_do_resultado_bate_com_o_tipo_upload_aplicado():
    result = await _upload(t_conv._mock_client_with_success_response(1), t_conv._payload())
    assert result["status"] == "applied"
    assert set(result) == set(ResultadoUploadAplicado.__annotations__)


@pytest.mark.asyncio
async def test_chaves_do_resultado_bate_com_o_tipo_upload_erro_sem_fuso():
    payload = t_conv._payload()
    del payload["__time_zone__"]
    result = await _upload(t_conv._mock_client_with_success_response(1), payload)
    assert result["status"] == "error"
    assert set(result) == set(ResultadoUploadErro.__annotations__)


@pytest.mark.asyncio
async def test_chaves_do_resultado_bate_com_o_tipo_upload_erro_do_google():
    client = t_conv._mock_client_with_success_response(1)
    client.get_service.return_value.upload_click_conversions.side_effect = RuntimeError("boom")
    result = await _upload(client, t_conv._payload())
    assert result["status"] == "error"
    assert set(result) == set(ResultadoUploadErro.__annotations__)


@pytest.mark.asyncio
async def test_chaves_do_resultado_bate_com_o_tipo_customer_match():
    from src.google_ads.customer_match import run_offline_user_data_job

    client, _service = t_cm._make_capture_client_with_offline_user_data_job_service()
    with (
        patch("src.governance.reserva.before_call", AsyncMock()),
        patch("src.governance.reserva.record_actual", AsyncMock()),
        patch("src.google_ads.customer_match.audit_log.record", AsyncMock(return_value=1)),
        patch(
            "src.google_ads.customer_match.build_client_for_manager",
            AsyncMock(return_value=client),
        ),
        patch(
            "src.google_ads.customer_match.connection.get_pool",
            return_value=t_cm._pool_with_transactable_conn(),
        ),
        patch("src.google_ads.customer_match.ensure_account_access", AsyncMock()),
    ):
        result = await run_offline_user_data_job(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="1163862076",
            user_list_id="1234567890",
            operation_type="add",
            hashed_members=[{"hashed_email": "abc"}],
        )
    assert set(result) == set(ResultadoCustomerMatch.__annotations__)
