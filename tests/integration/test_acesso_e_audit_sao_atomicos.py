"""Mudança de acesso e sua auditoria são atômicas.

Se a linha de auditoria falha depois do grant, o acesso mudou e ninguém sabe
quem mudou. Numa ferramenta cuja governança se apoia no `audit_log`, esse é o
pior desfecho possível — pior do que a mudança inteira falhar, porque falha
visível alguém conserta.

Postgres real, não mock: o comportamento em disputa é o rollback de uma
transação, que mock nenhum expressa.

As 12 rotas da Task 5 têm três formas de escrita diferentes (ver
tests/unit/test_structural_guards.py, que cobra as 12 por AST). Aqui só as
três formas são exercitadas de verdade, com banco:

- `admin_access_toggle`           — toggle único, via repositório (grant()).
- `admin_access_bulk_grant`       — bulk, via repositório (bulk_grant(), executemany).
- `admin_managers_toggle_active`  — SQL cru (UPDATE managers ... direto na rota).

As três rotas são chamadas como funções Python puras (a fixture é `db`, não
`client` — sem app FastAPI nem sessão HTTP no meio), com um `_FakeRequest`
mínimo e um `CurrentUser` construído a partir de um `Manager` real gravado
pela fixture `db`.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

from src.db.repositories import google_ads_accounts, managers
from src.web.deps import CurrentUser
from src.web.routes import admin_access, admin_overview


class _AuditLogWriteError(Exception):
    """Falha injetada no ponto de gravação do audit_log (`audit_log.record`)."""


class _FakeRequest:
    """As três rotas testadas só leem `request.headers` (HX-Request) — não
    precisa de um `Request` de verdade pra chamar a função da rota direto."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


async def _make_manager(conn, email: str, *, role: str = "gestor") -> managers.Manager:
    return await managers.create(conn, manager_id=uuid4(), email=email, full_name=None, role=role)


async def _make_account(conn, customer_id: str) -> None:
    await google_ads_accounts.upsert_many(
        conn,
        [{"customer_id": customer_id, "mcc_id": "6436352492", "descriptive_name": "Test"}],
    )


@pytest.mark.integration
async def test_admin_access_toggle_nao_persiste_grant_se_audit_falha(db) -> None:
    """Forma 1: toggle único via repositório (`manager_account_access.grant`).

    Sem transação, `grant()` já COMMITOU (é um `execute()` avulso, fora de
    qualquer `conn.transaction()`) quando `_audit_admin` levanta — o grant
    sobrevive à exceção porque não sobra nada pra dar rollback. Com transação,
    as duas escritas vivem ou morrem juntas.
    """
    async with db.acquire() as conn:
        admin_manager = await _make_manager(conn, "admin.toggle@v4company.com", role="admin")
        gestor = await _make_manager(conn, "gestor.toggle@v4company.com")
        await _make_account(conn, "1110000001")
    admin = CurrentUser(admin_manager)

    with (
        patch(
            "src.db.repositories.audit_log.record",
            side_effect=_AuditLogWriteError("audit indisponível"),
        ),
        pytest.raises(_AuditLogWriteError),
    ):
        await admin_access.admin_access_toggle(
            _FakeRequest(),
            user=admin,
            manager_id=str(gestor.id),
            customer_id="1110000001",
        )

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM manager_account_access WHERE manager_id = $1 AND customer_id = $2",
            gestor.id,
            "1110000001",
        )
    assert row is None, "o grant nao pode sobreviver a um audit_log.record que falhou"


@pytest.mark.integration
async def test_admin_access_bulk_grant_nao_persiste_se_audit_falha(db) -> None:
    """Forma 2: bulk via repositório (`manager_account_access.bulk_grant`,
    `executemany`) — estrutura de escrita diferente do toggle único."""
    async with db.acquire() as conn:
        admin_manager = await _make_manager(conn, "admin.bulk@v4company.com", role="admin")
        gestor = await _make_manager(conn, "gestor.bulk@v4company.com")
        await _make_account(conn, "1110000002")
        await _make_account(conn, "1110000003")
    admin = CurrentUser(admin_manager)

    with (
        patch(
            "src.db.repositories.audit_log.record",
            side_effect=_AuditLogWriteError("audit indisponível"),
        ),
        pytest.raises(_AuditLogWriteError),
    ):
        await admin_access.admin_access_bulk_grant(
            _FakeRequest(),
            user=admin,
            manager_id=str(gestor.id),
            customer_ids=["1110000002", "1110000003"],
        )

    async with db.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM manager_account_access WHERE manager_id = $1",
            gestor.id,
        )
    assert count == 0, "o bulk grant nao pode sobreviver a um audit_log.record que falhou"


@pytest.mark.integration
async def test_admin_managers_toggle_active_nao_persiste_se_audit_falha(db) -> None:
    """Forma 3: SQL cru (`UPDATE managers SET is_active = NOT is_active ...`)
    direto na rota, sem passar por repositório — a forma que as duas medições
    anteriores do brief perderam (ver task-5-brief.md, correção de 2026-09-17)."""
    async with db.acquire() as conn:
        admin_manager = await _make_manager(conn, "admin.raw@v4company.com", role="admin")
        gestor = await _make_manager(conn, "gestor.raw@v4company.com")
    admin = CurrentUser(admin_manager)
    assert gestor.is_active is True

    with (
        patch(
            "src.db.repositories.audit_log.record",
            side_effect=_AuditLogWriteError("audit indisponível"),
        ),
        pytest.raises(_AuditLogWriteError),
    ):
        await admin_overview.admin_managers_toggle_active(
            _FakeRequest(),
            manager_id=gestor.id,
            user=admin,
        )

    async with db.acquire() as conn:
        is_active = await conn.fetchval("SELECT is_active FROM managers WHERE id = $1", gestor.id)
    assert is_active is True, "o toggle nao pode sobreviver a um audit_log.record que falhou"
