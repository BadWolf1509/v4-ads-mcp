# tests/integration/test_google_reconcile_repo.py
"""C4: a ausência conta uma vez por DIA, não uma por EXECUÇÃO.

O job de resync tem `maxRetries: 3` (medido em `gcloud run jobs describe`: o
`migrate` recebeu `--max-retries=1` explícito, o `resync` nunca recebeu). Um
retry depois do commit da reconciliação reexecutava a mesma ausência, e a
carência de 3 dias que protege a conta do cliente caía em 2 execuções — do lado
Meta, o gêmeo deste laço revoga acesso de gestor em produção desde 05/09.

Contra banco real porque o que importa aqui é o efeito do SQL, não a chamada
(lição do F85, mesma razão do `test_meta_reconcile_repo.py`). O arquivo junta
o nível de repositório e o de job de propósito: a prova do C4 atravessa os
dois — a data só é idempotente se o fuso da conta chegar até ela.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import asyncpg
import pytest

from src.db.repositories import google_ads_accounts
from src.jobs import account_resync

# `America/Fortaleza` é UTC-3 o ano inteiro (sem horário de verão): às 00:30 UTC
# do dia 3, na conta ainda são 21:30 do dia 2. É a discordância do F141, e é a
# que `freezegun` não consegue representar.
INSTANTE_DO_BUG = datetime(2026, 9, 3, 0, 30, tzinfo=UTC)
DIA_DA_CONTA = date(2026, 9, 2)
DIA_DO_SERVIDOR = date(2026, 9, 3)

CONTA: dict[str, Any] = {
    "customer_id": "1234567890",
    "mcc_id": "6436352492",
    "descriptive_name": "Cliente Fortaleza",
    "currency_code": "BRL",
    "time_zone": "America/Fortaleza",
}


async def _semear_conta(
    conn: asyncpg.Connection, customer_id: str, *, missed_syncs: int = 0, **campos: Any
) -> None:
    """Conta no inventário pelo caminho real (`upsert_many`), carência opcional."""
    await google_ads_accounts.upsert_many(conn, [{**CONTA, "customer_id": customer_id, **campos}])
    if missed_syncs:
        await conn.execute(
            "UPDATE google_ads_accounts SET missed_syncs = $2 WHERE customer_id = $1",
            customer_id,
            missed_syncs,
        )


async def _linha(conn: asyncpg.Connection, customer_id: str) -> asyncpg.Record:
    row = await conn.fetchrow(
        "SELECT missed_syncs, last_missed_on, xmin::text AS versao "
        "FROM google_ads_accounts WHERE customer_id = $1",
        customer_id,
    )
    assert row is not None
    return row


# ---------- nível de repositório: `apply_absences` ----------


@pytest.mark.integration
async def test_duas_execucoes_no_mesmo_dia_contam_uma_ausencia(db) -> None:
    """C4: com `maxRetries: 3` no job, um retry após o commit reexecuta a
    reconciliação. Antes deste fix, a mesma ausência era contada de novo, e a
    carência de 3 dias que protege a conta do cliente caía em 2 execuções."""
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")

        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )

        linha = await _linha(conn, "1234567890")
    assert linha["missed_syncs"] == 1, "retry no mesmo dia contou duas vezes"
    assert linha["last_missed_on"] == DIA_DA_CONTA


@pytest.mark.integration
async def test_dia_novo_conta_de_novo(db) -> None:
    """A carência tem que continuar avançando: dia diferente, ausência nova.

    Contraparte obrigatória do teste acima — sozinho, ele passaria também com
    um incremento que nunca conta nada.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")

        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", date(2026, 9, 6))], reset=[]
        )
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", date(2026, 9, 7))], reset=[]
        )

        linha = await _linha(conn, "1234567890")
    assert linha["missed_syncs"] == 2
    assert linha["last_missed_on"] == date(2026, 9, 7)


@pytest.mark.integration
async def test_primeira_ausencia_conta_com_last_missed_on_nulo(db) -> None:
    """`IS DISTINCT FROM`, não `<>`: `NULL <> $2` avalia para NULL, que não
    satisfaz o WHERE.

    `last_missed_on` é NULL em TODA linha hoje (a 009 subiu sem backfill, de
    propósito), então com `<>` a primeira ausência de cada conta nunca seria
    contada — o contador ficaria congelado em 0 para o inventário inteiro, e a
    reconciliação pararia de proteger o que quer que fosse, em silêncio.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")
        antes = await _linha(conn, "1234567890")
        assert antes["last_missed_on"] is None, "premissa do teste: a coluna nasce NULL"

        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )

        linha = await _linha(conn, "1234567890")
    assert linha["missed_syncs"] == 1, "primeira ausencia da conta nao foi contada"
    assert linha["last_missed_on"] == DIA_DA_CONTA


@pytest.mark.integration
async def test_reset_zera_a_serie_inteira_e_nao_so_o_contador(db) -> None:
    """A série de ausências é (`missed_syncs`, `last_missed_on`) — as duas.

    Zerar só o contador deixaria a data velha na linha, e a ausência seguinte
    da conta seria PULADA se caísse no mesmo dia do reset: a conta voltaria a
    somar carência só no dia seguinte.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )

        await google_ads_accounts.apply_absences(conn, bump=[], reset=["1234567890"])
        depois_do_reset = await _linha(conn, "1234567890")

        # E a conta volta a faltar NO MESMO DIA do reset.
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )
        linha = await _linha(conn, "1234567890")

    assert depois_do_reset["missed_syncs"] == 0
    assert depois_do_reset["last_missed_on"] is None, "o reset deixou a data velha na linha"
    assert linha["missed_syncs"] == 1, "ausencia pulada por data velha que o reset nao limpou"


