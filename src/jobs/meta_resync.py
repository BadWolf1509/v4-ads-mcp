"""Cloud Run Job tail: reconcilia meta_ad_accounts contra a parceria autoritativa do BM.

Roda piggyback no fim do job diário account_resync (mesmo Cloud Run Job +
Cloud Scheduler) pra que conta de cliente nova entre no inventário zero-touch.

Le a parceria (`fetch_partnership`, autoritativa — a edge do BM, spec
2026-08-20) e MEDE o alcance do system user com uma leitura mínima por conta da
parceria (`meta_ads.alcance`, F154) — não mais pelo índice `/me/adaccounts`, que
omitia conta que o SU lê. `build_plan` decide; este módulo só aplica. Grants seguem MANUAIS (Modelo B): reconciliar nunca CONCEDE acesso —
só ajusta o inventário e, quando uma conta sai da parceria, revoga o que os
gestores tinham.

Standalone: `python -m src.jobs.meta_resync`
"""

import asyncio
import sys
from datetime import UTC, datetime

import asyncpg
import httpx
import structlog

from src.clock import account_today
from src.config import get_settings
from src.db import connection
from src.db.repositories import manager_meta_account_access, meta_ad_accounts
from src.governance.bookkeeping import best_effort
from src.jobs._audit import record_access_revocation, record_job_crash, record_job_run
from src.logging import configure_logging
from src.meta_ads.alcance import sondar_alcance
from src.meta_ads.partnership import fetch_partnership
from src.meta_ads.reconcile import Plan, build_plan

log = structlog.get_logger(__name__)


