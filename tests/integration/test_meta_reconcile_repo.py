# tests/integration/test_meta_reconcile_repo.py
"""O repositorio APLICA o plano; nao decide nada. Contra banco real porque o
que importa aqui e o efeito do SQL, nao a chamada (licao do F85).

C4: a ausencia conta uma vez por DIA, nao uma por EXECUCAO. Este e o lado que
SANGRA — o laco Meta revoga acesso de gestor a conta de cliente em producao
desde 05/09, e o job tem `maxRetries: 3`: um retry depois do commit da
reconciliacao contava a mesma ausencia de novo, e a carencia de 3 dias que
protege a conta do cliente caia em 2 execucoes.

Contra Postgres de verdade porque `IS DISTINCT FROM` sobre coluna NULL e
semantica de SQL, nao de Python — nenhum mock a representa.
"""

from contextlib import ExitStack
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest

from src.db.repositories import manager_meta_account_access, managers, meta_ad_accounts
from src.db.repositories.manager_meta_account_access import PARTNERSHIP_ENDED_REASON
from src.jobs import meta_resync

# `America/Noronha` e UTC-2 o ano inteiro (sem horario de verao): as 00:30 UTC
# do dia 3, na conta ainda sao 22:30 do dia 2. E a discordancia do F141, e e a
# que `freezegun` nao consegue representar. Fuso escolhido entre os MEDIDOS na
# producao Meta (probe 2026-09-06: `America/Sao_Paulo`, `America/Noronha`,
# `America/Manaus` — todos IANA), nao inventado.
INSTANTE_DO_BUG = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)
DIA_DA_CONTA = date(2026, 9, 2)
DIA_DO_SERVIDOR = date(2026, 9, 3)

CONTA = {
    "ad_account_id": "act_1",
    "business_id": "bm",
    "business_name": "BM",
    "account_name": "Conta 1",
    "currency": "BRL",
    "timezone_name": "America/Noronha",
    "account_status": 1,
}
OUTRA = {**CONTA, "ad_account_id": "act_2", "account_name": "Conta 2"}


async def _semear_conta(
    conn: asyncpg.Connection, ad_account_id: str, *, missed_syncs: int = 0, **campos: Any
) -> None:
    """Conta no inventario pelo caminho real (`upsert_many`), carencia opcional."""
    await meta_ad_accounts.upsert_many(conn, [{**CONTA, "ad_account_id": ad_account_id, **campos}])
    if missed_syncs:
        await conn.execute(
            "UPDATE meta_ad_accounts SET missed_syncs = $2 WHERE ad_account_id = $1",
            ad_account_id,
            missed_syncs,
        )


async def _linha(conn: asyncpg.Connection, ad_account_id: str) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT missed_syncs, last_missed_on, xmin::text AS versao "
        "FROM meta_ad_accounts WHERE ad_account_id = $1",
        ad_account_id,
    )
    assert row is not None
    return row


# ---------- nivel de repositorio: `apply_absences` ----------


@pytest.mark.integration
async def test_duas_execucoes_no_mesmo_dia_contam_uma_ausencia_meta(db) -> None:
    """C4, lado Meta — este laco REVOGA acesso em producao desde 05/09.

    Com `maxRetries: 3` no job, um retry apos o commit reexecuta a
    reconciliacao. Antes deste fix a mesma ausencia era contada de novo, e a
    carencia de 3 dias caia em 2 execucoes.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")

        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])
        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])

        linha = await _linha(conn, "act_1")
    assert linha["missed_syncs"] == 1, "retry no mesmo dia contou duas vezes"
    assert linha["last_missed_on"] == DIA_DA_CONTA


@pytest.mark.integration
async def test_dia_novo_conta_de_novo_meta(db) -> None:
    """A carencia tem que continuar avancando: dia diferente, ausencia nova.

    Contraparte obrigatoria do teste acima — sozinho, ele passaria tambem com
    um incremento que nunca conta nada.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")

        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", date(2026, 9, 6))], reset=[])
        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", date(2026, 9, 7))], reset=[])

        linha = await _linha(conn, "act_1")
    assert linha["missed_syncs"] == 2
    assert linha["last_missed_on"] == date(2026, 9, 7)


