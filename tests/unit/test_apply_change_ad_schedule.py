"""apply_change de update_ad_schedule reconsulta a grade (spec §4.6): o ACK da mutacao
nao basta — a UI falhou em silencio duas vezes nessa conta."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.mcp.tools import apply_change as mod


@pytest.fixture(autouse=True)
def _ctx():
    from src.mcp.context import McpRequestContext, clear_current, set_current

    set_current(McpRequestContext(manager_id=uuid4(), session_id=uuid4()))
    yield
    clear_current()


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def acquire(self):
        return _FakeConn()


@pytest.mark.asyncio
async def test_apply_reconsulta_a_grade_e_devolve_resulting_schedule(monkeypatch) -> None:
    saved = SimpleNamespace(
        operation_type="update_ad_schedule",
        customer_id="1234567890",
        blast_summary="x",
        payload={
            "campaign_ids": ["1"],
            "ops": [
                {"kind": "remove", "resource_name": "customers/1234567890/campaignCriteria/1~9"}
            ],
            "__target_count__": 1,
            "__partial_failure__": True,
        },
    )

    async def _consume(conn, *, token, session_id):
        return saved

    async def _run_mutation(**kwargs):
        assert kwargs["partial_failure"] is True
        return {
            "provider_request_id": "req-1",
            "applied_count": 1,
            "changed_count": 1,
            "resource_names": ["customers/1234567890/campaignCriteria/1~9"],
        }

    async def _run_report(**kwargs):
        assert "FROM campaign_criterion" in kwargs["query"]
        return [
            {
                "campaign_id": "1",
                "campaign_name": "A",
                "criterion_id": "10",
                "resource_name": "customers/1234567890/campaignCriteria/1~10",
                "day_of_week": "MONDAY",
                "start_hour": 7,
                "start_minute": 0,
                "end_hour": 17,
                "end_minute": 0,
                "bid_modifier": None,
                "status": "ENABLED",
            }
        ]

    monkeypatch.setattr(mod, "consume", _consume)
    monkeypatch.setattr(mod, "run_mutation", _run_mutation)
    monkeypatch.setattr(mod, "run_report", _run_report)
    monkeypatch.setattr(mod.connection, "get_pool", lambda: _FakePool())

    out = await mod.apply_change({"confirmation_token": "ABCDEFGH"})
    assert out["status"] == "applied" and out["applied_count"] == 1 and out["changed_count"] == 1
    rs = out["resulting_schedule"]["1"]
    assert rs["has_schedule"] is True and rs["hours_per_week"] == 10.0
    assert rs["windows"][0]["day_of_week"] == "MONDAY"
