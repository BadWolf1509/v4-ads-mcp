"""Builder tests for negatives.py add/remove (Onda 2 — fecha F50/F51 + A4/A5).

A4: add_negative_keywords DEVE setar negative=True (um False silencioso
adicionaria keywords POSITIVAS — gasto invertido). A5: remove usa o campo
`remove` = resource path string (não um sub-message create).
"""

from src.google_ads.mutates.negatives import (
    build_add_negative_keywords,
    build_remove_negative_keywords,
)
from tests.unit.fixtures.proto_capture import make_capture_client


def test_add_negative_keywords_sets_negative_true_and_keyword() -> None:
    client = make_capture_client()
    ops = build_add_negative_keywords(
        client,
        "1234567890",
        {"campaign_id": "111", "keywords": [{"text": "comprar barato", "match_type": "PHRASE"}]},
    )
    assert len(ops) == 1
    base = "campaign_criterion_operation.create"
    assert ops[0].field(f"{base}.campaign") == "customers/1234567890/campaigns/111"
    # A4: negative DEVE ser True
    assert ops[0].field(f"{base}.negative") is True
    assert ops[0].field(f"{base}.keyword.text") == "comprar barato"
    # KeywordMatchTypeEnum é _BareEnumDict → key
    assert ops[0].field(f"{base}.keyword.match_type") == "PHRASE"


def test_remove_negative_keywords_sets_remove_path() -> None:
    client = make_capture_client()
    ops = build_remove_negative_keywords(
        client, "1234567890", {"campaign_id": "111", "criterion_ids": ["222", "333"]}
    )
    assert len(ops) == 2
    # A5: remove = string path composto (campanha~criterion)
    assert (
        ops[0].field("campaign_criterion_operation.remove")
        == "customers/1234567890/campaignCriteria/111~222"
    )
    assert (
        ops[1].field("campaign_criterion_operation.remove")
        == "customers/1234567890/campaignCriteria/111~333"
    )
