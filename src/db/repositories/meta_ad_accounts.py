"""CRUD for `meta_ad_accounts`. Populated by Meta sync job (M.2+)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from src.meta_ads.reconcile import InventoryRow


def _rows_affected(result: str) -> int:
    """asyncpg devolve o command tag ('UPDATE 3'); extrai a contagem."""
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


@dataclass(slots=True, frozen=True)
class MetaAdAccount:
    ad_account_id: str
    business_id: str | None
    business_name: str | None
    account_name: str
    currency: str | None
    timezone_name: str | None
    account_status: int | None
    is_active: bool
    synced_at: datetime
    # F128: execucoes COMPLETAS do resync em que a conta nao veio na parceria
    # autoritativa. Zera ao reaparecer; ao cruzar o limiar (`threshold` de
    # `build_plan`, hoje 3) a conta e desativada — a fonte do limiar mudou da
    # constante deste modulo (removida na spec 2026-08-20) pro parametro puro
    # de `src/meta_ads/reconcile.py`, que decide o plano sem I/O.
    missed_syncs: int = 0
    # Alcance do system user, distinto de pertencer a parceria (spec
    # 2026-08-20): conta pode estar na lista autoritativa e mesmo assim ficar
    # fora do alcance do SU (acao humana pendente no Business Manager). NUNCA
    # usar isto como sinal de desativacao — quem decide e build_plan().
    su_reachable: bool = True


def _row_to_account(row: asyncpg.Record) -> MetaAdAccount:
    return MetaAdAccount(
        ad_account_id=row["ad_account_id"],
        business_id=row["business_id"],
        business_name=row["business_name"],
        account_name=row["account_name"],
        currency=row["currency"],
        timezone_name=row["timezone_name"],
        account_status=row["account_status"],
        is_active=row["is_active"],
        synced_at=row["synced_at"],
        missed_syncs=row["missed_syncs"],
        su_reachable=row["su_reachable"],
    )


async def upsert_many(
    conn: asyncpg.Connection,
    accounts: list[dict[str, Any]],
) -> int:
    """Insert or update accounts in bulk; returns count touched.

    Each dict accepts: ad_account_id, business_id, business_name,
    account_name, currency, timezone_name, account_status.
    """
    if not accounts:
        return 0
    rows = [
        (
            a["ad_account_id"],
            a.get("business_id"),
            a.get("business_name"),
            a["account_name"],
            a.get("currency"),
            a.get("timezone_name"),
            a.get("account_status"),
        )
        for a in accounts
    ]
    await conn.executemany(
        """
        INSERT INTO meta_ad_accounts
            (ad_account_id, business_id, business_name, account_name,
             currency, timezone_name, account_status, is_active, synced_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, true, now())
        ON CONFLICT (ad_account_id) DO UPDATE SET
            business_id = EXCLUDED.business_id,
            business_name = EXCLUDED.business_name,
            account_name = EXCLUDED.account_name,
            currency = EXCLUDED.currency,
            timezone_name = EXCLUDED.timezone_name,
            account_status = EXCLUDED.account_status,
            is_active = true,
            -- F128: a conta reapareceu, entao a serie de ausencias morre aqui.
            -- Sem isto, cliente que volta chegaria ao limiar com ausencias
            -- antigas e seria desativado logo apos ser reativado.
            missed_syncs = 0,
            synced_at = now()
        """,
        rows,
    )
    return len(rows)


async def mark_inactive_except(
    conn: asyncpg.Connection,
    *,
    business_id: str,
    keep_ad_account_ids: list[str],
) -> int:
    """Mark accounts under business_id as inactive if not in keep list (deletion detection)."""
    if not keep_ad_account_ids:
        result = await conn.execute(
            "UPDATE meta_ad_accounts SET is_active = false "
            "WHERE business_id = $1 AND is_active = true",
            business_id,
        )
    else:
        result = await conn.execute(
            """
            UPDATE meta_ad_accounts SET is_active = false
            WHERE business_id = $1
              AND is_active = true
              AND ad_account_id <> ALL($2::text[])
            """,
            business_id,
            keep_ad_account_ids,
        )
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


async def apply_absences(conn: asyncpg.Connection, *, bump: list[str], reset: list[str]) -> None:
    """Aplica a carência decidida pelo plano. Não decide nada."""
    if bump:
        await conn.execute(
            "UPDATE meta_ad_accounts SET missed_syncs = missed_syncs + 1 "
            "WHERE ad_account_id = ANY($1::text[])",
            bump,
        )
    if reset:
        await conn.execute(
            "UPDATE meta_ad_accounts SET missed_syncs = 0 "
            "WHERE ad_account_id = ANY($1::text[]) AND missed_syncs <> 0",
            reset,
        )


async def deactivate(conn: asyncpg.Connection, *, ad_account_ids: list[str]) -> int:
    """Desativa exatamente a lista dada — nunca 'tudo que não está em X'.

    A forma antiga (`mark_inactive_except`) tinha o modo de falha do F85 embutido:
    lista vazia significava 'desative o resto'. Aqui, lista vazia é no-op.
    """
    if not ad_account_ids:
        return 0
    return _rows_affected(
        await conn.execute(
            "UPDATE meta_ad_accounts SET is_active = false "
            "WHERE ad_account_id = ANY($1::text[]) AND is_active = true",
            ad_account_ids,
        )
    )


async def set_reachable(
    conn: asyncpg.Connection, *, reachable_ids: list[str], scope_ids: list[str]
) -> None:
    """Marca alcance do system user. NÃO desativa: alcance ≠ pertencer à parceria.

    `scope_ids` é obrigatório de propósito (M4 da revisão de branch): sem o
    `WHERE`, o UPDATE marcava `su_reachable = false` também em conta inativa ou
    fora da parceria — e "o SU não alcança" só é sinal acionável para quem ESTÁ
    na parceria (spec §3). Fora dela o que importa é a carência, não o alcance.
    Kwarg obrigatório em vez de default: quem chama tem de dizer sobre qual
    conjunto está afirmando alcance (lição F57).

    Lista de alcance vazia continua sendo no-op (F85): "o SU não lê NADA" quase
    sempre é falha de leitura, não estado real — e apagaria o sinal da conta
    inteira do BM de uma vez.
    """
    if not reachable_ids or not scope_ids:
        return
    await conn.execute(
        "UPDATE meta_ad_accounts SET su_reachable = (ad_account_id = ANY($1::text[])) "
        "WHERE ad_account_id = ANY($2::text[])",
        reachable_ids,
        scope_ids,
    )


async def list_inventory_rows(conn: asyncpg.Connection) -> list[InventoryRow]:
    """Devolve o inventário no formato que `build_plan()` consome — puro dado."""
    rows = await conn.fetch("SELECT ad_account_id, is_active, missed_syncs FROM meta_ad_accounts")
    return [
        InventoryRow(
            ad_account_id=r["ad_account_id"],
            is_active=r["is_active"],
            missed_syncs=r["missed_syncs"],
        )
        for r in rows
    ]


@dataclass(frozen=True, slots=True)
class ReconcileQueues:
    sem_delegacao: list[MetaAdAccount]
    sem_su: list[MetaAdAccount]
    # Conta + nº de grants revogados POR CHURN (exatamente o que o Restaurar
    # devolve). A conta pode estar ativa aqui: é a que voltou à parceria.
    saiu_da_parceria: list[tuple[MetaAdAccount, int]]


async def list_queues(conn: asyncpg.Connection) -> ReconcileQueues:
    """As três filas do painel. Cada uma é uma AÇÃO diferente do admin.

    Substitui `list_out_of_reach` (F128 (d)): aquela devolvia `is_active =
    false OR missed_syncs > 0`, o que não distinguia as três filas — não sabia
    se a conta tinha gestor delegado (precisa cruzar com os grants) nem se o
    system user a alcançava (precisa de `su_reachable`).

    Fix round 1 (review): as filas são exclusivas, `sem_su` tem precedência.
    Sem `AND a.su_reachable = true` aqui, uma conta na parceria, sem gestor E
    sem SU (caso real em produção — `CA - V4 Lima Soares`, `CHUTE 07`) caía
    nas DUAS filas ao mesmo tempo. Não é só duplicação visual: delegar um
    gestor numa conta que o system user não alcança produz um grant que só
    gera `#200` quando usado. A ordem certa do admin é atribuir o SU no
    Business Manager primeiro, delegar depois — uma fila que convida a
    segunda ação antes da primeira ser possível manda o admin fazer trabalho
    inútil.

    C1 (revisão de branch): a fila 3 NÃO pode key-ar em `is_active`. Quando a
    parceria volta, `upsert_many` reativa a conta na mesma execução — e é aí, e
    só aí, que restaurar faz sentido, porque `can_manager_access` exige conta
    ativa. Com o predicado antigo (`is_active = false`) a conta sumia da fila no
    instante em que se tornava restaurável, levando junto o único chamador de
    `restore_for_account` em todo o `src/`; sobrava redelegar tudo à mão, o
    trabalho manual que a revogação soft existe para eliminar. A chave passou a
    ser ter grant revogado por churn PENDENTE, e quem voltou vem primeiro.

    Pela mesma lógica de precedência da rodada anterior, `saiu_da_parceria`
    ganha de `sem_delegacao` (o segundo `NOT EXISTS` da primeira query): a conta
    que voltou satisfaz as duas — está ativa e sem nenhum grant vivo —, e a fila
    de delegação aparece ANTES no painel, então sem a exclusão o admin seria
    convidado a refazer à mão o que um clique em Restaurar devolve. Delegar
    outro gestor continua possível pela matriz, linkada no alerta da fila 3.
    """
    # Import local: `manager_meta_account_access` importa deste módulo
    # (MetaAdAccount/_row_to_account), então importar de volta no topo fecharia
    # ciclo. A razão tem de ser a MESMA que `restore_for_account` filtra — é o
    # que faz a contagem exibida ser exatamente o que o botão devolve (I5).
    from src.db.repositories.manager_meta_account_access import PARTNERSHIP_ENDED_REASON

    sem_delegacao = await conn.fetch(
        """
        SELECT a.* FROM meta_ad_accounts a
         WHERE a.is_active = true
           AND a.su_reachable = true
           AND NOT EXISTS (
               SELECT 1 FROM manager_meta_account_access m
                WHERE m.ad_account_id = a.ad_account_id AND m.revoked_at IS NULL
           )
           AND NOT EXISTS (
               SELECT 1 FROM manager_meta_account_access r
                WHERE r.ad_account_id = a.ad_account_id
                  AND r.revoked_at IS NOT NULL
                  AND r.revoked_reason = $1
           )
         ORDER BY a.account_name
        """,
        PARTNERSHIP_ENDED_REASON,
    )
    sem_su = await conn.fetch(
        "SELECT * FROM meta_ad_accounts "
        "WHERE is_active = true AND su_reachable = false ORDER BY account_name"
    )
    # F59: toda coluna aliasada em query com JOIN.
    saiu = await conn.fetch(
        """
        SELECT a.*, count(m.manager_id) AS revogados
          FROM meta_ad_accounts a
          JOIN manager_meta_account_access m ON m.ad_account_id = a.ad_account_id
         WHERE m.revoked_at IS NOT NULL
           AND m.revoked_reason = $1
         GROUP BY a.ad_account_id
         ORDER BY a.is_active DESC, a.account_name
        """,
        PARTNERSHIP_ENDED_REASON,
    )
    return ReconcileQueues(
        sem_delegacao=[_row_to_account(r) for r in sem_delegacao],
        sem_su=[_row_to_account(r) for r in sem_su],
        saiu_da_parceria=[(_row_to_account(r), r["revogados"]) for r in saiu],
    )


async def list_all(conn: asyncpg.Connection) -> list[MetaAdAccount]:
    rows = await conn.fetch(
        "SELECT * FROM meta_ad_accounts WHERE is_active = true ORDER BY account_name"
    )
    return [_row_to_account(r) for r in rows]


async def get_by_id(conn: asyncpg.Connection, ad_account_id: str) -> MetaAdAccount | None:
    row = await conn.fetchrow(
        "SELECT * FROM meta_ad_accounts WHERE ad_account_id = $1",
        ad_account_id,
    )
    return _row_to_account(row) if row else None
