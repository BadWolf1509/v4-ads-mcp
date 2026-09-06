"""Tests for the admin CLI commands (Task 2.3 + extension).

`create-manager` creates an active manager with zero account grants — used to
seed a "smoke" manager for the authenticated MCP deploy smoke test.

Extension (task 3.6): 1 caso por comando restante — `bootstrap-admin`,
`grant-all`, `create-session`, `list-sessions`. É a ferramenta de recuperação
de emergência (lição 2026-06-19: conta admin excluída exigiu re-sync via este
CLI) — cobertura direta reduz o risco de regressão silenciosa num caminho que
só roda "quando tudo mais já quebrou".
"""

import argparse
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from _pytest.monkeypatch import MonkeyPatch
from testcontainers.postgres import PostgresContainer

from src.auth.oauth_state import verify_state
from src.auth.sessions import hash_session_token
from src.db import connection, migrate
from src.db.repositories import google_ads_accounts, manager_account_access, managers, mcp_sessions
from src.scripts.admin import (
    cmd_bootstrap_admin,
    cmd_create_manager,
    cmd_create_session,
    cmd_grant_all,
    cmd_invite,
    cmd_list_sessions,
)
from tests.integration._audiencia import audiencia_crua
from tests.integration.conftest import _clone_db

_SIGNING_KEY = "x" * 32

# Este teste precisa do DSN cru (não do pool já aberto): cmd_create_manager faz
# seu próprio ciclo init_pool()/close_pool() via get_settings().database_url,
# então a fixture aqui só clona um banco do template (via helper do conftest)
# e expõe o DSN — sem manter pool aberto entre chamadas.


@pytest.fixture
async def dsn(pg: PostgresContainer) -> AsyncIterator[str]:
    async with _clone_db(pg) as db_dsn:
        yield db_dsn


@pytest.fixture(autouse=True)
def _env(dsn: str, monkeypatch: MonkeyPatch) -> None:
    # cmd_create_manager reads settings.database_url via get_settings(); point it
    # at the testcontainer so the CLI's own init_pool()/close_pool() cycle works.
    monkeypatch.setenv("DATABASE_URL", dsn)


@pytest.fixture
async def migrated(dsn: str) -> AsyncIterator[None]:
    """Run migrations once, then leave the pool closed for the CLI to own."""
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        await migrate.run_all()
        yield
    finally:
        await connection.close_pool()


def _args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {"email": "smoke@v4company.com", "name": None}
    return argparse.Namespace(**{**defaults, **overrides})


@pytest.mark.integration
async def test_create_manager_active_no_grants(migrated: None, dsn: str) -> None:
    """First call creates an active manager with no account grants."""
    rc = await cmd_create_manager(_args(name="Smoke Test"))
    assert rc == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, "smoke@v4company.com")
            assert m is not None
            assert m.status == "active"
            assert m.is_active is True
            assert m.role == "gestor"
            assert m.full_name == "Smoke Test"

            grants = await conn.fetchval(
                "SELECT count(*) FROM manager_account_access WHERE manager_id = $1", m.id
            )
            assert grants == 0
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_create_manager_idempotent(migrated: None, dsn: str) -> None:
    """Second call for the same email does not duplicate the row."""
    rc1 = await cmd_create_manager(_args())
    assert rc1 == 0

    rc2 = await cmd_create_manager(_args())
    assert rc2 == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM managers WHERE email = $1", "smoke@v4company.com"
            )
            assert count == 1
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_bootstrap_admin_creates_admin_manager(migrated: None, dsn: str) -> None:
    """First call: no manager exists for the email -> creates a NEW row with role=admin."""
    args = argparse.Namespace(email="root@v4company.com", name="Root Admin")
    rc = await cmd_bootstrap_admin(args)
    assert rc == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, "root@v4company.com")
            assert m is not None
            assert m.role == "admin"
            assert m.is_active is True
            assert m.full_name == "Root Admin"
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_bootstrap_admin_promotes_existing_gestor_to_admin(migrated: None, dsn: str) -> None:
    """Manager já existe como 'gestor' -> segunda chamada PROMOVE pra admin (idempotente,
    não duplica linha). Runbook de recuperação de emergência: role virou 'gestor' por
    engano ou o admin original foi excluído (lição 2026-06-19) -- re-promover via CLI
    sem precisar de acesso de admin prévio no painel."""
    # Cria como gestor comum primeiro (simula manager pré-existente).
    rc1 = await cmd_create_manager(argparse.Namespace(email="promote@v4company.com", name=None))
    assert rc1 == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            before = await managers.get_by_email(conn, "promote@v4company.com")
            assert before is not None
            assert before.role == "gestor"
    finally:
        await connection.close_pool()

    rc2 = await cmd_bootstrap_admin(
        argparse.Namespace(email="promote@v4company.com", name="Ignored Name")
    )
    assert rc2 == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            after = await managers.get_by_email(conn, "promote@v4company.com")
            count = await conn.fetchval(
                "SELECT count(*) FROM managers WHERE email = $1", "promote@v4company.com"
            )
        assert after is not None
        assert after.role == "admin"
        assert after.is_active is True
        assert count == 1  # não duplicou a linha
    finally:
        await connection.close_pool()


