"""Descomissionamento auditado: tirar do inventário as contas fora do escopo e revogar os grants.

Medido em 25/11: com o login-customer-id da MDO, o resync enxerga 1 de 24 contas Google ativas;
passada a carência, o teto de segurança (20% ou 5) bloquearia a remoção de 23 e o job sairia com
1 todo dia. Subir o teto seria gambiarra — a saída é retirar de propósito, com trilha. Os grants
saem com os motivos de CHURN (`left_mcc`/`partnership_ended`): conta que reaparecer volta pela
restauração que já existe.
"""

from __future__ import annotations

import json

import asyncpg
import pytest

from src.db.repositories import (
    google_ads_accounts,
    manager_account_access,
    manager_meta_account_access,
    meta_ad_accounts,
)
from src.db.repositories.motivos import LEFT_MCC_REASON, PARTNERSHIP_ENDED_REASON
from src.scripts import desligamento
from tests.integration._seed import seed_manager

MDO_G, OUTRA_G, OUTRA_G2 = "7000000001", "7000000002", "7000000003"
MDO_M, OUTRA_M = "act_9000000001", "act_9000000002"


async def _cenario(conn: asyncpg.Connection) -> object:
    await google_ads_accounts.upsert_many(
        conn,
        [
            {"customer_id": c, "mcc_id": "0000000000", "descriptive_name": c}
            for c in (MDO_G, OUTRA_G, OUTRA_G2)
        ],
    )
    await meta_ad_accounts.upsert_many(
        conn,
        [
            {"ad_account_id": a, "business_id": "bm_test", "account_name": a}
            for a in (MDO_M, OUTRA_M)
        ],
    )
    gestor = await seed_manager(conn)
    for c in (MDO_G, OUTRA_G, OUTRA_G2):
        await manager_account_access.grant(
            conn, manager_id=gestor, customer_id=c, access_level="write", granted_by=gestor
        )
    for a in (MDO_M, OUTRA_M):
        await manager_meta_account_access.grant(
            conn, manager_id=gestor, ad_account_id=a, access_level="write", granted_by=gestor
        )
    return gestor


async def _estado(conn: asyncpg.Connection) -> dict[str, object]:
    g = await conn.fetch("SELECT customer_id, is_active FROM google_ads_accounts ORDER BY 1")
    m = await conn.fetch("SELECT ad_account_id, is_active FROM meta_ad_accounts ORDER BY 1")
    gg = await conn.fetch(
        "SELECT customer_id, revoked_at IS NULL AS vivo, revoked_reason "
        "FROM manager_account_access ORDER BY 1"
    )
    mg = await conn.fetch(
        "SELECT ad_account_id, revoked_at IS NULL AS vivo, revoked_reason "
        "FROM manager_meta_account_access ORDER BY 1"
    )
    return {
        "google": {r[0]: r[1] for r in g},
        "meta": {r[0]: r[1] for r in m},
        "grants_google": {r[0]: (r[1], r[2]) for r in gg},
        "grants_meta": {r[0]: (r[1], r[2]) for r in mg},
    }


async def _audits(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT had_effect, params_summary FROM audit_log "
        "WHERE operation = 'cli_decommission' ORDER BY id"
    )


@pytest.mark.integration
async def test_recusa_id_de_manter_que_nao_e_conta_ativa(db) -> None:
    async with db.acquire() as conn:
        await _cenario(conn)
        antes = await _estado(conn)
        r = await desligamento.descomissionar(
            conn, manter_google=["7999999999"], manter_meta=[MDO_M], apply=True
        )
        assert r.invalidos == ["7999999999"]
        assert await _estado(conn) == antes
        assert await _audits(conn) == []


@pytest.mark.integration
async def test_recusa_lista_de_manter_vazia(db) -> None:
    async with db.acquire() as conn:
        await _cenario(conn)
        antes = await _estado(conn)
        r = await desligamento.descomissionar(conn, manter_google=[], manter_meta=[], apply=True)
        assert r.invalidos == ["(google vazio)", "(meta vazio)"]
        assert await _estado(conn) == antes


@pytest.mark.integration
async def test_dry_run_lista_e_nao_escreve(db) -> None:
    async with db.acquire() as conn:
        await _cenario(conn)
        antes = await _estado(conn)
        r = await desligamento.descomissionar(
            conn, manter_google=[MDO_G], manter_meta=[MDO_M], apply=False
        )
        assert r.invalidos == []
        assert r.google == [OUTRA_G, OUTRA_G2]
        assert r.meta == [OUTRA_M]
        assert (r.grants_google, r.grants_meta) == (2, 1)
        assert await _estado(conn) == antes
        assert await _audits(conn) == []


@pytest.mark.integration
async def test_apply_desativa_so_as_de_fora_revoga_com_motivo_de_churn_e_audita(db) -> None:
    async with db.acquire() as conn:
        await _cenario(conn)
        await desligamento.descomissionar(
            conn, manter_google=[MDO_G], manter_meta=[MDO_M], apply=True
        )
        e = await _estado(conn)
        audits = await _audits(conn)
    assert e["google"] == {MDO_G: True, OUTRA_G: False, OUTRA_G2: False}
    assert e["meta"] == {MDO_M: True, OUTRA_M: False}
    assert e["grants_google"] == {
        MDO_G: (True, None),
        OUTRA_G: (False, LEFT_MCC_REASON),
        OUTRA_G2: (False, LEFT_MCC_REASON),
    }
    assert e["grants_meta"] == {MDO_M: (True, None), OUTRA_M: (False, PARTNERSHIP_ENDED_REASON)}
    (audit,) = audits
    assert audit["had_effect"] is True
    resumo = json.loads(audit["params_summary"])
    assert resumo["contas_google"] == [OUTRA_G, OUTRA_G2]
    assert resumo["contas_meta"] == [OUTRA_M]
    assert (resumo["grants_google"], resumo["grants_meta"]) == (2, 1)


@pytest.mark.integration
async def test_segunda_rodada_nao_muda_nada(db) -> None:
    async with db.acquire() as conn:
        await _cenario(conn)
        kw = {"manter_google": [MDO_G], "manter_meta": [MDO_M], "apply": True}
        await desligamento.descomissionar(conn, **kw)  # type: ignore[arg-type]
        depois = await _estado(conn)
        await desligamento.descomissionar(conn, **kw)  # type: ignore[arg-type]
        assert await _estado(conn) == depois
        audits = await _audits(conn)
    assert [a["had_effect"] for a in audits] == [True, False]
