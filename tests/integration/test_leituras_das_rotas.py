"""Leituras que as rotas do painel faziam direto na conexão e foram para repositórios (G2).

Cada função nova tem um teste que afirma o que a rota mostrava com o SQL de antes:
a matriz só com grant vivo, a contagem só em conta ativa (e o gestor com "0" que
continua na lista), o convite pendente com o e-mail de quem convidou, as 5 linhas
do overview. Os pares gêmeos (Google x Meta) rodam o mesmo roteiro nos dois lados.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import ModuleType
from uuid import UUID, uuid4

import asyncpg
import pytest

from src.db.repositories import (
    audit_log,
    google_ads_accounts,
    google_oauth_connections,
    manager_account_access,
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
)
from tests.integration._seed import seed_manager


@dataclass(frozen=True)
class _Lado:
    nome: str
    repo: ModuleType
    coluna: str
    inventario: str
    tabela: str
    criar_conta: Callable[[asyncpg.Connection, str], Awaitable[None]]
    ids: tuple[str, str, str]


async def _conta_google(conn: asyncpg.Connection, customer_id: str) -> None:
    await google_ads_accounts.upsert_many(
        conn, [{"customer_id": customer_id, "mcc_id": "0000000000", "descriptive_name": "G"}]
    )


async def _conta_meta(conn: asyncpg.Connection, ad_account_id: str) -> None:
    await meta_ad_accounts.upsert_many(
        conn, [{"ad_account_id": ad_account_id, "business_id": "bm", "account_name": "M"}]
    )


_GOOGLE = _Lado(
    "google",
    manager_account_access,
    "customer_id",
    "google_ads_accounts",
    "manager_account_access",
    _conta_google,
    ("1111111111", "2222222222", "3333333333"),
)
_META = _Lado(
    "meta",
    manager_meta_account_access,
    "ad_account_id",
    "meta_ad_accounts",
    "manager_meta_account_access",
    _conta_meta,
    ("act_1", "act_2", "act_3"),
)
_LADOS = pytest.mark.parametrize("lado", [_GOOGLE, _META], ids=lambda lado: lado.nome)


async def _conceder(lado: _Lado, conn: asyncpg.Connection, gestor: UUID, conta: str) -> None:
    await lado.criar_conta(conn, conta)
    await lado.repo.grant(conn, manager_id=gestor, granted_by=gestor, **{lado.coluna: conta})


async def _desativar(lado: _Lado, conn: asyncpg.Connection, conta: str) -> None:
    await conn.execute(
        f"UPDATE {lado.inventario} SET is_active = false WHERE {lado.coluna} = $1", conta
    )


@pytest.mark.integration
@_LADOS
async def test_list_live_grants_so_devolve_grant_vivo(db, lado: _Lado) -> None:
    c1, c2, _ = lado.ids
    async with db.acquire() as conn:
        a = await seed_manager(conn)
        b = await seed_manager(conn)
        await _conceder(lado, conn, a, c1)
        await _conceder(lado, conn, b, c1)
        await _conceder(lado, conn, b, c2)
        await lado.repo.revoke(conn, manager_id=b, **{lado.coluna: c2})

        linhas = await lado.repo.list_live_grants(conn)

    assert {(str(r["manager_id"]), r[lado.coluna]) for r in linhas} == {
        (str(a), c1),
        (str(b), c1),
    }


@pytest.mark.integration
@_LADOS
async def test_list_live_grants_for_manager_so_do_gestor_e_vivo(db, lado: _Lado) -> None:
    c1, c2, c3 = lado.ids
    async with db.acquire() as conn:
        a = await seed_manager(conn)
        b = await seed_manager(conn)
        await _conceder(lado, conn, a, c1)
        await _conceder(lado, conn, a, c2)
        await _conceder(lado, conn, a, c3)
        await lado.repo.revoke(conn, manager_id=a, **{lado.coluna: c3})
        await _conceder(lado, conn, b, c3)

        linhas = await lado.repo.list_live_grants_for_manager(conn, a)

    assert {r[lado.coluna] for r in linhas} == {c1, c2}


@pytest.mark.integration
@_LADOS
async def test_list_managers_with_counts_conta_vivo_em_conta_ativa(db, lado: _Lado) -> None:
    """O numerador só conta grant vivo em conta ativa, e o gestor que fica com 0
    continua na lista (LEFT JOIN): sumir dela era o defeito que o filtro no WHERE tinha."""
    c1, c2, c3 = lado.ids
    async with db.acquire() as conn:
        zero = await seed_manager(conn, email="a-zero@v4company.com")
        tres = await seed_manager(conn, email="b-tres@v4company.com")
        inativo = await seed_manager(conn, email="c-inativo@v4company.com")
        await conn.execute("UPDATE managers SET is_active = false WHERE id = $1", inativo)
        for conta in (c1, c2, c3):
            await _conceder(lado, conn, tres, conta)
        await _conceder(lado, conn, zero, c2)
        # grant vivo em conta que saiu do inventário e grant revogado não contam
        await _desativar(lado, conn, c2)
        await lado.repo.revoke(conn, manager_id=tres, **{lado.coluna: c3})

        linhas = await lado.repo.list_managers_with_counts(conn)

    assert [(r["email"], r["access_count"]) for r in linhas] == [
        ("a-zero@v4company.com", 0),
        ("b-tres@v4company.com", 1),
    ]
    assert set(linhas[0].keys()) == {"id", "email", "full_name", "access_count"}


@pytest.mark.integration
@_LADOS
async def test_count_active_accounts_ignora_conta_inativa(db, lado: _Lado) -> None:
    c1, c2, c3 = lado.ids
    async with db.acquire() as conn:
        assert await lado.repo.count_active_accounts(conn) == 0
        for conta in (c1, c2, c3):
            await lado.criar_conta(conn, conta)
        await _desativar(lado, conn, c3)

        assert await lado.repo.count_active_accounts(conn) == 2


@pytest.mark.integration
@_LADOS
async def test_has_live_grant_distingue_vivo_revogado_e_ausente(db, lado: _Lado) -> None:
    c1, c2, _ = lado.ids
    async with db.acquire() as conn:
        a = await seed_manager(conn)
        await _conceder(lado, conn, a, c1)
        await _conceder(lado, conn, a, c2)
        await lado.repo.revoke(conn, manager_id=a, **{lado.coluna: c2})

        assert await lado.repo.has_live_grant(conn, a, c1) is True
        assert await lado.repo.has_live_grant(conn, a, c2) is False
        assert await lado.repo.has_live_grant(conn, a, "9999999999") is False
        assert await lado.repo.has_live_grant(conn, uuid4(), c1) is False


@pytest.mark.integration
async def test_list_invited_with_inviter_so_convite_pendente_do_mais_novo(db) -> None:
    async with db.acquire() as conn:
        admin = await seed_manager(conn, email="admin@v4company.com", role="admin")
        await managers.create_invited(conn, email="velho@v4company.com", invited_by=admin)
        await managers.create_invited(
            conn, email="novo@v4company.com", invited_by=admin, full_name="Novo Gestor"
        )
        aceito = await managers.create_invited(conn, email="aceito@v4company.com", invited_by=admin)
        await managers.mark_active(conn, manager_id=aceito.id)

        linhas = await managers.list_invited_with_inviter(conn)

    assert [r["email"] for r in linhas] == ["novo@v4company.com", "velho@v4company.com"]
    assert {r["invited_by_email"] for r in linhas} == {"admin@v4company.com"}
    assert linhas[0]["full_name"] == "Novo Gestor"
    assert set(linhas[0].keys()) == {"id", "email", "full_name", "invited_at", "invited_by_email"}


@pytest.mark.integration
async def test_email_exists_em_qualquer_status(db) -> None:
    async with db.acquire() as conn:
        admin = await seed_manager(conn, email="admin@v4company.com", role="admin")
        await managers.create_invited(conn, email="convidado@v4company.com", invited_by=admin)

        assert await managers.email_exists(conn, "admin@v4company.com") is True
        assert await managers.email_exists(conn, "convidado@v4company.com") is True
        assert await managers.email_exists(conn, "ninguem@v4company.com") is False


@pytest.mark.integration
async def test_get_email_devolve_o_email_ou_none(db) -> None:
    async with db.acquire() as conn:
        gestor = await seed_manager(conn, email="g@v4company.com")

        assert await managers.get_email(conn, gestor) == "g@v4company.com"
        assert await managers.get_email(conn, uuid4()) is None


@pytest.mark.integration
async def test_list_recent_onboarding_dez_mais_recentes(db) -> None:
    async with db.acquire() as conn:
        admin = await seed_manager(conn, email="m00@v4company.com", role="admin")
        for i in range(1, 12):
            await managers.create_invited(conn, email=f"m{i:02d}@v4company.com", invited_by=admin)

        linhas = await managers.list_recent_onboarding(conn)

    assert len(linhas) == 10
    assert linhas[0]["email"] == "m11@v4company.com"
    assert "m00@v4company.com" not in {r["email"] for r in linhas}
    assert set(linhas[0].keys()) == {"email", "status", "created_at", "invited_at"}


async def _registrar(conn: asyncpg.Connection, gestor: UUID, operacao: str, **kw) -> int:
    return await audit_log.record(
        conn,
        manager_id=gestor,
        session_id=None,
        customer_id=kw.get("customer_id"),
        action_type="read",
        operation=operacao,
    )


@pytest.mark.integration
async def test_top_operations_7d_ordena_por_contagem_e_corta_em_cinco(db) -> None:
    async with db.acquire() as conn:
        g = await seed_manager(conn)
        for operacao, n in [("a", 6), ("b", 5), ("c", 4), ("d", 3), ("e", 2), ("f", 1)]:
            for _ in range(n):
                await _registrar(conn, g, operacao)
        # fora da janela de 7 dias não conta
        await conn.execute(
            "UPDATE audit_log SET occurred_at = now() - interval '8 days' WHERE operation = 'a'"
        )

        linhas = await audit_log.top_operations_7d(conn)

    assert [(r["operation"], r["count"]) for r in linhas] == [
        ("b", 5),
        ("c", 4),
        ("d", 3),
        ("e", 2),
        ("f", 1),
    ]


@pytest.mark.integration
async def test_top_managers_7d_ordena_por_contagem(db) -> None:
    async with db.acquire() as conn:
        muito = await seed_manager(conn, email="muito@v4company.com")
        pouco = await seed_manager(conn, email="pouco@v4company.com")
        for _ in range(3):
            await _registrar(conn, muito, "x")
        await _registrar(conn, pouco, "x")

        linhas = await audit_log.top_managers_7d(conn)

    assert [(r["email"], r["count"]) for r in linhas] == [
        ("muito@v4company.com", 3),
        ("pouco@v4company.com", 1),
    ]


@pytest.mark.integration
async def test_list_recent_for_manager_cinco_ultimas_com_nome_da_conta(db) -> None:
    async with db.acquire() as conn:
        g = await seed_manager(conn)
        outro = await seed_manager(conn)
        await _conta_google(conn, "1111111111")
        for i in range(6):
            await _registrar(conn, g, f"op{i}", customer_id="1111111111" if i == 5 else None)
        await _registrar(conn, outro, "do_outro")

        linhas = await audit_log.list_recent_for_manager(conn, g)

    assert [r["operation"] for r in linhas] == ["op5", "op4", "op3", "op2", "op1"]
    assert linhas[0]["account_name"] == "G"
    assert linhas[1]["account_name"] is None
    assert set(linhas[0].keys()) == {
        "occurred_at",
        "operation",
        "customer_id",
        "status",
        "account_name",
    }


@pytest.mark.integration
async def test_nome_da_conta_do_audit_vale_para_google_e_meta_em_toda_leitura(db) -> None:
    """Fonte unica do nome (G5): Google -> descriptive_name, Meta (`act_...`) ->
    account_name, conta em nenhum inventario -> None (a tela cai no customer_id).
    Cobre as quatro leituras: dashboard, detalhe, pagina do gestor e do admin."""
    async with db.acquire() as conn:
        g = await seed_manager(conn)
        await _conta_google(conn, "1111111111")
        await _conta_meta(conn, "act_222")
        ids = {}
        for cid in ("1111111111", "act_222", "act_sem_cadastro"):
            ids[cid] = await _registrar(conn, g, f"op_{cid}", customer_id=cid)

        recentes = await audit_log.list_recent_for_manager(conn, g)
        pagina, _ = await audit_log.list_page_for_manager(conn, manager_id=g)
        admin, _ = await audit_log.list_page_admin(conn)
        detalhes = {
            cid: await audit_log.get_by_id(conn, audit_id=i, manager_id=g) for cid, i in ids.items()
        }

    esperado = {"1111111111": "G", "act_222": "M", "act_sem_cadastro": None}
    for leitura in (recentes, pagina, admin):
        assert len(leitura) == 3  # o JOIN novo nao multiplica linha
        assert {r["customer_id"]: r["account_name"] for r in leitura} == esperado
    assert {c: d["account_name"] for c, d in detalhes.items()} == esperado


@pytest.mark.integration
async def test_list_for_manager_todas_as_conexoes_a_mais_recente_primeiro(db) -> None:
    async with db.acquire() as conn:
        g = await seed_manager(conn)
        outro = await seed_manager(conn)
        velha = await google_oauth_connections.upsert(
            conn, manager_id=g, google_email="velha@x.com", refresh_token_enc=b"x", scopes=["s"]
        )
        await google_oauth_connections.revoke(conn, velha.id)
        await google_oauth_connections.upsert(
            conn, manager_id=g, google_email="nova@x.com", refresh_token_enc=b"x", scopes=["s"]
        )
        await google_oauth_connections.upsert(
            conn, manager_id=outro, google_email="alheia@x.com", refresh_token_enc=b"x", scopes=[]
        )

        linhas = await google_oauth_connections.list_for_manager(conn, g)

    assert [r["google_email"] for r in linhas] == ["nova@x.com", "velha@x.com"]
    assert linhas[0]["revoked_at"] is None
    assert linhas[1]["revoked_at"] is not None
    assert set(linhas[0].keys()) == {"id", "google_email", "scopes", "connected_at", "revoked_at"}


@pytest.mark.integration
async def test_get_owner_devolve_o_dono_ou_none(db) -> None:
    async with db.acquire() as conn:
        g = await seed_manager(conn)
        c = await google_oauth_connections.upsert(
            conn, manager_id=g, google_email="a@x.com", refresh_token_enc=b"x", scopes=[]
        )

        assert await google_oauth_connections.get_owner(conn, c.id) == g
        assert await google_oauth_connections.get_owner(conn, uuid4()) is None
