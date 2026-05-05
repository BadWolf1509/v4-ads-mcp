"""Unit tests for OAuth callback allowlist decision tree (Phase 2 — Q8)."""

from uuid import uuid4

import pytest

from src.auth.oauth import handle_callback_decision


@pytest.mark.asyncio
async def test_callback_rejects_non_v4_domain():
    """Email outside @v4company.com → /access-denied?reason=domain"""
    response = await handle_callback_decision(
        email="alice@gmail.com",
        google_id="g123",
        google_email="alice@gmail.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=domain"


@pytest.mark.asyncio
async def test_callback_active_email_logs_in():
    """status=active → login OK"""
    response = await handle_callback_decision(
        email="wellinton.ribeiro@v4company.com",
        google_id="g123",
        google_email="wellinton.ribeiro@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "active", "is_active": True},
    )
    assert response.kind == "login"
    assert response.action is None


@pytest.mark.asyncio
async def test_callback_invited_email_promotes_to_active():
    response = await handle_callback_decision(
        email="invitee@v4company.com",
        google_id="g123",
        google_email="invitee@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "invited", "is_active": True},
    )
    assert response.kind == "login"
    assert response.action == "promote_invited"


@pytest.mark.asyncio
async def test_callback_inactive_email_redirects():
    response = await handle_callback_decision(
        email="ex.gestor@v4company.com",
        google_id="g123",
        google_email="ex.gestor@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "inactive", "is_active": False},
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=deactivated"


@pytest.mark.asyncio
async def test_callback_not_invited_redirects():
    """Email is @v4company.com but not in allowlist and not in bootstrap"""
    response = await handle_callback_decision(
        email="random@v4company.com",
        google_id="g123",
        google_email="random@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=not_invited"


@pytest.mark.asyncio
async def test_callback_bootstrap_when_table_empty():
    response = await handle_callback_decision(
        email="boot@v4company.com",
        google_id="g123",
        google_email="boot@v4company.com",
        managers_table_empty=True,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "login"
    assert response.action == "bootstrap_admin"


@pytest.mark.asyncio
async def test_callback_bootstrap_ignored_when_table_populated():
    """Even if email matches bootstrap set, if managers exist, don't auto-create"""
    response = await handle_callback_decision(
        email="boot@v4company.com",
        google_id="g123",
        google_email="boot@v4company.com",
        managers_table_empty=False,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=not_invited"


@pytest.mark.asyncio
async def test_callback_email_normalized_lowercase():
    """Mixed-case email matches lowercase bootstrap entry"""
    response = await handle_callback_decision(
        email="BOOT@v4company.COM",
        google_id="g123",
        google_email="BOOT@v4company.COM",
        managers_table_empty=True,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "login"
    assert response.action == "bootstrap_admin"