@pytest.mark.integration
async def test_primeira_ausencia_conta_com_last_missed_on_nulo_meta(db) -> None:
    """`IS DISTINCT FROM`, nao `<>`: `NULL <> $2` avalia para NULL, que nao
    satisfaz o WHERE.

    `last_missed_on` e NULL em TODA linha hoje (a 009 subiu sem backfill, de
    proposito), entao com `<>` a primeira ausencia de cada conta nunca seria
    contada — o contador ficaria congelado em 0 no inventario inteiro, e a
    reconciliacao pararia de proteger o que quer que fosse, em silencio.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")
        antes = await _linha(conn, "act_1")
        assert antes["last_missed_on"] is None, "premissa do teste: a coluna nasce NULL"

        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])

        linha = await _linha(conn, "act_1")
    assert linha["missed_syncs"] == 1, "primeira ausencia da conta nao foi contada"
    assert linha["last_missed_on"] == DIA_DA_CONTA


@pytest.mark.integration
async def test_bump_nao_vaza_para_conta_vizinha_meta(db) -> None:
    """Blast radius do `bump`: o UPDATE mira UM id, nao o inventario.

    O predicado de id e justamente o que este PR reescreveu (`ANY($1::text[])`
    -> `$1` por linha, via `executemany`). Sem esta afirmacao, trocar o
    `WHERE ad_account_id = $1` por qualquer predicado sempre-verdadeiro passa
    verde — e em producao isso e `missed_syncs + 1` no inventario INTEIRO todo
    dia: as contas cruzam o limiar em 3 dias e o laco desativa e revoga todas.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")
        await _semear_conta(conn, "act_2")  # vizinha, NAO citada no bump

        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])

        alvo = await _linha(conn, "act_1")
        vizinha = await _linha(conn, "act_2")
    assert alvo["missed_syncs"] == 1
    assert vizinha["missed_syncs"] == 0, "bump vazou para conta que nao estava na lista"
    assert vizinha["last_missed_on"] is None


@pytest.mark.integration
async def test_reset_nao_vaza_para_conta_vizinha_meta(db) -> None:
    """Blast radius do `reset`: zerar a carencia de uma conta nao zera a das outras.

    O espelho do teste acima. Reset que ignora o id apaga a carencia acumulada
    do inventario inteiro — a conta que de fato saiu da parceria nunca chega ao
    limiar, e o offboarding para de acontecer em silencio.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1", missed_syncs=2)
        await _semear_conta(conn, "act_2", missed_syncs=3)  # vizinha, NAO citada no reset
        await conn.execute(
            "UPDATE meta_ad_accounts SET last_missed_on = $2 WHERE ad_account_id = $1",
            "act_2",
            DIA_DA_CONTA,
        )

        await meta_ad_accounts.apply_absences(conn, bump=[], reset=["act_1"])

        alvo = await _linha(conn, "act_1")
        vizinha = await _linha(conn, "act_2")
    assert alvo["missed_syncs"] == 0
    assert vizinha["missed_syncs"] == 3, "reset vazou para conta que nao estava na lista"
    assert vizinha["last_missed_on"] == DIA_DA_CONTA


@pytest.mark.integration
async def test_reset_zera_a_serie_inteira_e_nao_so_o_contador_meta(db) -> None:
    """A serie de ausencias e (`missed_syncs`, `last_missed_on`) — as duas.

    Zerar so o contador deixaria a data velha na linha, e a ausencia seguinte
    da conta seria PULADA se caisse no mesmo dia do reset: a conta voltaria a
    somar carencia so no dia seguinte.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")
        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])

        await meta_ad_accounts.apply_absences(conn, bump=[], reset=["act_1"])
        depois_do_reset = await _linha(conn, "act_1")

        # E a conta volta a faltar NO MESMO DIA do reset.
        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])
        linha = await _linha(conn, "act_1")

    assert depois_do_reset["missed_syncs"] == 0
    assert depois_do_reset["last_missed_on"] is None, "o reset deixou a data velha na linha"
    assert linha["missed_syncs"] == 1, "ausencia pulada por data velha que o reset nao limpou"


