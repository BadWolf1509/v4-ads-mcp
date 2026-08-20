"""Cloud Run Job tail: reconcilia meta_ad_accounts contra a parceria autoritativa do BM.

Roda piggyback no fim do job diário account_resync (mesmo Cloud Run Job +
Cloud Scheduler) pra que conta de cliente nova entre no inventário zero-touch.

Le duas fontes: `fetch_partnership` (autoritativa — a edge do BM, spec
2026-08-20) e `_fetch_all_adaccounts` (o alcance do system user via
/me/adaccounts). `build_plan` decide o que fazer com as duas; este módulo só
aplica. Grants seguem MANUAIS (Modelo B): reconciliar nunca CONCEDE acesso —
só ajusta o inventário e, quando uma conta sai da parceria, revoga o que os
gestores tinham.

Standalone: `python -m src.jobs.meta_resync`
"""

import asyncio
import sys

import httpx
import structlog

from src.auth.meta_oauth import _fetch_all_adaccounts
from src.config import get_settings
from src.db import connection
from src.db.repositories import manager_meta_account_access, meta_ad_accounts
from src.jobs._audit import record_access_revocation, record_job_crash, record_job_run
from src.meta_ads.partnership import fetch_partnership
from src.meta_ads.reconcile import Plan, build_plan

log = structlog.get_logger(__name__)


async def reconcile_meta() -> Plan:
    """Lê a parceria, planeja e aplica. Assume `connection.init_pool()` feito."""
    settings = get_settings()
    if not settings.meta_system_user_token:
        log.warning("meta_reconcile_no_token")
        return Plan(blocked_reason="token do system user nao configurado")
    if not settings.meta_business_id:
        log.warning("meta_reconcile_no_business_id")
        return Plan(blocked_reason="meta_business_id nao configurado")

    async with httpx.AsyncClient(timeout=60.0) as http:
        parceria = await fetch_partnership(
            http,
            access_token=settings.meta_system_user_token,
            business_id=settings.meta_business_id,
        )
        alcance = await _fetch_all_adaccounts(http, settings.meta_system_user_token)

    ids_parceria = {a["ad_account_id"] for a in parceria.accounts}
    ids_alcance = {
        i if i.startswith("act_") else f"act_{i}"
        for i in (a.get("id", "") for a in alcance.accounts)
    }

    pool = connection.get_pool()
    async with pool.acquire() as conn:
        # Leitura e plano ANTES do upsert (achado da revisão, round 1,
        # 2026-08-20): upsert_many marca is_active=true e ZERA missed_syncs pra
        # toda conta da parceria. Se rodasse primeiro, o inventário já
        # apareceria "em dia" quando lido — to_add e to_reset sairiam vazios
        # SEMPRE, e o audit nunca reportaria conta nova nem carência zerada.
        inventario = await meta_ad_accounts.list_inventory_rows(conn)
        plano = build_plan(
            partnership_ids=ids_parceria,
            reachable_ids=ids_alcance,
            inventory=inventario,
            complete=parceria.complete and alcance.complete,
        )
        # Aditivo e sempre seguro (mesmo com leitura parcial) — é o que faz a
        # conta nova aparecer pro admin delegar. `to_reset` fica parcialmente
        # redundante com o zeramento que o upsert já faz sozinho — inofensivo,
        # o plano e a escrita continuam consistentes.
        upserted = await meta_ad_accounts.upsert_many(conn, parceria.accounts)

        aplicado = settings.meta_reconcile_apply and plano.blocked_reason is None
        revogados = 0
        if aplicado:
            # Uma transação só pro bloco inteiro: metade aplicada (carência
            # somada sem desativar, ou desativada com grant ainda vivo) é
            # exatamente a inconsistência que este recurso existe pra evitar.
            async with conn.transaction():
                await meta_ad_accounts.apply_absences(
                    conn, bump=plano.to_bump, reset=plano.to_reset
                )
                # Só roda aqui dentro porque `aplicado` exige blocked_reason is
                # None, e build_plan() só devolve None com complete=True — ou
                # seja, com as duas leituras (parceria + alcance) completas.
                # Leitura parcial nunca chega a marcar alcance.
                await meta_ad_accounts.set_reachable(conn, reachable_ids=sorted(ids_alcance))
                await meta_ad_accounts.deactivate(conn, ad_account_ids=plano.to_remove)
                for ad_account_id in plano.to_remove:
                    atingidos = await manager_meta_account_access.revoke_for_account(
                        conn,
                        ad_account_id=ad_account_id,
                        reason=manager_meta_account_access.PARTNERSHIP_ENDED_REASON,
                    )
                    revogados += len(atingidos)
                    # Por conta, não por grant: forense suficiente, sem inundar
                    # a trilha. Mesma transação da revogação — ou os dois
                    # gravam, ou nenhum.
                    await record_access_revocation(
                        conn,
                        ad_account_id=ad_account_id,
                        reason=manager_meta_account_access.PARTNERSHIP_ENDED_REASON,
                        manager_ids=[str(m) for m in atingidos],
                    )

        await record_job_run(
            conn,
            operation="meta_reconcile",
            platform="meta",
            target_count=upserted,
            status="success" if plano.blocked_reason is None else "error",
            error_message=plano.blocked_reason,
            params_summary={
                "added": len(plano.to_add),
                "removed": len(plano.to_remove),
                "bumped": len(plano.to_bump),
                "unreachable": len(plano.unreachable),
                "revoked_grants": revogados,
                "applied": aplicado,
            },
        )
    log.info("meta_reconcile_complete", applied=aplicado, plan=plano)
    return plano


async def run() -> int:
    settings = get_settings()
    await connection.init_pool(settings.database_url)
    try:
        plano = await reconcile_meta()
        print(
            "OK: Meta reconcile — "
            f"add={len(plano.to_add)} bump={len(plano.to_bump)} "
            f"remove={len(plano.to_remove)} reset={len(plano.to_reset)} "
            f"unreachable={len(plano.unreachable)} blocked={plano.blocked_reason}"
        )
        return 0
    except Exception as e:
        # F93: sem isto, um crash aqui nao deixa NENHUMA linha no audit — o job
        # some da trilha e a quebra so aparece em quem for ler o Cloud Run.
        await record_job_crash(operation="meta_reconcile", platform="meta", exc=e)
        raise
    finally:
        await connection.close_pool()


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
