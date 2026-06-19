"""Unit test for meta_resync payload mapping (pure logic, no I/O)."""


def test_to_payload_maps_graph_rows():
    from src.jobs.meta_resync import _to_payload

    out = _to_payload(
        [
            {
                "id": "act_123",
                "name": "Conta X",
                "business": {"id": "b1", "name": "BM X"},
                "currency": "BRL",
                "timezone_name": "America/Sao_Paulo",
                "account_status": 1,
            },
            {"id": "456", "name": "Conta Y"},  # sem prefixo act_, sem business
        ]
    )

    assert out[0]["ad_account_id"] == "act_123"
    assert out[0]["business_id"] == "b1"
    assert out[0]["business_name"] == "BM X"
    # prefixo act_ adicionado quando ausente
    assert out[1]["ad_account_id"] == "act_456"
    assert out[1]["business_id"] is None
    assert out[1]["account_name"] == "Conta Y"
