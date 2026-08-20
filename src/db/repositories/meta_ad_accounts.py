"""CRUD for `meta_ad_accounts`. Populated by Meta sync job (M.2+)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

from src.meta_ads.reconcile import InventoryRow

# F128: quantas execucoes COMPLETAS seguidas sem ver a conta antes de desativar.
# O job roda diario, entao 3 ~ 3 dias. Nao e 1 de proposito: uma unica leitura
# esquisita (resposta completa porem pobre, hiccup de permissao) nao deve
# derrubar conta viva — a familia F65/F85 e exatamente esse modo de falha.
MISSED_SYNCS_THRESHOLD = 3


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
    # F128: execucoes COMPLETAS do resync em que a conta nao veio em
    # /me/adaccounts. Zera ao reaparecer; ao cruzar MISSED_SYNCS_THRESHOLD a
    # conta e desativada.
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


async def set_reachable(conn: asyncpg.Connection, *, reachable_ids: list[str]) -> None:
    """Marca alcance do system user. NÃO desativa: alcance ≠ pertencer à parceria."""
    if not reachable_ids:
        return
    await conn.execute(
        "UPDATE meta_ad_accounts SET su_reachable = (ad_account_id = ANY($1::text[]))",
        reachable_ids,
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


async def list_out_of_reach(conn: asyncpg.Connection) -> list[MetaAdAccount]:
    """Contas que sairam (ou estao saindo) do alcance do system user — F128 (d).

    Cobre as duas rotas de churn: a desativada (por BM ou por limiar) e a que
    ainda esta ativa mas ja acumulou ausencia. O painel precisa das duas porque
    **desativar nao revoga**: a partir da spec 2026-08-20, `can_manager_access`
    cruza com `is_active` (defesa em profundidade — nega mesmo se o
    reconciliador nao rodou ainda), mas as linhas de `manager_meta_account_access`
    continuam vivas, sem `revoked_at`, ate alguem chamar `revoke_for_account`.
    Sem esta lista, conta desativada some do admin e os grants dela ficam
    tecnicamente bloqueados porem nunca revogados de fato — ninguem percebe
    que precisam de limpeza.
    """
    rows = await conn.fetch(
        """
        SELECT * FROM meta_ad_accounts
         WHERE is_active = false OR missed_syncs > 0
         ORDER BY is_active, missed_syncs DESC, account_name
        """
    )
    return [_row_to_account(r) for r in rows]


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
