"""F91: reincidencia da classe F76 — `pool.acquire()` cru em reads quentes.

asyncpg NAO faz pre-ping. O Cloud Run mantem conexoes ociosas, o Supabase fecha
o socket, e a proxima query pega a conexao morta: `ConnectionDoesNotExistError`
na PREPARACAO do statement. O painel e de baixo trafego, entao este e o cenario
exato do F76 — o primeiro acesso da manha vira 500.

Dois grupos de call-site sobraram depois do F76/F77:
  (a) `src/web/deps.py` — roda a CADA page-load do painel;
  (b) o gate `ensure_account_access` a cada request MCP, mais o read de OAuth
      em `client.py` e o gate Meta em `meta_ads/reports.py`.

Todos sao reads pre-operacao, seguros de re-executar — o contrato exato de
`run_with_reconnect`, e o "Don't" ja declarado no CLAUDE.md.

A tecnica de cada teste: a 1a chamada levanta o erro de producao, a 2a devolve
o resultado normal. Sem o wrap, o erro de conexao escapa; com ele, o resultado
da 2a tentativa e o que sai. E o mesmo `_FakePool` de `test_db_connection.py`,
que conta acquires pra provar que a conexao nova e de fato NOVA.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest

from src.db import connection


class _FakeAcquire:
    def __init__(self, conn: object) -> None:
        self._conn = conn

    async def __aenter__(self) -> object:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    """Entrega conexoes em sequencia e conta acquires (fresh-acquire no retry)."""

    def __init__(self, quantas: int = 4) -> None:
        self._conns = [object() for _ in range(quantas)]
        self.acquires = 0

    def acquire(self) -> _FakeAcquire:
        conn = self._conns[self.acquires]
        self.acquires += 1
        return _FakeAcquire(conn)


def _derruba_a_primeira(resultado: Any) -> AsyncMock:
    """1a chamada = conexao morta (falha na PREPARACAO); 2a = sucesso."""
    return AsyncMock(
        side_effect=[
            asyncpg.exceptions.ConnectionDoesNotExistError(
                "connection was closed in the middle of operation"
            ),
            resultado,
        ]
    )


class _FakeRequest:
    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies


def _cookie_valido(manager_id: Any) -> dict[str, str]:
    from src.auth.panel_session import sign_panel_session
    from src.config import get_settings

    return {
        "v4_panel_session": sign_panel_session(
            manager_id=str(manager_id),
            email="gestor@v4company.com",
            signing_key=get_settings().session_signing_key,
        )
    }


def _manager_ativo(manager_id: Any) -> Any:
    from src.db.repositories.managers import Manager

    return Manager(
        id=manager_id,
        email="gestor@v4company.com",
        full_name="Gestor",
        role="member",
        status="active",
        is_active=True,
        created_at=None,
        last_seen_at=None,
        invited_by=None,
        invited_at=None,
    )


# --- (a) painel: roda a cada page-load ---------------------------------------


@pytest.mark.asyncio
async def test_current_manager_sobrevive_a_conexao_morta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F91: sem isto, o 1o acesso da manha ao painel e um 500."""
    from src.web import deps

    pool = _FakePool()
    monkeypatch.setattr(connection, "_pool", pool)
    mid = uuid4()

    with patch.object(deps.managers, "get_by_id", _derruba_a_primeira(_manager_ativo(mid))):
        user = await deps.current_manager(_FakeRequest(_cookie_valido(mid)))  # type: ignore[arg-type]

    assert user.id == mid
    assert pool.acquires == 2, "o retry tem que pegar uma conexao NOVA"


@pytest.mark.asyncio
async def test_optional_current_manager_sobrevive_a_conexao_morta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F91: mesma rota, versao que nao exige login (header, paginas publicas)."""
    from src.web import deps

    monkeypatch.setattr(connection, "_pool", _FakePool())
    mid = uuid4()

    with patch.object(deps.managers, "get_by_id", _derruba_a_primeira(_manager_ativo(mid))):
        user = await deps.optional_current_manager(_FakeRequest(_cookie_valido(mid)))  # type: ignore[arg-type]

    assert user is not None and user.id == mid


@pytest.mark.asyncio
async def test_pending_invites_count_sobrevive_a_conexao_morta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F91: badge da subnav admin — 11 rotas o chamam."""
    from src.db.repositories import managers as managers_repo
    from src.web import deps

    monkeypatch.setattr(connection, "_pool", _FakePool())

    with patch.object(managers_repo, "count_invited", _derruba_a_primeira(3)):
        assert await deps.pending_invites_count() == 3


# --- (b) MCP: roda a cada request --------------------------------------------