@pytest.mark.integration
async def test_reset_nao_reescreve_linha_ja_limpa_meta(db) -> None:
    """`AND missed_syncs <> 0` — a clausula que os DOIS lados tem.

    `to_reset` ja so traz conta com carencia, entao a clausula nao muda o valor
    final; o que ela muda e a linha ser reescrita ou nao, e e isso que este
    teste observa (`xmin` e a transacao que gravou a versao corrente da tupla;
    um UPDATE que casa o WHERE cria versao nova mesmo gravando valores
    identicos).
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")
        antes = await _linha(conn, "act_1")
        assert antes["missed_syncs"] == 0, "premissa: a linha ja esta limpa"

        await meta_ad_accounts.apply_absences(conn, bump=[], reset=["act_1"])

        depois = await _linha(conn, "act_1")
    assert depois["versao"] == antes["versao"], (
        "reset reescreveu linha que ja estava limpa — a clausula `missed_syncs <> 0` sumiu"
    )


@pytest.mark.integration
async def test_conta_que_volta_e_falta_no_mesmo_dia_tem_a_ausencia_contada_meta(db) -> None:
    """`upsert_many` zera `last_missed_on` junto com `missed_syncs` (F128).

    O `ON CONFLICT` ja zerava o contador — 'a conta voltou a parceria, entao a
    serie de ausencias morre aqui'. `last_missed_on` E parte dessa serie: sem
    zera-la junto, a conta que volta e falta de novo no MESMO dia carregaria a
    data velha e teria a ausencia pulada pelo `IS DISTINCT FROM` — carencia que
    nao avanca e conta que nunca sai, o espelho do bug que este PR corrige.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")
        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])

        # A conta reaparece na parceria: o job faz `upsert_many`, que mata a serie.
        await _semear_conta(conn, "act_1")
        depois_do_upsert = await _linha(conn, "act_1")

        # E some de novo no MESMO dia.
        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])
        linha = await _linha(conn, "act_1")

    assert depois_do_upsert["missed_syncs"] == 0
    assert depois_do_upsert["last_missed_on"] is None, (
        "upsert_many deixou a data velha: a serie de ausencias sobreviveu ao reaparecimento"
    )
    assert linha["missed_syncs"] == 1, "ausencia pulada por data que o upsert_many nao limpou"


@pytest.mark.integration
async def test_apply_absences_incrementa_e_zera(db) -> None:
    """O contrato basico, agora com a data: incrementa por DIA, e o reset zera."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        await meta_ad_accounts.apply_absences(conn, bump=[("act_2", date(2026, 9, 6))], reset=[])
        await meta_ad_accounts.apply_absences(conn, bump=[("act_2", date(2026, 9, 7))], reset=[])
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).missed_syncs == 2

        await meta_ad_accounts.apply_absences(conn, bump=[], reset=["act_2"])
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).missed_syncs == 0


@pytest.mark.integration
async def test_deactivate_so_mexe_no_que_foi_pedido(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        n = await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        assert n == 1
        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).is_active is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).is_active is False


@pytest.mark.integration
async def test_lista_vazia_e_noop_em_todas_as_operacoes(db) -> None:
    """F85: lista vazia quase sempre e falha de leitura, nao 'todas sumiram'."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        assert await meta_ad_accounts.deactivate(conn, ad_account_ids=[]) == 0
        await meta_ad_accounts.apply_absences(conn, bump=[], reset=[])
        await meta_ad_accounts.set_reachable(conn, reachable_ids=[], scope_ids=["act_1"])

        assert len(await meta_ad_accounts.list_all(conn)) == 2
        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True


@pytest.mark.integration
async def test_set_reachable_marca_quem_esta_fora_do_alcance(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])

        await meta_ad_accounts.set_reachable(
            conn, reachable_ids=["act_1"], scope_ids=["act_1", "act_2"]
        )

        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is False


