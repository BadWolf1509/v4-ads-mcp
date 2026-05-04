"""Wrapper around CustomerService.list_accessible_customers + GoogleAdsService details fetch."""

from typing import Any

from src.google_ads.errors import to_friendly


def list_accessible_customer_resource_names(client: Any) -> list[str]:
    """Call CustomerService.list_accessible_customers and return resource names.

    Resource names look like 'customers/1234567890'.
    """
    try:
        service = client.get_service("CustomerService")
        response = service.list_accessible_customers()
        return list(response.resource_names)
    except Exception as e:
        raise to_friendly(e) from e


def fetch_account_details(
    client: Any,
    *,
    login_customer_id: str,
    customer_ids: list[str],
) -> list[dict[str, Any]]:
    """Fetch descriptive_name, currency_code, time_zone, test_account flag for many accounts.

    Uses GoogleAdsService.search to query the customer_client view from the MCC,
    which lists all child customers including their attributes.
    """
    try:
        ga_service = client.get_service("GoogleAdsService")
        # Query the MCC for all its children at once.
        query = """
            SELECT
              customer_client.id,
              customer_client.descriptive_name,
              customer_client.currency_code,
              customer_client.time_zone,
              customer_client.test_account,
              customer_client.manager
            FROM customer_client
            WHERE customer_client.manager = false
        """
        results: list[dict[str, Any]] = []
        # Pagination handled by SDK; we iterate through pages.
        request = client.get_type("SearchGoogleAdsRequest")
        request.customer_id = login_customer_id
        request.query = query
        response = ga_service.search(request=request)
        for row in response:
            cc = row.customer_client
            cid = str(cc.id)
            if customer_ids and cid not in customer_ids:
                continue
            results.append(
                {
                    "customer_id": cid,
                    "mcc_id": login_customer_id,
                    "descriptive_name": cc.descriptive_name or f"Cliente {cid}",
                    "currency_code": cc.currency_code,
                    "time_zone": cc.time_zone,
                    "is_test_account": bool(cc.test_account),
                }
            )
        return results
    except Exception as e:
        raise to_friendly(e) from e
