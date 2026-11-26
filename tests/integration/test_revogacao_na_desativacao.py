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

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import asyncpg
import pytest
from fastapi.responses import Response

from src.config import Settings, get_settings
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
from src.jobs import _runner, account_resync
from src.web.deps import CurrentUser
from src.web.routes import admin_accounts, admin_overview
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
async def test_revogar_em_conta_inativa_grava_motivo_de_churn(db, lado: _Lado) -> None:
    """Dois bloqueios (gestor desativado e conta fora), vale o da conta: a linha
    leva o motivo de churn do lado, que a volta da conta restaura."""
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=False)
        ativa, inativa = lado.conta(1), lado.conta(2)
        await _grant(conn, lado, gestor, ativa)
        await _grant(conn, lado, gestor, inativa, conta_ativa=False)

        revogados = await lado.modulo.revogar_de_desativados(conn)

        assert sorted(revogados) == [(gestor, ativa), (gestor, inativa)]
        revoked_at, motivo = await _linha(conn, lado, gestor, inativa)
        assert revoked_at is not None
        assert motivo == lado.motivo_churn
        assert (await _linha(conn, lado, gestor, ativa))[1] == MANAGER_DEACTIVATED_REASON


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
        # Churn em conta ATIVA (a conta voltou e a reconciliação ainda não
        # restaurou): quem devolve é o `restore_for_account`, não a reativação.
        c4 = lado.conta(4)
        await _grant(conn, lado, gestor, c4, motivo=lado.motivo_churn)
        antes_c2 = await _linha(conn, lado, gestor, c2)
        antes_c3 = await _linha(conn, lado, gestor, c3)
        antes_c4 = await _linha(conn, lado, gestor, c4)

        restaurados, remarcados = await lado.modulo.restaurar_de_reativados(conn)

        assert restaurados == [(gestor, c1)]
        assert remarcados == []
        assert await _linha(conn, lado, gestor, c1) == (None, None)
        assert await _linha(conn, lado, gestor, c2) == antes_c2
        assert await _linha(conn, lado, gestor, c3) == antes_c3
        assert await _linha(conn, lado, gestor, c4) == antes_c4


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
        # A conta inativa já saiu com o motivo de churn: nada a remarcar.
        assert (restaurados, remarcados) == ([(gestor, lado.conta(1))], [])
        assert (await _linha(conn, lado, gestor, lado.conta(2)))[1] == lado.motivo_churn
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
        assert plano == {
            "a_revogar": 2,
            "a_restaurar": 2,
            "a_remarcar": 1,
            # Revisão final (I3): quem seria atingido, por balde (o `invited` fora).
            "gestores_a_revogar": [str(desativado)],
            "gestores_a_restaurar": [str(reativado)],
            "gestores_a_remarcar": [str(reativado)],
        }

        revogados = await lado.modulo.revogar_de_desativados(conn)
        restaurados, remarcados = await lado.modulo.restaurar_de_reativados(conn)
        assert plano == {
            "a_revogar": len(revogados),
            "a_restaurar": len(restaurados),
            "a_remarcar": len(remarcados),
            "gestores_a_revogar": sorted({str(g) for g, _ in revogados}),
            "gestores_a_restaurar": sorted({str(g) for g, _ in restaurados}),
            "gestores_a_remarcar": sorted({str(g) for g, _ in remarcados}),
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


@pytest.mark.integration
@pytest.mark.parametrize("status", ["invited", "active", "inactive"])
@pytest.mark.parametrize("is_active", [True, False])
async def test_predicado_nao_desativado_e_a_negacao(db, status: str, is_active: bool) -> None:
    """`PREDICADO_NAO_DESATIVADO` (a forma que as filas do painel copiam) é a
    negação exata de `PREDICADO_DESATIVADO` em toda combinação real, avaliado no
    Postgres. A tabela esperada fica escrita: concordância sozinha não prova nada."""
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=is_active, status=status)
        desativado, nao_desativado = await conn.fetchrow(
            f"SELECT {_acesso_comum.PREDICADO_DESATIVADO}, "
            f"{_acesso_comum.PREDICADO_NAO_DESATIVADO} FROM managers m WHERE m.id = $1",
            gestor,
        )
    esperado = is_active and status != "inactive"
    assert nao_desativado is esperado, (status, is_active, nao_desativado)
    assert desativado is (not esperado), (status, is_active, desativado)


# --- Task 2: a volta da conta (`restore_for_account`) respeita o gestor desativado ---


async def _restaurar_conta(conn: asyncpg.Connection, lado: _Lado, conta: str) -> list[str] | int:
    """`restore_for_account` do lado, com o retorno público de cada um (Google
    `list[str]` de gestores, Meta `int`)."""
    resultado: list[str] | int = await lado.modulo.restore_for_account(
        conn, **{lado.kwarg_conta: conta}
    )
    return resultado


def _restaurados_esperados(lado: _Lado, gestores: list[UUID]) -> list[str] | int:
    if lado.nome == "google":
        return sorted(str(g) for g in gestores)
    return len(gestores)


def _normalizar(resultado: list[str] | int) -> list[str] | int:
    return sorted(resultado) if isinstance(resultado, list) else resultado


async def _conta_ativa(conn: asyncpg.Connection, lado: _Lado, conta: str, ativa: bool) -> None:
    await conn.execute(
        f"UPDATE {lado.inventario} SET is_active = $2 WHERE {lado.coluna} = $1", conta, ativa
    )


async def _ativo(conn: asyncpg.Connection, gestor: UUID, ativo: bool) -> None:
    await conn.execute("UPDATE managers SET is_active = $2 WHERE id = $1", gestor, ativo)