@pytest.mark.integration
async def test_set_reachable_nao_toca_em_conta_fora_do_escopo(db) -> None:
    """M4: o UPDATE e escopado a parceria.

    Sem o WHERE, marcar alcance sobre a parceria carimbava su_reachable=false
    em TODA conta que nao viesse em /me/adaccounts — inclusive conta ja
    desativada ou em carencia, pra quem "o SU nao alcanca" nao e sinal
    acionavel nenhum (spec §3: o alerta e pra conta que ESTA na parceria).
    """
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        # act_2 sai da parceria: fora do escopo do proximo set_reachable.
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        await meta_ad_accounts.set_reachable(conn, reachable_ids=["act_1"], scope_ids=["act_1"])

        assert (await meta_ad_accounts.get_by_id(conn, "act_1")).su_reachable is True
        assert (await meta_ad_accounts.get_by_id(conn, "act_2")).su_reachable is True, (
            "conta fora do escopo nao pode ser marcada como 'sem SU' — ela nem "
            "esta mais na parceria, entao o sinal nao tem acao associada"
        )


@pytest.mark.integration
async def test_list_inventory_rows_devolve_o_que_o_plano_consome(db) -> None:
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_2"])

        linhas = {r.ad_account_id: r for r in await meta_ad_accounts.list_inventory_rows(conn)}

        assert linhas["act_1"].is_active is True
        assert linhas["act_2"].is_active is False
        assert linhas["act_1"].missed_syncs == 0


@pytest.mark.integration
async def test_list_inventory_rows_traz_o_fuso_da_conta_meta(db) -> None:
    """O fuso vem no inventario porque `apply_absences` precisa dele (F141).

    Resolve-lo depois seria uma leitura POR CONTA dentro da transacao ja aberta
    da reconciliacao. O fuso viajar junto do inventario torna o calculo do dia
    puro e sem I/O extra.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")
        await _semear_conta(conn, "act_2", timezone_name=None)

        linhas = {r.ad_account_id: r for r in await meta_ad_accounts.list_inventory_rows(conn)}

    assert linhas["act_1"].timezone_name == "America/Noronha"
    assert linhas["act_2"].timezone_name is None, "conta sem fuso tem que chegar como None"


@pytest.mark.integration
async def test_list_inventory_rows_traz_a_data_da_ultima_ausencia_meta(db) -> None:
    """`last_missed_on` viaja no inventario porque `build_plan` DECIDE com ela.

    Diferente do fuso, que o plano ignora: esta coluna e o que distingue "a
    ausencia de hoje ja esta no contador" (retry) de "ainda nao esta". Sem ela
    na linha o planejador soma `+1` sempre, e o retry do mesmo dia queima um
    dia de carencia — o contador fica certo e a DECISAO sai um dia adiantada,
    que deste lado e revogacao de acesso de gestor.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")
        await _semear_conta(conn, "act_2")  # sem ausencia nenhuma
        await meta_ad_accounts.apply_absences(conn, bump=[("act_1", DIA_DA_CONTA)], reset=[])

        linhas = {r.ad_account_id: r for r in await meta_ad_accounts.list_inventory_rows(conn)}

    assert linhas["act_1"].last_missed_on == DIA_DA_CONTA, (
        "a data da ultima ausencia nao chegou ao planejador"
    )
    assert linhas["act_2"].last_missed_on is None, (
        "conta sem serie de ausencias tem que chegar como None"
    )


# ---------- nivel de job: `reconcile_meta` ----------


def _patches_do_job(*, apply: bool):
    """Settings + as duas leituras da rede (parceria vazia, alcance vazio).

    Parceria vazia e completa e o cenario de churn: a conta semeada esta ATIVA
    no inventario e nao esta na parceria, entao `build_plan` a manda pro
    `to_bump` (carencia 0 + 1 = 1 < limiar 3). O banco e real; so a rede sai.
    """
    from src.auth.meta_oauth import AdAccountsFetch
    from src.meta_ads.partnership import PartnershipSnapshot

    return [
        patch.object(
            meta_resync,
            "get_settings",
            MagicMock(
                return_value=MagicMock(
                    meta_system_user_token="tok",
                    meta_business_id="bm",
                    meta_reconcile_apply=apply,
                )
            ),
        ),
        patch.object(
            meta_resync,
            "fetch_partnership",
            AsyncMock(return_value=PartnershipSnapshot([], True)),
        ),
        patch.object(
            meta_resync,
            "_fetch_all_adaccounts",
            AsyncMock(return_value=AdAccountsFetch(accounts=[], complete=True)),
        ),
    ]


