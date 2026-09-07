"""CRUD for `meta_ad_accounts`. Populated by Meta sync job (M.2+)."""

from dataclasses import dataclass
from datetime import date, datetime
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
    """Aplica a carência decidida pelo plano. Não decide nada — só escreve.

    C4: o incremento é condicional ao DIA. `missed_syncs = missed_syncs + 1`
    puro contava uma ausência por EXECUÇÃO, e o job tem `maxRetries: 3` — um
    retry depois do commit da reconciliação contava a mesma ausência de novo. A
    carência de 3 dias caía em 2 execuções, e deste lado isso é revogação REAL
    de acesso de gestor a conta de cliente: `meta_reconcile_apply` está ligada
    em produção desde 05/09 (o gêmeo Google segue em soak, não aplica).

    `IS DISTINCT FROM` e não `<>`: `last_missed_on` é NULL em toda linha hoje
    (a 009 subiu sem backfill), e `NULL <> $2` avalia para NULL, que não
    satisfaz o WHERE — com `<>` a primeira ausência de cada conta nunca seria
    contada, e o contador ficaria congelado em 0 no inventário inteiro.

    O dia vem do fuso da CONTA (F141), calculado por `src.clock.account_today`
    sobre o `timezone_name` que `list_inventory_rows` traz — sem I/O extra.
    Resolvê-lo por conta adquiriria uma segunda conexão do pool dentro da
    transação já aberta da reconciliação.

    Conta sem fuso cai no fallback UTC decidido do `account_today`. Aqui isso é
    ESCRITA, e o F146 diz que escrita não herda o fallback da leitura — então o
    que o fallback muda é a CHAVE da idempotência: sem fuso, "uma ausência por
    dia" passa a valer por dia UTC, e não por dia da CONTA. Não é uma garantia
    direcional — o erro cai para os dois lados, conforme a hora do run:

    - um dia local de conta a oeste de UTC mapeia em DUAS datas UTC, então duas
      execuções no mesmo dia da conta que atravessem a meia-noite UTC (ex.: 20h
      e 22h locais em UTC-3) carimbam datas diferentes e contam DUAS ausências
      no mesmo dia — que é exatamente o defeito que este C4 fecha, e erra para o
      lado que revoga CEDO, que deste lado é revogação REAL de acesso;
    - e a ausência das 21h à meia-noite locais sai carimbada com o dia seguinte,
      fazendo a ausência real do dia seguinte ser PULADA — carência mais lenta.

    Não alcançável hoje, e isto é medido e não suposto: o job roda uma vez por
    dia, os retries são em minutos, e a probe de 2026-09-06 achou nome IANA
    válido nas 25 contas vivas (`America/Sao_Paulo` 22, `America/Noronha` 2,
    `America/Manaus` 1). Mas quem sustenta a idempotência nesse caso é a AGENDA
    do job, não este fallback — a frase anterior afirmava "erra sempre para o
    lado que não revoga", garantia que o código não dá (M3 da revisão final).

    O `reset` zera as duas colunas: conta que reapareceu não pode carregar a
    data velha, senão a próxima ausência dela seria pulada se caísse no mesmo
    dia. E mantém `AND missed_syncs <> 0`, que o lado Google copiou daqui —
    simetria entre os dois laços é requisito, não estética (o F128 nasceu de
    uma cláusula que ficou de fora de um dos lados).
    """
    if bump:
        await conn.executemany(
            "UPDATE meta_ad_accounts "
            "   SET missed_syncs = missed_syncs + 1, last_missed_on = $2 "
            " WHERE ad_account_id = $1 "
            "   AND last_missed_on IS DISTINCT FROM $2",
            bump,
        )
    if reset:
        await conn.execute(
            "UPDATE meta_ad_accounts SET missed_syncs = 0, last_missed_on = NULL "
            "WHERE ad_account_id = ANY($1::text[]) AND missed_syncs <> 0",
            reset,
        )


async def deactivate(conn: asyncpg.Connection, *, ad_account_ids: list[str]) -> int:
    """Desativa exatamente a lista dada — nunca 'tudo que não está em X'.

    A forma antiga (`mark_inactive_except`) tinha o modo de falha do F85
    embutido: `keep_ad_account_ids` vazio significava 'desative o resto', e o
    gêmeo Google chegou a recusar esse caso justamente por isso. Aqui, lista
    vazia é no-op por construção. A função antiga foi APAGADA na revisão de
    branch (M1) em vez de deixada ao lado desta: ficou sem chamador nenhum
    quando o reconciliador passou a decidir por `build_plan`, e código morto
    armado é convite a alguém "reaproveitar" a forma perigosa.
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
    """Devolve o inventário no formato que `build_plan()` consome — puro dado.

    `timezone_name` vem junto por causa do C4: quem aplica a ausência precisa
    do dia NO FUSO DA CONTA (F141), e resolvê-lo depois seria uma leitura por
    conta dentro da transação aberta da reconciliação. `build_plan` ignora o
    campo.

    `last_missed_on`, ao contrário, `build_plan` LÊ: é o que diz se a ausência
    desta execução já está em `missed_syncs` (retry do mesmo dia) ou não. Sem
    ela na linha o planejador soma `+1` sempre e queima um dia de carência a
    cada retry — o contador fica certo e a DECISÃO sai um dia adiantada, que
    deste lado é revogação de acesso de gestor.
    """
    rows = await conn.fetch(
        "SELECT ad_account_id, is_active, missed_syncs, timezone_name, last_missed_on "
        "FROM meta_ad_accounts"
    )
    return [
        InventoryRow(
            ad_account_id=r["ad_account_id"],
            is_active=r["is_active"],
            missed_syncs=r["missed_syncs"],
            timezone_name=r["timezone_name"],
            last_missed_on=r["last_missed_on"],
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
