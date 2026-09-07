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

# I1 (revisão final da branch): DOIS fusos que caem em DIAS DIFERENTES no MESMO
# instante. Às 03:30 UTC do dia 3, em `America/Fortaleza` (UTC-3) já é 00:30 do
# dia 3, e em `America/Manaus` (UTC-4) ainda são 23:30 do dia 2. A escolha do
# instante é o teste: com dois fusos que caíssem no mesmo dia, "cada conta no seu
# fuso" e "um fuso para o lote inteiro" produziriam o mesmo resultado, e a
# mutação passaria verde. Os dois fusos são reais no MCC — as 26 contas estão em
# seis fusos, todos UTC-3 ou UTC-4 (F141).
INSTANTE_ENTRE_FUSOS = datetime(2026, 9, 3, 3, 30, tzinfo=UTC)
DIA_EM_FORTALEZA = date(2026, 9, 3)  # UTC-3: 00:30 do dia 3
DIA_EM_MANAUS = date(2026, 9, 2)  # UTC-4: 23:30 do dia 2

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
async def test_reset_e_redundante_apos_upsert_many_no_mesmo_run(db) -> None:
    """Task 4/Step 5: prova que `reset=plano.to_reset` era sempre no-op no
    call site de `reconcile_google` — não só por argumento (`to_reset` é
    subconjunto de `mcc_ids` por construção), mas no SQL de verdade.

    `reconcile_google` chama `upsert_many` (zera `missed_syncs`/
    `last_missed_on` pra TODA conta em `accounts`) e só DEPOIS
    `apply_absences(reset=...)`, na MESMA transação, sem I/O entre os dois.
    Uma conta com carência antiga que REAPARECE nesta execução (está de novo
    em `accounts`, e por isso em `to_reset` se `missed_syncs` era > 0) já sai
    do `upsert_many` limpa — pelo momento em que o reset explícito rodaria, a
    cláusula `AND missed_syncs <> 0` (mesmo mecanismo de
    `test_reset_nao_reescreve_linha_ja_limpa`, agora na sequência REAL do
    job) barra o UPDATE antes de reescrever a linha.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890", missed_syncs=2)

        # A conta reaparece no MCC nesta execução — `reconcile_google` faz
        # isto SEMPRE, antes de qualquer reset.
        await google_ads_accounts.upsert_many(conn, [CONTA])
        depois_do_upsert = await _linha(conn, "1234567890")
        assert depois_do_upsert["missed_syncs"] == 0, (
            "premissa do teste: upsert_many sozinho já zera a série de ausências"
        )

        # O reset que o call site de `reconcile_google` deixou de passar
        # (Step 5) — isolado aqui pra provar que rodá-lo não mudaria nada.
        await google_ads_accounts.apply_absences(conn, bump=[], reset=["1234567890"])
        depois_do_reset = await _linha(conn, "1234567890")

    assert depois_do_reset["versao"] == depois_do_upsert["versao"], (
        "reset reescreveu a linha depois do upsert_many — a equivalência que "
        "justifica reset=[] no call site de reconcile_google não se sustenta"
    )
    assert depois_do_reset["missed_syncs"] == 0
    assert depois_do_reset["last_missed_on"] is None


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


@pytest.mark.integration
async def test_list_inventory_rows_traz_a_data_da_ultima_ausencia(db) -> None:
    """`last_missed_on` viaja no inventário porque `build_plan` DECIDE com ela.

    Diferente do fuso, que o plano ignora: esta coluna é o que distingue "a
    ausência de hoje já está no contador" (retry) de "ainda não está". Sem ela
    na linha o planejador soma `+1` sempre, e o retry do mesmo dia queima um
    dia de carência — o contador fica certo e a DECISÃO sai um dia adiantada,
    que é o modo de falha invisível que este PR fecha.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890")
        await _semear_conta(conn, "9876543210")  # sem ausência nenhuma
        await google_ads_accounts.apply_absences(
            conn, bump=[("1234567890", DIA_DA_CONTA)], reset=[]
        )

        linhas = {r.customer_id: r for r in await google_ads_accounts.list_inventory_rows(conn)}

    assert linhas["1234567890"].last_missed_on == DIA_DA_CONTA, (
        "a data da ultima ausencia nao chegou ao planejador"
    )
    assert linhas["9876543210"].last_missed_on is None, (
        "conta sem serie de ausencias tem que chegar como None"
    )


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