@pytest.mark.integration
async def test_volta_da_conta_nao_reabre_grant_de_desativado(db, lado: _Lado) -> None:
    """Linha de churn de gestor desativado numa conta que voltou: continua
    revogada, agora com `manager_deactivated` (o bloqueio que resta), e não entra
    no retorno — que conta só o gestor ativo da mesma conta."""
    async with db.acquire() as conn:
        gestor = await _gestor(conn, is_active=False)
        ativo = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(conn, lado, gestor, conta, motivo=lado.motivo_churn)
        await _grant(conn, lado, ativo, conta, motivo=lado.motivo_churn)
        revoked_at_antes, _ = await _linha(conn, lado, gestor, conta)

        resultado = await _restaurar_conta(conn, lado, conta)

        assert _normalizar(resultado) == _restaurados_esperados(lado, [ativo])
        assert await _linha(conn, lado, ativo, conta) == (None, None)
        assert await _linha(conn, lado, gestor, conta) == (
            revoked_at_antes,
            MANAGER_DEACTIVATED_REASON,
        )


@pytest.mark.integration
async def test_volta_da_conta_reabre_gestor_ativo(db, lado: _Lado) -> None:
    """Controle: gestor ativo volta como sempre voltou, e linhas fora do churn
    (admin, `manager_deactivated`) não são tocadas."""
    async with db.acquire() as conn:
        ativo = await _gestor(conn)
        admin_revogado = await _gestor(conn)
        ja_desativado = await _gestor(conn, is_active=False)
        conta = lado.conta(1)
        await _grant(conn, lado, ativo, conta, motivo=lado.motivo_churn)
        await _grant(conn, lado, admin_revogado, conta, motivo=ADMIN_REVOKED_REASON)
        await _grant(conn, lado, ja_desativado, conta, motivo=MANAGER_DEACTIVATED_REASON)
        antes_admin = await _linha(conn, lado, admin_revogado, conta)
        antes_desativado = await _linha(conn, lado, ja_desativado, conta)

        resultado = await _restaurar_conta(conn, lado, conta)

        assert _normalizar(resultado) == _restaurados_esperados(lado, [ativo])
        assert await _linha(conn, lado, ativo, conta) == (None, None)
        assert await _linha(conn, lado, admin_revogado, conta) == antes_admin
        assert await _linha(conn, lado, ja_desativado, conta) == antes_desativado


@pytest.mark.integration
async def test_restaurar_conta_ainda_inativa_nao_reabre_desativado(db, lado: _Lado) -> None:
    """Chamada sobre conta ainda inativa (a rota recusa, mas o repositório não
    depende disso): dois bloqueios, vale o da conta — a linha do desativado fica
    revogada e com o motivo de churn, para a volta de verdade decidir."""
    async with db.acquire() as conn:
        desativado = await _gestor(conn, is_active=False)
        conta = lado.conta(1)
        await _grant(conn, lado, desativado, conta, motivo=lado.motivo_churn, conta_ativa=False)
        antes = await _linha(conn, lado, desativado, conta)

        resultado = await _restaurar_conta(conn, lado, conta)

        assert resultado == _restaurados_esperados(lado, [])
        assert await _linha(conn, lado, desativado, conta) == antes


@pytest.mark.integration
async def test_ordem_conta_volta_depois_gestor_reativa(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn)
        conta = lado.conta(1)
        # conta sai: o churn revogou o grant.
        await _grant(conn, lado, gestor, conta, motivo=lado.motivo_churn, conta_ativa=False)
        # gestor desativa: a linha já está revogada, nada muda.
        await _ativo(conn, gestor, False)
        assert await lado.modulo.revogar_de_desativados(conn, manager_id=gestor) == []
        # conta volta: o grant não reabre.
        await _conta_ativa(conn, lado, conta, True)
        assert await _restaurar_conta(conn, lado, conta) == _restaurados_esperados(lado, [])
        assert (await _linha(conn, lado, gestor, conta))[1] == MANAGER_DEACTIVATED_REASON
        # gestor reativa: agora volta.
        await _ativo(conn, gestor, True)
        restaurados, remarcados = await lado.modulo.restaurar_de_reativados(conn, manager_id=gestor)
        assert (restaurados, remarcados) == ([(gestor, conta)], [])
        assert await _linha(conn, lado, gestor, conta) == (None, None)


@pytest.mark.integration
async def test_ordem_gestor_reativa_depois_conta_volta(db, lado: _Lado) -> None:
    async with db.acquire() as conn:
        gestor = await _gestor(conn)
        conta = lado.conta(1)
        # conta sai.
        await _grant(conn, lado, gestor, conta, motivo=lado.motivo_churn, conta_ativa=False)
        # gestor desativa e reativa com a conta ainda fora: a linha segue churn.
        await _ativo(conn, gestor, False)
        assert await lado.modulo.revogar_de_desativados(conn, manager_id=gestor) == []
        await _ativo(conn, gestor, True)
        assert await lado.modulo.restaurar_de_reativados(conn, manager_id=gestor) == ([], [])
        assert (await _linha(conn, lado, gestor, conta))[1] == lado.motivo_churn
        # conta volta: o churn devolve.
        await _conta_ativa(conn, lado, conta, True)
        assert await _restaurar_conta(conn, lado, conta) == _restaurados_esperados(lado, [gestor])
        assert await _linha(conn, lado, gestor, conta) == (None, None)


# --- Task 3: a rota `toggle-active` revoga e restaura ---------------------------
#
# A função da rota é chamada direto (como em test_acesso_e_audit_sao_atomicos.py),
# com um request HTMX falso para o toast vir no `HX-Trigger`. Os dois lados
# entram juntos em cada teste, porque a rota chama os dois.


class _FakeRequestHtmx:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {"HX-Request": "true"}


async def _admin(conn: asyncpg.Connection) -> CurrentUser:
    manager = await managers.create(
        conn,
        manager_id=uuid4(),
        email=f"admin.{uuid4().hex[:8]}@v4company.com",
        full_name=None,
        role="admin",
    )
    return CurrentUser(manager)


async def _toggle(admin: CurrentUser, gestor: UUID, desejado: str) -> Response:
    return await admin_overview.admin_managers_toggle_active(
        _FakeRequestHtmx(),  # type: ignore[arg-type]
        manager_id=gestor,
        desejado=desejado,  # type: ignore[arg-type]
        user=admin,
    )


