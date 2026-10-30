"""Task 18 — os números do painel batem com o dado.

Quota MCP hoje (uma mutação = 1), Gestores ativos / badge (F84), série diária
(zeros nos dias vazios, "Sem dados" quando nada aconteceu) e o dia em
America/Sao_Paulo.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import managers
from src.governance.rate_limit import before_call
from src.web import numeros

_SIGNING_KEY = "x" * 32


def _cookie(manager_id, email):
    return {
        PANEL_SESSION_COOKIE_NAME: sign_panel_session(
            manager_id=str(manager_id), email=email, signing_key=_SIGNING_KEY, aud="panel"
        )
    }


async def _admin(pool, email="adm@v4company.com"):
    async with pool.acquire() as conn:
        mid = uuid4()
        await managers.create(conn, manager_id=mid, email=email, full_name=None, role="admin")
    return mid


async def _audit(conn, manager_id, quando):
    await conn.execute(
        "INSERT INTO audit_log (manager_id, action_type, operation, status, occurred_at) "
        "VALUES ($1, 'read', 'op', 'success', $2)",
        manager_id,
        quando,
    )


def _pontos(html: str) -> list[str]:
    m = re.search(r'<polyline points="([^"]+)"', html)
    assert m, "sem sparkline desenhada"
    return m.group(1).split()


@pytest.mark.integration
async def test_uma_mutacao_conta_um_em_quota_mcp_hoje(client: AsyncClient):
    pool = connection.get_pool()
    admin = await _admin(pool)
    async with pool.acquire() as conn:
        # O que a mutação faz: reserva no token global E no cap do gestor (F73).
        await before_call(conn, "tok-global", estimated_ops=1)
        await before_call(conn, f"mgr:{admin}", estimated_ops=1)

    for url in ("/admin", "/"):
        r = await client.get(url, cookies=_cookie(admin, "adm@v4company.com"))
        assert r.status_code == 200
        assert re.search(r"Quota MCP hoje.*?>\s*1\b(?!\d)", r.text, re.S | re.I), url
        assert not re.search(r"Quota MCP hoje.*?>\s*2\b", r.text, re.S | re.I), url


@pytest.mark.integration
async def test_gestor_com_is_active_false_aparece_inativo_e_sai_dos_ativos(client: AsyncClient):
    pool = connection.get_pool()
    admin = await _admin(pool)
    async with pool.acquire() as conn:
        outro = uuid4()
        await managers.create(
            conn, manager_id=outro, email="fora@v4company.com", full_name=None, role="gestor"
        )
        await managers.mark_active(conn, manager_id=outro)
        # offboarding pelo toggle do painel: escreve só is_active (F84).
        await conn.execute("UPDATE managers SET is_active = false WHERE id = $1", outro)
        assert await conn.fetchval("SELECT status FROM managers WHERE id = $1", outro) == "active"

    ck = _cookie(admin, "adm@v4company.com")
    lista = (await client.get("/admin/managers", cookies=ck)).text
    linha = re.search(r"<tr[^>]*>(?:(?!</tr>).)*fora@v4company\.com.*?</tr>", lista, re.S)
    assert linha
    assert 'data-status="inactive"' in linha.group(0)
    assert "Desativado" in linha.group(0)
    assert "Ativo<" not in linha.group(0)

    # Gestores ativos: só o admin (1 / 2), nos dois lugares que mostram o número.
    for url in ("/admin", "/"):
        r = await client.get(url, cookies=ck)
        assert re.search(r"Gestores ativos.*?>\s*1\s*(?:<span[^>]*>)?\s*/\s*2", r.text, re.S), url


@pytest.mark.integration
async def test_serie_de_30_dias_tem_zeros_nos_dias_vazios_e_um_dia_desenha(client: AsyncClient):
    pool = connection.get_pool()
    admin = await _admin(pool)
    ck = _cookie(admin, "adm@v4company.com")

    vazio = (await client.get("/admin", cookies=ck)).text
    assert "Sem dados ainda." in vazio

    async with pool.acquire() as conn:
        await _audit(conn, admin, datetime.now(UTC) - timedelta(hours=1))
    com_um_dia = (await client.get("/admin", cookies=ck)).text
    assert "Sem dados ainda." not in com_um_dia
    assert len(_pontos(com_um_dia)) == 30


@pytest.mark.integration
async def test_dia_do_painel_e_o_de_sao_paulo(client: AsyncClient):
    pool = connection.get_pool()
    admin = await _admin(pool)
    hoje = numeros.dias_do_painel(1)[0]
    meia_noite = numeros.inicio_do_dia(hoje)
    async with pool.acquire() as conn:
        # 1h antes da meia-noite de SP: ainda é "ontem" aqui, mesmo que em UTC
        # já seja o dia de hoje (SP = UTC-3).
        await _audit(conn, admin, meia_noite - timedelta(hours=1))
        ontem_e_hoje = await numeros.contagem_por_dia(conn, [hoje - timedelta(days=1), hoje])
        assert ontem_e_hoje == [1, 0]

        await _audit(conn, admin, meia_noite + timedelta(minutes=1))
        assert await numeros.contagem_por_dia(conn, [hoje - timedelta(days=1), hoje]) == [1, 1]
        # E o filtro por gestor
        assert await numeros.contagem_por_dia(conn, [hoje], manager_id=uuid4()) == [0]

    # "Chamadas hoje" do dashboard lê a mesma série: só a de depois da meia-noite.
    r = await client.get("/", cookies=_cookie(admin, "adm@v4company.com"))
    assert re.search(r"Chamadas hoje.*?v4-stat__value\">\s*1\s*<", r.text, re.S | re.I)