@pytest.mark.integration
async def test_retry_na_vespera_do_limiar_nao_remove_a_conta(db) -> None:
    """A DECISÃO também tem de ser idempotente por dia — não só o contador.

    Os dois testes de retry acima param em 2 ausências, longe do limiar 3:
    provam que `apply_absences` não conta duas vezes, e nenhum toca a única
    execução em que o retry importa, que é a que REMOVE. `build_plan` somava
    `missed_syncs + 1` por EXECUÇÃO — a suposição que o C4 quebrou —, então o
    retry da véspera lia o contador JÁ bumpado por esta mesma execução e
    decidia remover com dois dias de ausência em vez de três: conta desativada
    e grants dos gestores revogados um dia cedo. E `missed_syncs` ficava parado
    em 2, o que torna o sintoma invisível para quem auditar só o contador.

    Cobre também o F141 na decisão: com `INSTANTE_DO_BUG` o dia da conta
    (02/09 em `America/Fortaleza`) difere do dia UTC (03/09), então comparar
    `last_missed_on` com o dia do SERVIDOR não casaria e o `+1` voltaria.

    A contraprova está no fim: no dia SEGUINTE a conta tem de sair. Sem ela,
    um planejador que nunca remove passaria verde.
    """
    dia_seguinte = INSTANTE_DO_BUG.replace(day=4)
    async with db.acquire() as conn:
        # Uma ausência anterior: o run de hoje leva a duas, e o limiar é três.
        await _semear_conta(conn, "1234567890", missed_syncs=1)

        await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True, now=INSTANTE_DO_BUG
        )
        resumo_retry = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True, now=INSTANTE_DO_BUG
        )
        depois_do_retry = await _linha(conn, "1234567890")
        ativa_no_retry = await conn.fetchval(
            "SELECT is_active FROM google_ads_accounts WHERE customer_id = $1", "1234567890"
        )

        resumo_amanha = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=True, now=dia_seguinte
        )
        ativa_amanha = await conn.fetchval(
            "SELECT is_active FROM google_ads_accounts WHERE customer_id = $1", "1234567890"
        )

    assert resumo_retry["removed"] == 0, (
        "retry no mesmo dia removeu a conta com DOIS dias de ausencia — a decisao "
        "somou +1 sobre um contador que ESTA execucao ja tinha bumpado"
    )
    assert ativa_no_retry is True, "conta desativada (e grants revogados) um dia antes da hora"
    assert depois_do_retry["missed_syncs"] == 2, "o contador tem de seguir idempotente por dia"
    assert resumo_amanha["removed"] == 1, "a remocao no dia certo parou de acontecer"
    assert ativa_amanha is False, "no terceiro dia a conta tem de sair de verdade"


