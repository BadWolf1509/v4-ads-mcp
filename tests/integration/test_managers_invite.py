"""Tests for managers repository invite lifecycle (Phase 2 — Q8)."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import manager_account_access, managers


@pytest.fixture
async def pg() -> PostgresContainer:
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture
async def db(pg):
    dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield connection.get_pool()
    finally:
        await connection.close_pool()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_invited_marks_status_invited(db):
    inviter_id = uuid4()
    pool = db
    # Insert a fake admin to be the inviter (FK).
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role)
               VALUES ($1, 'admin@v4company.com', 'active', 'admin')""",
            inviter_id,
        )

    async with pool.acquire() as conn:
        invitee = await managers.create_invited(
            conn,
            email="newgestor@v4company.com",
            invited_by=inviter_id,
            full_name="New Gestor",
        )

    assert invitee.email == "newgestor@v4company.com"
    assert invitee.status == "invited"
    assert invitee.role == "gestor"
    assert invitee.invited_by == inviter_id
    assert invitee.invited_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mark_active_only_invited(db):
    """mark_active flips invited -> active. Should NOT promote inactive -> active."""
    pool = db
    inviter = uuid4()
    invited_id = uuid4()
    inactive_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'admin@v4company.com', 'active', 'admin'),
               ($2, 'invited@v4company.com', 'invited', 'gestor'),
               ($3, 'inactive@v4company.com', 'inactive', 'gestor')""",
            inviter,
            invited_id,
            inactive_id,
        )

    async with pool.acquire() as conn:
        ok = await managers.mark_active(conn, manager_id=invited_id)
        assert ok is True

        ok = await managers.mark_active(conn, manager_id=inactive_id)
        assert ok is False

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT email, status FROM managers WHERE id IN ($1, $2)",
            invited_id,
            inactive_id,
        )
    statuses = {r["email"]: r["status"] for r in rows}
    assert statuses["invited@v4company.com"] == "active"
    assert statuses["inactive@v4company.com"] == "inactive"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_invited_returns_only_invited(db):
    pool = db
    inviter = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'admin@v4company.com', 'active', 'admin'),
               ($2, 'pending1@v4company.com', 'invited', 'gestor'),
               ($3, 'pending2@v4company.com', 'invited', 'gestor'),
               ($4, 'active@v4company.com', 'active', 'gestor')""",
            inviter,
            uuid4(),
            uuid4(),
            uuid4(),
        )

    async with pool.acquire() as conn:
        invited = await managers.list_invited(conn)

    emails = {m.email for m in invited}
    assert "pending1@v4company.com" in emails
    assert "pending2@v4company.com" in emails
    assert "admin@v4company.com" not in emails
    assert "active@v4company.com" not in emails


@pytest.mark.integration
@pytest.mark.asyncio
async def test_delete_invite_only_if_invited(db):
    pool = db
    inviter = uuid4()
    invited_id = uuid4()
    active_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'admin@v4company.com', 'active', 'admin'),
               ($2, 'pending@v4company.com', 'invited', 'gestor'),
               ($3, 'active@v4company.com', 'active', 'gestor')""",
            inviter,
            invited_id,
            active_id,
        )

    async with pool.acquire() as conn:
        deleted = await managers.delete_invite(conn, manager_id=invited_id)
        assert deleted is True

        deleted = await managers.delete_invite(conn, manager_id=active_id)
        assert deleted is False

    async with pool.acquire() as conn:
        active_still_there = await conn.fetchval("SELECT 1 FROM managers WHERE id = $1", active_id)
        invited_gone = await conn.fetchval("SELECT 1 FROM managers WHERE id = $1", invited_id)
    assert active_still_there == 1
    assert invited_gone is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_count_invited(db):
    pool = db
    async with pool.acquire() as conn:
        # empty table
        n = await managers.count_invited(conn)
        assert n == 0

        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'a@v4company.com', 'invited', 'gestor'),
               ($2, 'b@v4company.com', 'invited', 'gestor'),
               ($3, 'c@v4company.com', 'active', 'admin')""",
            uuid4(),
            uuid4(),
            uuid4(),
        )

    async with pool.acquire() as conn:
        n = await managers.count_invited(conn)
    assert n == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_count_all(db):
    pool = db
    async with pool.acquire() as conn:
        assert await managers.count_all(conn) == 0
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'a@v4company.com', 'invited', 'gestor'),
               ($2, 'b@v4company.com', 'active', 'admin')""",
            uuid4(),
            uuid4(),
        )
    async with pool.acquire() as conn:
        assert await managers.count_all(conn) == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_grant_idempotent(db):
    mid = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES ($1, 'a@v4company.com', 'active', 'gestor')""",
            mid,
        )
        await conn.execute(
            """INSERT INTO google_ads_accounts (customer_id, descriptive_name, mcc_id, synced_at) VALUES
               ('1111111111', 'A', '6436352492', now()),
               ('2222222222', 'B', '6436352492', now()),
               ('3333333333', 'C', '6436352492', now())"""
        )
        await manager_account_access.bulk_grant(
            conn,
            manager_id=mid,
            customer_ids=["1111111111", "2222222222"],
            granted_by=mid,
        )
        # Re-run with overlap — should be idempotent
        await manager_account_access.bulk_grant(
            conn,
            manager_id=mid,
            customer_ids=["2222222222", "3333333333"],
            granted_by=mid,
        )
        rows = await conn.fetch(
            "SELECT customer_id FROM manager_account_access WHERE manager_id = $1", mid
        )
    cids = sorted([r["customer_id"] for r in rows])
    assert cids == ["1111111111", "2222222222", "3333333333"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_copy_access_replaces_destination(db):
    src = uuid4()
    dst = uuid4()
    pool = db
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO managers (id, email, status, role) VALUES
               ($1, 'src@v4company.com', 'active', 'gestor'),
               ($2, 'dst@v4company.com', 'active', 'gestor')""",
            src,
            dst,
        )
        await conn.execute(
            """INSERT INTO google_ads_accounts (customer_id, descriptive_name, mcc_id, synced_at) VALUES
               ('1111111111', 'A', '6436352492', now()),
               ('2222222222', 'B', '6436352492', now()),
               ('3333333333', 'C', '6436352492', now())"""
        )
        # src has 1+2; dst has 3
        await conn.execute(
            """INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by) VALUES
               ($1, '1111111111', 'write', $1),
               ($1, '2222222222', 'write', $1),
               ($2, '3333333333', 'write', $2)""",
            src,
            dst,
        )
        await manager_account_access.copy_access(
            conn,
            from_manager_id=src,
            to_manager_id=dst,
            granted_by=src,
        )
        # After copy: dst should have 1+2 (replaced 3)
        rows = await conn.fetch(
            "SELECT customer_id FROM manager_account_access WHERE manager_id = $1", dst
        )
    assert sorted([r["customer_id"] for r in rows]) == ["1111111111", "2222222222"]