async def _audits_do_toggle(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT params_summary, had_effect FROM audit_log "
        "WHERE operation = 'admin_manager_toggle_active' ORDER BY occurred_at, id"
    )


def _toast(resposta: Response) -> str:
    return str(json.loads(resposta.headers["HX-Trigger"])["toast"]["message"])


async def _gestor_com_5_grants(conn: asyncpg.Connection) -> tuple[UUID, list[str], list[str]]:
    google, meta = _LADOS["google"], _LADOS["meta"]
    gestor = await _gestor(conn)
    contas_google = [google.conta(n) for n in (1, 2, 3)]
    contas_meta = [meta.conta(n) for n in (1, 2)]
    for conta in contas_google:
        await _grant(conn, google, gestor, conta)
    for conta in contas_meta:
        await _grant(conn, meta, gestor, conta)
    return gestor, contas_google, contas_meta


_CHAVES_DE_CONTAGEM = ("revogados_", "restaurados_", "remarcados_")


@pytest.mark.integration
async def test_desativar_pela_rota_revoga_e_audita_contagens(db) -> None:
    async with db.acquire() as conn:
        admin = await _admin(conn)
        gestor, contas_google, contas_meta = await _gestor_com_5_grants(conn)

    resposta = await _toggle(admin, gestor, "inativo")

    async with db.acquire() as conn:
        for lado, contas in ((_LADOS["google"], contas_google), (_LADOS["meta"], contas_meta)):
            for conta in contas:
                revoked_at, motivo = await _linha(conn, lado, gestor, conta)
                assert revoked_at is not None
                assert motivo == MANAGER_DEACTIVATED_REASON
        (audit,) = await _audits_do_toggle(conn)
    summary = json.loads(audit["params_summary"])
    assert audit["had_effect"] is True
    assert summary["revogados_google"] == 3
    assert summary["revogados_meta"] == 2
    assert summary["target_manager_id"] == str(gestor)
    assert not any(k.startswith(("restaurados_", "remarcados_")) for k in summary)
    assert _toast(resposta) == "Gestor desativado: 5 acessos revogados."


@pytest.mark.integration
async def test_reativar_pela_rota_devolve_so_o_que_tirou(db) -> None:
    google = _LADOS["google"]
    async with db.acquire() as conn:
        admin = await _admin(conn)
        gestor, contas_google, contas_meta = await _gestor_com_5_grants(conn)
    await _toggle(admin, gestor, "inativo")
    async with db.acquire() as conn:
        extra = google.conta(9)
        await _grant(conn, google, gestor, extra, motivo=ADMIN_REVOKED_REASON)
        antes_extra = await _linha(conn, google, gestor, extra)

    resposta = await _toggle(admin, gestor, "ativo")

    async with db.acquire() as conn:
        for lado, contas in ((google, contas_google), (_LADOS["meta"], contas_meta)):
            for conta in contas:
                assert await _linha(conn, lado, gestor, conta) == (None, None)
        assert await _linha(conn, google, gestor, extra) == antes_extra
        audits = await _audits_do_toggle(conn)
    assert len(audits) == 2
    summary = json.loads(audits[1]["params_summary"])
    assert audits[1]["had_effect"] is True
    assert summary["restaurados_google"] == 3
    assert summary["restaurados_meta"] == 2
    assert summary["remarcados_google"] == 0
    assert summary["remarcados_meta"] == 0
    assert not any(k.startswith("revogados_") for k in summary)
    assert _toast(resposta) == "Gestor reativado: 5 acessos restaurados."


@pytest.mark.integration
async def test_reativar_com_conta_fora_do_inventario_conta_remarcados(db) -> None:
    google = _LADOS["google"]
    async with db.acquire() as conn:
        admin = await _admin(conn)
        gestor = await _gestor(conn)
        await _grant(conn, google, gestor, google.conta(1))
        await _grant(conn, google, gestor, google.conta(2))
    await _toggle(admin, gestor, "inativo")
    async with db.acquire() as conn:
        await _conta_ativa(conn, google, google.conta(2), False)

    resposta = await _toggle(admin, gestor, "ativo")

    async with db.acquire() as conn:
        assert await _linha(conn, google, gestor, google.conta(1)) == (None, None)
        revoked_at, motivo = await _linha(conn, google, gestor, google.conta(2))
        assert revoked_at is not None
        assert motivo == LEFT_MCC_REASON
        audits = await _audits_do_toggle(conn)
    summary = json.loads(audits[1]["params_summary"])
    assert (summary["restaurados_google"], summary["remarcados_google"]) == (1, 1)
    assert _toast(resposta) == (
        "Gestor reativado: 1 acesso restaurado. "
        "1 acesso continua revogado porque a conta saiu do inventário."
    )


@pytest.mark.integration
async def test_segundo_clique_nao_muda_nada(db) -> None:
    async with db.acquire() as conn:
        admin = await _admin(conn)
        gestor, _, _ = await _gestor_com_5_grants(conn)
    await _toggle(admin, gestor, "inativo")
    async with db.acquire() as conn:
        fotos = [await _foto(conn, lado) for lado in _LADOS.values()]

    proibido = AssertionError("o segundo clique não pode chamar as funções de acesso")
    with (
        patch.object(manager_account_access, "revogar_de_desativados", side_effect=proibido),
        patch.object(manager_meta_account_access, "revogar_de_desativados", side_effect=proibido),
        patch.object(manager_account_access, "restaurar_de_reativados", side_effect=proibido),
        patch.object(manager_meta_account_access, "restaurar_de_reativados", side_effect=proibido),
    ):
        resposta = await _toggle(admin, gestor, "inativo")

    async with db.acquire() as conn:
        assert [await _foto(conn, lado) for lado in _LADOS.values()] == fotos
        audits = await _audits_do_toggle(conn)
    assert [a["had_effect"] for a in audits] == [True, False]
    summary = json.loads(audits[1]["params_summary"])
    assert not any(k.startswith(_CHAVES_DE_CONTAGEM) for k in summary)
    assert _toast(resposta) == "O gestor já estava assim."