@pytest.mark.integration
async def test_grant_all_grants_access_to_active_accounts(migrated: None, dsn: str) -> None:
    """grant-all concede acesso 'write' a todo google_ads_accounts com is_active=true;
    chamadas repetidas não duplicam grants (ON CONFLICT DO NOTHING no repo)."""
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.create(
                conn,
                manager_id=uuid4(),
                email="grantee@v4company.com",
                full_name=None,
            )
            manager_id = m.id
            await google_ads_accounts.upsert_many(
                conn,
                [
                    {
                        "customer_id": "1112223330",
                        "mcc_id": "6436352492",
                        "descriptive_name": "Conta Teste 1",
                    },
                    {
                        "customer_id": "4445556660",
                        "mcc_id": "6436352492",
                        "descriptive_name": "Conta Teste 2",
                    },
                ],
            )
    finally:
        await connection.close_pool()

    rc = await cmd_grant_all(argparse.Namespace(email="grantee@v4company.com"))
    assert rc == 0

    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            granted = await manager_account_access.list_accounts_for_manager(conn, manager_id)
    finally:
        await connection.close_pool()
    assert {g.customer_id for g in granted} == {"1112223330", "4445556660"}

    # Segunda chamada não deve duplicar (ON CONFLICT DO NOTHING) nem falhar.
    rc2 = await cmd_grant_all(argparse.Namespace(email="grantee@v4company.com"))
    assert rc2 == 0
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            granted_again = await manager_account_access.list_accounts_for_manager(conn, manager_id)
    finally:
        await connection.close_pool()
    assert len(granted_again) == 2


@pytest.mark.integration
async def test_grant_all_manager_not_found_returns_error_code(migrated: None, dsn: str) -> None:
    """Email sem manager correspondente -> rc=1 (não crasha), sem criar grants órfãos."""
    rc = await cmd_grant_all(argparse.Namespace(email="ghost@v4company.com"))
    assert rc == 1


@pytest.mark.integration
async def test_create_session_issues_a_findable_bearer_token(migrated: None, dsn: str) -> None:
    """create-session gera um token cujo HASH bate no DB (find_by_hash) -- valida
    o mesmo caminho que a UI /sessions usa pra emitir Bearers."""
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            await managers.create(
                conn,
                manager_id=uuid4(),
                email="sessionholder@v4company.com",
                full_name=None,
            )
    finally:
        await connection.close_pool()

    rc = await cmd_create_session(
        argparse.Namespace(email="sessionholder@v4company.com", label="Claude Desktop", ttl_days=90)
    )
    assert rc == 0

    # cmd_create_session printou o token em texto puro (só aparece 1x) --
    # não temos como capturá-lo daqui sem mockar stdout, então validamos
    # indiretamente: exatamente 1 sessão não-revogada foi criada com o label certo.
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, "sessionholder@v4company.com")
            assert m is not None
            sessions = await mcp_sessions.list_for_manager(conn, m.id)
    finally:
        await connection.close_pool()
    assert len(sessions) == 1
    assert sessions[0].label == "Claude Desktop"
    assert sessions[0].revoked_at is None
    assert sessions[0].expires_at is not None


@pytest.mark.integration
async def test_create_session_manager_not_found_returns_error_code(
    migrated: None, dsn: str
) -> None:
    rc = await cmd_create_session(
        argparse.Namespace(email="nosuchmanager@v4company.com", label="x", ttl_days=90)
    )
    assert rc == 1