@pytest.mark.integration
async def test_o_dia_da_ausencia_vem_do_fuso_da_conta_meta(db) -> None:
    """F141 nesta trilha: `hoje` e propriedade da CONTA, nao do servidor.

    As 00:30 UTC do dia 3, em `America/Noronha` (UTC-2) ainda sao 22:30 do dia
    2. Com o relogio do servidor, a ausencia das 22h a meia-noite locais seria
    carimbada com o dia SEGUINTE — e a ausencia real do dia seguinte cairia no
    `IS DISTINCT FROM` e nao seria contada. O bug do F141 vira carencia
    silenciosamente mais longa, todo dia, na janela em que ninguem testa.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")

        with ExitStack() as stack:
            for p in _patches_do_job(apply=False):
                stack.enter_context(p)
            plano = await meta_resync.reconcile_meta(conn, now=INSTANTE_DO_BUG)

        linha = await _linha(conn, "act_1")
    assert plano.to_bump == ["act_1"]
    assert linha["missed_syncs"] == 1
    assert linha["last_missed_on"] == DIA_DA_CONTA, (
        f"a ausencia foi carimbada com o dia do servidor ({DIA_DO_SERVIDOR}), "
        f"nao com o dia da conta ({DIA_DA_CONTA})"
    )


@pytest.mark.integration
async def test_retry_do_job_no_mesmo_dia_nao_consome_a_carencia_meta(db) -> None:
    """O C4 pelo caminho que a PRODUCAO percorre, ponta a ponta — e este e o
    lado que aplica de verdade desde 05/09.

    `maxRetries: 3`: o job pode reexecutar a reconciliacao inteira depois do
    commit. Duas execucoes no mesmo dia tem de valer UMA ausencia; o dia
    seguinte volta a contar, senao a carencia nunca avanca e conta que saiu da
    parceria fica viva para sempre.
    """
    dia_seguinte = INSTANTE_DO_BUG.replace(day=4)
    async with db.acquire() as conn:
        await _semear_conta(conn, "act_1")

        with ExitStack() as stack:
            for p in _patches_do_job(apply=True):
                stack.enter_context(p)
            await meta_resync.reconcile_meta(conn, now=INSTANTE_DO_BUG)
            await meta_resync.reconcile_meta(conn, now=INSTANTE_DO_BUG)
            depois_do_retry = await _linha(conn, "act_1")

            await meta_resync.reconcile_meta(conn, now=dia_seguinte)
            linha = await _linha(conn, "act_1")

    assert depois_do_retry["missed_syncs"] == 1, (
        "retry do job contou a mesma ausencia de novo — a carencia de 3 dias cai em 2 execucoes"
    )
    assert linha["missed_syncs"] == 2, "dia novo tem que voltar a contar"
    assert linha["last_missed_on"] == date(2026, 9, 3)


@pytest.mark.integration
async def test_retry_na_vespera_do_limiar_nao_remove_a_conta_meta(db) -> None:
    """A DECISAO tambem tem de ser idempotente por dia — nao so o contador.

    O teste de retry acima para em 2 ausencias, longe do limiar 3: prova que
    `apply_absences` nao conta duas vezes, e nao toca a unica execucao em que o
    retry importa, que e a que REMOVE. `build_plan` somava `missed_syncs + 1`
    por EXECUCAO — a suposicao que o C4 quebrou —, entao o retry da vespera lia
    o contador JA bumpado por esta mesma execucao e decidia remover com dois
    dias de ausencia em vez de tres. Neste lado isso e producao viva: desde
    05/09 o laco desativa a conta e REVOGA os grants dos gestores. E
    `missed_syncs` ficava parado em 2, o que torna o sintoma invisivel para
    quem auditar so o contador.

    Cobre tambem o F141 na decisao: com `INSTANTE_DO_BUG` o dia da conta (02/09
    em `America/Noronha`) difere do dia UTC (03/09), entao comparar
    `last_missed_on` com o dia do SERVIDOR nao casaria e o `+1` voltaria.

    A contraprova esta no fim: no dia SEGUINTE a conta tem de sair. Sem ela, um
    planejador que nunca remove passaria verde.
    """
    dia_seguinte = INSTANTE_DO_BUG.replace(day=4)
    async with db.acquire() as conn:
        # Uma ausencia anterior: o run de hoje leva a duas, e o limiar e tres.
        await _semear_conta(conn, "act_1", missed_syncs=1)

        with ExitStack() as stack:
            for p in _patches_do_job(apply=True):
                stack.enter_context(p)
            await meta_resync.reconcile_meta(conn, now=INSTANTE_DO_BUG)
            plano_retry = await meta_resync.reconcile_meta(conn, now=INSTANTE_DO_BUG)
            depois_do_retry = await _linha(conn, "act_1")
            ativa_no_retry = await conn.fetchval(
                "SELECT is_active FROM meta_ad_accounts WHERE ad_account_id = $1", "act_1"
            )

            plano_amanha = await meta_resync.reconcile_meta(conn, now=dia_seguinte)
            ativa_amanha = await conn.fetchval(
                "SELECT is_active FROM meta_ad_accounts WHERE ad_account_id = $1", "act_1"
            )

    assert plano_retry.to_remove == [], (
        "retry no mesmo dia removeu a conta com DOIS dias de ausencia — a decisao "
        "somou +1 sobre um contador que ESTA execucao ja tinha bumpado"
    )
    assert ativa_no_retry is True, "conta desativada (e grants revogados) um dia antes da hora"
    assert depois_do_retry["missed_syncs"] == 2, "o contador tem de seguir idempotente por dia"
    assert plano_amanha.to_remove == ["act_1"], "a remocao no dia certo parou de acontecer"
    assert ativa_amanha is False, "no terceiro dia a conta tem de sair de verdade"


# ---------- filas do painel ----------


@pytest.mark.integration
async def test_list_queues_sem_su_tem_precedencia_sobre_sem_delegacao(db) -> None:
    """Fix round 1 (review): conta sem gestor E sem SU caia nas DUAS filas
    antes deste fix — caso real em producao (CA - V4 Lima Soares, CHUTE 07).
    sem_su ganha: delegar um gestor numa conta que o SU nao alcanca so produz
    #200 quando ele tenta usar; a ordem certa do admin e SU primeiro,
    delegacao depois — por isso as filas tem que ser exclusivas."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        # act_1 fica alcancavel (cai em sem_delegacao, o caso normal); act_2
        # fica de fora (sem SU E sem gestor — o caso que se sobrepunha).
        await meta_ad_accounts.set_reachable(
            conn, reachable_ids=["act_1"], scope_ids=["act_1", "act_2"]
        )

        queues = await meta_ad_accounts.list_queues(conn)

        sem_delegacao_ids = {a.ad_account_id for a in queues.sem_delegacao}
        sem_su_ids = {a.ad_account_id for a in queues.sem_su}

        assert sem_delegacao_ids == {"act_1"}
        assert sem_su_ids == {"act_2"}
        assert not (sem_delegacao_ids & sem_su_ids), "as filas nao podem se sobrepor"


