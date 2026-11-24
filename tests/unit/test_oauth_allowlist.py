"""Unit tests for OAuth callback allowlist decision tree (Phase 2 — Q8)."""

from uuid import uuid4

from src.auth.oauth import handle_callback_decision


def test_callback_gmail_convidado_promove():
    """A trava de dominio saiu: convidado de qualquer dominio entra."""
    response = handle_callback_decision(
        email="wellington.ribeiro.eng@gmail.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "invited", "is_active": True},
    )
    assert response.kind == "login"
    assert response.action == "promote_invited"


def test_callback_gmail_nao_convidado_nao_entra():
    """Fora da tabela `managers` continua barrado, qualquer que seja o dominio."""
    response = handle_callback_decision(
        email="alice@gmail.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=not_invited"


def test_callback_gmail_desativado_barrado():
    response = handle_callback_decision(
        email="alice@gmail.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "active", "is_active": False},
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=deactivated"


def test_callback_formato_invalido():
    response = handle_callback_decision(
        email="a@b@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "active", "is_active": True},
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=email"


def test_callback_active_email_logs_in():
    """status=active → login OK"""
    response = handle_callback_decision(
        email="wellinton.ribeiro@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "active", "is_active": True},
    )
    assert response.kind == "login"
    assert response.action is None


def test_callback_invited_email_promotes_to_active():
    response = handle_callback_decision(
        email="invitee@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "invited", "is_active": True},
    )
    assert response.kind == "login"
    assert response.action == "promote_invited"


def test_callback_inactive_email_redirects():
    response = handle_callback_decision(
        email="ex.gestor@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager={"id": uuid4(), "status": "inactive", "is_active": False},
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=deactivated"


def test_callback_not_invited_redirects():
    """Email is @v4company.com but not in allowlist and not in bootstrap"""
    response = handle_callback_decision(
        email="random@v4company.com",
        managers_table_empty=False,
        bootstrap_emails=set(),
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=not_invited"


def test_callback_bootstrap_when_table_empty():
    response = handle_callback_decision(
        email="boot@v4company.com",
        managers_table_empty=True,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "login"
    assert response.action == "bootstrap_admin"


def test_callback_bootstrap_ignored_when_table_populated():
    """Even if email matches bootstrap set, if managers exist, don't auto-create"""
    response = handle_callback_decision(
        email="boot@v4company.com",
        managers_table_empty=False,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "redirect"
    assert response.location == "/access-denied?reason=not_invited"


def test_callback_email_normalized_lowercase():
    """Mixed-case email matches lowercase bootstrap entry"""
    response = handle_callback_decision(
        email="BOOT@v4company.COM",
        managers_table_empty=True,
        bootstrap_emails={"boot@v4company.com"},
        existing_manager=None,
    )
    assert response.kind == "login"
    assert response.action == "bootstrap_admin"
