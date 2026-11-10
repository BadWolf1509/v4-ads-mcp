"""Caracterizacao dos builders de status: a operacao montada nao pode mudar.

Os valores esperados em ESPERADO foram capturados do codigo ANTES da refatoracao
table-driven (`mutates/_status.py`). Se um deles mudar, a operacao enviada ao
Google mudou - e o payload persistido nos tokens pendentes deixa de significar
o que significava.
"""

from typing import Any

import pytest

from src.google_ads.mutates._status import ALVOS_DE_STATUS
from src.google_ads.mutates.ad_groups import build_update_ad_group_status
from src.google_ads.mutates.ads import build_update_ad_status
from src.google_ads.mutates.bulk import _IDS_POR_ALVO, _SUPPORTED_TARGETS, build_bulk_pause
from src.google_ads.mutates.campaigns import build_update_campaign_status
from src.google_ads.mutates.keywords import build_update_keyword_status
from tests.unit.fixtures.proto_capture import make_capture_client, to_plain

CID = "1234567890"


class _Enum:
    """Stub por NOME de enum: o valor carrega o enum e o status, para pinar os dois."""

    def __init__(self, nome: str) -> None:
        self._nome = nome

    def __getitem__(self, key: str) -> str:
        return f"{self._nome}.{key}"

    def __getattr__(self, key: str) -> str:
        return f"{self._nome}.{key}"


def _client() -> Any:
    client = make_capture_client()
    for nome in (
        "CampaignStatusEnum",
        "AdGroupStatusEnum",
        "AdGroupAdStatusEnum",
        "AdGroupCriterionStatusEnum",
    ):
        setattr(client.enums, nome, _Enum(nome))
    client.copy_from.reset_mock()
    return client


def _serializa(client: Any, ops: list[Any]) -> dict[str, Any]:
    chamadas = client.copy_from.call_args_list
    assert len(chamadas) == len(ops)
    for op, chamada in zip(ops, chamadas, strict=True):
        # A mascara tem de ir para o update_mask da operacao (o oneof desse alvo).
        (campo,) = op._captured
        assert chamada.args[0] is op._captured[campo]._captured["update_mask"]
    return {
        "ops": [to_plain(op) for op in ops],
        "mascaras": [list(c.args[1].paths) for c in chamadas],
    }


PAYLOADS: dict[str, tuple[Any, dict[str, Any]]] = {
    "campaign": (
        build_update_campaign_status,
        {"campaign_ids": ["11", "22"], "new_status": "paused"},
    ),
    "ad_group": (
        build_update_ad_group_status,
        {"ad_group_ids": ["33", "44"], "new_status": "enabled"},
    ),
    "ad": (
        build_update_ad_status,
        {"ads": [{"ad_group_id": "5", "ad_id": "6"}], "new_status": "removed"},
    ),
    "keyword": (
        build_update_keyword_status,
        {"keywords": [{"ad_group_id": "7", "criterion_id": "8"}], "new_status": "paused"},
    ),
    "bulk_keyword": (
        build_bulk_pause,
        {"target_type": "keyword", "entities": [{"ad_group_id": "7", "criterion_id": "8"}]},
    ),
    "bulk_ad": (
        build_bulk_pause,
        {"target_type": "ad", "entities": [{"ad_group_id": "5", "ad_id": "6"}]},
    ),
    "bulk_campaign": (
        build_bulk_pause,
        {"target_type": "campaign", "entities": [{"campaign_id": "11"}, {"campaign_id": "22"}]},
    ),
    "bulk_ad_group": (
        build_bulk_pause,
        {"target_type": "ad_group", "entities": [{"ad_group_id": "33"}]},
    ),
}

ESPERADO: dict[str, Any] = {
    "ad": {
        "mascaras": [["status"]],
        "ops": [
            {
                "ad_group_ad_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/adGroupAds/5~6",
                        "status": "AdGroupAdStatusEnum.REMOVED",
                    },
                    "update_mask": {},
                }
            }
        ],
    },
    "ad_group": {
        "mascaras": [["status"], ["status"]],
        "ops": [
            {
                "ad_group_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/adGroups/33",
                        "status": "AdGroupStatusEnum.ENABLED",
                    },
                    "update_mask": {},
                }
            },
            {
                "ad_group_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/adGroups/44",
                        "status": "AdGroupStatusEnum.ENABLED",
                    },
                    "update_mask": {},
                }
            },
        ],
    },
    "bulk_ad": {
        "mascaras": [["status"]],
        "ops": [
            {
                "ad_group_ad_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/adGroupAds/5~6",
                        "status": "AdGroupAdStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            }
        ],
    },
    "bulk_ad_group": {
        "mascaras": [["status"]],
        "ops": [
            {
                "ad_group_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/adGroups/33",
                        "status": "AdGroupStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            }
        ],
    },
    "bulk_campaign": {
        "mascaras": [["status"], ["status"]],
        "ops": [
            {
                "campaign_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/campaigns/11",
                        "status": "CampaignStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            },
            {
                "campaign_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/campaigns/22",
                        "status": "CampaignStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            },
        ],
    },
    "bulk_keyword": {
        "mascaras": [["status"]],
        "ops": [
            {
                "ad_group_criterion_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/adGroupCriteria/7~8",
                        "status": "AdGroupCriterionStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            }
        ],
    },
    "campaign": {
        "mascaras": [["status"], ["status"]],
        "ops": [
            {
                "campaign_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/campaigns/11",
                        "status": "CampaignStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            },
            {
                "campaign_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/campaigns/22",
                        "status": "CampaignStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            },
        ],
    },
    "keyword": {
        "mascaras": [["status"]],
        "ops": [
            {
                "ad_group_criterion_operation": {
                    "update": {
                        "resource_name": "customers/1234567890/adGroupCriteria/7~8",
                        "status": "AdGroupCriterionStatusEnum.PAUSED",
                    },
                    "update_mask": {},
                }
            }
        ],
    },
}


@pytest.mark.parametrize("nome", list(PAYLOADS))
def test_proto_igual_ao_de_antes(nome: str) -> None:
    builder, payload = PAYLOADS[nome]
    client = _client()
    ops = builder(client, CID, payload)
    assert _serializa(client, ops) == ESPERADO[nome]


def test_tabelas_de_alvos_do_bulk_tem_as_mesmas_chaves() -> None:
    """Alvo so em `_SUPPORTED_TARGETS` passaria na validacao e daria KeyError."""
    assert set(_SUPPORTED_TARGETS) == set(_IDS_POR_ALVO) == set(ALVOS_DE_STATUS)
