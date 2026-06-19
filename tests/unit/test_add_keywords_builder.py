"""Unit tests for build_add_keywords builder.

Usa make_capture_client (NÃO MagicMock) pra assertar os field assignments de
proto reais — MagicMock aceitaria qualquer atributo silenciosamente e mascararia
texto/match_type/bid errados (F16/F42/F44)."""

import pytest

from tests.unit.fixtures.proto_capture import make_capture_client


@pytest.fixture
def client():
    return make_capture_client()


def test_builder_emits_one_op_per_keyword(client):
    from src.google_ads.mutates.keywords import build_add_keywords

    payload = {
        "ad_group_id": "111",
        "keywords": [
            {"text": "nutricionista jp", "match_type": "EXACT"},
            {"text": "nutricionista esportiva", "match_type": "PHRASE"},
        ],
    }
    ops = build_add_keywords(client, "1234567890", payload)
    assert len(ops) == 2

    base = "ad_group_criterion_operation.create"
    # op 0 — campos exatos escritos no create
    assert ops[0].field(f"{base}.ad_group") == "customers/1234567890/adGroups/111"
    assert ops[0].field(f"{base}.status") == "AG_ENABLED"  # ENABLED por default
    assert ops[0].field(f"{base}.keyword.text") == "nutricionista jp"
    assert ops[0].field(f"{base}.keyword.match_type") == "EXACT"
    # op 1 — text/match_type distintos provam que não há vazamento entre ops
    assert ops[1].field(f"{base}.keyword.text") == "nutricionista esportiva"
    assert ops[1].field(f"{base}.keyword.match_type") == "PHRASE"


def test_builder_supports_optional_cpc_bid_micros(client):
    from src.google_ads.mutates.keywords import build_add_keywords

    payload = {
        "ad_group_id": "111",
        "keywords": [
            {"text": "kw com bid", "match_type": "EXACT", "cpc_bid_micros": 2000000},
            {"text": "kw sem bid", "match_type": "PHRASE"},
        ],
    }
    ops = build_add_keywords(client, "1234567890", payload)
    assert len(ops) == 2

    base = "ad_group_criterion_operation.create"
    # presente → setado com o valor; ausente → NÃO setado (herda o bid do ad_group)
    assert ops[0].has(f"{base}.cpc_bid_micros") is True
    assert ops[0].field(f"{base}.cpc_bid_micros") == 2000000
    assert ops[1].has(f"{base}.cpc_bid_micros") is False


def test_builder_match_type_case_normalized(client):
    """match_type 'exact' (lowercase) é normalizado pra 'EXACT' no campo escrito."""
    from src.google_ads.mutates.keywords import build_add_keywords

    payload = {
        "ad_group_id": "111",
        "keywords": [{"text": "x", "match_type": "exact"}],
    }
    ops = build_add_keywords(client, "1234567890", payload)
    assert len(ops) == 1
    assert ops[0].field("ad_group_criterion_operation.create.keyword.match_type") == "EXACT"


def test_builder_empty_list_returns_empty(client):
    """Edge: lista vazia → ops vazia (schema rejeita, mas o builder é defensivo)."""
    from src.google_ads.mutates.keywords import build_add_keywords

    ops = build_add_keywords(client, "1234567890", {"ad_group_id": "111", "keywords": []})
    assert ops == []
