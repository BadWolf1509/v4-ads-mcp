"""Tests for managers repository invite lifecycle (Phase 2 — Q8)."""

from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from src.db import connection, migrate
from src.db.repositories import managers


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
