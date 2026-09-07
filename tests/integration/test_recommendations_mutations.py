"""Integration tests for recommendation mutation tools."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
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
    # Seed google_ads_accounts + grant write access so ensure_account_access passes.
    async with pool.acquire() as conn:
        await google_ads_accounts.upsert_many(
            conn,
            [{"customer_id": "1234567890", "mcc_id": "0000000000", "descriptive_name": "Test"}],
        )
        await manager_account_access.grant(
            conn, manager_id=mid, customer_id="1234567890", access_level="write", granted_by=mid
        )
    ctx = McpRequestContext(manager_id=mid, session_id=sess.id)
    set_current(ctx)
    yield ctx
    clear_current()


def _fake_client_with_response():
    fc = MagicMock()
    fr = MagicMock()
    fs = MagicMock()
    fs.apply_recommendation = MagicMock(return_value=fr)
    fs.dismiss_recommendation = MagicMock(return_value=fr)
    fc.get_service = MagicMock(return_value=fs)
    fc.get_type = MagicMock(return_value=MagicMock())
    return fc


_REC_RN = "customers/1234567890/recommendations/abc"


def _fake_lookup(tipo: str):
    """`run_report` falso pro lookup de tipo/detalhe do apply_recommendation (C2).

    A row e um `Recommendation()` de verdade — proto-plus devolve o zero-value do
    campo que a GAQL nao pediu (F145), entao um dict pronto aqui esconderia campo
    removido do SELECT.
    """
    from google.ads.googleads.v24.enums.types.recommendation_type import RecommendationTypeEnum
    from google.ads.googleads.v24.resources.types.recommendation import Recommendation

    async def _run(**kwargs):
        query = kwargs["query"]
        fmt = kwargs["row_formatter"]
        if "FROM campaign" in query:
            campaign = SimpleNamespace(
                id=99,
                name="Campanha de teste",
                status="ENABLED",
                bidding_strategy_type="MAXIMIZE_CONVERSIONS",
            )
            return [
                fmt(
                    SimpleNamespace(
                        campaign=campaign, campaign_budget=SimpleNamespace(amount_micros=50_000_000)
                    )
                )
            ]
        rec = Recommendation()
        rec.type_ = RecommendationTypeEnum.RecommendationType[tipo]
        rec.resource_name = _REC_RN
        rec.campaign = "customers/1234567890/campaigns/99"
        if tipo == "CAMPAIGN_BUDGET":
            rec.campaign_budget_recommendation.current_budget_amount_micros = 50_000_000
            rec.campaign_budget_recommendation.recommended_budget_amount_micros = 180_000_000
        return [fmt(SimpleNamespace(recommendation=rec))]

    return _run


@pytest.mark.integration
async def test_apply_recommendation_de_keyword_auto_aplica(db, session_ctx):
    """Contraprova do gate C2: tipo fora da familia orcamento/lance segue auto."""
    from src.mcp.tools import apply_recommendation as mod

    with (
        patch.object(mod, "run_report", _fake_lookup("KEYWORD")),
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client_with_response()),
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-apply",
        ),
    ):
        result = await mod.apply_recommendation(
            {"customer_id": "1234567890", "recommendation_resource_name": _REC_RN}
        )

    assert result["status"] == "applied"
    assert result["operation"] == "apply_recommendation"
    assert result["provider_request_id"] == "req-apply"


@pytest.mark.integration
async def test_apply_recommendation_de_orcamento_so_aplica_via_apply_change(db, session_ctx):
    """C2 ponta a ponta: orcamento vira token no banco, e o token de fato aplica.

    Fecha as DUAS metades. A primeira: a recomendacao de orcamento nao toca o
    RecommendationService sem confirmacao. A segunda (F150): o token emitido
    precisa ter um executor do outro lado — sem o ramo no `apply_change`, ele
    cairia no `run_mutation`, que so sabe montar operacoes do
    GoogleAdsService.mutate, e a tool preveria sem nunca aplicar.
    """
    from src.mcp.tools import apply_recommendation as mod
    from src.mcp.tools.apply_change import apply_change

    with patch.object(mod, "run_report", _fake_lookup("CAMPAIGN_BUDGET")):
        preview = await mod.apply_recommendation(
            {"customer_id": "1234567890", "recommendation_resource_name": _REC_RN}
        )

    assert preview["status"] == "dry_run"
    assert preview["current_amount_brl"] == 50.0
    assert preview["recommended_amount_brl"] == 180.0
    token = preview["confirmation_token"]

    fake_client = _fake_client_with_response()
    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=fake_client),
        ),
        patch("src.google_ads.mutations.get_request_id", return_value="req-confirmado"),
    ):
        aplicado = await apply_change({"confirmation_token": token})

    assert aplicado["status"] == "applied"
    assert aplicado["operation"] == "apply_recommendation"
    assert aplicado["provider_request_id"] == "req-confirmado"
    assert aplicado["applied_count"] == 1
    # O blast_summary reexibido tem que carregar os numeros (e o que o gestor le
    # dez minutos depois, na hora de confirmar).
    assert "50" in aplicado["blast_summary"] and "180" in aplicado["blast_summary"]
    # Foi pelo RecommendationService, nao pelo GoogleAdsService.mutate.
    fake_client.get_service.assert_called_with("RecommendationService", interceptors=ANY)


@pytest.mark.integration
async def test_dismiss_recommendation_auto_applies(db, session_ctx):
    from src.mcp.tools.dismiss_recommendation import dismiss_recommendation

    with (
        patch(
            "src.google_ads.mutations.build_client_for_manager",
            AsyncMock(return_value=_fake_client_with_response()),
        ),
        patch(
            "src.google_ads.mutations.get_request_id",
            return_value="req-dismiss",
        ),
    ):
        result = await dismiss_recommendation(
            {
                "customer_id": "1234567890",
                "recommendation_resource_name": "customers/1234567890/recommendations/xyz",
            }
        )

    assert result["status"] == "applied"
    assert result["operation"] == "dismiss_recommendation"
    assert result["provider_request_id"] == "req-dismiss"
