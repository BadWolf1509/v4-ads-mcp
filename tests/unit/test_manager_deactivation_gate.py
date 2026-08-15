"""F84: `status` e `is_active` divergem, e os gates de sessao liam so uma delas.

As duas colunas podem divergir e NADA no codigo as sincroniza:
- o toggle do painel faz `UPDATE managers SET is_active = NOT is_active` e nunca
  toca em `status`;
- nenhum codigo escreve `status='inactive'` (so `mark_active`, invited->active).

O gate de LOGIN checava as duas (`status == "active" and is_active`, com
fallthrough explicito pra negar em `status == "inactive" OR is_active=False`).
Os gates de SESSAO VIVA — MCP e painel — checavam so `is_active`.

Cenario concreto: offboarding feito por SQL direto marcando `status='inactive'`
(o unico caminho existente, ja que a UI nao escreve essa coluna) bloqueava o
login mas deixava TODO Bearer MCP do gestor funcionando ate expirar — TTL padrao
de 90 dias — e o cookie do painel valido por ate 24h. A coluna que a UI de admin
exibe nao era a que o gate do MCP lia.

Os testes usam o dataclass REAL `Manager`, nao um fake com um campo so: fake que
nao carrega as duas colunas nao consegue nem expressar a divergencia (licao de
fidelidade de mock, familia F16/F48/F89).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.db.repositories.managers import Manager
from src.mcp.session import UnauthorizedError


def make_manager(*, is_active: bool = True, status: str = "active") -> Manager:
    """Manager REAL com as duas colunas controlaveis."""
    return Manager(
        id=uuid4(),
        email="gestor@v4company.com",
        full_name="Gestor",
        role="gestor",
        is_active=is_active,
        created_at=datetime.now(UTC),
        last_seen_at=None,
        status=status,
        invited_by=None,
        invited_at=None,
    )


# --------------------------------------------------------------------------
# O predicado unico
# --------------------------------------------------------------------------


def test_is_active_false_conta_como_desativado() -> None:
    assert make_manager(is_active=False, status="active").is_deactivated is True


def test_status_inactive_conta_como_desativado_mesmo_com_is_active_true() -> None:
    """F84 — o caso que vazava: offboarding por SQL setava so `status`."""
    assert make_manager(is_active=True, status="inactive").is_deactivated is True


def test_gestor_normal_nao_e_desativado() -> None:
    assert make_manager(is_active=True, status="active").is_deactivated is False


def test_invited_nao_e_tratado_como_desativado() -> None:
    """`invited` e estado de onboarding, nao de bloqueio.

    O gate de login promove invited->active; bloquear aqui quebraria esse fluxo.
    So `inactive` bloqueia.
    """
    assert make_manager(is_active=True, status="invited").is_deactivated is False


# --------------------------------------------------------------------------
# Gate do MCP (o que mantinha o Bearer vivo por ate 90 dias)
# --------------------------------------------------------------------------


def _pool_mock() -> MagicMock:
    pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=MagicMock())
    cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = cm
    return pool


@pytest.mark.asyncio
async def test_sessao_mcp_negada_quando_status_inactive() -> None:
    """F84: Bearer de gestor offboardado por SQL tem que morrer na resolucao."""
    from src.mcp.session import resolve_session_to_context

    sessao = MagicMock(id=uuid4(), manager_id=uuid4())
    gestor = make_manager(is_active=True, status="inactive")

    with (
        patch("src.mcp.session.connection.get_pool", return_value=_pool_mock()),
        patch("src.mcp.session.mcp_sessions.find_by_hash", AsyncMock(return_value=sessao)),
        patch("src.mcp.session.managers.get_by_id", AsyncMock(return_value=gestor)),
        pytest.raises(UnauthorizedError, match="inactive"),
    ):
        await resolve_session_to_context("Bearer sometoken")


@pytest.mark.asyncio
async def test_sessao_mcp_permitida_para_gestor_ativo() -> None:
    """Regressao: fechar o buraco nao pode derrubar quem esta em ordem."""
    from src.mcp.session import resolve_session_to_context

    sessao = MagicMock(id=uuid4(), manager_id=uuid4())
    gestor = make_manager(is_active=True, status="active")

    with (
        patch("src.mcp.session.connection.get_pool", return_value=_pool_mock()),
        patch("src.mcp.session.mcp_sessions.find_by_hash", AsyncMock(return_value=sessao)),
        patch("src.mcp.session.managers.get_by_id", AsyncMock(return_value=gestor)),
        patch("src.mcp.session.mcp_sessions.touch_last_used", AsyncMock()),
        patch("src.mcp.session.managers.touch_last_seen", AsyncMock()),
    ):
        ctx = await resolve_session_to_context("Bearer sometoken")

    assert ctx.manager_id == sessao.manager_id


# --------------------------------------------------------------------------
# Gate do painel
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_painel_nega_gestor_com_status_inactive() -> None:
    """F84: o cookie do painel valia ate 24h no mesmo cenario."""
    from fastapi import HTTPException

    from src.web import deps

    gestor = make_manager(is_active=True, status="inactive")

    with (
        patch.object(
            deps, "_resolve_session", AsyncMock(return_value=MagicMock(manager_id=str(uuid4())))
        ),
        patch.object(deps.connection, "get_pool", return_value=_pool_mock()),
        patch.object(deps.managers, "get_by_id", AsyncMock(return_value=gestor)),
        pytest.raises(HTTPException) as exc,
    ):
        await deps.current_manager(MagicMock())

    assert exc.value.status_code == 302


@pytest.mark.asyncio
async def test_login_nega_convidado_desativado_antes_de_promover() -> None:
    """F84 no gate de LOGIN: o branch `invited` lia só `status`.

    `create_invited` grava `is_active=true`, mas o toggle do painel funciona em
    qualquer gestor — inclusive num convite pendente. Nesse estado
    (status='invited', is_active=False) o branch de convite disparava ANTES da
    checagem de desativação: a pessoa logava e era promovida a 'active', pra
    então bater em porta fechada no primeiro page-load. A desativação tem que
    ser avaliada primeiro.
    """
    from src.auth.oauth import handle_callback_decision

    decisao = await handle_callback_decision(
        email="convidado@v4company.com",
        google_id="g1",
        google_email="convidado@v4company.com",
        existing_manager={"id": uuid4(), "status": "invited", "is_active": False},
        managers_table_empty=False,
        bootstrap_emails=set(),
    )

    assert decisao.kind == "redirect"
    assert "deactivated" in decisao.location


@pytest.mark.asyncio
async def test_painel_opcional_devolve_none_para_status_inactive() -> None:
    from src.web import deps

    gestor = make_manager(is_active=True, status="inactive")

    with (
        patch.object(
            deps, "_resolve_session", AsyncMock(return_value=MagicMock(manager_id=str(uuid4())))
        ),
        patch.object(deps.connection, "get_pool", return_value=_pool_mock()),
        patch.object(deps.managers, "get_by_id", AsyncMock(return_value=gestor)),
    ):
        assert await deps.optional_current_manager(MagicMock()) is None
