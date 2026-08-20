"""CRUD for `manager_meta_account_access` (which manager can operate which Meta ad account)."""

from uuid import UUID

import asyncpg

from src.db.repositories.meta_ad_accounts import MetaAdAccount, _row_to_account

# Motivo gravado quando o reconciliador (job) revoga acesso por a conta ter
# saido da parceria. Constante — nao string livre — porque `restore_for_account`
# filtra por este MESMO valor: se o caller de `revoke_for_account` passasse
# outro texto (typo, refactor), o restore filtraria por um motivo que nenhuma
# linha tem e devolveria zero silenciosamente, sem erro.
PARTNERSHIP_ENDED_REASON = "partnership_ended"


async def grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_id: str,
    access_level: str = "write",
    granted_by: UUID | None = None,
) -> None:
    """Reconceder é a forma de restaurar (spec 2026-08-20): se a linha já existia
    revogada (`revoke` agora é soft), o ON CONFLICT limpa `revoked_at`/
    `revoked_reason` em vez de só atualizar `access_level` — senão o toggle do
    painel "concede" e o gate continua negando, porque a linha segue revogada.
    """
    await conn.execute(
        """
        INSERT INTO manager_meta_account_access
            (manager_id, ad_account_id, access_level, granted_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, ad_account_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by,
            revoked_at = NULL,
            revoked_reason = NULL
        """,
        manager_id,
        ad_account_id,
        access_level,
        granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    granted_by: UUID | None = None,
) -> int:
    """Grant write access to every active meta_ad_accounts row for this manager."""
    result = await conn.execute(
        """
        INSERT INTO manager_meta_account_access
            (manager_id, ad_account_id, access_level, granted_by)
        SELECT $1, ad_account_id, 'write', $2
        FROM meta_ad_accounts
        WHERE is_active = true
        ON CONFLICT (manager_id, ad_account_id) DO NOTHING
        """,
        manager_id,
        granted_by,
    )
    return int(result.split()[-1]) if result.startswith("INSERT") else 0


async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_id: str,
    reason: str = "manual",
) -> None:
    """Revogação SOFT (spec 2026-08-20): a linha fica, só marca `revoked_at`.

    Era DELETE. Curadoria de acesso é trabalho humano — apagar a linha perderia
    quem tinha acesso quando a parceria (ou o gestor) volta.
    """
    await conn.execute(
        """
        UPDATE manager_meta_account_access
           SET revoked_at = now(), revoked_reason = $3
         WHERE manager_id = $1 AND ad_account_id = $2
        """,
        manager_id,
        ad_account_id,
        reason,
    )


async def revoke_for_account(
    conn: asyncpg.Connection, *, ad_account_id: str, reason: str
) -> list[UUID]:
    """Revogação SOFT de todos os grants vivos da conta; devolve os atingidos.

    A linha fica: sem ela não há o que restaurar quando a parceria volta, só
    refazer à mão — e a curadoria de quem tinha acesso é trabalho humano.
    """
    rows = await conn.fetch(
        """
        UPDATE manager_meta_account_access
           SET revoked_at = now(), revoked_reason = $2
         WHERE ad_account_id = $1 AND revoked_at IS NULL
        RETURNING manager_id
        """,
        ad_account_id,
        reason,
    )
    return [r["manager_id"] for r in rows]


async def restore_for_account(conn: asyncpg.Connection, *, ad_account_id: str) -> int:
    """Desfaz `revoke_for_account` — SO o que o churn revogou, nada mais.

    I4 (fix round 2): restaurar sem filtrar `revoked_reason` devolveria
    tambem um acesso que um admin tirou de proposito por outro motivo (ex.:
    `copy_access` substituindo, ou um `revoke` manual) so porque a MESMA
    conta reapareceu na parceria depois — confundindo "a conta voltou" com
    "desfaça toda revogação que essa conta acumulou". Restore existe pra UMA
    coisa: desfazer exatamente o que `revoke_for_account` revogou quando a
    parceria saiu — por isso filtra a mesma razão que esse caminho grava.
    """
    rows = await conn.fetch(
        """
        UPDATE manager_meta_account_access
           SET revoked_at = NULL, revoked_reason = NULL
         WHERE ad_account_id = $1
           AND revoked_at IS NOT NULL
           AND revoked_reason = $2
        RETURNING manager_id
        """,
        ad_account_id,
        PARTNERSHIP_ENDED_REASON,
    )
    return len(rows)


async def list_accounts_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[MetaAdAccount]:
    """Return MetaAdAccount rows the manager has any access to (active accounts only)."""
    rows = await conn.fetch(
        """
        SELECT a.*
        FROM meta_ad_accounts a
        INNER JOIN manager_meta_account_access m ON m.ad_account_id = a.ad_account_id
        WHERE m.manager_id = $1
          AND a.is_active = true
          AND m.revoked_at IS NULL
        ORDER BY a.account_name
        """,
        manager_id,
    )
    return [_row_to_account(r) for r in rows]