# --- Task 4: a etapa `_etapa_gestores` do job diário ----------------------------
#
# A etapa chama os wrappers dos dois módulos sem `manager_id`, numa transação só,
# atrás da trava `manager_offboarding_apply`. Os dois lados entram juntos em cada
# teste, porque a etapa converge os dois.


def _settings(*, apply: bool) -> Settings:
    return get_settings().model_copy(update={"manager_offboarding_apply": apply})


async def _audits_da_etapa(conn: asyncpg.Connection) -> dict[str, list[asyncpg.Record]]:
    rows = await conn.fetch(
        "SELECT platform, status, target_count, params_summary, error_message FROM audit_log "
        "WHERE operation = 'manager_offboarding_reconcile' ORDER BY occurred_at, id"
    )
    por_lado: dict[str, list[asyncpg.Record]] = {"google": [], "meta": []}
    for r in rows:
        por_lado[r["platform"]].append(r)
    return por_lado


def _summary(audit: asyncpg.Record) -> dict[str, object]:
    return dict(json.loads(audit["params_summary"]))


def _contagens(audit: asyncpg.Record) -> dict[str, object]:
    """O `params_summary` sem as listas de pares e de gestores do plano (afirmadas
    em teste próprio)."""
    return {k: v for k, v in _summary(audit).items() if not k.startswith(("pares_", "gestores_"))}


async def _dois_desativados_com_grants(conn: asyncpg.Connection) -> None:
    """3 grants vivos Google e 2 Meta, em dois gestores desativados pelas duas
    formas do predicado (`is_active=false` e `status='inactive'`)."""
    google, meta = _LADOS["google"], _LADOS["meta"]
    um = await _gestor(conn)
    outro = await _gestor(conn)
    await _grant(conn, google, um, google.conta(1))
    await _grant(conn, google, um, google.conta(2))
    await _grant(conn, meta, um, meta.conta(1))
    await _grant(conn, google, outro, google.conta(3))
    await _grant(conn, meta, outro, meta.conta(2))
    await _ativo(conn, um, False)
    await conn.execute("UPDATE managers SET status = 'inactive' WHERE id = $1", outro)


@pytest.mark.integration
async def test_etapa_com_trava_desligada_audita_e_nao_escreve(db) -> None:
    async with db.acquire() as conn:
        await _dois_desativados_com_grants(conn)
        fotos = [await _foto(conn, lado) for lado in _LADOS.values()]

    falhou = await account_resync._etapa_gestores(db, _settings(apply=False))

    assert falhou is False
    async with db.acquire() as conn:
        assert [await _foto(conn, lado) for lado in _LADOS.values()] == fotos
        audits = await _audits_da_etapa(conn)
    esperado = {"google": 3, "meta": 2}
    for plataforma, a_revogar in esperado.items():
        (audit,) = audits[plataforma]
        assert audit["status"] == "success"
        assert audit["target_count"] == 0
        # Sem trava: as contagens e os gestores do plano (afirmados em
        # `test_etapa_com_trava_desligada_diz_quem_seria_atingido`), nada de pares.
        # As conexões OAuth de desativado (25/11) moram só no lado Google: só ele as tem.
        conexoes = {"conexoes_a_revogar": 0} if plataforma == "google" else {}
        assert _contagens(audit) == {
            "apply": False,
            "a_revogar": a_revogar,
            "a_restaurar": 0,
            "a_remarcar": 0,
            **conexoes,
        }
        assert sorted(k for k in _summary(audit) if k.startswith(("pares_", "gestores_"))) == [
            "gestores_a_remarcar",
            "gestores_a_restaurar",
            "gestores_a_revogar",
        ]


