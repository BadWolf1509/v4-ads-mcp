"""Mutate builder da assinatura de aplicacao automatica de recomendacao (N3).

Vai pelo GoogleAdsService.mutate (`recommendation_subscription_operation`), nao pelo
RecommendationService: este e o recurso da assinatura, nao a recomendacao.
So `update` de `status`. Criar assinatura esta fora do escopo — seria ligar um
auto-apply que nao existia.
"""

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.mutates._common import register_builder
from src.google_ads.queries.recommendation_subscription import (
    STATUS_ALVO,
    resource_name_da_assinatura,
)


@register_builder("update_recommendation_subscription")
def build_update_recommendation_subscription(
    client: Any, customer_id: str, payload: dict[str, Any]
) -> list[Any]:
    """payload: {type: <RecommendationType sem UNKNOWN/UNSPECIFIED>, status: PAUSED|ENABLED}"""
    status = payload["status"]
    if status not in STATUS_ALVO:
        raise ValueError(f"status fora do contrato: {status!r} (aceitos: {STATUS_ALVO})")
    resource_name = resource_name_da_assinatura(customer_id, payload["type"])
    op = client.get_type("MutateOperation")
    sub_op = op.recommendation_subscription_operation
    sub = sub_op.update
    sub.resource_name = resource_name
    sub.status = client.enums.RecommendationSubscriptionStatusEnum[status]
    client.copy_from(sub_op.update_mask, FieldMask(paths=["status"]))
    return [op]
