"""Seeds compartilhados dos testes de integracao (dados ficticios).

Os helpers criam o minimo que o gate e as sessoes exigem. O e-mail e unico
por padrao (`t-<hex>@v4company.com`), entao dois seeds no mesmo banco nao
colidem; um teste que afirma ou reutiliza o e-mail passa `email=` explicito.
"""

from uuid import UUID, uuid4

import asyncpg

from src.auth.sessions import generate_session_token, hash_session_token
from src.db.repositories import (
    google_ads_accounts,
    manager_account_access,
    manager_meta_account_access,
    managers,
    mcp_sessions,
    meta_ad_accounts,
)


async def seed_manager(
    conn: asyncpg.Connection, *, email: str | None = None, role: str = "gestor"
) -> UUID:
    """Cria um gestor (papel `gestor` ou `admin`) e devolve o id."""
    manager = await managers.create(
        conn,
        manager_id=uuid4(),
        email=email or f"t-{uuid4().hex[:8]}@v4company.com",
        full_name=None,
        role=role,
    )
    return manager.id


async def seed_manager_with_session(
    conn: asyncpg.Connection, *, label: str = "t", **kw: str | None
) -> tuple[UUID, UUID, str]:
    """Gestor + sessao MCP: devolve (manager_id, session_id, token em texto puro)."""
    manager_id = await seed_manager(conn, **kw)  # type: ignore[arg-type]
    token = generate_session_token()
    session = await mcp_sessions.create(
        conn, manager_id=manager_id, token_hash=hash_session_token(token), label=label
    )
    return manager_id, session.id, token


async def grant_google(conn: asyncpg.Connection, manager_id: UUID, customer_id: str) -> None:
    """Cria a conta Google (se faltar) e concede acesso `write` ao gestor."""
    await google_ads_accounts.upsert_many(
        conn,
        [{"customer_id": customer_id, "mcc_id": "0000000000", "descriptive_name": "Test"}],
    )
    await manager_account_access.grant(
        conn,
        manager_id=manager_id,
        customer_id=customer_id,
        access_level="write",
        granted_by=manager_id,
    )


async def seed_meta_account(
    conn: asyncpg.Connection,
    manager_id: UUID,
    *,
    ad_account_id: str = "act_123456",
    account_status: int = 1,
) -> None:
    """Cria a conta Meta no inventario e concede acesso ao gestor."""
    await meta_ad_accounts.upsert_many(
        conn,
        [
            {
                "ad_account_id": ad_account_id,
                "business_id": "bm_test",
                "business_name": "Test BM",
                "account_name": "Test Account",
                "currency": "BRL",
                "timezone_name": "America/Sao_Paulo",
                "account_status": account_status,
            }
        ],
    )
    await manager_meta_account_access.grant(
        conn, manager_id=manager_id, ad_account_id=ad_account_id
    )
