"""Bulk-pause mutate builder for bulk_pause_by_query.

Reads the dry-run-captured payload {target_type, entities} and emits
MutateOperation messages of the right oneof field per target_type. Each
entity is mutated with update_mask=['status'] and the appropriate
StatusEnum.PAUSED.
"""

from collections.abc import Callable
from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.mutates._common import register_builder
from src.google_ads.mutates._status import (
    ALVOS_DE_STATUS,
    operacao_de_status,
)

_SUPPORTED_TARGETS = ("keyword", "ad", "campaign", "ad_group")

# Como achar os ids do caminho do recurso em cada entidade do payload persistido.
_IDS_POR_ALVO: dict[str, Callable[[dict[str, Any]], tuple[str, ...]]] = {
    "keyword": lambda e: (e["ad_group_id"], e["criterion_id"]),
    "ad": lambda e: (e["ad_group_id"], e["ad_id"]),
    "campaign": lambda e: (e["campaign_id"],),
    "ad_group": lambda e: (e["ad_group_id"],),
}


@register_builder("bulk_pause_by_query")
def build_bulk_pause(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    """payload: {target_type: 'keyword'|'ad'|'campaign'|'ad_group', entities: [...]}.

    Entity shape depends on target_type:
      keyword:   {ad_group_id: str, criterion_id: str}
      ad:        {ad_group_id: str, ad_id: str}
      campaign:  {campaign_id: str}
      ad_group:  {ad_group_id: str}

    Returns list[MutateOperation] — heterogeneous-safe (all-same target_type
    in one call, but the builder picks the right oneof field per row).
    """
    target_type = payload["target_type"]
    if target_type not in _SUPPORTED_TARGETS:
        raise ValueError(
            f"target_type='{target_type}' invalido. Aceitos: {list(_SUPPORTED_TARGETS)}."
        )

    entities = payload["entities"]
    alvo = ALVOS_DE_STATUS[target_type]
    caminho = getattr(client.get_service(alvo.servico), alvo.caminho)
    status_enum = getattr(client.enums, alvo.enum)
    mascara = FieldMask(paths=["status"])
    ids_de = _IDS_POR_ALVO[target_type]
    return [
        operacao_de_status(
            client, alvo, caminho(customer_id, *ids_de(e)), status_enum.PAUSED, mascara
        )
        for e in entities
    ]
