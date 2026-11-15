"""Revogação de acesso na desativação do gestor (desenho de 15/11), núcleo SQL.

Desativar um gestor só trocava `managers.is_active`: ele ficava barrado na
entrada, mas os grants Google e Meta continuavam vivos, e reativar devolvia
tudo no mesmo clique. As funções de `_acesso_comum` operam sobre o ESTADO
(gestor desativado x grant vivo), nunca sobre o delta, e valem para os dois
lados: cada teste roda com `lado` em Google e Meta, pelos wrappers de cada
módulo (que é o que a rota e o job chamam).

Regra dos motivos: o motivo nomeia o que bloqueia agora; com dois bloqueios,
vale o da conta (por isso a restauração em conta inativa remarca como churn).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from types import ModuleType
from uuid import UUID

import asyncpg
import pytest

from src.db.repositories import (
    _acesso_comum,
    google_ads_accounts,
    manager_account_access,
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
)
from src.db.repositories.motivos import (
    ADMIN_REVOKED_REASON,
    BULK_COPY_REPLACED_REASON,
    LEFT_MCC_REASON,
    MANAGER_DEACTIVATED_REASON,
    PARTNERSHIP_ENDED_REASON,
)
from tests.integration._seed import seed_manager


async def _conta_google(conn: asyncpg.Connection, conta: str) -> None:
    await google_ads_accounts.upsert_many(
        conn, [{"customer_id": conta, "mcc_id": "0000000000", "descriptive_name": "Test"}]
    )


async def _conta_meta(conn: asyncpg.Connection, conta: str) -> None:
    await meta_ad_accounts.upsert_many(
        conn, [{"ad_account_id": conta, "business_id": "bm_test", "account_name": "Test"}]
    )


@dataclass(frozen=True)
class _Lado:
    nome: str
    modulo: ModuleType
    descritor: _acesso_comum.TabelaDeAcesso
    motivo_churn: str
    kwarg_conta: str
    criar_conta: Callable[[asyncpg.Connection, str], Awaitable[None]]
    prefixo: str

    def conta(self, n: int) -> str:
        return f"{self.prefixo}{n:010d}"

    @property
    def tabela(self) -> str:
        return self.descritor.tabela

    @property
    def coluna(self) -> str:
        return self.descritor.coluna_conta

    @property
    def inventario(self) -> str:
        return self.descritor.inventario


_LADOS = {
    "google": _Lado(
        nome="google",
        modulo=manager_account_access,
        descritor=_acesso_comum.GOOGLE,
        motivo_churn=LEFT_MCC_REASON,
        kwarg_conta="customer_id",
        criar_conta=_conta_google,
        prefixo="",
    ),
    "meta": _Lado(
        nome="meta",
        modulo=manager_meta_account_access,
        descritor=_acesso_comum.META,
        motivo_churn=PARTNERSHIP_ENDED_REASON,
        kwarg_conta="ad_account_id",
        criar_conta=_conta_meta,
        prefixo="act_",
    ),
}


@pytest.fixture(params=["google", "meta"])
def lado(request: pytest.FixtureRequest) -> _Lado:
    return _LADOS[request.param]


async def _gestor(
    conn: asyncpg.Connection, *, is_active: bool = True, status: str = "active"
) -> UUID:
    manager_id = await seed_manager(conn)
    await conn.execute(
        "UPDATE managers SET is_active = $2, status = $3 WHERE id = $1",
        manager_id,
        is_active,
        status,
    )
    return manager_id


async def _grant(
    conn: asyncpg.Connection,
    lado: _Lado,
    manager_id: UUID,
    conta: str,
    *,
    motivo: str | None = None,
    conta_ativa: bool = True,
) -> None:
    """Conta (ativa ou não) + grant vivo; com `motivo`, a linha fica revogada."""
    await lado.criar_conta(conn, conta)
    await lado.modulo.grant(
        conn, manager_id=manager_id, granted_by=manager_id, **{lado.kwarg_conta: conta}
    )
    if motivo is not None:
        await conn.execute(
            f"UPDATE {lado.tabela} SET revoked_at = now() - interval '1 day', "
            f"revoked_reason = $3 WHERE manager_id = $1 AND {lado.coluna} = $2",
            manager_id,
            conta,
            motivo,
        )
    if not conta_ativa:
        await conn.execute(
            f"UPDATE {lado.inventario} SET is_active = false WHERE {lado.coluna} = $1", conta
        )


async def _linha(
    conn: asyncpg.Connection, lado: _Lado, manager_id: UUID, conta: str
) -> tuple[datetime | None, str | None]:
    row = await conn.fetchrow(
        f"SELECT revoked_at, revoked_reason FROM {lado.tabela} "
        f"WHERE manager_id = $1 AND {lado.coluna} = $2",
        manager_id,
        conta,
    )
    assert row is not None
    return row["revoked_at"], row["revoked_reason"]


async def _foto(conn: asyncpg.Connection, lado: _Lado) -> list[asyncpg.Record]:
    return await conn.fetch(
        f"SELECT manager_id, {lado.coluna}, access_level, granted_at, granted_by, "
        f"revoked_at, revoked_reason FROM {lado.tabela} ORDER BY manager_id, {lado.coluna}"
    )


@pytest.mark.integration
async def test_revoga_grants_vivos_de_desativado_com_motivo(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=False)
        c1, c2, c3 = lado.conta(1), lado.conta(2), lado.conta(3)
        await _grant(conn, lado, gestor, c1)
        await _grant(conn, lado, gestor, c2)
        await _grant(conn, lado, gestor, c3, motivo=ADMIN_REVOKED_REASON)
        antes_c3 = await _linha(conn, lado, gestor, c3)

        revogados = await lado.modulo.revogar_de_desativados(conn)

        assert sorted(revogados) == [(gestor, c1), (gestor, c2)]
        for conta in (c1, c2):
            revoked_at, motivo = await _linha(conn, lado, gestor, conta)
            assert revoked_at is not None
            assert motivo == MANAGER_DEACTIVATED_REASON
        assert await _linha(conn, lado, gestor, c3) == antes_c3


@pytest.mark.integration
async def test_status_inactive_tambem_e_desativado(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=True, status="inactive")
        await _grant(conn, lado, gestor, lado.conta(1))

        revogados = await lado.modulo.revogar_de_desativados(conn)

        assert revogados == [(gestor, lado.conta(1))]
        assert (await _linha(conn, lado, gestor, lado.conta(1)))[1] == (MANAGER_DEACTIVATED_REASON)


@pytest.mark.integration
async def test_invited_nao_e_desativado(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=True, status="invited")
        await _grant(conn, lado, gestor, lado.conta(1))

        assert await lado.modulo.revogar_de_desativados(conn) == []
        assert await _linha(conn, lado, gestor, lado.conta(1)) == (None, None)


@pytest.mark.integration
async def test_com_manager_id_so_atinge_aquele_gestor(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        a = await _gestor(conn, is_active=False)
        b = await _gestor(conn, is_active=False)
        await _grant(conn, lado, a, lado.conta(1))
        await _grant(conn, lado, b, lado.conta(1))

        revogados = await lado.modulo.revogar_de_desativados(conn, manager_id=a)

        assert revogados == [(a, lado.conta(1))]
        assert await _linha(conn, lado, b, lado.conta(1)) == (None, None)


@pytest.mark.integration
async def test_restaura_so_manager_deactivated_em_conta_ativa(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn)
        c1, c2, c3 = lado.conta(1), lado.conta(2), lado.conta(3)
        await _grant(conn, lado, gestor, c1, motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(conn, lado, gestor, c2, motivo=ADMIN_REVOKED_REASON)
        await _grant(conn, lado, gestor, c3, motivo=BULK_COPY_REPLACED_REASON)
        antes_c2 = await _linha(conn, lado, gestor, c2)
        antes_c3 = await _linha(conn, lado, gestor, c3)

        restaurados, remarcados = await lado.modulo.restaurar_de_reativados(conn)

        assert restaurados == [(gestor, c1)]
        assert remarcados == []
        assert await _linha(conn, lado, gestor, c1) == (None, None)
        assert await _linha(conn, lado, gestor, c2) == antes_c2
        assert await _linha(conn, lado, gestor, c3) == antes_c3


@pytest.mark.integration
async def test_restaurar_em_conta_inativa_remarca_como_churn(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(
            conn, lado, gestor, conta, motivo=MANAGER_DEACTIVATED_REASON, conta_ativa=False
        )
        revoked_at_antes, _ = await _linha(conn, lado, gestor, conta)

        restaurados, remarcados = await lado.modulo.restaurar_de_reativados(conn)

        assert restaurados == []
        assert remarcados == [(gestor, conta)]
        assert await _linha(conn, lado, gestor, conta) == (revoked_at_antes, lado.motivo_churn)


@pytest.mark.integration
async def test_restaurar_ignora_gestor_ainda_desativado(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=False)
        ativa, inativa = lado.conta(1), lado.conta(2)
        await _grant(conn, lado, gestor, ativa, motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(
            conn, lado, gestor, inativa, motivo=MANAGER_DEACTIVATED_REASON, conta_ativa=False
        )
        antes = await _foto(conn, lado)

        assert await lado.modulo.restaurar_de_reativados(conn) == ([], [])
        assert await _foto(conn, lado) == antes


@pytest.mark.integration
async def test_restaurar_com_manager_id_so_atinge_aquele_gestor(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        a, b = await _gestor(conn), await _gestor(conn)
        await _grant(conn, lado, a, lado.conta(1), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(conn, lado, b, lado.conta(1), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(
            conn, lado, b, lado.conta(2), motivo=MANAGER_DEACTIVATED_REASON, conta_ativa=False
        )

        assert await lado.modulo.restaurar_de_reativados(conn, manager_id=a) == (
            [(a, lado.conta(1))],
            [],
        )
        assert (await _linha(conn, lado, b, lado.conta(1)))[1] == MANAGER_DEACTIVATED_REASON
        assert (await _linha(conn, lado, b, lado.conta(2)))[1] == MANAGER_DEACTIVATED_REASON


@pytest.mark.integration
async def test_duas_rodadas_a_segunda_nao_muda_nada(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=False)
        await _grant(conn, lado, gestor, lado.conta(1))
        await _grant(conn, lado, gestor, lado.conta(2), conta_ativa=False)

        assert len(await lado.modulo.revogar_de_desativados(conn)) == 2
        foto = await _foto(conn, lado)
        assert await lado.modulo.revogar_de_desativados(conn) == []
        assert await _foto(conn, lado) == foto

        await conn.execute("UPDATE managers SET is_active = true WHERE id = $1", gestor)
        restaurados, remarcados = await lado.modulo.restaurar_de_reativados(conn)
        assert (restaurados, remarcados) == ([(gestor, lado.conta(1))], [(gestor, lado.conta(2))])
        foto = await _foto(conn, lado)
        assert await lado.modulo.restaurar_de_reativados(conn) == ([], [])
        assert await _foto(conn, lado) == foto


@pytest.mark.integration
async def test_planejar_convergencia_conta_sem_escrever(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        desativado = await _gestor(conn, is_active=False)
        reativado = await _gestor(conn)
        invited = await _gestor(conn, status="invited")
        # a revogar: 2 vivos do desativado (um em conta inativa também conta).
        await _grant(conn, lado, desativado, lado.conta(1))
        await _grant(conn, lado, desativado, lado.conta(2), conta_ativa=False)
        # fora da conta: já revogado por admin, e linha `manager_deactivated` de quem
        # continua desativado.
        await _grant(conn, lado, desativado, lado.conta(3), motivo=ADMIN_REVOKED_REASON)
        await _grant(conn, lado, desativado, lado.conta(4), motivo=MANAGER_DEACTIVATED_REASON)
        # a restaurar: 2 em conta ativa; a remarcar: 1 em conta inativa.
        await _grant(conn, lado, reativado, lado.conta(1), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(conn, lado, reativado, lado.conta(3), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(
            conn,
            lado,
            reativado,
            lado.conta(2),
            motivo=MANAGER_DEACTIVATED_REASON,
            conta_ativa=False,
        )
        await _grant(conn, lado, reativado, lado.conta(4), motivo=ADMIN_REVOKED_REASON)
        # invited vivo: nem revoga nem restaura.
        await _grant(conn, lado, invited, lado.conta(1))
        antes = await _foto(conn, lado)

        plano = await _acesso_comum.planejar_convergencia(
            conn, lado.descritor, motivo_churn=lado.motivo_churn
        )

        assert await _foto(conn, lado) == antes, "planejar_convergencia escreveu"
        assert plano == {"a_revogar": 2, "a_restaurar": 2, "a_remarcar": 1}

        revogados = await lado.modulo.revogar_de_desativados(conn)
        restaurados, remarcados = await lado.modulo.restaurar_de_reativados(conn)
        assert plano == {
            "a_revogar": len(revogados),
            "a_restaurar": len(restaurados),
            "a_remarcar": len(remarcados),
        }


@pytest.mark.integration
@pytest.mark.parametrize("status", ["invited", "active", "inactive"])
@pytest.mark.parametrize("is_active", [True, False])
async def test_predicado_sql_igual_ao_python(db, status: str, is_active: bool) -> None:
    """`PREDICADO_DESATIVADO` avaliado no Postgres, sobre a linha real de
    `managers`, bate com `Manager.is_deactivated` nos 6 pares."""
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=is_active, status=status)
        no_sql = await conn.fetchval(
            f"SELECT {_acesso_comum.PREDICADO_DESATIVADO} FROM managers m WHERE m.id = $1",
            gestor,
        )
        manager = await managers.get_by_id(conn, gestor)
        assert manager is not None
        # Concordância sozinha não prova nada (dois lados errados concordam): a
        # tabela esperada fica escrita, com `invited` fora de "desativado".
        esperado = (not is_active) or status == "inactive"
        assert manager.is_deactivated is esperado, (status, is_active)
        assert no_sql is esperado, (status, is_active, no_sql)