@pytest.mark.asyncio
async def test_gate_do_run_report_sobrevive_a_conexao_morta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F91: o hard-gate abre conexao ANTES de qualquer trabalho, a cada request.

    A 2a tentativa levanta `AccountAccessDeniedError` de proposito: se ela sair,
    o retry aconteceu; se sair o erro de conexao, nao aconteceu. Isso testa o
    wrap sem precisar mockar o executor inteiro.
    """
    from src.google_ads import reports
    from src.google_ads.access import AccountAccessDeniedError

    monkeypatch.setattr(connection, "_pool", _FakePool())

    gate = AsyncMock(
        side_effect=[
            asyncpg.exceptions.ConnectionDoesNotExistError("dead"),
            AccountAccessDeniedError("sem acesso"),
        ]
    )
    with (
        patch.object(reports, "ensure_account_access", gate),
        pytest.raises(AccountAccessDeniedError),
    ):
        await reports.run_report(
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="9999999999",
            query="SELECT 1",
            row_formatter=lambda r: {},
            operation_name="test_op",
        )

    assert gate.await_count == 2, "o gate nao foi re-executado numa conexao nova"


@pytest.mark.asyncio
async def test_read_de_oauth_do_client_sobrevive_a_conexao_morta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F91: todo executor Google passa por aqui pra montar o client."""
    from src.db.repositories import google_oauth_connections
    from src.google_ads.client import NoOAuthConnectionError, build_client_for_manager

    monkeypatch.setattr(connection, "_pool", _FakePool())

    # 2a tentativa devolve None -> NoOAuthConnectionError prova que houve retry.
    with (
        patch.object(google_oauth_connections, "get_active_for_manager", _derruba_a_primeira(None)),
        pytest.raises(NoOAuthConnectionError),
    ):
        await build_client_for_manager(manager_id=uuid4())


@pytest.mark.asyncio
async def test_gate_meta_sobrevive_a_conexao_morta(monkeypatch: pytest.MonkeyPatch) -> None:
    """F91: no Modelo B a matriz e o UNICO freio — ela nao pode cair por socket."""
    from src.db.repositories import manager_meta_account_access
    from src.meta_ads import reports as meta_reports
    from src.meta_ads.reports import MetaAccessDeniedError

    monkeypatch.setattr(connection, "_pool", _FakePool())

    with (
        patch.object(manager_meta_account_access, "can_manager_access", _derruba_a_primeira(False)),
        patch.object(meta_reports.audit_log, "record", AsyncMock()),
        pytest.raises(MetaAccessDeniedError),
    ):
        await meta_reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_123",
            edge="insights",
            params={},
            operation_name="test_meta_op",
        )


# --- o risco que o proprio fix introduz --------------------------------------


@pytest.mark.asyncio
async def test_audit_de_negacao_nao_e_retentado(monkeypatch: pytest.MonkeyPatch) -> None:
    """F91: envolver o gate em retry poderia re-executar uma ESCRITA.

    O gate e read + (no caminho de negacao) um INSERT de audit. Como o wrap
    reexecuta a operacao inteira, uma falha de conexao no INSERT faria o retry
    gravar a negacao duas vezes — "mutacao NAO leva retry cego" (CLAUDE.md).
    `best_effort` mantem o retry restrito ao read: a falha do audit vira log,
    nao excecao, e a negacao segue chegando ao gestor.
    """
    from src.db.repositories import audit_log, google_ads_accounts, manager_account_access
    from src.google_ads import access

    monkeypatch.setattr(connection, "_pool", _FakePool())
    conn = object()
    escritas = {"n": 0}

    async def audit_que_cai(*a: Any, **k: Any) -> None:
        escritas["n"] += 1
        raise asyncpg.exceptions.ConnectionDoesNotExistError("dead")

    with (
        patch.object(manager_account_access, "can_manager_access", AsyncMock(return_value=False)),
        patch.object(audit_log, "record", audit_que_cai),
        # Item 2 (revisão final): a escolha de mensagem no caminho de negação
        # faz mais uma leitura (`get_by_customer_id`) — `conn` aqui é um
        # `object()` propositalmente vazio (só prova que o retry não chama
        # nada nele), então sem este patch a leitura estouraria AttributeError
        # em vez do AccountAccessDeniedError que o teste espera.
        patch.object(
            google_ads_accounts,
            "get_by_customer_id",
            AsyncMock(return_value=MagicMock(is_active=True)),
        ),
        pytest.raises(access.AccountAccessDeniedError),
    ):
        await connection.run_with_reconnect(
            lambda _c: access.ensure_account_access(
                conn,  # type: ignore[arg-type]
                manager_id=uuid4(),
                customer_id="9999999999",
                session_id=uuid4(),
                operation_name="op",
            )
        )

    assert escritas["n"] == 1, "o INSERT de audit foi re-executado pelo retry"


@pytest.mark.asyncio
async def test_audit_de_negacao_meta_nao_e_retentado(monkeypatch: pytest.MonkeyPatch) -> None:
    """F91: mesmo invariante no lado Meta, onde o read e o write foram separados."""
    from src.db.repositories import manager_meta_account_access
    from src.meta_ads import reports as meta_reports
    from src.meta_ads.reports import MetaAccessDeniedError

    monkeypatch.setattr(connection, "_pool", _FakePool())
    escritas = {"n": 0}

    async def audit_que_cai(*a: Any, **k: Any) -> None:
        escritas["n"] += 1
        raise asyncpg.exceptions.ConnectionDoesNotExistError("dead")

    with (
        patch.object(
            manager_meta_account_access, "can_manager_access", AsyncMock(return_value=False)
        ),
        patch.object(meta_reports.audit_log, "record", audit_que_cai),
        pytest.raises(MetaAccessDeniedError),
    ):
        await meta_reports.run_meta_graph_get(
            manager_id=uuid4(),
            session_id=uuid4(),
            ad_account_id="act_123",
            edge="insights",
            params={},
            operation_name="test_meta_op",
        )

    assert escritas["n"] == 1, "o INSERT de audit foi re-executado pelo retry"
