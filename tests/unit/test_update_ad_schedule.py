"""update_ad_schedule (spec §4): grade completa, dry-run com CPA, orcamento compartilhado, no-op."""

from __future__ import annotations

from src.governance.blast_radius import RiskLevel, classify


def test_classify_conhece_a_operacao_e_confirma() -> None:
    """Sem entrada propria a tool cai no 'unknown operation — default seguro' (nota do estado-atual)."""
    r = classify(operation="update_ad_schedule", params={"target_count": 3})
    assert r.level is RiskLevel.CONFIRM
    assert "unknown" not in r.reason