async def _gestor_com_grant(conn, ad_account_id: str, email: str):
    mid = uuid4()
    await managers.create(conn, manager_id=mid, email=email, full_name=None)
    await manager_meta_account_access.bulk_grant(
        conn, manager_id=mid, ad_account_ids=[ad_account_id], granted_by=mid
    )
    return mid


@pytest.mark.integration
async def test_fila_saiu_segue_a_conta_depois_que_a_parceria_volta(db) -> None:
    """C1: a conta que VOLTOU tem de continuar na fila, com o botao alcancavel.

    Este e o cenario da §8 ("a parceria voltou") reproduzido pelo caminho que a
    PRODUCAO percorre — desativa, revoga por churn, e so entao reaparece na
    parceria (upsert_many reativa). Com a fila key-ada em `is_active = false`, a
    conta sumia exatamente aqui, junto com o unico chamador de
    `restore_for_account` no src/; e clicar ANTES nao adiantava, porque o gate
    nega enquanto a conta esta inativa.
    """
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA])
        mid = await _gestor_com_grant(conn, "act_1", "voltou@v4company.com")
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1"])
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason=PARTNERSHIP_ENDED_REASON
        )
        # A parceria volta: o job faz upsert_many, que reativa e zera a carencia.
        await meta_ad_accounts.upsert_many(conn, [CONTA])

        queues = await meta_ad_accounts.list_queues(conn)

        saiu = {c.ad_account_id: (c, n) for c, n in queues.saiu_da_parceria}
        assert "act_1" in saiu, "a conta sumiu da fila justamente ao virar restauravel"
        conta, revogados = saiu["act_1"]
        assert conta.is_active is True
        assert revogados == 1
        # Precedencia: quem tem grant restauravel nao aparece tambem na fila de
        # delegacao, senao o painel convida a refazer a mao o que o botao devolve.
        assert "act_1" not in {a.ad_account_id for a in queues.sem_delegacao}

        # E o botao funciona de verdade neste estado (era o outro lado do C1: o
        # restore rodava, o flash dizia "restaurado", e o gate seguia negando).
        assert (
            await manager_meta_account_access.restore_for_account(conn, ad_account_id="act_1") == 1
        )
        assert await manager_meta_account_access.can_manager_access(conn, mid, "act_1") is True
        depois = await meta_ad_accounts.list_queues(conn)
        assert "act_1" not in {c.ad_account_id for c, _ in depois.saiu_da_parceria}


