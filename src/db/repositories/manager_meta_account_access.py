"""CRUD for `manager_meta_account_access` (which manager can operate which Meta ad account)."""

from uuid import UUID

import asyncpg

from src.db.repositories import _acesso_comum
from src.db.repositories._acesso_comum import META
from src.db.repositories.manager_account_access import NivelDeAcesso
from src.db.repositories.meta_ad_accounts import MetaAdAccount, row_to_account
from src.db.repositories.motivos import (
    ADMIN_REVOKED_REASON,
    PARTNERSHIP_ENDED_REASON,
)

# Motivo gravado quando o reconciliador (job) revoga acesso por a conta ter
# saido da parceria: vive em `motivos.py` (módulo neutro) e é reexportado daqui,
# porque `restore_for_account` filtra por este MESMO valor.
__all__ = ["PARTNERSHIP_ENDED_REASON"]


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
    SQL no núcleo (`_acesso_comum.grant`), o mesmo do gêmeo Google.
    """
    await _acesso_comum.grant(
        conn,
        META,
        manager_id=manager_id,
        conta=ad_account_id,
        access_level=access_level,
        granted_by=granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    granted_by: UUID | None = None,
) -> int:
    """Grant write access to every active meta_ad_accounts row for this manager.

    I4 (revisão de branch): era `ON CONFLICT DO NOTHING`, a última instância da
    classe que `grant`/`bulk_grant`/`copy_access` já tinham corrigido. Enquanto
    `revoke` era DELETE a linha sumia e o INSERT recriava; sob revogação soft a
    linha PERSISTE revogada, então o `DO NOTHING` pulava em silêncio exatamente
    as contas em que o gestor já tinha perdido acesso — um "conceder tudo"
    devolveria acesso a todas MENOS essas, sem erro nenhum. Reconceder é a forma
    de restaurar (spec 2026-08-20), então o conflito limpa a revogação.

    Sem chamador de produção hoje (o gêmeo Google, `manager_account_access.
    grant_all_active`, é o que `src/scripts/admin.py` usa). Corrigida em vez de
    apagada: é a direção segura (concede, nunca revoga), tem gêmeo vivo de mesma
    forma, e a §8 do desenho da matriz de acesso já prevê o "Conceder todas" no
    painel — apagar aqui só criaria assimetria entre os dois lados.

    F167 e decisão de 11/11 ("só tocar o que muda"), igual ao gêmeo Google: só a
    linha nova, revogada ou promovida ganha `granted_at`/`granted_by`; a ativa no
    mesmo nível fica intacta e não entra na contagem.
    SQL no núcleo (`_acesso_comum.grant_all_active`).
    """
    return await _acesso_comum.grant_all_active(
        conn, META, manager_id=manager_id, granted_by=granted_by
    )


async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    ad_account_id: str,
    reason: str = ADMIN_REVOKED_REASON,
) -> None:
    """Revogação SOFT (spec 2026-08-20): a linha fica, só marca `revoked_at`.

    Era DELETE. Curadoria de acesso é trabalho humano — apagar a linha perderia
    quem tinha acesso quando a parceria (ou o gestor) volta.

    Só pega linha viva (spec 2026-09-28 §3.2.1): revogar de novo uma linha que o churn
    já revogou trocaria `partnership_ended` pelo motivo novo, e o `restore_for_account`
    deixaria de devolvê-la quando a parceria voltasse. SQL no núcleo
    (`_acesso_comum.revoke`).
    """
    await _acesso_comum.revoke(
        conn, META, manager_id=manager_id, conta=ad_account_id, reason=reason
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
    return [row_to_account(r) for r in rows]


async def can_manager_access(
    conn: asyncpg.Connection,
    manager_id: UUID,
    ad_account_id: str,
    *,
    level: NivelDeAcesso = "read",
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
    executemany with ON CONFLICT does not expose per-batch counts (espelha o
    gêmeo Google).

    Reconceder é a forma de restaurar (spec 2026-08-20): se a linha já existia
    revogada, o ON CONFLICT limpa `revoked_at`/`revoked_reason` em vez de
    ignorar — senão o gestor readicionado numa bulk-grant continuaria bloqueado
    pelo gate.

    F128: o ON CONFLICT também seta `access_level = EXCLUDED.access_level`,
    espelhando o que `grant` (linha única) já fazia e o gêmeo Google
    (`manager_account_access.bulk_grant`) já corrigiu. Sem isso, quem já tinha
    'read' numa conta continuava com 'read' depois de um "conceder tudo" — a
    chamada devolve sucesso, mas o nível antigo sobrevive em silêncio.
    SQL no núcleo (`_acesso_comum.bulk_grant`).
    """
    return await _acesso_comum.bulk_grant(
        conn,
        META,
        manager_id=manager_id,
        contas=ad_account_ids,
        granted_by=granted_by,
        access_level=access_level,
    )


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

    T5e (revisão de branch): origem == destino aniquilaria o gestor — o UPDATE
    de limpeza revoga tudo que ele tem, e o SELECT seguinte, filtrando
    `revoked_at IS NULL`, já não acha nada pra reconceder. A rota checa antes
    (`src/web/routes/admin_access.py:204`, `admin_access_meta_bulk_copy`),
    mas a defesa não pode viver só lá: quem chamar o repositório de outro
    lugar não herda a checagem. A recusa e o SQL vivem no núcleo
    (`_acesso_comum.copy_access`), os mesmos do gêmeo Google.
    """
    return await _acesso_comum.copy_access(
        conn,
        META,
        from_manager_id=from_manager_id,
        to_manager_id=to_manager_id,
        granted_by=granted_by,
    )


async def list_live_grants(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """`(manager_id, ad_account_id)` de todo grant vivo — a matriz de `/admin/access/meta`.

    Revogação é soft (a linha fica), então sem `revoked_at IS NULL` a célula
    continuaria marcada depois do admin revogar.
    """
    rows = await conn.fetch(
        "SELECT manager_id, ad_account_id FROM manager_meta_account_access WHERE revoked_at IS NULL"
    )
    return list(rows)


async def list_live_grants_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[asyncpg.Record]:
    """`ad_account_id` dos grants vivos de UM gestor (detalhe do gestor no painel)."""
    rows = await conn.fetch(
        "SELECT ad_account_id FROM manager_meta_account_access "
        "WHERE manager_id = $1 AND revoked_at IS NULL",
        manager_id,
    )
    return list(rows)


async def list_managers_with_counts(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Gestores ativos com `access_count` (`/admin/access/meta/by-manager`).

    `revoked_at` entra na CONDIÇÃO do LEFT JOIN, não no WHERE: o WHERE excluiria o
    gestor inteiro (o LEFT viraria INNER) quando todos os grants dele estão
    revogados, e ele tem que continuar aparecendo com "0 / total".
    """
    rows = await conn.fetch(
        """SELECT m.id, m.email, m.full_name,
                  count(a.ad_account_id) AS access_count
           FROM managers m
           LEFT JOIN manager_meta_account_access mmaa
                  ON mmaa.manager_id = m.id AND mmaa.revoked_at IS NULL
           LEFT JOIN meta_ad_accounts a
                  ON a.ad_account_id = mmaa.ad_account_id AND a.is_active = true
           WHERE m.is_active = true
           GROUP BY m.id ORDER BY m.email"""
    )
    return list(rows)


async def count_active_accounts(conn: asyncpg.Connection) -> int:
    """Contas ATIVAS do inventário: o denominador de `list_managers_with_counts`.

    O detalhe do gestor monta a matriz por `list_all`, que já filtra `is_active`;
    sem o filtro aqui o denominador crescia a cada conta desativada pelo
    offboarding automático e as duas telas voltavam a discordar.
    """
    n = await conn.fetchval("SELECT count(*) FROM meta_ad_accounts WHERE is_active = true")
    return int(n or 0)


async def has_live_grant(conn: asyncpg.Connection, manager_id: UUID, ad_account_id: str) -> bool:
    """O par (gestor, conta) tem grant VIVO (`revoked_at IS NULL`)?

    Linha revogada é soft e fica: sem o filtro o toggle do painel chamaria
    `revoke` de novo em vez de reconceder. Não cruza com o inventário (isso é o
    gate, `can_manager_access`): aqui é só o estado da linha de grant.
    """
    existe = await conn.fetchval(
        "SELECT 1 FROM manager_meta_account_access "
        "WHERE manager_id = $1 AND ad_account_id = $2 AND revoked_at IS NULL",
        manager_id,
        ad_account_id,
    )
    return bool(existe)
