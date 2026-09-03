"""Builder do update_ad_schedule. `make_capture_client`, nunca MagicMock (F16/F42/F44).

Campos do proto lidos do SDK v24 por import (nao por analogia): AdScheduleInfo =
{day_of_week, start_hour, start_minute, end_hour, end_minute};
CampaignCriterionOperation = {update_mask, create, update, remove}.
"""

from __future__ import annotations

import pytest

from src.google_ads.mutates.ad_schedule import build_update_ad_schedule
from tests.unit.fixtures.proto_capture import make_capture_client

CID = "1234567890"


def _add(day="MONDAY", sh=7, sm=0, eh=17, em=30, bm=None) -> dict:
    return {
        "kind": "add",
        "campaign_id": "22169885957",
        "window": {
            "day_of_week": day,
            "start_hour": sh,
            "start_minute": sm,
            "end_hour": eh,
            "end_minute": em,
        },
        "bid_modifier": bm,
    }


def test_add_cria_campaign_criterion_com_ad_schedule_completo() -> None:
    ops = build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add()]})
    assert len(ops) == 1
    op = ops[0]
    assert op.field("campaign_criterion_operation.create.campaign").endswith(
        "/campaigns/22169885957"
    )
    assert op.field("campaign_criterion_operation.create.ad_schedule.day_of_week") == "MONDAY"
    assert op.field("campaign_criterion_operation.create.ad_schedule.start_hour") == 7
    assert op.field("campaign_criterion_operation.create.ad_schedule.start_minute") == "ZERO"
    assert op.field("campaign_criterion_operation.create.ad_schedule.end_hour") == 17
    assert op.field("campaign_criterion_operation.create.ad_schedule.end_minute") == "THIRTY"


def test_add_com_bid_modifier_seta_o_campo_e_sem_ele_nao_toca() -> None:
    com = build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add(bm=1.2)]})[0]
    assert com.field("campaign_criterion_operation.create.bid_modifier") == 1.2
    sem = build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add()]})[0]
    assert not sem.has("campaign_criterion_operation.create.bid_modifier")


def test_remove_usa_o_resource_name_verbatim() -> None:
    rn = f"customers/{CID}/campaignCriteria/22169885957~348624223154"
    op = build_update_ad_schedule(
        make_capture_client(), CID, {"ops": [{"kind": "remove", "resource_name": rn}]}
    )[0]
    assert op.field("campaign_criterion_operation.remove") == rn


def test_update_de_bid_modifier_usa_update_com_mask_e_nao_recria() -> None:
    rn = f"customers/{CID}/campaignCriteria/22169885957~348624223154"
    op = build_update_ad_schedule(
        make_capture_client(),
        CID,
        {"ops": [{"kind": "update", "resource_name": rn, "bid_modifier": 0.8}]},
    )[0]
    assert op.field("campaign_criterion_operation.update.resource_name") == rn
    assert op.field("campaign_criterion_operation.update.bid_modifier") == 0.8
    assert not op.has("campaign_criterion_operation.create") and not op.has(
        "campaign_criterion_operation.remove"
    )


def test_minuto_invalido_no_payload_estoura_antes_do_google() -> None:
    """Defesa em profundidade: o schema recusa antes; se um payload velho passar, aqui estoura."""
    with pytest.raises(ValueError):
        build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add(sm=10)]})


def test_kind_desconhecido_estoura() -> None:
    with pytest.raises(ValueError):
        build_update_ad_schedule(make_capture_client(), CID, {"ops": [{"kind": "replace"}]})


def test_day_of_week_invalido_estoura_antes_do_google() -> None:
    with pytest.raises(ValueError, match="day_of_week"):
        build_update_ad_schedule(make_capture_client(), CID, {"ops": [_add(day="MONDAI")]})


def test_update_sem_bid_modifier_estoura_com_valueerror() -> None:
    rn = f"customers/{CID}/campaignCriteria/22169885957~348624223154"
    with pytest.raises(ValueError, match="bid_modifier"):
        build_update_ad_schedule(
            make_capture_client(), CID, {"ops": [{"kind": "update", "resource_name": rn}]}
        )