@pytest.mark.integration
async def test_fila_saiu_poe_quem_voltou_antes_do_historico(db) -> None:
    """A conta acionavel nao pode afundar no meio de quem saiu e nao voltou."""
    async with db.acquire() as conn:
        # OUTRA ("Conta 2") ordena depois de CONTA ("Conta 1") por nome — se a
        # ordenacao fosse so por account_name, a que voltou viria em segundo.
        await meta_ad_accounts.upsert_many(conn, [CONTA, OUTRA])
        await _gestor_com_grant(conn, "act_1", "hist@v4company.com")
        await _gestor_com_grant(conn, "act_2", "volta@v4company.com")
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1", "act_2"])
        for aid in ("act_1", "act_2"):
            await manager_meta_account_access.revoke_for_account(
                conn, ad_account_id=aid, reason=PARTNERSHIP_ENDED_REASON
            )
        await meta_ad_accounts.upsert_many(conn, [OUTRA])  # so act_2 volta

        queues = await meta_ad_accounts.list_queues(conn)

        assert [c.ad_account_id for c, _ in queues.saiu_da_parceria] == ["act_2", "act_1"]


@pytest.mark.integration
async def test_fila_saiu_conta_so_o_que_o_restore_devolve(db) -> None:
    """I5: o numero exibido e o mesmo conjunto que o botao reconcede.

    Um gestor destogglado a mao (`manual`) numa conta que depois sai da parceria
    entrava na contagem: o painel mostrava 2, o Restaurar devolvia 1, e a
    contagem caia sem o admin entender por que.
    """
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA])
        mid_manual = await _gestor_com_grant(conn, "act_1", "manual@v4company.com")
        await _gestor_com_grant(conn, "act_1", "churn@v4company.com")
        await manager_meta_account_access.revoke(
            conn, manager_id=mid_manual, ad_account_id="act_1", reason="manual"
        )
        await meta_ad_accounts.deactivate(conn, ad_account_ids=["act_1"])
        await manager_meta_account_access.revoke_for_account(
            conn, ad_account_id="act_1", reason=PARTNERSHIP_ENDED_REASON
        )

        queues = await meta_ad_accounts.list_queues(conn)

        (_conta, revogados) = next(
            (c, n) for c, n in queues.saiu_da_parceria if c.ad_account_id == "act_1"
        )
        restaurados = await manager_meta_account_access.restore_for_account(
            conn, ad_account_id="act_1"
        )
        assert revogados == restaurados == 1


@pytest.mark.integration
async def test_fila_saiu_ignora_conta_sem_revogacao_por_churn(db) -> None:
    """Revogacao manual sozinha nao poe a conta na fila de churn."""
    async with db.acquire() as conn:
        await meta_ad_accounts.upsert_many(conn, [CONTA])
        mid = await _gestor_com_grant(conn, "act_1", "so-manual@v4company.com")
        await manager_meta_account_access.revoke(
            conn, manager_id=mid, ad_account_id="act_1", reason="manual"
        )

        queues = await meta_ad_accounts.list_queues(conn)

        assert queues.saiu_da_parceria == []
        # Sem grant vivo e sem churn pendente, ela e caso de delegacao mesmo.
        assert "act_1" in {a.ad_account_id for a in queues.sem_delegacao}
