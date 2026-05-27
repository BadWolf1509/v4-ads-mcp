"""Unit tests for _row_formatter em get_keyword_performance (Sprint 3b.40 B9).

Pure formatter — mocks SDK row attributes. Validates F56 fix (negative field).
"""

from types import SimpleNamespace

from src.mcp.tools.get_keyword_performance import _row_formatter


def _fake_enum(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _make_sdk_row(*, negative: bool, criterion_id: int = 12345) -> SimpleNamespace:
    """Construct minimal SDK-like row object with all fields _row_formatter needs."""
    return SimpleNamespace(
        ad_group_criterion=SimpleNamespace(
            criterion_id=criterion_id,
            keyword=SimpleNamespace(
                text="aluguel de airless",
                match_type=_fake_enum("BROAD"),
            ),
            status=_fake_enum("ENABLED"),
            negative=negative,
            quality_info=SimpleNamespace(
                quality_score=7,
                creative_quality_score=_fake_enum("ABOVE_AVERAGE"),
                post_click_quality_score=_fake_enum("AVERAGE"),
                search_predicted_ctr=_fake_enum("BELOW_AVERAGE"),
            ),
            position_estimates=SimpleNamespace(
                first_page_cpc_micros=500_000,  # R$0.50
                top_of_page_cpc_micros=1_200_000,  # R$1.20
            ),
        ),
        ad_group=SimpleNamespace(id=1001, name="AG1"),
        campaign=SimpleNamespace(id=10, name="C1"),
        metrics=SimpleNamespace(
            impressions=100,
            clicks=10,
            cost_micros=5_000_000,  # R$5.00
            conversions=1.0,
            conversions_value=50.0,
        ),
    )


def test_b9_negative_field_false_when_positive_criterion():
    """B9 (F56): row positiva → negative=False (bool, não None)."""
    row = _make_sdk_row(negative=False)
    out = _row_formatter(row)
    assert out["negative"] is False
    assert isinstance(out["negative"], bool)


def test_b9_negative_field_true_when_negative_criterion():
    """B9 (F56): row negativa → negative=True."""
    row = _make_sdk_row(negative=True, criterion_id=99999)
    out = _row_formatter(row)
    assert out["negative"] is True
    assert out["criterion_id"] == "99999"
