"""CRUD for `manager_account_access` (which manager can operate which account)."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from src.db.repositories.google_ads_accounts import GoogleAdsAccount, _row_to_account

# Motivos gravados por `revoke`/`revoke_for_inactive_accounts`. Constantes — não
# string livre — porque `restore_for_account` filtra por ESTE MESMO valor
# (`LEFT_MCC_REASON`): um typo ou refactor que passasse outro texto faria o
# restore filtrar por um motivo que nenhuma linha tem e devolver zero em
# silêncio, sem erro (mesmo raciocínio do gêmeo Meta, PARTNERSHIP_ENDED_REASON).
LEFT_MCC_REASON = "left_mcc"
ADMIN_REVOKED_REASON = "admin_revoked"


@dataclass(slots=True, frozen=True)
class AccountAccess:
    manager_id: UUID
    customer_id: str
    access_level: str  # 'read' | 'write'
    granted_at: datetime
    granted_by: UUID | None


async def grant(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
    access_level: str = "write",
    granted_by: UUID | None = None,
) -> None:
    """Concede acesso. Reconceder é a forma de restaurar: se a linha já existia
    revogada (`revoke` agora é soft), o ON CONFLICT limpa `revoked_at`/
    `revoked_reason` em vez de só atualizar `access_level` — senão o toggle do
    painel "concede" e o gate continua negando, porque a linha segue revogada.
    """
    await conn.execute(
        """
        INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (manager_id, customer_id) DO UPDATE SET
            access_level = EXCLUDED.access_level,
            granted_at = now(),
            granted_by = EXCLUDED.granted_by,
            revoked_at = NULL,
            revoked_reason = NULL
        """,
        manager_id,
        customer_id,
        access_level,
        granted_by,
    )


async def grant_all_active(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    granted_by: UUID | None = None,
) -> int:
    """Grant write access to every active google_ads_accounts row for this manager.

    Reconceder é a forma de restaurar: o `DO NOTHING` original pulava em
    silêncio justo a conta que o gestor tinha perdido por revogação soft — um
    "conceder tudo" devolveria acesso a todas MENOS essas, sem erro nenhum. Por
    isso o conflito limpa a revogação em vez de ignorar (espelha o gêmeo Meta).
    Efeito colateral aceito: a contagem devolvida passa a incluir toda linha
    TOCADA pelo INSERT (nova OU restaurada), não só a genuinamente nova.
    """
    result = await conn.execute(
        """
        INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
        SELECT $1, customer_id, 'write', $2
        FROM google_ads_accounts
        WHERE is_active = true
        ON CONFLICT (manager_id, customer_id) DO UPDATE SET
            revoked_at = NULL,
            revoked_reason = NULL
        """,
        manager_id,
        granted_by,
    )
    return int(result.split()[-1]) if result.startswith("INSERT") else 0


async def revoke(
    conn: asyncpg.Connection,
    *,
    manager_id: UUID,
    customer_id: str,
    reason: str = ADMIN_REVOKED_REASON,
) -> None:
    """Revogação SOFT. A linha fica; o gate nega.

    Era DELETE. Item 5 (revisão final): esta docstring dizia que a soft-revoke
    dá "trilha de quem perdeu o quê e quando" — impreciso em dois pontos, sem
    mudar o comportamento (que é o mesmo do gêmeo Meta em produção). O que a
    troca de DELETE por UPDATE de fato entrega é ESTADO CORRENTE, não um log
    append-only: `revoked_reason` (`left_mcc` vs `admin_revoked`) é o que
    distingue churn — restaurável por `restore_for_account` — de decisão do
    admin, que não volta sozinha; é essa distinção que sustenta o desenho.
    Mas reconceder por QUALQUER caminho (`grant`, `bulk_grant`,
    `grant_all_active`, `copy_access`) zera `revoked_at`/`revoked_reason` de
    volta pra NULL — a partir daí não sobra na tabela nenhum registro de que a
    revogação aconteceu. Não existe coluna `revoked_by`: quem revogou só fica
    em `audit_log`, e só nos caminhos que passam por `_audit_admin` (o painel;
    `revoke_for_inactive_accounts`, sem chamador em produção ainda, não
    audita nada). E `bulk_grant`/`grant_all_active` reconcedem sem tocar `granted_at`/
    `granted_by` — a linha restaurada por esses dois caminhos lê "concedida
    há muito tempo, nunca revogada", indistinguível de uma que nunca saiu do
    ar; só `grant()` (o toggle do painel) e `copy_access` atualizam os dois
    campos ao reconceder.
    """
    await conn.execute(
        """
        UPDATE manager_account_access
           SET revoked_at = now(), revoked_reason = $3
         WHERE manager_id = $1 AND customer_id = $2 AND revoked_at IS NULL
        """,
        manager_id,
        customer_id,
        reason,
    )


async def list_accounts_for_manager(
    conn: asyncpg.Connection, manager_id: UUID
) -> list[GoogleAdsAccount]:
    """Return GoogleAdsAccount rows the manager has any access to (active accounts only)."""
    rows = await conn.fetch(
        """
        SELECT a.*
        FROM google_ads_accounts a
        INNER JOIN manager_account_access m ON m.customer_id = a.customer_id
        WHERE m.manager_id = $1
          AND a.is_active = true
          AND m.revoked_at IS NULL
        ORDER BY a.descriptive_name
        """,
        manager_id,
    )
    return [_row_to_account(r) for r in rows]


async def can_manager_access(
    conn: asyncpg.Connection, manager_id: UUID, customer_id: str, *, level: str = "read"
) -> bool:
    """Gate por conta — e, como no Meta, é a ÚNICA fronteira que sobra.

    `build_client_for_manager` usa o token do próprio gestor, mas com
    `login_customer_id` = o MCC, e as identidades dos gestores são usuárias do
    MCC (confirmado 2026-09-05). Logo o token alcança as 26 contas de cliente e
    quem os limita às atribuídas é esta função.

    O JOIN com o inventário é o fix da pendência 10: em 2026-09-05 havia 34
    grants `write` vivos em 9 contas que saíram do MCC, e este predicado
    aprovava os 34. Quem os negava era o Google — delegar ao provedor a
    aplicação de uma regra nossa.

    `revoked_at IS NULL` é o fix da Task 3: revogação passou a ser soft (a
    linha fica, pra dar trilha e caminho de volta), então "existe grant" deixou
    de significar "tem acesso" — só a ausência de revogação significa.
    """
    row = await conn.fetchrow(
        """
        SELECT m.access_level
          FROM manager_account_access m
          JOIN google_ads_accounts a ON a.customer_id = m.customer_id
         WHERE m.manager_id = $1
           AND m.customer_id = $2
           AND a.is_active = true
           AND m.revoked_at IS NULL
        """,
        manager_id,
        customer_id,
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
    customer_ids: list[str],
    granted_by: UUID,
    access_level: str = "write",
) -> int:
    """Idempotent bulk grant. Inserts rows that don't exist; restores revoked ones.

    Returns len(customer_ids) — not the count of rows actually inserted;
    executemany with ON CONFLICT does not expose per-batch counts (espelha o
    gêmeo Meta).

    Reconceder é a forma de restaurar: se a linha já existia revogada, o ON
    CONFLICT limpa `revoked_at`/`revoked_reason` em vez de ignorar — senão o
    gestor readicionado numa bulk-grant continuaria bloqueado pelo gate.
    """
    if not customer_ids:
        return 0
    rows = [(manager_id, cid, access_level, granted_by) for cid in customer_ids]
    await conn.executemany(
        """INSERT INTO manager_account_access (manager_id, customer_id, access_level, granted_by)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (manager_id, customer_id) DO UPDATE SET
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
    """Replace destination's access with source's LIVE access. Atomic.

    I2 (revisão de branch, revertendo a decisão original do brief): o brief
    mandava manter o DELETE cru no destino, com a justificativa de que o
    INSERT abaixo não tinha ON CONFLICT. Essa justificativa descrevia o
    código daquele momento, não uma restrição real — e o DELETE apaga junto a
    TRILHA de revogação que o destino já tinha antes desta chamada. Dano
    concreto: conta X sai do MCC → `revoke_for_inactive_accounts` marca A e B
    como `left_mcc` → admin copia acesso de A pra B → a linha `left_mcc` de B
    é apagada aqui → X volta ao MCC → `restore_for_account(X)` devolve A e
    nunca mais B, em silêncio e permanentemente.

    O gêmeo Meta já tinha resolvido isto em produção como achado "C1": o
    destino é soft-revogado (razão própria, não apaga o que já estava
    revogado por outro motivo) e o INSERT ganha `ON CONFLICT ... DO UPDATE`
    pra restaurar — não recriar — a linha que sobrevive dos dois lados. Forma
    copiada aqui.

    Só os grants VIVOS da origem são copiados (`revoked_at IS NULL`) — sem o
    filtro, copiar de um gestor com um grant revogado de propósito ressuscitava
    esse grant como vivo pro destino, porque o INSERT não gravava
    `revoked_at` (ficava NULL por default). Achado extra da task original
    (fora das 4 decisões): mesmo bug que o gêmeo Meta já documentou e fechou
    como C1; no Google ele nunca tinha se manifestado porque `revoke` era
    DELETE — não sobrava linha revogada pra ressuscitar.

    Item 4 (revisão final, mesmo achado T5e do gêmeo Meta): origem == destino
    aniquilaria o gestor — o UPDATE de limpeza revoga (soft) tudo que ele tem
    de vivo, e o SELECT seguinte, filtrando `manager_id = origem AND
    revoked_at IS NULL`, já não acha nada pra reconceder (a origem é o
    próprio destino, que acabou de ficar todo revogado). A rota
    (`routes.py:1367`) já recusa antes de chamar, mas a defesa não pode viver
    só lá: esta branch acabou de acrescentar funções de repositório que
    outro código pode chamar direto, sem herdar a checagem da rota.
    """
    if from_manager_id == to_manager_id:
        raise ValueError("copy_access: origem e destino sao o mesmo gestor")
    async with conn.transaction():
        # "Replace" primeiro revoga (soft) o que o destino tinha de VIVO — sem
        # isso, uma conta que só o destino tinha (fora do conjunto da origem)
        # ficaria viva pra sempre, e nunca seria "substituição" de verdade. Só
        # pega `revoked_at IS NULL`: quem já estava revogado no destino (por
        # `left_mcc`, `admin_revoked`, ou uma cópia anterior) não é tocado, e
        # é exatamente essa trilha que sobrevive à cópia.
        await conn.execute(
            """
            UPDATE manager_account_access
               SET revoked_at = now(), revoked_reason = 'bulk_copy_replaced'
             WHERE manager_id = $1 AND revoked_at IS NULL
            """,
            to_manager_id,
        )
        result = await conn.execute(
            """
            INSERT INTO manager_account_access
                   (manager_id, customer_id, access_level, granted_by)
            SELECT $1, customer_id, access_level, $2
              FROM manager_account_access
             WHERE manager_id = $3 AND revoked_at IS NULL
            ON CONFLICT (manager_id, customer_id) DO UPDATE SET
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
    # asyncpg returns 'INSERT 0 N'
    return int(result.rsplit(" ", 1)[-1])


async def revoke_for_inactive_accounts(
    conn: asyncpg.Connection, *, reason: str = LEFT_MCC_REASON
) -> dict[str, list[str]]:
    """Revoga todo grant vivo em conta inativa. Devolve customer_id -> manager_ids.

    Opera sobre o ESTADO (`is_active = false`), não sobre o delta da execução.
    Em 2026-09-05 havia 34 grants vivos em 9 contas já inativas: um plano
    calculado a partir de `ativos` nunca os alcançaria, e o sprint fecharia
    verde sem tocar no que o motivou.
    """
    rows = await conn.fetch(
        """
        UPDATE manager_account_access m
           SET revoked_at = now(), revoked_reason = $1
          FROM google_ads_accounts a
         WHERE a.customer_id = m.customer_id
           AND a.is_active = false
           AND m.revoked_at IS NULL
        RETURNING m.customer_id, m.manager_id
        """,
        reason,
    )
    atingidos: dict[str, list[str]] = {}
    for r in rows:
        atingidos.setdefault(r["customer_id"], []).append(str(r["manager_id"]))
    return atingidos


async def restore_for_account(conn: asyncpg.Connection, *, customer_id: str) -> list[str]:
    """Devolve o acesso revogado por CHURN. Revogação de admin não volta."""
    rows = await conn.fetch(
        """
        UPDATE manager_account_access
           SET revoked_at = NULL, revoked_reason = NULL
         WHERE customer_id = $1
           AND revoked_at IS NOT NULL
           AND revoked_reason = $2
        RETURNING manager_id
        """,
        customer_id,
        LEFT_MCC_REASON,
    )
    return [str(r["manager_id"]) for r in rows]


async def count_grants_on_inactive_accounts(conn: asyncpg.Connection) -> int:
    """Quantos grants VIVOS existem em conta inativa. Leitura pura.

    O número que o dry-run reporta como `revoke_candidates` (Task 5, fora
    desta leva — a função entra aqui porque o brief a declarava sem dono).
    """
    return int(
        await conn.fetchval(
            """
            SELECT count(*)
              FROM manager_account_access m
              JOIN google_ads_accounts a ON a.customer_id = m.customer_id
             WHERE a.is_active = false AND m.revoked_at IS NULL
            """
        )
    )
