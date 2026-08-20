"""CRUD for `meta_ad_accounts`. Populated by Meta sync job (M.2+)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

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


async def bump_missing(
    conn: asyncpg.Connection,
    *,
    seen_ad_account_ids: list[str],
    threshold: int = MISSED_SYNCS_THRESHOLD,
) -> tuple[int, int]:
    """Conta ausencia por TEMPO, nao por BM (F128). Devolve (marcadas, desativadas).

    `mark_inactive_except` escopa por `business_id` e por isso nao alcanca o caso
    mais comum da operacao: parceria encerrada → system user perde o acesso → o
    BM inteiro some de `/me/adaccounts` → nao ha keep-list pra ele. Aqui o escopo
    e a execucao inteira: quem nao apareceu ganha +1, e quem chega ao limiar sai.

    **Chame SOMENTE com inventario completo** (`AdAccountsFetch.complete`): sobre
    lista truncada "ausente" significa "pagina que nao veio" (F93).

    Lista de vistas vazia e NO-OP — e o mesmo fail-safe que o F85 instalou do
    lado Google, e pela mesma razao: inventario vazio quase sempre e falha de
    leitura, nao "todas as contas sumiram". Sem essa guarda, tres respostas
    vazias seguidas apagariam o inventario inteiro.
    """
    if not seen_ad_account_ids:
        return (0, 0)

    marcadas = _rows_affected(
        await conn.execute(
            """
            UPDATE meta_ad_accounts
               SET missed_syncs = missed_syncs + 1
             WHERE is_active = true
               AND ad_account_id <> ALL($1::text[])
            """,
            seen_ad_account_ids,
        )
    )
    desativadas = _rows_affected(
        await conn.execute(
            """
            UPDATE meta_ad_accounts
               SET is_active = false
             WHERE is_active = true
               AND missed_syncs >= $1
            """,
            threshold,
        )
    )
    return marcadas, desativadas


async def list_out_of_reach(conn: asyncpg.Connection) -> list[MetaAdAccount]:
    """Contas que sairam (ou estao saindo) do alcance do system user — F128 (d).

    Cobre as duas rotas de churn: a desativada (por BM ou por limiar) e a que
    ainda esta ativa mas ja acumulou ausencia. O painel precisa das duas porque
    **desativar nao revoga**: `can_manager_access` le so a tabela de grants, sem
    olhar `is_active`. Sem esta lista, conta desativada some do admin e os grants
    dela ficam vivos sem ninguem ver.
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