@pytest.mark.integration
async def test_list_sessions_shows_only_non_revoked_by_default(
    migrated: None, dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """list-sessions imprime as sessões ativas do gestor; revogadas ficam de fora
    a menos que --all seja passado."""
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.create(
                conn,
                manager_id=uuid4(),
                email="listsessions@v4company.com",
                full_name=None,
            )
            active_sess = await mcp_sessions.create(
                conn,
                manager_id=m.id,
                token_hash=hash_session_token("token-active"),
                label="Ativa",
            )
            revoked_sess = await mcp_sessions.create(
                conn,
                manager_id=m.id,
                token_hash=hash_session_token("token-revoked"),
                label="Revogada",
            )
            await mcp_sessions.revoke(conn, revoked_sess.id)
    finally:
        await connection.close_pool()

    rc = await cmd_list_sessions(argparse.Namespace(email="listsessions@v4company.com", all=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ativa" in out
    assert "Revogada" not in out
    assert str(active_sess.id) in out


@pytest.mark.integration
async def test_list_sessions_with_all_flag_includes_revoked(
    migrated: None, dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.create(
                conn,
                manager_id=uuid4(),
                email="listsessionsall@v4company.com",
                full_name=None,
            )
            revoked_sess = await mcp_sessions.create(
                conn,
                manager_id=m.id,
                token_hash=hash_session_token("token-revoked-2"),
                label="RevogadaTambemLista",
            )
            await mcp_sessions.revoke(conn, revoked_sess.id)
    finally:
        await connection.close_pool()

    rc = await cmd_list_sessions(
        argparse.Namespace(email="listsessionsall@v4company.com", all=True)
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "RevogadaTambemLista" in out


@pytest.mark.integration
async def test_list_sessions_no_sessions_prints_placeholder(
    migrated: None, dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            await managers.create(
                conn,
                manager_id=uuid4(),
                email="nosessions@v4company.com",
                full_name=None,
            )
    finally:
        await connection.close_pool()

    rc = await cmd_list_sessions(argparse.Namespace(email="nosessions@v4company.com", all=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "(no sessions)" in out


def _convite_da_saida(saida: str) -> str:
    """Extrai o `?invite=` da URL que o comando imprime."""
    for linha in saida.splitlines():
        if "invite=" in linha:
            convites = parse_qs(urlparse(linha.strip()).query).get("invite") or []
            assert len(convites) == 1, f"esperava um `invite` na URL, achei {convites!r}"
            return convites[0]
    raise AssertionError(f"nenhuma URL com `invite=` na saída: {saida!r}")


@pytest.mark.integration
async def test_invite_assina_convite_com_audiencia_cli_invite(
    migrated: None, dsn: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """`invite` assina o token conferido pelo `/oauth/google/start` (`admin.py:102`).

    Nada prendia este lado — não havia teste de `cmd_invite`. Uma troca entre
    dois valores VÁLIDOS do `Literal` aqui (`"panel"` ou `"google_oauth"` no
    lugar de `"cli_invite"`) passa no `mypy --strict` e passava na suíte
    inteira: o convite só falharia na mão do gestor, no primeiro clique.

    A claim é lida do CORPO do token porque `verify_state` a remove do payload
    devolvido — ela só responde "casa com a que pedi", não diz o que foi escrito.
    """
    rc_criar = await cmd_create_manager(_args(email="convidado@v4company.com"))
    assert rc_criar == 0

    rc = await cmd_invite(
        argparse.Namespace(email="convidado@v4company.com", base_url="https://painel.exemplo/")
    )
    assert rc == 0

    convite = _convite_da_saida(capsys.readouterr().out)
    assert audiencia_crua(convite) == "cli_invite"

    # E o par fecha: o `/start` (único consumidor) aceita o que este lado assinou.
    await connection.init_pool(dsn, min_size=1, max_size=4)
    try:
        pool = connection.get_pool()
        async with pool.acquire() as conn:
            m = await managers.get_by_email(conn, "convidado@v4company.com")
    finally:
        await connection.close_pool()
    assert m is not None
    assert verify_state(convite, _SIGNING_KEY, aud="cli_invite") == {"manager_id": str(m.id)}
