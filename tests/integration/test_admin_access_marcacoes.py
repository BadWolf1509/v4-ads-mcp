"""Matriz e detalhe de acesso marcam EXATAMENTE os grants vivos, nas duas plataformas.

Rede da T5.3 (15/11), escrita antes de as rotas gêmeas virarem helper por tipo.
Os testes que já existiam conferem só a AUSÊNCIA de `checked` (grant revogado
não aparece) — e uma chave de `access_set` errada (coluna de outra plataforma,
tupla na ordem trocada) também deixa a página sem `checked` nenhum, passando
calada. Aqui a página tem de marcar o par concedido e só ele, com a leitura
real do banco (o snapshot de `tests/unit/test_acesso_templates_snapshot.py`
troca a leitura por dados fixos e não cobre o `_load`).
"""

import re
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.auth.panel_session import PANEL_SESSION_COOKIE_NAME, sign_panel_session
from src.db import connection
from src.db.repositories import (
    google_ads_accounts,
    manager_account_access,
    manager_meta_account_access,
    managers,
    meta_ad_accounts,
)

_SIGNING_KEY = "x" * 32
_CHECKBOX = re.compile(
    r'<input type="checkbox"\s+aria-labelledby="v4-mgr-(?P<mgr>\S+) v4-acc-(?P<conta>\S+)"'
    r"\s+(?P<checked>checked)?"
)


async def _semear(plataforma: str) -> tuple[UUID, UUID, UUID, list[str]]:
    """Admin, dois gestores, duas contas; o gestor A recebe a primeira conta."""
    admin_id, gestor_a, gestor_b = uuid4(), uuid4(), uuid4()
    async with connection.get_pool().acquire() as conn:
        for mid, email, papel in (
            (admin_id, "admin@v4company.com", "admin"),
            (gestor_a, "gestor.a@v4company.com", "gestor"),
            (gestor_b, "gestor.b@v4company.com", "gestor"),
        ):
            await managers.create(conn, manager_id=mid, email=email, full_name=None, role=papel)
        if plataforma == "google":
            contas = ["1000000001", "1000000002"]
            await google_ads_accounts.upsert_many(
                conn,
                [
                    {"customer_id": c, "mcc_id": "M1", "descriptive_name": f"Cliente {c}"}
                    for c in contas
                ],
            )
            await manager_account_access.grant(conn, manager_id=gestor_a, customer_id=contas[0])
        else:
            contas = ["act_2000000001", "act_2000000002"]
            await meta_ad_accounts.upsert_many(
                conn,
                [
                    {
                        "ad_account_id": c,
                        "business_id": None,
                        "business_name": None,
                        "account_name": f"Conta {c}",
                        "currency": "BRL",
                        "timezone_name": "America/Sao_Paulo",
                        "account_status": 1,
                    }
                    for c in contas
                ],
            )
            await manager_meta_account_access.grant(
                conn, manager_id=gestor_a, ad_account_id=contas[0]
            )
    return admin_id, gestor_a, gestor_b, contas


def _cookie(admin_id: UUID) -> dict[str, str]:
    token = sign_panel_session(
        manager_id=str(admin_id),
        email="admin@v4company.com",
        signing_key=_SIGNING_KEY,
        aud="panel",
    )
    return {PANEL_SESSION_COOKIE_NAME: token}


def _caixas(html: str) -> dict[tuple[str, str], bool]:
    caixas = {(m["mgr"], m["conta"]): m["checked"] is not None for m in _CHECKBOX.finditer(html)}
    assert caixas, "nenhuma checkbox de acesso na página: o regex não casa mais o template"
    return caixas


_PREFIXO = {"google": "/admin/access", "meta": "/admin/access/meta"}


@pytest.mark.integration
@pytest.mark.parametrize("plataforma", ["google", "meta"])
async def test_matriz_marca_so_o_grant_vivo(client: AsyncClient, plataforma: str) -> None:
    admin_id, gestor_a, gestor_b, contas = await _semear(plataforma)

    resposta = await client.get(_PREFIXO[plataforma], cookies=_cookie(admin_id))

    assert resposta.status_code == 200
    caixas = _caixas(resposta.text)
    esperado: dict[tuple[str, str], bool] = {
        (str(g), c): (g == gestor_a and c == contas[0])
        for g in (gestor_a, gestor_b)
        for c in contas
    }
    # A matriz lista todo gestor ativo (o admin inclusive): confere-se o recorte semeado.
    assert {k: caixas.get(k) for k in esperado} == esperado


@pytest.mark.integration
@pytest.mark.parametrize("plataforma", ["google", "meta"])
async def test_detalhe_marca_so_o_grant_vivo_do_gestor(
    client: AsyncClient, plataforma: str
) -> None:
    admin_id, gestor_a, _, contas = await _semear(plataforma)

    resposta = await client.get(f"{_PREFIXO[plataforma]}/{gestor_a}", cookies=_cookie(admin_id))

    assert resposta.status_code == 200
    assert "gestor.a@v4company.com" in resposta.text
    caixas: dict[Any, bool] = _caixas(resposta.text)
    assert caixas == {(str(gestor_a), contas[0]): True, (str(gestor_a), contas[1]): False}


@pytest.mark.integration
@pytest.mark.parametrize("plataforma", ["google", "meta"])
async def test_detalhe_de_gestor_inexistente_e_404(client: AsyncClient, plataforma: str) -> None:
    admin_id, *_ = await _semear(plataforma)

    resposta = await client.get(f"{_PREFIXO[plataforma]}/{uuid4()}", cookies=_cookie(admin_id))

    assert resposta.status_code == 404
