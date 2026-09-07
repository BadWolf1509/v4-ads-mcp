"""Cloud Run Job: refresh google_ads_accounts from the MCC.

Picks any active OAuth connection (admin's by default) and uses its
refresh token to call list_accessible_customers + customer_client
search on the MCC. Upserts results, marks deactivated accounts.

Entry point: `python -m src.jobs.account_resync`
"""

import asyncio
import sys
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog

from src.auth.tokens import decrypt_refresh_token, derive_master_key_from_settings
from src.clock import account_today
from src.config import get_settings
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    managers,
)
from src.google_ads.accounts import (
    fetch_account_details,
    list_accessible_customer_resource_names,
)
from src.google_ads.client import build_client
from src.google_ads.reconcile import build_plan
from src.governance.bookkeeping import best_effort
from src.jobs._audit import record_access_revocation, record_job_crash, record_job_run
from src.jobs.purge import purge_expired
from src.logging import configure_logging

log = structlog.get_logger(__name__)


async def _pick_oauth_connection(conn: asyncpg.Connection) -> tuple[Any, Any]:
    """Return (manager, oauth_conn) for the first active admin's OAuth.

    Falls back to any active connection if no admin has one.
    """
    admins = await conn.fetch(
        "SELECT id FROM managers WHERE role = 'admin' AND is_active = true ORDER BY created_at"
    )
    for row in admins:
        oc = await google_oauth_connections.get_active_for_manager(conn, row["id"])
        if oc is not None:
            m = await managers.get_by_id(conn, row["id"])
            return m, oc

    # Fallback: any active connection.
    row = await conn.fetchrow(
        "SELECT manager_id FROM google_oauth_connections WHERE revoked_at IS NULL ORDER BY connected_at DESC LIMIT 1"
    )
    if row is None:
        return None, None
    oc = await google_oauth_connections.get_active_for_manager(conn, row["manager_id"])
    m = await managers.get_by_id(conn, row["manager_id"])
    return m, oc