@pytest.mark.integration
async def test_reset_nao_reescreve_linha_ja_limpa(db) -> None:
    """`AND missed_syncs <> 0` — a cláusula que o lado Meta já tem.

    Simetria entre os dois laços é requisito, não estética: o F128 nasceu de uma
    cláusula que ficou de fora de um dos lados. `to_reset` já só traz conta com
    carência, então a cláusula não muda o valor final — o que ela muda é a linha
    ser reescrita ou não, e é isso que este teste observa (`xmin` é a transação
    que gravou a versão corrente da tupla; um UPDATE que casa o WHERE cria versão
    nova mesmo gravando valores idênticos).
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")
        antes = await _linha(conn, "1234567890")
        assert antes["missed_syncs"] == 0, "premissa: a linha ja esta limpa"

        await google_ads_accounts.apply_absences(conn, bump=[], reset=["1234567890"])

        depois = await _linha(conn, "1234567890")
    assert depois["versao"] == antes["versao"], (
        "reset reescreveu linha que ja estava limpa — a clausula `missed_syncs <> 0` sumiu"
    )


@pytest.mark.integration
async def test_conta_que_volta_e_falta_no_mesmo_dia_tem_a_ausencia_contada(db) -> None:
    """`upsert_many` zera `last_missed_on` junto com `missed_syncs` (F128).

    O `ON CONFLICT` já zerava o contador — 'a conta reapareceu, então a série de
    ausências morre aqui'. `last_missed_on` É parte dessa série: sem zerá-la
    junto, a conta que volta e falta de novo no MESMO dia carregaria a data
    velha e teria a ausência pulada pelo `IS DISTINCT FROM` — carência que não
    avança é conta que nunca sai, o espelho do bug que este PR corrige.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )

        # A conta reaparece no MCC: o job faz `upsert_many`, que mata a série.
        await _semear_conta(conn, "1234567890")
        depois_do_upsert = await _linha(conn, "1234567890")

        # E some de novo no MESMO dia.
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )
        linha = await _linha(conn, "1234567890")

    assert depois_do_upsert["missed_syncs"] == 0
    assert depois_do_upsert["last_missed_on"] is None, (
        "upsert_many deixou a data velha: a serie de ausencias sobreviveu ao reaparecimento"
    )
    assert linha["missed_syncs"] == 1, "ausencia pulada por data que o upsert_many nao limpou"


@pytest.mark.integration
async def test_bump_nao_vaza_para_conta_vizinha(db) -> None:
    """A blast radius do `bump` é só quem está na lista — nunca o inventário inteiro.

    Achado I1 da revisão da Task 2: todo teste acima roda com UMA conta só, e
    nenhum consegue distinguir "soma a carência da conta certa" de "soma a
    carência de todo mundo" — tirar `WHERE customer_id = $1` do UPDATE (e só
    ele) passava verde nos dez. Em produção isso é `missed_syncs + 1` no
    inventário inteiro, todo dia: as 26 contas cruzam o limiar de desativação
    em 3 dias, e `revoke_for_inactive_accounts` revoga todos os grants. É o
    predicado que este PR reescreveu (`ANY($1::text[])` → uma linha por
    `executemany`).
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")
        await _semear_conta(conn, "9876543210")  # vizinha, não citada no bump

        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )

        alvo = await _linha(conn, "1234567890")
        vizinha = await _linha(conn, "9876543210")

    assert alvo["missed_syncs"] == 1
    assert alvo["last_missed_on"] == DIA_DA_CONTA
    assert vizinha["missed_syncs"] == 0, "bump vazou para conta que nao estava na lista"
    assert vizinha["last_missed_on"] is None, "bump carimbou last_missed_on da vizinha"


@pytest.mark.integration
async def test_reset_nao_vaza_para_conta_vizinha(db) -> None:
    """Idem para o `reset`: só quem está na lista perde a carência.

    Mesmo achado I1, segunda metade — sem `WHERE customer_id = ANY($1::text[])`
    o UPDATE zeraria QUALQUER conta com `missed_syncs <> 0`, não só quem
    reapareceu no MCC. A vizinha entra com carência e `last_missed_on`
    diferentes dos da conta-alvo pós-reset, para nenhum dos dois campos
    coincidir por acidente com o valor que o reset grava.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890", missed_syncs=2)
        await _semear_conta(conn, "9876543210", missed_syncs=3)  # vizinha, fora do reset
        await conn.execute(
            "UPDATE google_ads_accounts SET last_missed_on = $2 WHERE customer_id = $1",
            "9876543210",
            DIA_DA_CONTA,
        )

        await google_ads_accounts.apply_absences(conn, bump=[], reset=["1234567890"])

        alvo = await _linha(conn, "1234567890")
        vizinha = await _linha(conn, "9876543210")

    assert alvo["missed_syncs"] == 0
    assert alvo["last_missed_on"] is None
    assert vizinha["missed_syncs"] == 3, "reset vazou para conta que nao estava na lista"
    assert vizinha["last_missed_on"] == DIA_DA_CONTA, "reset vazou last_missed_on da vizinha"


