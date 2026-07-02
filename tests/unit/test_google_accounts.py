"""Testes de parsing/mapeamento de src/google_ads/accounts.py.

Módulo usado no OAuth callback + resync job. Duas funções:
- list_accessible_customer_resource_names(client): lista resource_names do CustomerService.
- fetch_account_details(client, ...): mapeia rows do customer_client view → dicts.

Client é MagicMock configurado pros retornos do SDK; exercitamos o parsing/mapeamento
REAL do módulo (filtro por customer_ids, fallback de descriptive_name, cast de bool,
tradução de erro via to_friendly).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.google_ads.accounts import (
    fetch_account_details,
    list_accessible_customer_resource_names,
)
from src.google_ads.errors import GoogleAdsFriendlyError

_MCC = "6436352492"


# ---------------------------------------------------------------------------
# list_accessible_customer_resource_names
# ---------------------------------------------------------------------------


def test_list_accessible_returns_resource_names() -> None:
    client = MagicMock()
    service = MagicMock()
    service.list_accessible_customers.return_value = SimpleNamespace(
        resource_names=["customers/1111111111", "customers/2222222222"]
    )
    client.get_service.return_value = service

    out = list_accessible_customer_resource_names(client)

    assert out == ["customers/1111111111", "customers/2222222222"]
    client.get_service.assert_called_once_with("CustomerService")


def test_list_accessible_empty() -> None:
    client = MagicMock()
    service = MagicMock()
    service.list_accessible_customers.return_value = SimpleNamespace(resource_names=[])
    client.get_service.return_value = service

    assert list_accessible_customer_resource_names(client) == []


def test_list_accessible_wraps_error_in_friendly() -> None:
    client = MagicMock()
    client.get_service.side_effect = RuntimeError("gRPC blew up")

    with pytest.raises(GoogleAdsFriendlyError):
        list_accessible_customer_resource_names(client)


# ---------------------------------------------------------------------------
# fetch_account_details
# ---------------------------------------------------------------------------


def _row(
    *,
    cid: int,
    name: str = "Cliente X",
    currency: str = "BRL",
    tz: str = "America/Sao_Paulo",
    test: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        customer_client=SimpleNamespace(
            id=cid,
            descriptive_name=name,
            currency_code=currency,
            time_zone=tz,
            test_account=test,
            manager=False,
        )
    )


def _client_returning(rows: list[SimpleNamespace]) -> MagicMock:
    """MagicMock client cujo GoogleAdsService.search devolve `rows` (iterável)."""
    client = MagicMock()
    ga_service = MagicMock()
    ga_service.search.return_value = iter(rows)
    client.get_service.return_value = ga_service
    # get_type("SearchGoogleAdsRequest") → objeto simples com attrs setáveis.
    client.get_type.return_value = SimpleNamespace(customer_id=None, query=None)
    return client


def test_fetch_account_details_maps_rows() -> None:
    client = _client_returning(
        [
            _row(cid=1111111111, name="Padaria do Zé", currency="BRL", tz="America/Sao_Paulo"),
            _row(cid=2222222222, name="Loja B", currency="USD", tz="America/Recife", test=True),
        ]
    )

    out = fetch_account_details(client, login_customer_id=_MCC, customer_ids=[])

    assert len(out) == 2
    assert out[0] == {
        "customer_id": "1111111111",
        "mcc_id": _MCC,
        "descriptive_name": "Padaria do Zé",
        "currency_code": "BRL",
        "time_zone": "America/Sao_Paulo",
        "is_test_account": False,
    }
    assert out[1]["is_test_account"] is True
    assert out[1]["currency_code"] == "USD"


def test_fetch_account_details_sets_request_fields() -> None:
    """login_customer_id vira request.customer_id + a query bate no customer_client view."""
    client = _client_returning([_row(cid=1111111111)])

    fetch_account_details(client, login_customer_id=_MCC, customer_ids=[])

    request_arg = client.get_service.return_value.search.call_args.kwargs["request"]
    assert request_arg.customer_id == _MCC
    assert "FROM customer_client" in request_arg.query
    assert "customer_client.manager = false" in request_arg.query


def test_fetch_account_details_filters_by_customer_ids() -> None:
    """customer_ids não-vazio → só as contas pedidas passam (as demais são puladas)."""
    client = _client_returning(
        [
            _row(cid=1111111111, name="Quero"),
            _row(cid=2222222222, name="Não quero"),
            _row(cid=3333333333, name="Quero também"),
        ]
    )

    out = fetch_account_details(
        client, login_customer_id=_MCC, customer_ids=["1111111111", "3333333333"]
    )

    ids = {a["customer_id"] for a in out}
    assert ids == {"1111111111", "3333333333"}


def test_fetch_account_details_descriptive_name_fallback() -> None:
    """descriptive_name vazio → fallback 'Cliente {id}'."""
    client = _client_returning([_row(cid=1111111111, name="")])

    out = fetch_account_details(client, login_customer_id=_MCC, customer_ids=[])

    assert out[0]["descriptive_name"] == "Cliente 1111111111"


def test_fetch_account_details_empty_result() -> None:
    client = _client_returning([])
    out = fetch_account_details(client, login_customer_id=_MCC, customer_ids=[])
    assert out == []


def test_fetch_account_details_wraps_error_in_friendly() -> None:
    client = MagicMock()
    client.get_service.side_effect = RuntimeError("search exploded")

    with pytest.raises(GoogleAdsFriendlyError):
        fetch_account_details(client, login_customer_id=_MCC, customer_ids=[])