async def reconcile_google(
    conn: asyncpg.Connection,
    *,
    accounts: list[dict[str, Any]],
    complete: bool,
    apply: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcilia o inventário Google contra o MCC. Devolve o params_summary.

    Função própria (não código inline em `run()`) pra ser testável contra um
    banco real sem subir o job inteiro — espelha `meta_resync.reconcile_meta`.

    Uma transação só pro bloco de escrita inteiro: metade aplicada — carência
    somada sem desativar, ou desativada com grant vivo — é exatamente a
    inconsistência que este recurso existe pra evitar.

    `now` é o instante da EXECUÇÃO, lido UMA vez e passado adiante (C4/F141):
    todas as ausências deste run são carimbadas com o mesmo instante, cada uma
    convertida para o dia do fuso da SUA conta. Ler o relógio por conta faria o
    resultado depender de quanto tempo o laço levou — e se esse laço um dia
    ganhar I/O, um run atravessando a meia-noite de alguma conta carimbaria
    dias diferentes na mesma passagem. Hoje ele é uma comprehension sem
    `await`, então a invariante "um relógio por execução" é sustentada pela
    FORMA do código, não por teste (m2 da revisão da Task 2 — a frase antiga
    descrevia um cenário que o laço atual não consegue produzir).
    Injetável porque só assim o teste consegue um instante em que UTC e a conta
    discordam (a diferença que `freezegun` não representa).
    """
    agora = now if now is not None else datetime.now(UTC)
    async with conn.transaction():
        # Ler ANTES do upsert. `upsert_many` marca is_active=true e zera
        # missed_syncs pra toda conta do MCC; lido depois dele, o inventário já
        # parece "em dia" e `to_add` sai vazio SEMPRE (revisão Meta, round 1).
        inventario = await google_ads_accounts.list_inventory_rows(conn)
        plano = build_plan(
            mcc_ids={a["customer_id"] for a in accounts},
            inventory=inventario,
            complete=complete,
            # O MESMO instante que carimba as ausências abaixo. `build_plan`
            # precisa dele para saber se a ausência desta execução já está no
            # contador (retry do mesmo dia) — se os dois divergissem, plano e
            # carimbo falariam de dias diferentes.
            now=agora,
        )
        n = await google_ads_accounts.upsert_many(conn, accounts)
        # C4/F141: o plano devolve ids; a ausência precisa do DIA em que caiu, no
        # fuso da conta. O fuso vem do inventário lido acima (indexação direta,
        # não `.get()`: `to_bump` é derivado de `inventario`, então a chave existe
        # por construção — e se um dia deixar de existir, quebrar alto é melhor
        # que carimbar o inventário inteiro em UTC calado).
        fusos = {r.customer_id: r.time_zone for r in inventario}
        bump = [(cid, account_today(fusos[cid], now=agora)) for cid in plano.to_bump]
        # Task 4/Step 5: `reset=[]`, não `plano.to_reset`. `upsert_many`
        # (duas linhas acima, MESMA transação, sem I/O entre os dois) já zera
        # `missed_syncs`/`last_missed_on` para toda conta em `accounts` — e
        # `to_reset` é subconjunto de `mcc_ids` por construção (`build_plan`:
        # `r.customer_id in mcc_ids`), com `mcc_ids` derivado do próprio
        # `accounts` (linha ~102, `{a["customer_id"] for a in accounts}`).
        # Ou seja: toda vez que este UPDATE chegasse a rodar pra um id de
        # `to_reset`, `missed_syncs` já estaria em 0 — e a cláusula `AND
        # missed_syncs <> 0` de `apply_absences` barra a linha antes de
        # reescrevê-la. Provado (não só argumentado) em
        # `test_reset_e_redundante_apos_upsert_many_no_mesmo_run`
        # (tests/integration/test_google_reconcile_repo.py): mesmo `xmin`
        # antes/depois do reset explícito, na mesma sequência que este
        # `reconcile_google` usa. `plano.to_reset` continua computado — quem
        # o lê é só `resumo["reset"]` (a contagem pro audit; ~linha 172), não
        # mais este call site.
        #
        # Deliberadamente NÃO espelhado no lado Meta
        # (`src/jobs/meta_resync.py`): lá `meta_reconcile_apply` já está
        # ligada em produção (revoga acesso de verdade desde 05/09), e a
        # mesma equivalência não foi provada contra ESSE código — só contra
        # este. CLAUDE.md: "Don't assertar superfície... por analogia."
        await google_ads_accounts.apply_absences(conn, bump=bump, reset=[])

        # Contado SEMPRE, inclusive no dry-run: a trava governa DESTRUIÇÃO, não
        # observação. Sem isto o soak inteiro reporta zero e não distingue "não
        # há o que revogar" de "há 34 e a trava está segurando".
        #
        # I1 (revisão de branch, 2026-09-05): backlog (`is_active=false` já
        # gravado) SOMADO aos grants vivos nas contas que ESTA execução vai
        # desativar (`plano.to_remove`, ainda ativas agora — a contagem roda
        # antes do `deactivate()` abaixo). Só o backlog deixava o dry-run cego
        # justamente pra véspera da revogação: conta a 1 ausência do limiar
        # media revoke_candidates=0 nos dois modos (dry-run e apply), quando o
        # apply de verdade ia revogar 1 grant no dia seguinte.
        candidatos_backlog = await manager_account_access.count_grants_on_inactive_accounts(conn)
        candidatos_a_sair = await manager_account_access.count_grants_on_accounts(
            conn, customer_ids=plano.to_remove
        )
        candidatos = candidatos_backlog + candidatos_a_sair

        # Destrutivo: exige leitura completa E a trava ligada.
        # `blocked_reason is None` já implica leitura completa (`build_plan`
        # com `complete=False` sempre devolve blocked_reason preenchido e
        # to_remove vazio — é o que faz inventário vazio ser zero desativação
        # E zero revogação, mesmo que `apply` esteja True).
        aplicado = apply and plano.blocked_reason is None
        revogados = 0
        if aplicado:
            await google_ads_accounts.deactivate(conn, customer_ids=plano.to_remove)
            # Sobre o ESTADO, não sobre o delta desta execução: é o que cobre as
            # contas que JÁ estavam inativas (34 grants em 9 contas em
            # 2026-09-05), que nenhum `to_remove` calculado a partir de `ativos`
            # alcançaria.
            atingidos = await manager_account_access.revoke_for_inactive_accounts(conn)
            revogados = sum(len(v) for v in atingidos.values())
            # C2 (revisão de branch): por conta, não por grant (forense
            # suficiente sem inundar a trilha), na MESMA transação da
            # revogação — ou os dois gravam, ou nenhum. Espelha
            # `meta_resync.reconcile_meta`; sem isto o estado da tabela era a
            # única prova de que a revogação aconteceu, e reconceder por
            # qualquer caminho (`grant`/`bulk_grant`/`grant_all_active`/
            # `copy_access`) zera `revoked_at`/`revoked_reason` — depois disso
            # não sobra registro nenhum de que um acesso humano foi retirado.
            for customer_id, manager_ids in atingidos.items():
                await record_access_revocation(
                    conn,
                    platform="google",
                    ad_account_id=customer_id,
                    reason=manager_account_access.LEFT_MCC_REASON,
                    manager_ids=manager_ids,
                )

    return {
        "added": len(plano.to_add),
        "bumped": len(plano.to_bump),
        "removed": len(plano.to_remove),
        "reset": len(plano.to_reset),
        "revoke_candidates": candidatos,
        "revoked_grants": revogados,
        "applied": aplicado,
        "complete": complete,
        "upserted": n,
        "blocked_reason": plano.blocked_reason,
    }


async def avisar_contas_sem_grant(conn: asyncpg.Connection) -> int:
    """Emite o evento que a policy de alerta observa. Devolve quantas achou.

    `warning`, não `error`: a anomalia é do inventário, não da execução — o
    job fez o trabalho certo. Não é pra evitar a policy de "Cloud Run Job
    failed": verificado ao vivo no Cloud Monitoring, ela é keyed em
    `completed_execution_count{result="failed"}` — resultado/exit code da
    execução, não severidade de log; um `log.error` isolado que não derruba o
    job não a dispara, e hoje não existe policy de severidade cobrindo
    `cloud_run_job`.

    Só emite quando há o que avisar: alarme que aparece sempre ensina a ser
    ignorado (mesma razão do `aviso_cobertura` do F151).
    """
    queues = await google_ads_accounts.list_queues(conn)
    if not queues.sem_delegacao:
        return 0
    log.warning(
        "google_accounts_sem_grant",
        total=len(queues.sem_delegacao),
        customer_ids=[r["customer_id"] for r in queues.sem_delegacao],
    )
    return len(queues.sem_delegacao)


async def run() -> int:
    settings = get_settings()
    # Task 7: sem isto, o job loga em texto puro (o renderer default do
    # structlog não-configurado) — `configure_logging` só era chamado em
    # `src/app.py` (o serviço web). `avisar_contas_sem_grant` abaixo depende de
    # `jsonPayload.event` pra alimentar a métrica log-based do alerta; achado
    # ao inspecionar logs reais do job em produção (linhas em texto puro tipo
    # "2026-09-05 09:00:24 [info] resync_complete ..."), não só por leitura —
    # sem este fix a métrica nunca teria uma entrada JSON pra casar.
    configure_logging(level=settings.log_level, json_output=settings.app_env != "development")
    await connection.init_pool(settings.database_url)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            manager, oc = await _pick_oauth_connection(conn)
            if oc is None:
                log.error("resync_no_oauth_connection")
                print(
                    "No active OAuth connection — bootstrap an admin and have them complete /oauth/google/start first.",
                    file=sys.stderr,
                )
                await record_job_run(
                    conn,
                    operation="google_reconcile",
                    platform="google",
                    status="error",
                    error_message="no active OAuth connection",
                )
                return 1

        master_key = derive_master_key_from_settings(settings.aes_master_key)
        refresh_token = decrypt_refresh_token(oc.refresh_token_enc, master_key)

        client = build_client(
            refresh_token=refresh_token,
            developer_token=settings.google_ads_developer_token,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            login_customer_id=settings.google_ads_login_customer_id,
        )

        # Discover accessible customers (mostly: just the MCC itself).
        resource_names = list_accessible_customer_resource_names(client)
        log.info("resync_accessible_customers", count=len(resource_names))

        # Pull descriptive details for all child customers under the MCC.
        accounts = fetch_account_details(
            client,
            login_customer_id=settings.google_ads_login_customer_id,
            customer_ids=[],  # empty → all
        )

        # F85: `[]` sem exceção é anomalia de leitura, não "o MCC ficou vazio".
        # Agir nisso desativaria o inventário inteiro (25 contas) por 24h. Espelha
        # a decisão do lado Meta (F65/F93): inventário suspeito não alimenta
        # deletion detection, e o run é auditado como erro pra não passar batido.
        #
        # Task 5: a proteção mudou de forma, não de intenção. Antes era um branch
        # aqui mesmo (`if inventario_ok: mark_inactive_except(...)`); agora
        # `inventario_ok` vira o `complete=` de `reconcile_google` → `build_plan`,
        # que com `complete=False` devolve `to_remove` vazio e `blocked_reason`
        # preenchido — zero desativação E zero revogação, mesmo com a trava
        # (`google_reconcile_apply`) ligada.
        inventario_ok = bool(accounts)
        if not inventario_ok:
            log.error("resync_empty_account_list", mcc_id=settings.google_ads_login_customer_id)

        async with pool.acquire() as conn:
            resumo = await reconcile_google(
                conn,
                accounts=accounts,
                complete=inventario_ok,
                apply=settings.google_reconcile_apply,
            )
            # Task 4/F83: `record_job_run` roda DEPOIS do `return` de
            # `reconcile_google` — a transação da reconciliação já fechou
            # (commitou) antes desta linha, então uma exceção aqui é falha de
            # BOOKKEEPING sobre uma operação que já aconteceu, não da
            # reconciliação em si. Sem `best_effort` ela subia pro `except`
            # externo (~:373+), que grava um `record_job_crash` e RE-LEVANTA —
            # o Cloud Run Job (`maxRetries: 3`) reexecutava a reconciliação
            # INTEIRA só porque o audit da vez anterior não gravou. Com as
            # Tasks 2/3 esse retry já não corrompe nada; isto fecha a causa do
            # retry. Mesma classe do F83 dos executores de mutação
            # (src/google_ads/mutations.py), só que aqui o bookkeeping roda
            # numa chamada solta, não num `finally` — por isso o guard
            # estrutural do F83 (test_finally_bookkeeping_is_best_effort) não
            # alcança este ponto (ver task-4-report.md).
            async with best_effort("job_run_audit_failed", operation="google_reconcile"):
                await record_job_run(
                    conn,
                    operation="google_reconcile",
                    platform="google",
                    target_count=resumo["upserted"],
                    status="success" if resumo["blocked_reason"] is None else "error",
                    error_message=resumo["blocked_reason"],
                    params_summary={
                        k: v for k, v in resumo.items() if k not in ("upserted", "blocked_reason")
                    },
                )
            # Task 7: depois do record_job_run, na MESMA conexão — lê o
            # inventário já reconciliado por esta execução.
            #
            # Best-effort SIM se aplica aqui — ao contrário do que este
            # comentário dizia antes (revisão de branch, 2026-09-05: "é só um
            # SELECT + log, nada a proteger"). Verdade só sobre escrita
            # parcial, não sobre o que importa: sem isolar, uma falha
            # transitória em `list_queues` (i) escapa do `async with
            # pool.acquire()` acima e pula INTEIRAMENTE o piggyback Meta e o
            # purge diário abaixo — que já são best-effort próprios —, e (ii)
            # cai no `except` externo, que grava um SEGUNDO record_job_run
            # como crash logo depois do sucesso já commitado linhas acima:
            # duas linhas de auditoria contraditórias pra mesma execução.
            # Isolado no mesmo padrão dos dois vizinhos (Meta/purge).
            try:
                await avisar_contas_sem_grant(conn)
            except Exception as e:  # noqa: BLE001
                log.warning("avisar_contas_sem_grant_failed", error=str(e))
                print(
                    f"WARN: avisar_contas_sem_grant falhou (non-fatal): {e}",
                    file=sys.stderr,
                )

        log.info("resync_complete", **resumo)
        print(f"OK: google reconcile — {resumo}")

        # Piggyback: refresh do inventário Meta no MESMO job/scheduler, pra conta
        # nova aparecer zero-touch. Best-effort — falha Meta não quebra o resync
        # Google (e é no-op se o system-user token não estiver no job).
        try:
            from src.jobs.meta_resync import reconcile_meta

            # `conn` explícito (revisão da Task 3): `reconcile_meta` deixou de
            # aceitar `None` e adquirir a própria conexão. Este `acquire` está
            # FORA de qualquer transação aberta — que é justamente a garantia
            # que o default `None` não conseguia dar a call-site nenhum.
            async with pool.acquire() as conn_meta:
                plano_meta = await reconcile_meta(conn_meta)
            print(
                "OK: Meta reconcile — "
                f"add={len(plano_meta.to_add)} remove={len(plano_meta.to_remove)} "
                f"blocked={plano_meta.blocked_reason}"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("meta_reconcile_failed", error=str(e))
            print(f"WARN: Meta reconcile falhou (non-fatal): {e}", file=sys.stderr)
            # F93 pela terceira porta (I2 da revisão de branch): `record_job_crash`
            # vivia só dentro de `meta_resync.run()`, que SÓ o entry point
            # `python -m src.jobs.meta_resync` alcança. O Cloud Run Job diário
            # roda por aqui, e este `except` engolia tudo — a edge de parceria
            # podia mudar de forma ou de permissão (risco nº 1 da §13) e a
            # reconciliação ficaria morta por dias sem UMA linha no audit_log,
            # nem status=error. Fica DEPOIS do log/print de propósito: o rastro
            # da falha original é registrado primeiro, e `record_job_crash` já
            # embrulha o próprio I/O em `best_effort` (F83), então o audit não
            # vira um segundo crash por cima do primeiro.
            await record_job_crash(operation="meta_reconcile", platform="meta", exc=e)

        # Purge diário de tabelas transientes (pending_confirmations, rate_counters,
        # meta_rate_counters). Best-effort: falha de purge não derruba o resync.
        # audit_log NUNCA é purgado (compliance) — não faz parte deste escopo.
        try:
            counts = await purge_expired(pool)
            total_purged = sum(counts.values())
            async with pool.acquire() as conn:
                await record_job_run(
                    conn,
                    operation="db_purge",
                    platform="google",
                    status="success",
                    target_count=total_purged,
                    params_summary=counts,
                )
            print(f"OK: purged {total_purged} rows ({counts})")
        except Exception as e:  # noqa: BLE001
            log.warning("db_purge_failed", error=str(e))
            print(f"WARN: purge falhou (non-fatal): {e}", file=sys.stderr)

        return 0
    except Exception as e:
        # F93: crash inesperado (build_client, fetch_account_details, upsert_many)
        # nao pode sumir da trilha — o rastro ficaria so no Cloud Run.
        #
        # I2 (revisão de branch, 2026-09-05): `operation` unificado com o
        # caminho de sucesso/bloqueio (`google_reconcile`, espelhando
        # `meta_reconcile` dos dois lados no gêmeo) — era `account_resync`
        # aqui e no "sem OAuth connection" acima, string DIFERENTE da que o
        # run bem-sucedido grava. Pra job diário atrás de trava, é o dia em
        # que o job MORREU que interessa: com operação diferente por caminho,
        # a query de triagem do soak (`WHERE operation='google_reconcile'`) só
        # mostrava os dias em que o job chegava ao fim, e o dia ausente da
        # série ficava indistinguível de "rodou e não achou nada".
        await record_job_crash(operation="google_reconcile", platform="google", exc=e)
        raise
    finally:
        await connection.close_pool()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