async def can_manager_access(
    conn: asyncpg.Connection,
    manager_id: UUID,
    ad_account_id: str,
    *,
    level: str = "read",
) -> bool:
    """Gate do Modelo B — e a ÚNICA fronteira que sobra.

    O token de system user entrega tudo que o BM alcança, então a Meta não nega
    nada por nós (confused deputy). Por isso o gate cruza com o inventário: conta
    fora da parceria é negada aqui mesmo que o reconciliador ainda não tenha
    rodado, e grant revogado não vale.
    """
    row = await conn.fetchrow(
        """
        SELECT m.access_level
          FROM manager_meta_account_access m
          JOIN meta_ad_accounts a ON a.ad_account_id = m.ad_account_id
         WHERE m.manager_id = $1
           AND m.ad_account_id = $2
           AND m.revoked_at IS NULL
           AND a.is_active = true
        """,
        manager_id,
        ad_account_id,
    )
    if row is None:
        return False
    if level == "read":
        return True
    return bool(row["access_level"] == "write")


async def bulk_grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_ids: list[str],
    granted_by: UUID,
    access_level: str = "write",
) -> int:
    """Idempotent bulk grant. Inserts rows that don't exist; restores revoked ones.

    Returns len(ad_account_ids) — not the count of rows actually inserted.
    executemany with ON CONFLICT does not expose per-batch counts.

    Reconceder é a forma de restaurar (spec 2026-08-20): se a linha já existia
    revogada, o ON CONFLICT limpa `revoked_at`/`revoked_reason` em vez de
    ignorar — senão o gestor readicionado numa bulk-grant continuaria bloqueado
    pelo gate.
    """
    if not ad_account_ids:
        return 0
    rows = [(manager_id, aid, access_level, granted_by) for aid in ad_account_ids]
    await conn.executemany(
        """INSERT INTO manager_meta_account_access
               (manager_id, ad_account_id, access_level, granted_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (manager_id, ad_account_id) DO UPDATE SET
               revoked_at = NULL,
               revoked_reason = NULL""",
        rows,
    )
    return len(rows)


async def copy_access(
    conn: asyncpg.Connection,
    *,
    from_manager_id: UUID,
    to_manager_id: UUID,
    granted_by: UUID,
) -> int:
    """Replace destination's Meta access with source's LIVE access. Atomic.

    C1 (fix round 1, spec 2026-08-20): antes era DELETE + INSERT sem filtro —
    dois problemas. Primeiro, o SELECT da origem não excluía grant revogado,
    então copiar de um gestor com um grant revogado (conta ainda `is_active`,
    então o JOIN de `can_manager_access` não salvava) ressuscitava esse grant
    como vivo pro destino — o INSERT nem grava `revoked_at`, então o default é
    NULL. Segundo, o DELETE do destino apagava o próprio rastro de revogação
    que este commit inteiro existe pra preservar.

    Agora: só os grants VIVOS da origem entram na cópia, e o destino é
    soft-revogado (nunca apagado) antes de receber os novos — quem já estava
    revogado no destino (por outro motivo, antes desta chamada) nem é tocado,
    porque o UPDATE de limpeza só pega `revoked_at IS NULL`. O ON CONFLICT
    restaura (não recria) a linha quando ela sobrevive dos dois lados.
    """
    async with conn.transaction():
        # "Replace" primeiro revoga (soft) o que o destino tinha de vivo — sem
        # isso, uma conta que só a destino tinha (fora do conjunto da origem)
        # ficaria viva pra sempre, e nunca seria "substituição" de verdade.
        await conn.execute(
            """
            UPDATE manager_meta_account_access
               SET revoked_at = now(), revoked_reason = 'bulk_copy_replaced'
             WHERE manager_id = $1 AND revoked_at IS NULL
            """,
            to_manager_id,
        )
        result = await conn.execute(
            """
            INSERT INTO manager_meta_account_access
                   (manager_id, ad_account_id, access_level, granted_by)
            SELECT $1, ad_account_id, access_level, $2
              FROM manager_meta_account_access
             WHERE manager_id = $3 AND revoked_at IS NULL
            ON CONFLICT (manager_id, ad_account_id) DO UPDATE SET
                access_level = EXCLUDED.access_level,
                granted_at = now(),
                granted_by = EXCLUDED.granted_by,
                revoked_at = NULL,
                revoked_reason = NULL
            """,
            to_manager_id,
            granted_by,
            from_manager_id,
        )
    return int(result.rsplit(" ", 1)[-1])