@pytest.mark.integration
async def test_conta_com_carencia_que_reaparece_sai_zerada_com_reset_vazio(db) -> None:
    """Task 4/Step 5, ponta a ponta: `reconcile_google` passou a chamar
    `apply_absences(..., reset=[])` — este teste prova que a conta que
    reaparece com carência antiga ainda sai zerada (via `upsert_many`
    sozinho) e que `resumo["reset"]` continua reportando a contagem certa,
    mesmo sem mais ALIMENTAR o UPDATE de reset.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890", missed_syncs=2)

        resumo = await account_resync.reconcile_google(
            conn, accounts=[CONTA], complete=True, apply=True, now=INSTANTE_DO_BUG
        )

        linha = await _linha(conn, "1234567890")

    assert resumo["reset"] == 1, "to_reset continua contando a conta pro audit"
    assert linha["missed_syncs"] == 0, "conta reaparecida tem que sair com a serie zerada"
    assert linha["last_missed_on"] is None


@pytest.mark.integration
async def test_lote_com_duas_contas_carimba_cada_uma_no_seu_fuso(db) -> None:
    """I1 (revisão final): o caminho MULTI-CONTA do `bump`, que nenhum teste tocava.

    As 24 chamadas de `apply_absences` da suíte passavam `bump` com **um** par
    `(id, data)`. Duas mutações atravessavam isso verdes, e as duas erram para o
    lado que não revoga — que é o lado invisível:

    - `bump[:1]` no `executemany`: duas contas saem do MCC no mesmo dia e só a
      primeira acumula carência. A segunda fica congelada em 0 para sempre e
      NUNCA é desativada — o offboarding morre em silêncio, com o contador
      parecendo saudável.
    - `account_today` içado para fora da comprehension (um fuso para o lote
      inteiro): o fuso de uma conta carimba a data de todas. É o F141 de volta,
      dentro do laço que revoga acesso, e só na janela noturna.

    O instante é escolhido para que os dois fusos estejam em DIAS DIFERENTES
    (ver `INSTANTE_ENTRE_FUSOS`): é isso que dá ao teste poder de distinguir as
    duas hipóteses. Com dois fusos no mesmo dia, o hoist passaria.

    A terceira asserção — o retry no mesmo instante — prende a idempotência por
    dia nas DUAS linhas ao mesmo tempo: um `WHERE` que perdesse o predicado de
    data levaria as duas a 2.
    """
    async with db.acquire() as conn:
        await _semear_conta(conn, "1234567890", time_zone="America/Fortaleza")
        await _semear_conta(conn, "9876543210", time_zone="America/Manaus")

        resumo = await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=False, now=INSTANTE_ENTRE_FUSOS
        )
        fortaleza = await _linha(conn, "1234567890")
        manaus = await _linha(conn, "9876543210")

        # Retry do mesmo run (maxRetries: 3), MESMO instante: nenhuma das duas
        # pode contar de novo.
        await account_resync.reconcile_google(
            conn, accounts=[], complete=True, apply=False, now=INSTANTE_ENTRE_FUSOS
        )
        fortaleza_retry = await _linha(conn, "1234567890")
        manaus_retry = await _linha(conn, "9876543210")

    assert resumo["bumped"] == 2, "o plano tem que marcar as DUAS contas ausentes"
    assert fortaleza["missed_syncs"] == 1
    assert manaus["missed_syncs"] == 1, (
        "a segunda conta do lote nao acumulou carencia — o `executemany` aplicou "
        "so o primeiro par, e essa conta nunca seria desativada"
    )
    assert fortaleza["last_missed_on"] == DIA_EM_FORTALEZA, (
        f"conta em America/Fortaleza (UTC-3) devia ser carimbada com {DIA_EM_FORTALEZA}, "
        f"veio {fortaleza['last_missed_on']} — um fuso so para o lote inteiro"
    )
    assert manaus["last_missed_on"] == DIA_EM_MANAUS, (
        f"conta em America/Manaus (UTC-4) devia ser carimbada com {DIA_EM_MANAUS}, "
        f"veio {manaus['last_missed_on']} — um fuso so para o lote inteiro"
    )
    assert fortaleza["last_missed_on"] != manaus["last_missed_on"], (
        "as duas contas cairam no MESMO dia: o instante deixou de discriminar os "
        "fusos e o teste perdeu o poder de matar a mutacao do hoist"
    )
    assert (fortaleza_retry["missed_syncs"], manaus_retry["missed_syncs"]) == (1, 1), (
        "o retry no mesmo dia contou de novo em alguma das duas linhas"
    )
