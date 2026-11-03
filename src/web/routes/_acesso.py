"""Escrita de acesso a contas, uma vez para Google e Meta.

As rotas gêmeas de `admin_access.py` (toggle, bulk-grant, bulk-copy) faziam a
mesma coisa com tabela, coluna e plataforma do audit trocadas. A diferença
mora agora em `PlataformaAcesso`; a regra (idempotência do toggle, acesso e
audit numa transação só) mora aqui, uma vez.

Cada helper abre a PRÓPRIA `conn.transaction()` em volta da escrita e do
`_audit_admin` (Task 5, F91): se o audit falha depois do grant, os dois
desfazem juntos. Quem chama passa uma conexão crua do pool, nunca
`run_with_reconnect` — retry de escrita pode duplicar a mutação.
"""

from dataclasses import dataclass
from types import ModuleType
from typing import Literal
from uuid import UUID

import asyncpg

from src.db.repositories import manager_account_access, manager_meta_account_access
from src.web.deps import CurrentUser
from src.web.routes._shared import _audit_admin


@dataclass(frozen=True)
class PlataformaAcesso:
    """O que separa a rota Google da Meta.

    repositorio: módulo com `grant`/`revoke`/`bulk_grant`/`copy_access`.
    coluna_conta: nome da coluna (e do kwarg do repositório) da conta.
    campo_lista: kwarg de `bulk_grant` com a lista de contas.
    plataforma_audit: `platform` gravado em `audit_log`.
    prefixo_url: raiz das rotas no painel.
    sql_acesso_vivo: SELECT do grant vivo (`revoked_at IS NULL`) do par
        (gestor, conta) — linha revogada é soft e fica, então sem o filtro o
        toggle chamaria revoke() de novo em vez de reconceder.
    """

    repositorio: ModuleType
    coluna_conta: Literal["customer_id", "ad_account_id"]
    campo_lista: Literal["customer_ids", "ad_account_ids"]
    plataforma_audit: Literal["google", "meta"]
    prefixo_url: str
    sql_acesso_vivo: str


PLATAFORMAS: dict[Literal["google", "meta"], PlataformaAcesso] = {
    "google": PlataformaAcesso(
        repositorio=manager_account_access,
        coluna_conta="customer_id",
        campo_lista="customer_ids",
        plataforma_audit="google",
        prefixo_url="/admin/access",
        sql_acesso_vivo=(
            "SELECT 1 FROM manager_account_access "
            "WHERE manager_id = $1 AND customer_id = $2 AND revoked_at IS NULL"
        ),
    ),
    "meta": PlataformaAcesso(
        repositorio=manager_meta_account_access,
        coluna_conta="ad_account_id",
        campo_lista="ad_account_ids",
        plataforma_audit="meta",
        prefixo_url="/admin/access/meta",
        sql_acesso_vivo=(
            "SELECT 1 FROM manager_meta_account_access "
            "WHERE manager_id = $1 AND ad_account_id = $2 AND revoked_at IS NULL"
        ),
    ),
}


async def aplicar_toggle(
    conn: asyncpg.Connection,
    plataforma: PlataformaAcesso,
    *,
    admin: CurrentUser,
    manager_id: UUID,
    conta: str,
    desejado: bool,
) -> bool:
    """Aplica o estado PEDIDO (`desejado`), não "o contrário do que o banco tem".

    Aba velha ou duplo clique pedem o que já é verdade: nada muda e nada é
    auditado. Devolve `mudou`.
    """
    existe = await conn.fetchval(plataforma.sql_acesso_vivo, manager_id, conta)
    mudou = desejado != bool(existe)
    async with conn.transaction():
        if mudou:
            alvo = {plataforma.coluna_conta: conta}
            if desejado:
                await plataforma.repositorio.grant(
                    conn,
                    manager_id=manager_id,
                    access_level="write",
                    granted_by=admin.id,
                    **alvo,
                )
            else:
                await plataforma.repositorio.revoke(conn, manager_id=manager_id, **alvo)
            await _audit_admin(
                conn,
                admin=admin,
                operation="admin_access_grant" if desejado else "admin_access_revoke",
                customer_id=conta,
                platform=plataforma.plataforma_audit,
                target_manager_id=str(manager_id),
                granted=desejado,
            )
    return mudou


async def conceder_em_massa(
    conn: asyncpg.Connection,
    plataforma: PlataformaAcesso,
    *,
    admin: CurrentUser,
    manager_id: UUID,
    contas: list[str],
) -> None:
    """Concede (ou restaura) acesso de escrita a `contas`, com audit."""
    async with conn.transaction():
        await plataforma.repositorio.bulk_grant(
            conn,
            manager_id=manager_id,
            granted_by=admin.id,
            **{plataforma.campo_lista: contas},
        )
        await _audit_admin(
            conn,
            admin=admin,
            operation="admin_access_bulk_grant",
            platform=plataforma.plataforma_audit,
            target_manager_id=str(manager_id),
            count=len(contas),
            ids=contas[:20],
        )


async def copiar_acessos(
    conn: asyncpg.Connection,
    plataforma: PlataformaAcesso,
    *,
    admin: CurrentUser,
    de_manager_id: UUID,
    para_manager_id: UUID,
) -> None:
    """Substitui o acesso vivo do destino pelo da origem, com audit.

    `copy_access` abre a própria transação; aninhada nesta vira SAVEPOINT
    (idioma padrão asyncpg). Origem == destino é barrado antes, na rota.
    """
    async with conn.transaction():
        await plataforma.repositorio.copy_access(
            conn,
            from_manager_id=de_manager_id,
            to_manager_id=para_manager_id,
            granted_by=admin.id,
        )
        await _audit_admin(
            conn,
            admin=admin,
            operation="admin_access_bulk_copy",
            platform=plataforma.plataforma_audit,
            from_manager_id=str(de_manager_id),
            to_manager_id=str(para_manager_id),
        )