@pytest.mark.integration
async def test_etapa_com_trava_ligada_converge(db) -> None:
    google, meta = _LADOS["google"], _LADOS["meta"]
    async with db.acquire() as conn:
        # Review Focus 1: grant concedido DEPOIS da desativação (admin marca a
        # caixa na matriz) — nenhuma rota revogou, só a etapa o alcança.
        tardio = await _gestor(conn, is_active=False)
        await _grant(conn, google, tardio, google.conta(1))
        await _grant(conn, meta, tardio, meta.conta(1))
        # Review Focus 3: reativado por SQL direto (`status` inactive -> active,
        # `is_active` já true), com as linhas que a desativação deixou.
        por_sql = await _gestor(conn, status="inactive")
        await _grant(conn, google, por_sql, google.conta(2), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(conn, meta, por_sql, meta.conta(2), motivo=MANAGER_DEACTIVATED_REASON)
        # conta fora do inventário: continua revogada, agora como churn.
        await _grant(
            conn,
            google,
            por_sql,
            google.conta(3),
            motivo=MANAGER_DEACTIVATED_REASON,
            conta_ativa=False,
        )
        # revogação de admin não volta por esse caminho.
        await _grant(conn, google, por_sql, google.conta(4), motivo=ADMIN_REVOKED_REASON)
        antes_admin = await _linha(conn, google, por_sql, google.conta(4))
        await conn.execute("UPDATE managers SET status = 'active' WHERE id = $1", por_sql)

    falhou = await account_resync._etapa_gestores(db, _settings(apply=True))

    assert falhou is False
    async with db.acquire() as conn:
        for lado in (google, meta):
            revoked_at, motivo = await _linha(conn, lado, tardio, lado.conta(1))
            assert revoked_at is not None
            assert motivo == MANAGER_DEACTIVATED_REASON
            assert await _linha(conn, lado, por_sql, lado.conta(2)) == (None, None)
        revoked_at, motivo = await _linha(conn, google, por_sql, google.conta(3))
        assert revoked_at is not None
        assert motivo == LEFT_MCC_REASON
        assert await _linha(conn, google, por_sql, google.conta(4)) == antes_admin
        audits = await _audits_da_etapa(conn)
    (audit_google,) = audits["google"]
    (audit_meta,) = audits["meta"]
    assert _contagens(audit_google) == {
        "apply": True,
        "a_revogar": 1,
        "a_restaurar": 1,
        "a_remarcar": 1,
        "revogados": 1,
        "restaurados": 1,
        "remarcados": 1,
        "conexoes_a_revogar": 0,
        "conexoes_revogadas": 0,
        "conexoes_de": [],
    }
    assert audit_google["target_count"] == 2
    assert _contagens(audit_meta) == {
        "apply": True,
        "a_revogar": 1,
        "a_restaurar": 1,
        "a_remarcar": 0,
        "revogados": 1,
        "restaurados": 1,
        "remarcados": 0,
    }
    assert audit_meta["target_count"] == 2

    # Review Focus 4: a segunda rodada (retry do job) não muda nada.
    async with db.acquire() as conn:
        fotos = [await _foto(conn, lado) for lado in _LADOS.values()]
    assert await account_resync._etapa_gestores(db, _settings(apply=True)) is False
    async with db.acquire() as conn:
        assert [await _foto(conn, lado) for lado in _LADOS.values()] == fotos
        audits = await _audits_da_etapa(conn)
    zeros = dict.fromkeys(
        ("a_revogar", "a_restaurar", "a_remarcar", "revogados", "restaurados", "remarcados"), 0
    )
    for plataforma in ("google", "meta"):
        segunda = audits[plataforma][1]
        assert segunda["target_count"] == 0
        conexoes = (
            {"conexoes_a_revogar": 0, "conexoes_revogadas": 0, "conexoes_de": []}
            if plataforma == "google"
            else {}
        )
        assert _contagens(segunda) == {"apply": True, **zeros, **conexoes}


def _job_sobre_o_pool_do_teste(settings: Settings) -> ExitStack:
    """`run()` de verdade sobre o pool que o fixture `db` já abriu: `init_pool` e
    `close_pool` do esqueleto viram no-op (o fixture fecha o pool no teardown)."""
    stack = ExitStack()
    stack.enter_context(patch.object(_runner.connection, "init_pool", AsyncMock()))
    stack.enter_context(patch.object(_runner.connection, "close_pool", AsyncMock()))
    stack.enter_context(
        patch.object(account_resync, "get_settings", MagicMock(return_value=settings))
    )
    stack.enter_context(patch.object(account_resync, "configure_logging", MagicMock()))
    return stack


async def _status_de(conn: asyncpg.Connection, operation: str) -> list[tuple[str, str]]:
    rows = await conn.fetch(
        "SELECT platform, status FROM audit_log WHERE operation = $1 ORDER BY platform, id",
        operation,
    )
    return [(r["platform"], r["status"]) for r in rows]


@pytest.mark.integration
async def test_etapa_roda_mesmo_sem_oauth(db) -> None:
    async with db.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM google_oauth_connections") == 0
        await _dois_desativados_com_grants(conn)

    with _job_sobre_o_pool_do_teste(_settings(apply=True)):
        rc = await account_resync.run()

    assert rc == 1, "sem OAuth o job continua saindo com 1"
    async with db.acquire() as conn:
        for lado in _LADOS.values():
            vivos = await conn.fetchval(
                f"SELECT count(*) FROM {lado.tabela} WHERE revoked_at IS NULL"
            )
            assert vivos == 0, f"{lado.nome}: a etapa dos gestores não rodou sem OAuth"
        assert await _status_de(conn, "google_reconcile") == [("google", "error")]
        assert await _status_de(conn, "manager_offboarding_reconcile") == [
            ("google", "success"),
            ("meta", "success"),
        ]
        assert await _status_de(conn, "db_purge") == [("google", "success")]


@pytest.mark.integration
async def test_etapa_que_falha_entra_no_exit_code(db) -> None:
    async with db.acquire() as conn:
        await _dois_desativados_com_grants(conn)
        fotos = [await _foto(conn, lado) for lado in _LADOS.values()]

    # O lado Meta falha DEPOIS de o Google ter escrito: a transação única desfaz
    # o Google também.
    boom = RuntimeError("meta caiu no meio")
    with _job_sobre_o_pool_do_teste(_settings(apply=True)) as stack:
        stack.enter_context(
            patch.object(
                account_resync,
                "_etapa_google",
                AsyncMock(return_value=account_resync.Desfecho.OK),
            )
        )
        stack.enter_context(
            patch.object(account_resync, "_etapa_meta", AsyncMock(return_value=False))
        )
        stack.enter_context(
            patch.object(
                manager_meta_account_access,
                "revogar_de_desativados",
                AsyncMock(side_effect=boom),
            )
        )
        crash = stack.enter_context(patch.object(account_resync, "record_job_crash", AsyncMock()))
        rc = await account_resync.run()

    assert rc == 1
    crash.assert_not_awaited()
    async with db.acquire() as conn:
        assert [await _foto(conn, lado) for lado in _LADOS.values()] == fotos
        assert await _status_de(conn, "manager_offboarding_reconcile") == [
            ("google", "error"),
            ("meta", "error"),
        ]
        mensagens = await conn.fetch(
            "SELECT error_message FROM audit_log WHERE operation = 'manager_offboarding_reconcile'"
        )
        assert all("meta caiu no meio" in r["error_message"] for r in mensagens)
        assert await _status_de(conn, "db_purge") == [("google", "success")]


@pytest.mark.integration
async def test_etapa_espera_desativacao_concorrente_e_nao_restaura(db) -> None:
    """Corrida com a rota: o gestor foi reativado por SQL (o job ia restaurar) e a
    rota o desativa no mesmo instante. Sem a trava dos gestores, o job lia o
    gestor ainda ativo e restaurava, e a revogação da rota (que só vê linha viva)
    não alcançava o que o job acabara de devolver: desativado com grant vivo."""
    google = _LADOS["google"]
    async with db.acquire() as conn:
        gestor = await _gestor(conn)
        await _grant(conn, google, gestor, google.conta(1), motivo=MANAGER_DEACTIVATED_REASON)

    async with db.acquire() as rota:
        tx = rota.transaction()
        await tx.start()
        try:
            # A rota inteira, ainda sem commit: `definir_ativo` (FOR UPDATE +
            # UPDATE) e a revogação, que não acha linha viva (a do gestor ainda
            # está revogada). É a ordem que deixava o estado errado: o job
            # restaurando DEPOIS da revogação da rota e antes do commit dela.
            assert await managers.definir_ativo(rota, manager_id=gestor, ativo=False) is not None
            assert (
                await manager_account_access.revogar_de_desativados(rota, manager_id=gestor) == []
            )
            etapa = asyncio.create_task(account_resync._etapa_gestores(db, _settings(apply=True)))
            await asyncio.sleep(0.5)
            assert not etapa.done(), "a etapa não esperou a transação da rota"
        finally:
            await tx.commit()
        assert await etapa is False

    async with db.acquire() as conn:
        revoked_at, motivo = await _linha(conn, google, gestor, google.conta(1))
    assert revoked_at is not None, "o job restaurou o grant de quem a rota desativou"
    assert motivo == MANAGER_DEACTIVATED_REASON


# --- Task 4, fix round 1 ----------------------------------------------------------


@pytest.mark.integration
async def test_etapa_com_trava_ligada_audita_quem_foi_atingido(db) -> None:
    """Forense como as outras reconciliações: com a trava ligada, cada linha do
    audit leva os pares `[gestor, conta]` atingidos. Reconceder zera o motivo, e a
    restauração o zera na hora — sem isto não sobra rastro de quem o job mexeu."""
    google, meta = _LADOS["google"], _LADOS["meta"]
    async with db.acquire() as conn:
        tardio = await _gestor(conn, is_active=False)
        await _grant(conn, google, tardio, google.conta(1))
        await _grant(conn, meta, tardio, meta.conta(1))
        por_sql = await _gestor(conn, status="inactive")
        await _grant(conn, google, por_sql, google.conta(2), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(conn, meta, por_sql, meta.conta(2), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(
            conn,
            google,
            por_sql,
            google.conta(3),
            motivo=MANAGER_DEACTIVATED_REASON,
            conta_ativa=False,
        )
        await conn.execute("UPDATE managers SET status = 'active' WHERE id = $1", por_sql)

    assert await account_resync._etapa_gestores(db, _settings(apply=True)) is False

    async with db.acquire() as conn:
        audits = await _audits_da_etapa(conn)
    resumo_google = _summary(audits["google"][0])
    resumo_meta = _summary(audits["meta"][0])
    assert resumo_google["pares_revogados"] == [[str(tardio), google.conta(1)]]
    assert resumo_google["pares_restaurados"] == [[str(por_sql), google.conta(2)]]
    assert resumo_google["pares_remarcados"] == [[str(por_sql), google.conta(3)]]
    assert resumo_meta["pares_revogados"] == [[str(tardio), meta.conta(1)]]
    assert resumo_meta["pares_restaurados"] == [[str(por_sql), meta.conta(2)]]
    assert resumo_meta["pares_remarcados"] == []


class _ContaStatements:
    """Conexão que conta os statements e repassa ao banco de verdade."""

    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn
        self.statements: list[str] = []

    async def execute(self, sql: str, *args: object) -> str:
        self.statements.append(sql)
        return str(await self._conn.execute(sql, *args))

    async def fetch(self, sql: str, *args: object) -> list[asyncpg.Record]:
        self.statements.append(sql)
        return list(await self._conn.fetch(sql, *args))

    async def fetchrow(self, sql: str, *args: object) -> asyncpg.Record | None:
        self.statements.append(sql)
        return await self._conn.fetchrow(sql, *args)

    async def fetchval(self, sql: str, *args: object) -> object:
        self.statements.append(sql)
        return await self._conn.fetchval(sql, *args)


@pytest.mark.integration
async def test_restore_for_account_e_um_statement_so(db, lado: _Lado) -> None:
    """Com dois UPDATEs (um para o gestor desativado, outro para o ativo), a rota
    desativando o gestor entre os dois deixava a linha de churn presa em conta
    ATIVA: o 1º o via ativo e não remarcava, o 2º o via desativado e não
    restaurava — e nem a rota, nem a etapa, nem a reativação a alcançam. Com UM
    statement a decisão por gestor sai do mesmo snapshot: não há janela."""
    async with db.acquire() as conn:
        desativado = await _gestor(conn, is_active=False)
        ativo = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(conn, lado, desativado, conta, motivo=lado.motivo_churn)
        await _grant(conn, lado, ativo, conta, motivo=lado.motivo_churn)

        contador = _ContaStatements(conn)
        resultado = await lado.modulo.restore_for_account(contador, **{lado.kwarg_conta: conta})

        assert len(contador.statements) == 1, contador.statements
        assert _normalizar(resultado) == _restaurados_esperados(lado, [ativo])
        assert await _linha(conn, lado, ativo, conta) == (None, None)
        revoked_at, motivo = await _linha(conn, lado, desativado, conta)
        assert revoked_at is not None
        assert motivo == MANAGER_DEACTIVATED_REASON


@pytest.mark.integration
async def test_linha_da_corrida_do_restore_e_alcancada_pela_convergencia(db, lado: _Lado) -> None:
    """O que sobra de corrida com um statement só: o gestor desativado DEPOIS do
    snapshot do restore sai com grant VIVO (o restore o viu ativo). Esse estado é
    o que `revogar_de_desativados` alcança — aqui pela etapa do job. Reproduz o
    estado final da corrida em sequência (restore, depois a desativação), não a
    intercalação: dentro de um statement não há ponto para intercalar."""
    async with db.acquire() as conn:
        gestor = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(conn, lado, gestor, conta, motivo=lado.motivo_churn)
        await _restaurar_conta(conn, lado, conta)
        await _ativo(conn, gestor, False)
        assert await _linha(conn, lado, gestor, conta) == (None, None)

    assert await account_resync._etapa_gestores(db, _settings(apply=True)) is False

    async with db.acquire() as conn:
        revoked_at, motivo = await _linha(conn, lado, gestor, conta)
    assert revoked_at is not None
    assert motivo == MANAGER_DEACTIVATED_REASON


# --- Revisão final (I1): a fila do painel conta o que o botão devolve ----------
#
# Depois da T2, `restore_for_account` não devolve a linha de churn de gestor
# desativado (remarca como `manager_deactivated`), mas as filas `voltaram_ao_mcc`
# (Google) e `saiu_da_parceria` (Meta) contavam toda linha de churn da conta.
# Medido na revisão final: fila exibia 2, o botão devolvia 1.


async def _na_fila_de_restauracao(conn: asyncpg.Connection, lado: _Lado, conta: str) -> int | None:
    """A contagem que o painel exibe para a conta na fila de restauração do lado
    (`None` = a conta não está na fila)."""
    if lado.nome == "google":
        filas_google = await google_ads_accounts.list_queues(conn)
        contagens = {
            r["customer_id"]: r["grants_restauraveis"] for r in filas_google.voltaram_ao_mcc
        }
    else:
        filas_meta = await meta_ad_accounts.list_queues(conn)
        contagens = {a.ad_account_id: n for a, n in filas_meta.saiu_da_parceria}
    valor = contagens.get(conta)
    return None if valor is None else int(valor)


async def _na_fila_sem_delegacao(conn: asyncpg.Connection, lado: _Lado) -> set[str]:
    if lado.nome == "google":
        filas_google = await google_ads_accounts.list_queues(conn)
        return {r["customer_id"] for r in filas_google.sem_delegacao}
    filas_meta = await meta_ad_accounts.list_queues(conn)
    return {a.ad_account_id for a in filas_meta.sem_delegacao}


def _quantos_restaurados(resultado: list[str] | int) -> int:
    return len(resultado) if isinstance(resultado, list) else resultado


@pytest.mark.integration
async def test_fila_conta_so_o_que_o_botao_devolve(db, lado: _Lado) -> None:
    """O probe da revisão final: dois grants de churn na conta que voltou, um de
    gestor ativo e um de desativado. A fila tem de exibir 1, o que o botão devolve."""
    async with db.acquire() as conn:
        desativado = await _gestor(conn, is_active=False)
        ativo = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(conn, lado, desativado, conta, motivo=lado.motivo_churn)
        await _grant(conn, lado, ativo, conta, motivo=lado.motivo_churn)

        exibido = await _na_fila_de_restauracao(conn, lado, conta)
        resultado = await _restaurar_conta(conn, lado, conta)

    assert _quantos_restaurados(resultado) == 1
    assert exibido == 1, f"a fila exibe {exibido} e o botão devolve 1"


@pytest.mark.integration
async def test_conta_so_com_churn_de_desativado_vai_para_sem_delegacao(db, lado: _Lado) -> None:
    """Consequência do filtro: a conta ativa cujo único churn é de gestor
    desativado não tem o que o botão devolva, e sai da fila de restauração. Sem
    grant vivo, ela tem de aparecer na fila de delegação: a precedência da fila de
    restauração sobre `sem_delegacao` só vale quando há o que restaurar; sem isto
    a conta sumiria das duas filas (e do aviso de conta sem grant)."""
    async with db.acquire() as conn:
        desativado = await _gestor(conn, is_active=False)
        conta = lado.conta(1)
        await _grant(conn, lado, desativado, conta, motivo=lado.motivo_churn)

        assert await _na_fila_de_restauracao(conn, lado, conta) is None
        assert conta in await _na_fila_sem_delegacao(conn, lado)


class _FakeRequestForm:
    """POST de formulário (sem HTMX): a rota responde 303 para `destino`."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


async def _restore_pela_rota(admin: CurrentUser, lado: _Lado, conta: str) -> Response:
    if lado.nome == "google":
        return await admin_accounts.admin_accounts_google_restore(
            _FakeRequestForm(),  # type: ignore[arg-type]
            customer_id=conta,
            user=admin,
        )
    return await admin_accounts.admin_accounts_meta_restore(
        _FakeRequestForm(),  # type: ignore[arg-type]
        ad_account_id=conta,
        user=admin,
    )


_OPERACAO_DO_RESTORE = {
    "google": "admin_accounts_google_restore",
    "meta": "admin_accounts_meta_restore",
}


async def _audit_do_restore(conn: asyncpg.Connection, lado: _Lado) -> dict[str, object]:
    audit = await conn.fetchrow(
        "SELECT params_summary FROM audit_log WHERE operation = $1",
        _OPERACAO_DO_RESTORE[lado.nome],
    )
    assert audit is not None
    return dict(json.loads(audit["params_summary"]))


@pytest.mark.integration
async def test_restore_pela_rota_audita_e_avisa_os_retidos(db, lado: _Lado) -> None:
    """O admin clica em Restaurar e um grant fica retido pela desativação do
    gestor: o audit e o aviso dizem quantos, em vez do `?ok=restored` genérico."""
    async with db.acquire() as conn:
        admin = await _admin(conn)
        desativado = await _gestor(conn, is_active=False)
        ativo = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(conn, lado, desativado, conta, motivo=lado.motivo_churn)
        await _grant(conn, lado, ativo, conta, motivo=lado.motivo_churn)

    resposta = await _restore_pela_rota(admin, lado, conta)

    async with db.acquire() as conn:
        summary = await _audit_do_restore(conn, lado)
    assert summary["restored_grants"] == 1
    assert summary["retidos_gestor_desativado"] == 1
    assert resposta.status_code == 303
    assert resposta.headers["location"].endswith("?ok=restored&retidos=1")


@pytest.mark.integration
async def test_restore_sem_retidos_mantem_o_destino(db, lado: _Lado) -> None:
    """Sem gestor desativado na conta, nada muda para o admin: o destino é o
    `?ok=restored` de sempre, e o audit diz zero retidos."""
    async with db.acquire() as conn:
        admin = await _admin(conn)
        ativo = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(conn, lado, ativo, conta, motivo=lado.motivo_churn)

    resposta = await _restore_pela_rota(admin, lado, conta)

    async with db.acquire() as conn:
        summary = await _audit_do_restore(conn, lado)
    assert (summary["restored_grants"], summary["retidos_gestor_desativado"]) == (1, 0)
    assert resposta.headers["location"].endswith("?ok=restored")


# --- Revisão final (M6): `restore_for_account` é idempotente --------------------


@pytest.mark.integration
async def test_restore_for_account_segunda_chamada_nao_muda_nada(db, lado: _Lado) -> None:
    """Duplo clique em Restaurar (ou aba velha reenviada): a segunda chamada não
    acha churn (nem o do ativo, já restaurado, nem o do desativado, já remarcado)
    e não muda linha nenhuma."""
    async with db.acquire() as conn:
        desativado = await _gestor(conn, is_active=False)
        ativo = await _gestor(conn)
        conta = lado.conta(1)
        await _grant(conn, lado, desativado, conta, motivo=lado.motivo_churn)
        await _grant(conn, lado, ativo, conta, motivo=lado.motivo_churn)

        primeira = await _restaurar_conta(conn, lado, conta)
        foto = await _foto(conn, lado)
        segunda = await _restaurar_conta(conn, lado, conta)

        assert _quantos_restaurados(primeira) == 1
        assert _quantos_restaurados(segunda) == 0
        assert await _foto(conn, lado) == foto
        assert await _linha(conn, lado, ativo, conta) == (None, None)
        _, motivo = await _linha(conn, lado, desativado, conta)
        assert motivo == MANAGER_DEACTIVATED_REASON


# --- Revisão final (I2): o audit da rota leva os pares atingidos ----------------


@pytest.mark.integration
async def test_rota_audita_os_pares_que_mexeu(db) -> None:
    """A reativação zera o motivo das linhas: sem os pares no audit, não sobra
    rastro de quais contas a rota revogou e devolveu. Mesmo formato do job
    (`[[manager_id, conta], ...]`), uma chave por balde e plataforma."""
    google, meta = _LADOS["google"], _LADOS["meta"]
    async with db.acquire() as conn:
        admin = await _admin(conn)
        gestor = await _gestor(conn)
        await _grant(conn, google, gestor, google.conta(1))
        await _grant(conn, google, gestor, google.conta(2))
        await _grant(conn, meta, gestor, meta.conta(1))

    await _toggle(admin, gestor, "inativo")
    async with db.acquire() as conn:
        await _conta_ativa(conn, google, google.conta(2), False)
    await _toggle(admin, gestor, "ativo")

    async with db.acquire() as conn:
        desativar, reativar = await _audits_do_toggle(conn)
    g = str(gestor)
    resumo = json.loads(desativar["params_summary"])
    assert resumo["pares_revogados_google"] == [[g, google.conta(1)], [g, google.conta(2)]]
    assert resumo["pares_revogados_meta"] == [[g, meta.conta(1)]]
    assert (resumo["revogados_google"], resumo["revogados_meta"]) == (2, 1)
    resumo = json.loads(reativar["params_summary"])
    assert resumo["pares_restaurados_google"] == [[g, google.conta(1)]]
    assert resumo["pares_remarcados_google"] == [[g, google.conta(2)]]
    assert resumo["pares_restaurados_meta"] == [[g, meta.conta(1)]]
    assert resumo["pares_remarcados_meta"] == []
    assert (resumo["restaurados_google"], resumo["remarcados_google"]) == (1, 1)
    assert (resumo["restaurados_meta"], resumo["remarcados_meta"]) == (1, 0)


# --- Revisão final (I3): o dry-run diz quem seria atingido ----------------------


@pytest.mark.integration
async def test_etapa_com_trava_desligada_diz_quem_seria_atingido(db) -> None:
    """Ligar a trava é a decisão destrutiva, e ela se apoia neste audit: além das
    contagens, os `manager_id` distintos de cada balde. Um gestor desativado por
    engano aparece pelo id, não só como "+N" no número."""
    google, meta = _LADOS["google"], _LADOS["meta"]
    async with db.acquire() as conn:
        a_revogar = await _gestor(conn, is_active=False)
        await _grant(conn, google, a_revogar, google.conta(1))
        await _grant(conn, google, a_revogar, google.conta(2))
        await _grant(conn, meta, a_revogar, meta.conta(1))
        reativado = await _gestor(conn)
        await _grant(conn, google, reativado, google.conta(3), motivo=MANAGER_DEACTIVATED_REASON)
        await _grant(
            conn,
            google,
            reativado,
            google.conta(4),
            motivo=MANAGER_DEACTIVATED_REASON,
            conta_ativa=False,
        )
        fotos = [await _foto(conn, lado) for lado in _LADOS.values()]

    assert await account_resync._etapa_gestores(db, _settings(apply=False)) is False

    async with db.acquire() as conn:
        assert [await _foto(conn, lado) for lado in _LADOS.values()] == fotos
        audits = await _audits_da_etapa(conn)
    resumo_google = _summary(audits["google"][0])
    resumo_meta = _summary(audits["meta"][0])
    assert resumo_google["gestores_a_revogar"] == [str(a_revogar)]
    assert resumo_google["gestores_a_restaurar"] == [str(reativado)]
    assert resumo_google["gestores_a_remarcar"] == [str(reativado)]
    assert (
        resumo_google["a_revogar"],
        resumo_google["a_restaurar"],
        resumo_google["a_remarcar"],
    ) == (2, 1, 1)
    assert resumo_meta["gestores_a_revogar"] == [str(a_revogar)]
    assert resumo_meta["gestores_a_restaurar"] == []
    assert resumo_meta["gestores_a_remarcar"] == []
    assert resumo_meta["a_revogar"] == 1
