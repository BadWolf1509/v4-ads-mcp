"""`days` dos dois exports CSV do audit tem teto.

Item 4 do relatorio de DB da varredura de 21/09
(`docs/_archive/varredura-2026-09-21/05-db-e-migrations.md`): `days: int = 7`
sem limite em `/audit/export.csv` — alcancavel por gestor nao-admin — e em
`/admin/audit/export.csv`. `days=100000` virava export da tabela inteira.

Teto de 365: o export e trilha de compliance, e um ano cobre a historia inteira
do `audit_log`. O seletor do painel vai ate 90 dias, mas nao e ele que limita a
rota — a URL aceita o que vier.

A armadilha deste teste: `current_manager` e resolvido ANTES da validacao da
query. Sem sessao, a rota devolve 302 pra /login e nunca chega ao 422 — um teste
sem gestor autenticado ficaria verde sem afirmar nada. Por isso o override, e por
isso a recusa afirma o `loc` do erro, nao so o status.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.db.repositories.managers import Manager
from src.web.deps import CurrentUser, current_manager

ROTAS = ["/audit/export.csv", "/admin/audit/export.csv"]


def _admin() -> CurrentUser:
    # Admin passa pelas duas rotas: `/admin/audit/export.csv` chama `_require_admin`.
    return CurrentUser(
        Manager(
            id=uuid4(),
            email="admin@v4company.com",
            full_name="Admin",
            role="admin",
            is_active=True,
            created_at=datetime.now(UTC),
            last_seen_at=None,
            status="active",
            invited_by=None,
            invited_at=None,
        )
    )


@pytest.fixture
async def gestor_client() -> AsyncIterator[AsyncClient]:
    from src.app import create_app

    app = create_app(skip_db_init=True)
    app.dependency_overrides[current_manager] = _admin
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("rota", ROTAS)
@pytest.mark.parametrize("days", [0, 366, 100000])
async def test_days_fora_do_teto_e_recusado(
    gestor_client: AsyncClient, rota: str, days: int
) -> None:
    resp = await gestor_client.get(rota, params={"days": days})
    assert resp.status_code == 422
    # O 422 tem que ser POR CAUSA do `days` — nao de outro parametro, nem de auth.
    assert [e["loc"] for e in resp.json()["detail"]] == [["query", "days"]]


class _Pool:
    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        yield MagicMock()


@pytest.mark.parametrize("rota", ROTAS)
async def test_days_no_teto_chega_ao_export(gestor_client: AsyncClient, rota: str) -> None:
    """Controle: o teto nao pode recusar o proprio teto, e o valor tem que CHEGAR
    a quem consulta — senao a recusa acima poderia ser "recusa tudo"."""
    recebido: list[int] = []

    async def _linhas(*_: Any, **kwargs: Any) -> AsyncIterator[str]:
        recebido.append(kwargs["days"])
        yield "occurred_at,operation\n"

    with (
        patch("src.db.connection.get_pool", return_value=_Pool()),
        patch("src.db.repositories.audit_log.export_csv_rows", _linhas),
    ):
        resp = await gestor_client.get(rota, params={"days": 365})

    assert resp.status_code == 200
    assert resp.text.startswith("occurred_at")
    assert recebido == [365]
