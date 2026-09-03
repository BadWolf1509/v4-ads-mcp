"""Builder do update_ad_schedule (spec §4). Burro de proposito: o diff foi calculado
no dry-run e viaja no payload — o que o gestor confirmou e exatamente o que se aplica.
"""

from __future__ import annotations

from typing import Any

from google.protobuf.field_mask_pb2 import FieldMask

from src.google_ads.ad_schedule import DIAS, MINUTO_ENUM
from src.google_ads.mutates._common import register_builder


@register_builder("update_ad_schedule")
def build_update_ad_schedule(client: Any, customer_id: str, payload: dict[str, Any]) -> list[Any]:
    campaign_service = client.get_service("CampaignService")
    dias = client.enums.DayOfWeekEnum
    minutos = client.enums.MinuteOfHourEnum
    ops: list[Any] = []
    for item in payload["ops"]:
        kind = item.get("kind")
        op = client.get_type("MutateOperation")
        cco = op.campaign_criterion_operation
        if kind == "add":
            w = item["window"]
            if w["day_of_week"] not in DIAS:
                raise ValueError(
                    f"day_of_week={w['day_of_week']!r} invalido; use um de {', '.join(DIAS)}"
                )
            for campo in ("start_minute", "end_minute"):
                if int(w[campo]) not in MINUTO_ENUM:
                    raise ValueError(f"{campo}={w[campo]} fora de {sorted(MINUTO_ENUM)}")
            crit = cco.create
            crit.campaign = campaign_service.campaign_path(customer_id, item["campaign_id"])
            crit.ad_schedule.day_of_week = dias[w["day_of_week"]]
            crit.ad_schedule.start_hour = int(w["start_hour"])
            crit.ad_schedule.start_minute = minutos[MINUTO_ENUM[int(w["start_minute"])]]
            crit.ad_schedule.end_hour = int(w["end_hour"])
            crit.ad_schedule.end_minute = minutos[MINUTO_ENUM[int(w["end_minute"])]]
            if item.get("bid_modifier") is not None:
                crit.bid_modifier = float(item["bid_modifier"])
        elif kind == "remove":
            cco.remove = item["resource_name"]
        elif kind == "update":
            bm = item.get("bid_modifier")
            if bm is None:
                raise ValueError(
                    "update sem bid_modifier: a unica coisa que um update de ad_schedule muda e o bid_modifier"
                )
            crit = cco.update
            crit.resource_name = item["resource_name"]
            crit.bid_modifier = float(bm)
            client.copy_from(cco.update_mask, FieldMask(paths=["bid_modifier"]))
        else:
            raise ValueError(f"kind desconhecido em ops: {kind!r}")
        ops.append(op)
    return ops