@pytest.mark.integration
async def test_lista_vazia_continua_sendo_noop(db) -> None:
    """F85: lista vazia quase sempre é falha de leitura, não 'todas sumiram'."""
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890", missed_syncs=2)

        await google_ads_accounts.apply_absences(conn, bump=[], reset=[])

        linha = await _linha(conn, "1234567890")
    assert linha["missed_syncs"] == 2
    assert linha["last_missed_on"] is None


@pytest.mark.integration
async def test_list_inventory_rows_traz_o_fuso_da_conta(db) -> None:
    """O fuso vem no inventário porque `apply_absences` precisa dele (F141).

    `resolve_account_today` faria uma leitura POR CONTA e adquiriria uma segunda
    conexão do pool (`run_with_reconnect`) dentro da transação já aberta da
    reconciliação — pool de 5 no serviço. O fuso viajar junto do inventário
    torna o cálculo do dia puro e sem I/O extra.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")
        await _semear_conta(conn, "9876543210", time_zone=None)

        linhas = {r.customer_id: r for r in await google_ads_accounts.list_inventory_rows(conn)}

    assert linhas["1234567890"].time_zone == "America/Fortaleza"
    assert linhas["9876543210"].time_zone is None, "conta sem fuso tem que chegar como None"


# ---------- nível de job: `reconcile_google` ----------


@pytest.mark.integration
async def test_o_dia_da_ausencia_vem_do_fuso_da_conta(db) -> None:
    """F141 nesta trilha: `hoje` é propriedade da CONTA, não do servidor.

    Às 00:30 UTC do dia 3, em `America/Fortaleza` ainda são 21:30 do dia 2. Com
    o relógio do servidor, a ausência das 21h à meia-noite locais seria
    carimbada com o dia SEGUINTE — e a ausência real do dia seguinte cairia no
    `IS DISTINCT FROM` e não seria contada. O bug do F141 vira carência
    silenciosamente mais longa, todo dia, na janela em que ninguém testa.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")

        resumo = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=False, now=INSTANTE_DO_BUG
        )

        linha = await _linha(conn, "1234567890")
    assert resumo["bumped"] == 1
    assert linha["missed_syncs"] == 1
    assert linha["last_missed_on"] == DIA_DA_CONTA, (
        f"a ausencia foi carimbada com o dia do servidor ({DIA_DO_SERVIDOR}), "
        f"nao com o dia da conta ({DIA_DA_CONTA})"
    )


@pytest.mark.integration
async def test_retry_do_job_no_mesmo_dia_nao_consome_a_carencia(db) -> None:
    """O C4 pelo caminho que a PRODUÇÃO percorre, ponta a ponta.

    `maxRetries: 3`: o job pode reexecutar a reconciliação inteira depois do
    commit. Duas execuções no mesmo dia têm de valer UMA ausência; o dia
    seguinte volta a contar, senão a carência nunca avança e conta que saiu do
    MCC fica viva para sempre.
    """
    dia_seguinte = INSTANTE_DO_BUG.replace(day=4)
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")

        await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True, now=INSTANTE_DO_BUG
        )
        await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True, now=INSTANTE_DO_BUG
        )
        depois_do_retry = await _linha(conn, "1234567890")

        await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True, now=dia_seguinte
        )
        linha = await _linha(conn, "1234567890")

    assert depois_do_retry["missed_syncs"] == 1, (
        "retry do job contou a mesma ausencia de novo — a carencia de 3 dias cai em 2 execucoes"
    )
    assert linha["missed_syncs"] == 2, "dia novo tem que voltar a contar"
    assert linha["last_missed_on"] == date(2026, 9, 3)
