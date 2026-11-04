"""apply_change end-to-end with mocked Google Ads SDK."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db.repositories import managers, mcp_sessions
from src.governance.dry_run import create_pending
from src.mcp.context import McpRequestContext, clear_current, set_current


@pytest.fixture
async def session_ctx(db):
    pool = db
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="t@v4.com", full_name=None)
        from src.auth.sessions import generate_session_token, hash_session_token

        token = generate_session_token()
        sess = await mcp_sessions.create(
            conn, manager_id=mid, token_hash=hash_session_token(token), label="t"
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


@pytest.mark.integration
async def test_apply_change_executes_mutation(db, session_ctx):
    """Token saved as 'update_campaign_status' is consumed and a mock mutation is run."""
    from src.mcp.tools.apply_change import apply_change

    pool = db
    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
        async with pool.acquire() as conn:
            token = await create_pending(
                conn,
                manager_id=session_ctx.manager_id,
                session_id=session_ctx.session_id,
                customer_id="1234567890",
                operation_type="update_campaign_status",
                payload={
                    "campaign_ids": ["111"],
                    "new_status": "PAUSED",
                    "__target_count__": 1,
                },
                blast_summary="Pausar campanha 111",
            )

    fake_client = MagicMock()
    fake_service = MagicMock()
    fake_response = MagicMock()
    fake_service.mutate = MagicMock(return_value=fake_response)
    fake_client.get_service = MagicMock(return_value=fake_service)
    fake_client.get_type = MagicMock(return_value=MagicMock(mutate_operations=[]))

    with (
        patch(
            "src.google_ads.mutations.ensure_account_access",
            AsyncMock(return_value=None),
        ),
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch(
            "src.google_ads.mutations.get_builder",
            return_value=lambda c, cid, p: [MagicMock()],
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="fake-google-request-id",
        ),
    ):
        result = await apply_change({"confirmation_token": token})

    assert result["status"] == "applied"
    assert result["operation"] == "update_campaign_status"
    assert result["provider_request_id"] == "fake-google-request-id"


@pytest.mark.integration
async def test_apply_change_returns_error_on_invalid_token(db, session_ctx):
    from src.mcp.tools.apply_change import apply_change

    result = await apply_change({"confirmation_token": "ABCD1234"})
    assert result["status"] == "error"
    assert result["operation"] == "apply_change"
    assert "not found" in result["error_message"]


async def _token(pool, ctx, operation_type: str, payload: dict) -> str:
    with patch("src.governance.dry_run.ensure_account_access", AsyncMock(return_value=None)):
        async with pool.acquire() as conn:
            return await create_pending(
                conn,
                manager_id=ctx.manager_id,
                session_id=ctx.session_id,
                customer_id="1234567890",
                operation_type=operation_type,
                payload=payload,
                blast_summary="resumo",
            )


@pytest.mark.integration
async def test_token_e_consumido_uma_vez_e_antes_da_escrita(db, session_ctx):
    """Caracterizacao G5: a escrita sai uma vez; o mesmo token nao escreve de novo."""
    from src.mcp.tools.apply_change import apply_change

    token = await _token(
        db, session_ctx, "update_campaign_status", {"campaign_ids": ["1"], "__target_count__": 1}
    )
    escrita = AsyncMock(return_value={"provider_request_id": "r", "applied_count": 1})
    with patch("src.mcp.tools.apply_change.run_mutation", escrita):
        primeira = await apply_change({"confirmation_token": token})
        segunda = await apply_change({"confirmation_token": token})

    assert primeira["status"] == "applied"
    assert escrita.await_count == 1
    assert segunda["status"] == "error"
    assert "already consumed" in segunda["error_message"]


@pytest.mark.integration
async def test_pre_check_que_recusa_ja_encontrou_o_token_consumido(db, session_ctx):
    """Caracterizacao G5: o consumo vem ANTES do pre-check. Uma recusa nao escreve, e
    o token recusado nao serve mais — a mensagem manda gerar um novo."""
    from src.mcp.tools.apply_change import apply_change

    token = await _token(
        db,
        session_ctx,
        "apply_recommendation",
        {
            "recommendation_resource_name": "customers/1234567890/recommendations/abc",
            "__target_count__": 1,
            "valores_do_preview": {
                "type": "CAMPAIGN_BUDGET",
                "current_amount_brl": 50.0,
                "recommended_amount_brl": 180.0,
                "valores": {},
            },
        },
    )
    escrita = AsyncMock(return_value={"provider_request_id": "r", "applied_count": 1})
    with (
        patch("src.mcp.tools.apply_change.run_report", AsyncMock(return_value=[])),
        patch("src.mcp.tools.apply_change.run_recommendation_action", escrita),
    ):
        recusa = await apply_change({"confirmation_token": token})
        de_novo = await apply_change({"confirmation_token": token})

    assert recusa["status"] == "error"
    assert "nao esta mais pendente" in recusa["error_message"]
    assert escrita.await_count == 0
    assert de_novo["status"] == "error"
    assert "already consumed" in de_novo["error_message"]
