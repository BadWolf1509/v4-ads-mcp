"""CRUD for `google_ads_accounts`. Populated by the resync job."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import asyncpg
import structlog

from src.google_ads.reconcile import InventoryRow

log = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class GoogleAdsAccount:
    customer_id: str
    mcc_id: str
    descriptive_name: str
    currency_code: str | None
    time_zone: str | None
    is_test_account: bool
    is_active: bool
    synced_at: datetime


def _row_to_account(row: asyncpg.Record) -> GoogleAdsAccount:
    return GoogleAdsAccount(
        customer_id=row["customer_id"],
        mcc_id=row["mcc_id"],
        descriptive_name=row["descriptive_name"],
        currency_code=row["currency_code"],
        time_zone=row["time_zone"],
        is_test_account=row["is_test_account"],
        is_active=row["is_active"],
        synced_at=row["synced_at"],
    )


async def upsert_many(
    conn: asyncpg.Connection,
    accounts: list[
        dict[str, Any]
    ],  # each: customer_id, mcc_id, descriptive_name, currency_code, time_zone, is_test_account
) -> int:
    """Insert or update accounts in bulk; returns count touched."""
    if not accounts:
        return 0
    rows = [
        (
            a["customer_id"],
            a["mcc_id"],
            a["descriptive_name"],
            a.get("currency_code"),
            a.get("time_zone"),
            bool(a.get("is_test_account", False)),
        )
        for a in accounts
    ]
    await conn.executemany(
        """
        INSERT INTO google_ads_accounts
            (customer_id, mcc_id, descriptive_name, currency_code,
             time_zone, is_test_account, is_active, synced_at)
        VALUES ($1, $2, $3, $4, $5, $6, true, now())
        ON CONFLICT (customer_id) DO UPDATE SET
            mcc_id = EXCLUDED.mcc_id,
            descriptive_name = EXCLUDED.descriptive_name,
            currency_code = EXCLUDED.currency_code,
            time_zone = EXCLUDED.time_zone,
            is_test_account = EXCLUDED.is_test_account,
            is_active = true,
            -- F128: a conta reapareceu, entao a serie de ausencias morre aqui.
            -- Sem isto, cliente que volta chegaria ao limiar com ausencias
            -- antigas e seria desativado logo apos ser reativado. Espelha
            -- meta_ad_accounts.upsert_many (C1 da revisao de branch, 2026-09-05:
            -- a clausula tinha ficado de fora do lado Google).
            --
            -- C4: a serie e (missed_syncs, last_missed_on) — as DUAS. Zerar so o
            -- contador deixaria a data velha na linha, e a conta que volta e
            -- falta de novo no MESMO dia teria a ausencia pulada pelo
            -- `IS DISTINCT FROM` de `apply_absences`.
            missed_syncs = 0,
            last_missed_on = NULL,
            synced_at = now()
        """,
        rows,
    )
    return len(rows)


async def apply_absences(
    conn: asyncpg.Connection, *, bump: list[tuple[str, date]], reset: list[str]
) -> None:
    """Aplica a carência decidida por `build_plan()`. Não decide nada — só escreve.

    C4: o incremento é condicional ao DIA. `missed_syncs = missed_syncs + 1` puro
    contava uma ausência por EXECUÇÃO, e o job tem `maxRetries: 3` — um retry
    depois do commit da reconciliação contava a mesma ausência de novo. A
    carência de 3 dias caía em 2 execuções, e do lado Meta isso é revogação de
    acesso de gestor a conta de cliente.

    `IS DISTINCT FROM` e não `<>`: `last_missed_on` é NULL em toda linha hoje, e
    `NULL <> $2` avalia para NULL, que não satisfaz o WHERE — com `<>` a
    primeira ausência de cada conta nunca seria contada.

    O dia vem do fuso da CONTA (F141), calculado por `account_today` sobre o fuso
    que `list_inventory_rows` traz — sem I/O extra. `resolve_account_today` faria
    uma leitura por conta e adquiriria uma segunda conexão do pool dentro da
    transação já aberta da reconciliação.

    Conta sem fuso cai no fallback UTC decidido do `account_today` (há caminho
    para isso: `upsert_many` grava `a.get("time_zone")`). Aqui isso é ESCRITA, e
    o F146 diz que escrita não herda o fallback da leitura — a análise: para
    conta a oeste de UTC o carimbo sai um dia à frente, e o efeito é a ausência
    do dia seguinte ser PULADA. Carência mais lenta, nunca mais rápida; erra
    para o lado que não revoga. (m1 da revisão da Task 2; o gêmeo Meta leva a
    mesma frase.)

    O `reset` zera as duas colunas: conta que reapareceu não pode carregar a data
    velha, senão a próxima ausência dela seria pulada se caísse no mesmo dia. E
    leva `AND missed_syncs <> 0`, que o lado Meta já tem — simetria entre os dois
    laços é requisito, não estética (o F128 nasceu de uma cláusula que ficou de
    fora de um dos lados).
    """
    if bump:
        await conn.executemany(
            "UPDATE google_ads_accounts "
            "   SET missed_syncs = missed_syncs + 1, last_missed_on = $2 "
            " WHERE customer_id = $1 "
            "   AND last_missed_on IS DISTINCT FROM $2",
            bump,
        )
    if reset:
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = 0, last_missed_on = NULL "
            "WHERE customer_id = ANY($1::text[]) AND missed_syncs <> 0",
            reset,
        )


async def deactivate(conn: asyncpg.Connection, *, customer_ids: list[str]) -> int:
    """Desativa exatamente a lista dada — nunca 'tudo que não está em X'.

    Espelha `meta_ad_accounts.deactivate`. `mark_inactive_except` (abaixo) carrega
    o modo de falha do F85 na própria forma — keep-list vazia significa "desative
    o resto" —, então quem decide a lista de remoção passou a ser `build_plan()`
    (via `reconcile_google`, `src/jobs/account_resync.py`), e esta função só
    aplica: lista vazia é no-op por construção, sem branch de opt-in nenhum.
    `mark_inactive_except` não foi apagada — segue como caminho de emergência.
    """
    if not customer_ids:
        return 0
    result = await conn.execute(
        "UPDATE google_ads_accounts SET is_active = false "
        "WHERE customer_id = ANY($1::text[]) AND is_active = true",
        customer_ids,
    )
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


async def list_inventory_rows(conn: asyncpg.Connection) -> list[InventoryRow]:
    """Devolve o inventário no formato que `build_plan()` consome — puro dado.

    `time_zone` vem junto por causa do C4: quem aplica a ausência precisa do dia
    NO FUSO DA CONTA (F141), e resolvê-lo depois seria uma leitura por conta
    dentro da transação aberta da reconciliação. `build_plan` ignora o campo.

    `last_missed_on`, ao contrário, `build_plan` LÊ: é o que diz se a ausência
    desta execução já está em `missed_syncs` (retry do mesmo dia) ou não. Sem
    ela na linha o planejador soma `+1` sempre e queima um dia de carência a
    cada retry — o contador fica certo e a DECISÃO sai um dia adiantada.
    """
    rows = await conn.fetch(
        "SELECT customer_id, is_active, missed_syncs, time_zone, last_missed_on "
        "FROM google_ads_accounts"
    )
    return [
        InventoryRow(
            customer_id=r["customer_id"],
            is_active=r["is_active"],
            missed_syncs=r["missed_syncs"],
            time_zone=r["time_zone"],
            last_missed_on=r["last_missed_on"],
        )
        for r in rows
    ]


async def mark_inactive_except(
    conn: asyncpg.Connection,
    *,
    mcc_id: str,
    keep_customer_ids: list[str],
    allow_full_deactivation: bool = False,
) -> int:
    """Mark accounts under mcc_id as inactive if not in keep list (deletion detection).

    Task 5 (2026-09-05): o job diário (`src/jobs/account_resync.py`) PAROU de
    chamar esta função — a decisão de quem remover passou para `build_plan()` +
    `deactivate()` acima, com carência por conta em vez de "primeira ausência já
    desativa". Ela continua existindo, coberta pelos testes abaixo, como caminho
    de emergência (`allow_full_deactivation=True`) para quem precisar zerar o
    inventário de um MCC à mão.

    F85 — keep-list vazia é NO-OP por default. `fetch_account_details` pode
    devolver `[]` sem levantar exceção (search com 0 linhas, mudança de semântica
    do `customer_client`, hiccup de permissão), e antes esse caso caía num branch
    que desativava TODO o inventário: as 25 contas do MCC sumiam do painel, de
    `list_my_accounts` e de `grant_all_active` até o resync seguinte, 24h depois.
    Lista vazia quase sempre significa falha de leitura, não "o MCC ficou vazio".

    O lado Meta já era fail-safe (F65): payload vazio não desativa nada. Esta é a
    mesma escolha, agora explícita — e a desativação em massa continua possível
    via `allow_full_deactivation=True`, que exige o caller assumir a intenção.
    """
    if not keep_customer_ids and not allow_full_deactivation:
        log.warning("mark_inactive_except_empty_keep_list_ignored", mcc_id=mcc_id)
        return 0
    if not keep_customer_ids:
        # Opt-in explícito: desativa tudo sob o MCC.
        result = await conn.execute(
            "UPDATE google_ads_accounts SET is_active = false WHERE mcc_id = $1 AND is_active = true",
            mcc_id,
        )
    else:
        result = await conn.execute(
            """
            UPDATE google_ads_accounts SET is_active = false
            WHERE mcc_id = $1
              AND is_active = true
              AND customer_id <> ALL($2::text[])
            """,
            mcc_id,
            keep_customer_ids,
        )
    # asyncpg.execute returns 'UPDATE N'
    return int(result.split()[-1]) if result.startswith("UPDATE") else 0


async def list_all(conn: asyncpg.Connection) -> list[GoogleAdsAccount]:
    rows = await conn.fetch(
        "SELECT * FROM google_ads_accounts WHERE is_active = true ORDER BY descriptive_name"
    )
    return [_row_to_account(r) for r in rows]


async def get_by_customer_id(conn: asyncpg.Connection, customer_id: str) -> GoogleAdsAccount | None:
    """Uma conta pela PK. F141: e daqui que sai o `time_zone` que resolve `hoje`.

    Devolve tambem conta inativa — quem decide se ela pode ser usada e o gate
    de acesso, nao esta leitura.
    """
    row = await conn.fetchrow(
        "SELECT * FROM google_ads_accounts WHERE customer_id = $1", customer_id
    )
    return _row_to_account(row) if row is not None else None


@dataclass(slots=True, frozen=True)
class ReconcileQueues:
    sem_delegacao: list[asyncpg.Record]
    voltaram_ao_mcc: list[asyncpg.Record]


async def list_queues(conn: asyncpg.Connection) -> ReconcileQueues:
    """As duas filas do painel. Cada uma é uma AÇÃO diferente do admin.

    C1 (lição do sprint Meta, `meta_ad_accounts.list_queues`): a fila 2 NÃO
    chaveia em `is_active`. Quando a conta volta ao MCC, `upsert_many` a
    reativa na MESMA execução — e é aí, e só aí, que restaurar faz sentido,
    porque `can_manager_access` exige conta ativa. Com o predicado
    `is_active = false`, a conta sumiria da fila no instante em que se
    tornasse restaurável, e sobraria redelegar tudo à mão — o trabalho manual
    que a revogação soft existe para eliminar. A chave é ter grant revogado
    por churn PENDENTE (`revoked_reason = LEFT_MCC_REASON`); por isso o nome
    é `voltaram_ao_mcc`, não `sairam_do_mcc` — ao contrário da fila 3 do
    gêmeo Meta, esta não mistura histórico de quem segue fora: `is_active =
    true` aqui é uma exigência real da query, não um bug — só entram contas
    JÁ acionáveis.

    As filas são exclusivas e `voltaram_ao_mcc` tem precedência: a conta que
    voltou satisfaz as duas (está ativa e sem grant VIVO), e sem a exclusão o
    admin seria convidado a refazer à mão o que um clique devolve.
    """
    from src.db.repositories.manager_account_access import LEFT_MCC_REASON

    voltaram = await conn.fetch(
        """
        SELECT a.customer_id, a.descriptive_name,
               count(m.manager_id) AS grants_restauraveis
          FROM google_ads_accounts a
          JOIN manager_account_access m ON m.customer_id = a.customer_id
         WHERE a.is_active = true
           AND m.revoked_at IS NOT NULL
           AND m.revoked_reason = $1
         GROUP BY a.customer_id, a.descriptive_name
         ORDER BY a.descriptive_name
        """,
        LEFT_MCC_REASON,
    )
    sem_delegacao = await conn.fetch(
        """
        SELECT a.customer_id, a.descriptive_name, a.synced_at
          FROM google_ads_accounts a
         WHERE a.is_active = true
           AND NOT EXISTS (
                 SELECT 1 FROM manager_account_access m
                  WHERE m.customer_id = a.customer_id AND m.revoked_at IS NULL)
           AND NOT EXISTS (
                 SELECT 1 FROM manager_account_access m
                  WHERE m.customer_id = a.customer_id
                    AND m.revoked_reason = $1)
         ORDER BY a.descriptive_name
        """,
        LEFT_MCC_REASON,
    )
    return ReconcileQueues(sem_delegacao=list(sem_delegacao), voltaram_ao_mcc=list(voltaram))
