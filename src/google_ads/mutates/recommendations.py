"""Recommendation actions — special case (RecommendationService, not GoogleAdsService.mutate).

Unlike other mutations, recommendations use a dedicated service. We don't
use the @register_builder pattern here; instead, the tools call
run_recommendation_action directly.
"""

from typing import Any

from src.google_ads.request_id import get_capture_interceptor


def execute_apply_recommendation(client: Any, customer_id: str, payload: dict[str, Any]) -> Any:
    """payload: {recommendation_resource_name: str}"""
    rec_service = client.get_service(
        "RecommendationService", interceptors=[get_capture_interceptor()]
    )
    operation = client.get_type("ApplyRecommendationOperation")
    operation.resource_name = payload["recommendation_resource_name"]
    response = rec_service.apply_recommendation(
        customer_id=customer_id,
        operations=[operation],
    )
    return response


def execute_dismiss_recommendation(client: Any, customer_id: str, payload: dict[str, Any]) -> Any:
    """payload: {recommendation_resource_name: str}"""
    rec_service = client.get_service(
        "RecommendationService", interceptors=[get_capture_interceptor()]
    )
    operation = client.get_type("DismissRecommendationRequest.DismissRecommendationOperation")
    operation.resource_name = payload["recommendation_resource_name"]
    response = rec_service.dismiss_recommendation(
        customer_id=customer_id,
        operations=[operation],
    )
    return response
