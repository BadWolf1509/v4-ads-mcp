"""Desligamento revoga a credencial (JML): conexões OAuth de gestor desativado.

Medido em 25/11: depois de desativar os 4 gestores `@v4company` pelo painel, 5 conexões OAuth
seguiam vivas (refresh tokens guardados) — o toggle revogava os grants, não as conexões, e a
rota de revogar conexão só aceita o dono. Reativar NÃO devolve a conexão: o gestor reconecta.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import asyncpg
import pytest

from src.db.repositories import google_oauth_connections, managers
from src.scripts import desligamento
from src.web.deps import CurrentUser
from src.web.routes import admin_overview
from tests.integration._seed import seed_manager


async def _conexao(conn: asyncpg.Connection, manager_id: UUID, email: str | None = None) -> UUID:
    oc = await google_oauth_connections.upsert(
        conn,
        manager_id=manager_id,
        google_email=email or f"g-{uuid4().hex[:6]}@exemplo.com",
        refresh_token_enc=b"cifrado",
        scopes=["https://www.googleapis.com/auth/adwords"],
    )
    return oc.id


async def _vivas(conn: asyncpg.Connection, manager_id: UUID) -> int:
    return int(
        await conn.fetchval(
            "SELECT count(*) FROM google_oauth_connections "
            "WHERE manager_id = $1 AND revoked_at IS NULL",
            manager_id,
        )
    )


async def _inativo(conn: asyncpg.Connection) -> UUID:
    gestor = await seed_manager(conn)
    await managers.definir_ativo(conn, manager_id=gestor, ativo=False)
    return gestor


@pytest.mark.integration
async def test_revoke_all_for_manager_so_atinge_aquele_gestor(db) -> None:
    async with db.acquire() as conn:
        alvo, outro = await seed_manager(conn), await seed_manager(conn)
        await _conexao(conn, alvo)
        await _conexao(conn, alvo)
        await _conexao(conn, outro)
        assert await google_oauth_connections.revoke_all_for_manager(conn, alvo) == 2
        assert await _vivas(conn, alvo) == 0
        assert await _vivas(conn, outro) == 1
        assert await google_oauth_connections.revoke_all_for_manager(conn, alvo) == 0


@pytest.mark.integration
async def test_listar_vivas_de_inativos_ignora_ativo_e_ja_revogada(db) -> None:
    async with db.acquire() as conn:
        inativo = await _inativo(conn)
        viva = await _conexao(conn, inativo)
        revogada = await _conexao(conn, inativo)
        await google_oauth_connections.revoke(conn, revogada)
        ativo = await seed_manager(conn)
        await _conexao(conn, ativo)
        linhas = await google_oauth_connections.list_live_of_inactive_managers(conn)
    assert [r["id"] for r in linhas] == [viva]


async def _audits(conn: asyncpg.Connection, operacao: str) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT had_effect, target_count, params_summary FROM audit_log "
        "WHERE operation = $1 ORDER BY id",
        operacao,
    )


@pytest.mark.integration
async def test_backfill_dry_run_nao_escreve_apply_revoga_e_segunda_rodada_sem_efeito(db) -> None:
    async with db.acquire() as conn:
        inativo = await _inativo(conn)
        await _conexao(conn, inativo)
        ativo = await seed_manager(conn)
        await _conexao(conn, ativo)

        plano = await desligamento.revogar_conexoes_de_inativos(conn, apply=False)
        assert len(plano) == 1
        assert await _vivas(conn, inativo) == 1
        assert await _audits(conn, "cli_revoke_inactive_connections") == []

        feito = await desligamento.revogar_conexoes_de_inativos(conn, apply=True)
        assert len(feito) == 1
        assert await _vivas(conn, inativo) == 0
        assert await _vivas(conn, ativo) == 1

        await desligamento.revogar_conexoes_de_inativos(conn, apply=True)
        audits = await _audits(conn, "cli_revoke_inactive_connections")
    assert [a["had_effect"] for a in audits] == [True, False]
    assert audits[0]["target_count"] == 1


class _FakeRequestHtmx:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {"HX-Request": "true"}


async def _toggle(admin: CurrentUser, gestor: UUID, desejado: str) -> None:
    await admin_overview.admin_managers_toggle_active(
        _FakeRequestHtmx(),  # type: ignore[arg-type]
        manager_id=gestor,
        desejado=desejado,  # type: ignore[arg-type]
        user=admin,
    )


@pytest.mark.integration
async def test_desativar_pela_rota_revoga_conexoes_e_reativar_nao_devolve(db) -> None:
    async with db.acquire() as conn:
        admin_id = await seed_manager(conn, role="admin")
        admin = CurrentUser(await managers.get_by_id(conn, admin_id))  # type: ignore[arg-type]
        gestor = await seed_manager(conn)
        await _conexao(conn, gestor)
        await _conexao(conn, gestor)

    await _toggle(admin, gestor, "inativo")
    async with db.acquire() as conn:
        assert await _vivas(conn, gestor) == 0
        (audit,) = await _audits(conn, "admin_manager_toggle_active")
    assert json.loads(audit["params_summary"])["conexoes_revogadas"] == 2

    await _toggle(admin, gestor, "ativo")
    async with db.acquire() as conn:
        assert await _vivas(conn, gestor) == 0
