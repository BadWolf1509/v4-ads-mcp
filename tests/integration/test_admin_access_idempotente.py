"""Task 20 — a matriz de acesso aplica o estado PEDIDO, não inverte o do banco.

Aba velha mostrava "sem acesso" e o gestor já tinha (ou o contrário): o clique
chegava e a rota, decidindo pelo banco, fazia o oposto do que a tela prometia.
Agora o checkbox manda `desejado=grant|revoke`; pedido igual ao estado atual não
muda nada e não grava audit. Rodado nas duas rotas, Google e Meta.
"""

import json
import re
from dataclasses import dataclass
from uuid import uuid4

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


@dataclass
class Rota:
    nome: str
    url: str
    campo: str
    conta: str
    tabela: str
    coluna: str
    plataforma: str


GOOGLE = Rota(
    "google",
    "/admin/access/toggle",
    "customer_id",
    "1234567890",
    "manager_account_access",
    "customer_id",
    "google",
)
META = Rota(
    "meta",
    "/admin/access/meta/toggle",
    "ad_account_id",
    "act_123456789",
    "manager_meta_account_access",
    "ad_account_id",
    "meta",
)


async def _cenario():
    pool = connection.get_pool()
    async with pool.acquire() as conn:
        admin, gestor = uuid4(), uuid4()
        await managers.create(
            conn, manager_id=admin, email="admin@v4company.com", full_name=None, role="admin"
        )
        await managers.create(
            conn, manager_id=gestor, email="gestor@v4company.com", full_name=None, role="gestor"
        )
        await google_ads_accounts.upsert_many(
            conn, [{"customer_id": "1234567890", "mcc_id": "M1", "descriptive_name": "Cliente A"}]
        )
        await meta_ad_accounts.upsert_many(
            conn,
            [
                {
                    "ad_account_id": "act_123456789",
                    "business_id": "biz_1",
                    "business_name": "Empresa",
                    "account_name": "Conta Meta",
                    "currency": "BRL",
                    "timezone_name": "America/Sao_Paulo",
                    "account_status": 1,
                }
            ],
        )
    cookie = sign_panel_session(
        manager_id=str(admin), email="admin@v4company.com", signing_key=_SIGNING_KEY, aud="panel"
    )
    return pool, admin, gestor, {PANEL_SESSION_COOKIE_NAME: cookie}


async def _tem_acesso(pool, rota: Rota, gestor) -> bool:
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                f"SELECT 1 FROM {rota.tabela} WHERE manager_id=$1 AND {rota.coluna}=$2 "
                "AND revoked_at IS NULL",
                gestor,
                rota.conta,
            )
        )


async def _n_audit(pool, rota: Rota) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE platform=$1 "
            "AND operation IN ('admin_access_grant','admin_access_revoke')",
            rota.plataforma,
        )


async def _conceder(pool, rota: Rota, gestor, admin):
    async with pool.acquire() as conn:
        if rota is GOOGLE:
            await manager_account_access.grant(
                conn,
                manager_id=gestor,
                customer_id=rota.conta,
                access_level="write",
                granted_by=admin,
            )
        else:
            await manager_meta_account_access.grant(
                conn,
                manager_id=gestor,
                ad_account_id=rota.conta,
                access_level="write",
                granted_by=admin,
            )


def _toast(resp) -> str:
    return json.loads(resp.headers["HX-Trigger"])["toast"]["message"]


def _post(client, rota, ck, gestor, desejado):
    data = {"manager_id": str(gestor), rota.campo: rota.conta}
    if desejado is not None:
        data["desejado"] = desejado
    return client.post(rota.url, data=data, cookies=ck)


@pytest.mark.integration
@pytest.mark.parametrize("rota", [GOOGLE, META], ids=lambda r: r.nome)
async def test_grant_em_quem_ja_tem_mantem_e_nao_grava_audit(client: AsyncClient, rota: Rota):
    pool, admin, gestor, ck = await _cenario()
    await _conceder(pool, rota, gestor, admin)

    resp = await _post(client, rota, ck, gestor, "grant")  # aba velha: achava que não tinha

    assert resp.status_code == 200
    assert '"checkbox" checked' in resp.text  # o fragmento mostra a verdade
    assert await _tem_acesso(pool, rota, gestor) is True  # NÃO inverteu
    assert await _n_audit(pool, rota) == 0
    assert _toast(resp) == "O acesso já estava liberado"


@pytest.mark.integration
@pytest.mark.parametrize("rota", [GOOGLE, META], ids=lambda r: r.nome)
async def test_revoke_em_quem_nao_tem_mantem_e_nao_grava_audit(client: AsyncClient, rota: Rota):
    pool, admin, gestor, ck = await _cenario()

    resp = await _post(client, rota, ck, gestor, "revoke")  # aba velha: achava que tinha

    assert resp.status_code == 200
    assert '"checkbox" checked' not in resp.text
    assert await _tem_acesso(pool, rota, gestor) is False  # NÃO concedeu
    assert await _n_audit(pool, rota) == 0
    assert _toast(resp) == "O acesso já estava revogado"


@pytest.mark.integration
@pytest.mark.parametrize("rota", [GOOGLE, META], ids=lambda r: r.nome)
async def test_pedido_que_muda_aplica_audita_e_o_toast_diz_o_que_houve(
    client: AsyncClient, rota: Rota
):
    pool, admin, gestor, ck = await _cenario()

    r1 = await _post(client, rota, ck, gestor, "grant")
    assert await _tem_acesso(pool, rota, gestor) is True
    assert _toast(r1) == "Acesso liberado"
    # o próximo clique do fragmento devolvido pede o OPOSTO do estado novo
    assert "revoke" in r1.text.replace("&quot;", '"')

    r2 = await _post(client, rota, ck, gestor, "revoke")
    assert await _tem_acesso(pool, rota, gestor) is False
    assert _toast(r2) == "Acesso revogado"
    assert "grant" in r2.text.replace("&quot;", '"')
    assert await _n_audit(pool, rota) == 2


@pytest.mark.integration
@pytest.mark.parametrize("rota", [GOOGLE, META], ids=lambda r: r.nome)
@pytest.mark.parametrize("valor", [None, "toggle", ""], ids=["ausente", "invalido", "vazio"])
async def test_sem_desejado_valido_e_422(client: AsyncClient, rota: Rota, valor):
    pool, admin, gestor, ck = await _cenario()

    resp = await _post(client, rota, ck, gestor, valor)

    assert resp.status_code == 422
    assert await _tem_acesso(pool, rota, gestor) is False
    assert await _n_audit(pool, rota) == 0


@pytest.mark.integration
@pytest.mark.parametrize(
    ("rota", "url_matriz"), [(GOOGLE, "/admin/access"), (META, "/admin/access/meta")]
)
async def test_matriz_renderiza_o_estado_desejado_no_checkbox(
    client: AsyncClient, rota: Rota, url_matriz: str
):
    """O `desejado` sai da renderização: marcado -> revoke, desmarcado -> grant."""
    pool, admin, gestor, ck = await _cenario()

    def desejado_do_gestor(html: str) -> str:
        celula = re.search(rf'data-manager-id="{gestor}">(.*?)</td>', html, re.S)
        assert celula
        return re.search(r'"desejado": "(\w+)"', celula.group(1)).group(1)

    sem = (await client.get(url_matriz, cookies=ck)).text
    assert desejado_do_gestor(sem) == "grant"

    await _conceder(pool, rota, gestor, admin)
    com = (await client.get(url_matriz, cookies=ck)).text
    assert desejado_do_gestor(com) == "revoke"
