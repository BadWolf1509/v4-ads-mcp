"""A lista autoritativa da parceria = client_ad_accounts UNIAO owned_ad_accounts.

Medido em 2026-08-20: 24 + 1 = 25, enquanto /me/adaccounts devolvia 23 — a edge
do BM enxerga conta que o system user ainda nao foi atribuido a ler.
"""

import httpx
import pytest
import respx

from src.meta_ads.partnership import fetch_partnership

BASE = "https://graph.facebook.com/v22.0/619664032237208"


@pytest.mark.asyncio
@respx.mock
async def test_une_as_duas_edges_e_normaliza() -> None:
    respx.get(f"{BASE}/client_ad_accounts").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "act_1",
                        "name": "Cliente",
                        "account_status": 1,
                        "business": {"id": "bm_c", "name": "BM do cliente"},
                    }
                ]
            },
        )
    )
    respx.get(f"{BASE}/owned_ad_accounts").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "act_2", "name": "Propria", "account_status": 1}]}
        )
    )

    async with httpx.AsyncClient() as http:
        snap = await fetch_partnership(http, access_token="tok", business_id="619664032237208")

    assert snap.complete is True
    por_id = {a["ad_account_id"]: a for a in snap.accounts}
    assert set(por_id) == {"act_1", "act_2"}
    assert por_id["act_1"]["business_id"] == "bm_c"
    assert por_id["act_1"]["account_name"] == "Cliente"
    # conta própria não tem `business` no payload da Graph
    assert por_id["act_2"]["business_id"] is None


@pytest.mark.asyncio
@respx.mock
async def test_uma_edge_incompleta_contamina_o_snapshot() -> None:
    """Meia leitura nao pode virar 'a parceria encolheu' — F93/F85."""
    respx.get(f"{BASE}/client_ad_accounts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "act_1", "name": "C"}]})
    )
    respx.get(f"{BASE}/owned_ad_accounts").mock(
        return_value=httpx.Response(500, json={"error": {}})
    )

    async with httpx.AsyncClient() as http:
        snap = await fetch_partnership(http, access_token="tok", business_id="619664032237208")

    assert snap.complete is False
    assert len(snap.accounts) == 1  # o que veio não se perde


@pytest.mark.asyncio
@respx.mock
async def test_prefixo_act_normalizado() -> None:
    respx.get(f"{BASE}/client_ad_accounts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "123", "name": "Sem prefixo"}]})
    )
    respx.get(f"{BASE}/owned_ad_accounts").mock(return_value=httpx.Response(200, json={"data": []}))

    async with httpx.AsyncClient() as http:
        snap = await fetch_partnership(http, access_token="tok", business_id="619664032237208")

    assert snap.accounts[0]["ad_account_id"] == "act_123"


@pytest.mark.asyncio
@respx.mock
async def test_linha_sem_id_nao_vira_conta_fantasma() -> None:
    """M6: sem o `continue`, `id` ausente virava `"act_"` e era upsertado como
    conta REAL — id que nenhuma edge devolve, logo ausente da parceria em toda
    execucao seguinte, acumulando carencia ate ser 'desativado' por churn."""
    respx.get(f"{BASE}/client_ad_accounts").mock(
        return_value=httpx.Response(
            200, json={"data": [{"name": "Sem id"}, {"id": "act_ok", "name": "Boa"}]}
        )
    )
    respx.get(f"{BASE}/owned_ad_accounts").mock(return_value=httpx.Response(200, json={"data": []}))

    async with httpx.AsyncClient() as http:
        snap = await fetch_partnership(http, access_token="tok", business_id="619664032237208")

    assert [a["ad_account_id"] for a in snap.accounts] == ["act_ok"]
