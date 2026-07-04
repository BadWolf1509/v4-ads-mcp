"""Regression tests for audit_log platform kwarg (Sprint M.2a Task 1).

Verifica que record() aceita platform kwarg + default "google" + persiste
column corretamente. Funciona em conjunto com Task 2 (migration 004 rename).
"""

from uuid import uuid4

import pytest

from src.db.repositories import audit_log, managers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_default_platform_is_google(db) -> None:
    """Backward compat: callers que não passam platform= continuam funcionando, default = 'google'."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="apgoog@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="1234567890",
            action_type="read",
            operation="list_my_accounts",
            status="success",
        )
        row = await conn.fetchrow("SELECT platform FROM audit_log WHERE id = $1", log_id)
        assert row is not None
        assert row["platform"] == "google"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_accepts_platform_meta(db) -> None:
    """Novo Meta tools podem passar platform='meta'."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="apmeta@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="act_999",
            action_type="read",
            operation="meta_list_my_ad_accounts",
            status="success",
            platform="meta",
        )
        row = await conn.fetchrow("SELECT platform FROM audit_log WHERE id = $1", log_id)
        assert row is not None
        assert row["platform"] == "meta"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_audit_log_writes_provider_request_id(db) -> None:
    """Regression: column renamed from provider_request_id (Task 2)."""
    async with db.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email="aprid@v4.com", full_name=None)
        log_id = await audit_log.record(
            conn,
            manager_id=mid,
            session_id=None,
            customer_id="act_999",
            action_type="read",
            operation="meta_list_my_ad_accounts",
            provider_request_id="x-fb-trace-id-123",
            status="success",
            platform="meta",
        )
        row = await conn.fetchrow(
            "SELECT provider_request_id, platform FROM audit_log WHERE id = $1", log_id
        )
        assert row is not None
        assert row["provider_request_id"] == "x-fb-trace-id-123"
        assert row["platform"] == "meta"
