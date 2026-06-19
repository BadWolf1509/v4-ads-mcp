"""Unit tests for build_add_negatives_from_search_terms builder.

Usa make_capture_client (NÃO MagicMock) pra assertar dispatch por scope +
negative=True + keyword.text/match_type. A regressão clássica A4 (Google trocava
negative=True por False) só é pega assertando o campo real — MagicMock mascara."""

import pytest

from tests.unit.fixtures.proto_capture import make_capture_client


@pytest.fixture
def client():
    return make_capture_client()


def test_builder_dispatches_campaign_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {
                "search_term": "ruim 1",
                "match_type": "EXACT",
                "scope": "campaign",
                "scope_id": "111",
            },
            {
                "search_term": "ruim 2",
                "match_type": "PHRASE",
                "scope": "campaign",
                "scope_id": "111",
            },
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 2

    base = "campaign_criterion_operation.create"
    assert ops[0].field(f"{base}.campaign") == "customers/1234567890/campaigns/111"
    assert ops[0].field(f"{base}.negative") is True  # exclusão, NÃO keyword positiva
    assert ops[0].field(f"{base}.keyword.text") == "ruim 1"
    assert ops[0].field(f"{base}.keyword.match_type") == "EXACT"
    assert ops[1].field(f"{base}.keyword.match_type") == "PHRASE"


def test_builder_dispatches_ad_group_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "termo", "match_type": "EXACT", "scope": "ad_group", "scope_id": "222"},
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 1

    base = "ad_group_criterion_operation.create"
    assert ops[0].field(f"{base}.ad_group") == "customers/1234567890/adGroups/222"
    assert ops[0].field(f"{base}.negative") is True
    assert ops[0].field(f"{base}.keyword.text") == "termo"
    assert ops[0].field(f"{base}.keyword.match_type") == "EXACT"


def test_builder_dispatches_shared_set_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {
                "search_term": "compartilhada",
                "match_type": "BROAD",
                "scope": "shared_set",
                "scope_id": "333",
            },
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 1

    base = "shared_criterion_operation.create"
    assert ops[0].field(f"{base}.shared_set") == "customers/1234567890/sharedSets/333"
    # shared_set NÃO seta negative (o próprio conjunto já é de negativas) — ausente
    assert ops[0].has(f"{base}.negative") is False
    assert ops[0].field(f"{base}.keyword.text") == "compartilhada"
    assert ops[0].field(f"{base}.keyword.match_type") == "BROAD"


def test_builder_mixes_scopes_in_single_call(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "t1", "match_type": "EXACT", "scope": "campaign", "scope_id": "111"},
            {"search_term": "t2", "match_type": "EXACT", "scope": "ad_group", "scope_id": "222"},
            {"search_term": "t3", "match_type": "EXACT", "scope": "shared_set", "scope_id": "333"},
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 3
    # cada row vai pro oneof correto (dispatch por scope)
    assert ops[0].has("campaign_criterion_operation.create.campaign") is True
    assert ops[1].has("ad_group_criterion_operation.create.ad_group") is True
    assert ops[2].has("shared_criterion_operation.create.shared_set") is True


def test_builder_rejects_unknown_scope(client):
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "x", "match_type": "EXACT", "scope": "account", "scope_id": "1"},
        ]
    }
    with pytest.raises(ValueError):
        build_add_negatives_from_search_terms(client, "1234567890", payload)


def test_builder_default_match_type_is_exact(client):
    """Items sem match_type defaultam pra EXACT (spec §3.2) — campo escrito é EXACT."""
    from src.google_ads.mutates.negatives import build_add_negatives_from_search_terms

    payload = {
        "negatives": [
            {"search_term": "x", "scope": "campaign", "scope_id": "111"},
        ]
    }
    ops = build_add_negatives_from_search_terms(client, "1234567890", payload)
    assert len(ops) == 1
    assert ops[0].field("campaign_criterion_operation.create.keyword.match_type") == "EXACT"