async def reconcile_meta(conn: asyncpg.Connection, *, now: datetime | None = None) -> Plan:
    """Lê a parceria, planeja e aplica na conexão que RECEBE.

    `conn` é obrigatório, como em `reconcile_google` — a simetria entre os dois
    laços é requisito, e o F128 nasceu de uma cláusula que ficou de fora de um
    dos lados. Havia aqui um `conn: … | None = None` que caía num
    `pool.acquire()` interno. Medido na revisão: chamado sem `conn` de DENTRO
    de uma transação já aberta, ele pegava OUTRA conexão do pool — a
    reconciliação decidia `to_bump`/`to_remove` sobre um inventário que não
    era o que o chamador acabava de gravar (0 vs 1 linha visível) e, se a
    transação externa segurasse lock em `meta_ad_accounts` (o que `upsert_many`
    faz), a escrita interna travava até o `command_timeout` — sem deadlock
    detectado, porque a sessão externa está *idle in transaction*.

    Nenhum chamador fazia isso; o problema é que nada impedia, e não dá para
    provar estaticamente que um call-site futuro não está dentro de uma
    transação. O padrão é o mesmo do lado Google: **quem chama é dono da
    unidade de trabalho** e diz de onde a conexão vem. Custa duas linhas em
    cada um dos dois call-sites de produção (`run()` aqui e o piggyback do
    `account_resync`), que é literalmente o que o gêmeo já faz.

    `now` é o instante da EXECUÇÃO, lido UMA vez e passado adiante (C4/F141):
    todas as ausências deste run são carimbadas com o mesmo instante, cada uma
    convertida para o dia do fuso da SUA conta. Ler o relógio por conta faria o
    resultado depender de quanto tempo o laço levou. Injetável porque só assim
    o teste consegue um instante em que UTC e a conta discordam (a diferença
    que `freezegun` não representa).
    """
    settings = get_settings()
    if not settings.meta_system_user_token:
        log.warning("meta_reconcile_no_token")
        return Plan(blocked_reason="token do system user nao configurado")
    if not settings.meta_business_id:
        log.warning("meta_reconcile_no_business_id")
        return Plan(blocked_reason="meta_business_id nao configurado")

    # Lido antes da rede: a sonda resolve "ontem" no fuso de cada conta sobre este
    # mesmo instante, e o carimbo das ausências abaixo também (C4/F141).
    agora = now if now is not None else datetime.now(UTC)
    async with httpx.AsyncClient(timeout=60.0) as http:
        parceria = await fetch_partnership(
            http,
            access_token=settings.meta_system_user_token,
            business_id=settings.meta_business_id,
        )
        # F154: o alcance é MEDIDO — uma leitura mínima por conta da parceria, na
        # forma das tools. O índice `/me/adaccounts` omitia conta que o SU lê (a
        # CHUTE 07, em 27/09), e a fila do painel mandava atribuir um SU que já lia.
        alcance = await sondar_alcance(
            http,
            access_token=settings.meta_system_user_token,
            contas=[(a["ad_account_id"], a.get("timezone_name")) for a in parceria.accounts],
            agora=agora,
        )

    ids_parceria = {a["ad_account_id"] for a in parceria.accounts}

    # F154 fecha o M10: a completude é só a da parceria, a fonte autoritativa
    # (spec 2026-08-20 §3). Antes era `parceria AND /me/adaccounts`, e uma
    # indisponibilidade do índice — que não define o inventário — congelava o
    # offboarding e gravava `status=error` todo dia. A sonda não entra aqui: conta
    # não medida só deixa de ter o alcance atualizado, não bloqueia nada.
    leitura_completa = parceria.complete

    # Uma transação só pro bloco de escrita inteiro: metade aplicada
    # (carência somada sem desativar, ou desativada com grant ainda vivo) é
    # exatamente a inconsistência que este recurso existe pra evitar.
    async with conn.transaction():
        # Leitura e plano ANTES do upsert (achado da revisão, round 1,
        # 2026-08-20): upsert_many marca is_active=true e ZERA missed_syncs
        # pra toda conta da parceria. Se rodasse primeiro, o inventário já
        # apareceria "em dia" quando lido — to_add e to_reset sairiam
        # vazios SEMPRE, e o audit nunca reportaria conta nova nem carência
        # zerada.
        inventario = await meta_ad_accounts.list_inventory_rows(conn)
        plano = build_plan(
            partnership_ids=ids_parceria,
            # F154: as recusas MEDIDAS (`#200`), não o complemento de um índice.
            refused_ids=set(alcance.recusa),
            inventory=inventario,
            complete=leitura_completa,
            # O MESMO instante que carimba as ausências abaixo.
            # `build_plan` precisa dele para saber se a ausência desta
            # execução já está no contador (retry do mesmo dia) — se os
            # dois divergissem, plano e carimbo falariam de dias
            # diferentes.
            now=agora,
        )

        # A trava `meta_reconcile_apply` governa DESTRUIÇÃO, não OBSERVAÇÃO
        # (C2 da revisão de branch). Upsert, carência e alcance escrevem em
        # toda execução, inclusive no dry-run: é o dry-run que dá sentido ao
        # soak. Com `set_reachable` atrás da trava, `su_reachable` ficava no
        # `DEFAULT true` da migration durante todo o soak, a fila "Sem o
        # system user atribuído" nascia vazia e as mesmas contas apareciam
        # em "Aguardando delegação" — convidando a delegar gestor em conta
        # que o SU não lê. Com `apply_absences` atrás dela, `missed_syncs`
        # ficava congelado e `to_remove` era estruturalmente inalcançável.
        # Nada dos três desativa nem revoga: a spec §3/§5 classifica o
        # inalcançável como "só sinaliza" e "NUNCA desativa".
        upserted = await meta_ad_accounts.upsert_many(conn, parceria.accounts)
        # Aditivo é seguro mesmo com leitura parcial — é o que faz a conta
        # nova aparecer pro admin delegar. `to_reset` fica parcialmente
        # redundante com o zeramento que o upsert já faz sozinho; e com
        # leitura parcial `to_bump` sai vazio pelo próprio build_plan, então
        # ausência não vira carência sobre página que não veio (F93).
        #
        # C4/F141: o plano devolve ids; a ausência precisa do DIA em que
        # caiu, no fuso da conta. O fuso vem do inventário lido acima
        # (indexação direta, não `.get()`: `to_bump` é derivado de
        # `inventario` por construção — `build_plan` só o preenche a partir
        # de `ativos` —, e se um dia deixar de ser, quebrar alto é melhor
        # que carimbar o inventário inteiro em UTC calado).
        fusos = {r.ad_account_id: r.timezone_name for r in inventario}
        bump = [(aid, account_today(fusos[aid], now=agora)) for aid in plano.to_bump]
        await meta_ad_accounts.apply_absences(conn, bump=bump, reset=plano.to_reset)
        # `leitura_completa`, NÃO `aplicado`: confundir os dois foi o C2 — a trava
        # de rollout é outra pergunta. Com a parceria truncada o escopo também vem
        # truncado, e o alcance espera a leitura inteira. Conta que a sonda não mediu
        # não é tocada (`set_reachable` só grava `le`/`recusa`).
        if leitura_completa:
            await meta_ad_accounts.set_reachable(
                conn,
                le=sorted(alcance.le),
                recusa=sorted(alcance.recusa),
                scope_ids=sorted(ids_parceria),
            )

        # Destrutivo: exige leitura completa E a trava ligada.
        # `blocked_reason is None` já implica leitura completa (build_plan
        # só devolve None com complete=True) e plano dentro do teto do guard
        # percentual.
        aplicado = settings.meta_reconcile_apply and plano.blocked_reason is None
        revogados = 0
        if aplicado:
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
                    platform="meta",
                    ad_account_id=ad_account_id,
                    reason=manager_meta_account_access.PARTNERSHIP_ENDED_REASON,
                    manager_ids=[str(m) for m in atingidos],
                )

    # Auditoria do run FORA da transação de propósito: bookkeeping não pode
    # desfazer reconciliação já aplicada (família do F83).
    #
    # Task 4: "se ela mesma falhar, o crash cai no record_job_crash de quem
    # chamou" descrevia a INTENÇÃO, mas nada aqui protegia a falha em si. Sem
    # `best_effort`, a exceção subia INTEIRA — via `run()` standalone (`python
    # -m src.jobs.meta_resync`) ou via o try/except do piggyback em
    # `account_resync.run()` — e o chamador tratava uma reconciliação
    # BEM-SUCEDIDA (já commitada, `meta_reconcile_apply` ligada em produção
    # desde 05/09) como se tivesse falhado, gravando um `record_job_crash`
    # logo depois do `record_job_run` que já tinha tentado (e falhado) marcar
    # sucesso — duas linhas de audit contraditórias pra mesma execução.
    async with best_effort("job_run_audit_failed", operation="meta_reconcile"):
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
                # F154: só as recusas medidas; o que a sonda não mediu sai
                # separado, para "não sei" não se passar por "não alcança".
                "unreachable": len(plano.unreachable),
                "alcance_nao_medido": len(alcance.nao_medido),
                "revoked_grants": revogados,
                # M3: a §9 nomeia `complete` explicitamente. Desde o F154 ele é
                # só a leitura da parceria — o alcance não bloqueia mais nada.
                "complete": leitura_completa,
                "applied": aplicado,
            },
        )
    log.info("meta_reconcile_complete", applied=aplicado, plan=plano)
    return plano


async def run() -> int:
    settings = get_settings()
    # Task 4: só o gêmeo Google chamava isto (Task 7 de um sprint anterior).
    # Sem `configure_logging`, este job loga em texto puro (o renderer
    # default do structlog não-configurado) — sem `jsonPayload.severity`, o
    # Cloud Logging classifica tudo como DEFAULT, e nada aqui casa com uma
    # métrica log-based por severidade. O lado que faltava era o que revoga
    # de verdade em produção desde 05/09.
    configure_logging(level=settings.log_level, json_output=settings.app_env != "development")
    await connection.init_pool(settings.database_url)
    try:
        # A conexão nasce AQUI, no topo do job, e não dentro de
        # `reconcile_meta`: quem chama é dono da unidade de trabalho (espelha
        # `account_resync.run()`). Assim nenhum call-site futuro abre uma
        # segunda transação por baixo de uma que já esteja aberta.
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            plano = await reconcile_meta(conn)
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
