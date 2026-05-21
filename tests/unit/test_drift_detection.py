"""Unit tests for drift_detection pure module (Sprint 3b.33)."""

from src.google_ads.drift_detection import (
    ChangeEventRow,
    detect_drift,
    dict_to_change_event_row,
)


def _make_row(
    *,
    user_email: str = "pedro.vytor@v4company.com",
    client_type: str = "GOOGLE_ADS_WEB_CLIENT",
    resource_type: str = "CAMPAIGN",
    operation: str = "UPDATE",
    change_date_time: str = "2026-05-20 10:13:00",
    resource_id: str = "22169885957",
    resource_name: str = "CAB - Geral",
    changed_fields: tuple[str, ...] = ("campaign.ai_max_setting.enable_ai_max",),
    campaign_id: str | None = "22169885957",
    ad_group_id: str | None = None,
) -> ChangeEventRow:
    return ChangeEventRow(
        change_date_time=change_date_time,
        user_email=user_email,
        client_type=client_type,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        operation=operation,
        changed_fields=changed_fields,
        campaign_id=campaign_id,
        ad_group_id=ad_group_id,
    )


# === Algorithm tests (16) ===


def test_empty_responsible_list_all_drift():
    """Incident mode default: lista vazia → todos changes são drift."""
    rows = [_make_row(user_email="anyone@v4.com")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    assert result.summary.total_drift_changes == 1
    assert result.summary.total_changes_in_window == 1


def test_single_email_match_no_drift():
    """Happy path co-management: user autorizado → zero drift."""
    rows = [_make_row(user_email="wellinton@v4company.com")]
    result = detect_drift(rows, responsible_user_emails=["wellinton@v4company.com"], limit=100)
    assert result.summary.total_drift_changes == 0
    assert result.summary.total_changes_in_window == 1
    assert result.drift_changes == ()


def test_multi_email_match_partial_drift():
    """V4 multi-gestor: 2 emails autorizados, 1 não-autorizado."""
    rows = [
        _make_row(user_email="wellinton@v4company.com"),
        _make_row(user_email="lucas@v4company.com"),
        _make_row(user_email="intruso@external.com"),
    ]
    result = detect_drift(
        rows,
        responsible_user_emails=["wellinton@v4company.com", "lucas@v4company.com"],
        limit=100,
    )
    assert result.summary.total_drift_changes == 1
    assert result.drift_changes[0].user_email == "intruso@external.com"


def test_auto_apply_always_drift_even_with_full_authorization():
    """Auto-apply ALWAYS goes to drift, mesmo se user_email autorizado."""
    rows = [
        _make_row(
            user_email="wellinton@v4company.com",
            client_type="GOOGLE_ADS_RECOMMENDATIONS",
        )
    ]
    result = detect_drift(rows, responsible_user_emails=["wellinton@v4company.com"], limit=100)
    assert result.summary.total_drift_changes == 1


def test_case_insensitive_email_matching():
    """Email matching é case-insensitive."""
    rows = [_make_row(user_email="Pedro@V4Company.com")]
    result = detect_drift(rows, responsible_user_emails=["PEDRO@v4company.com"], limit=100)
    assert result.summary.total_drift_changes == 0


def test_flag_auto_apply_detected_positive():
    """Flag emitida quando há GOOGLE_ADS_RECOMMENDATIONS."""
    rows = [_make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email="")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "auto_apply_detected" in flag_codes


def test_flag_auto_apply_detected_negative():
    """Sem GOOGLE_ADS_RECOMMENDATIONS → flag ausente."""
    rows = [_make_row(client_type="GOOGLE_ADS_WEB_CLIENT")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "auto_apply_detected" not in flag_codes


def test_flag_multiple_users_detected_positive():
    """2+ users não-autorizados → flag emitida."""
    rows = [
        _make_row(user_email="pedro@v4company.com"),
        _make_row(user_email="lucas@v4company.com"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "multiple_users_detected" in flag_codes


def test_flag_multiple_users_detected_negative():
    """Apenas 1 user não-autorizado → flag ausente."""
    rows = [
        _make_row(user_email="pedro@v4company.com"),
        _make_row(user_email="pedro@v4company.com"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "multiple_users_detected" not in flag_codes


def test_flag_multiple_users_ignores_auto_apply_bucket():
    """Auto-apply não conta como user adicional pra multiple_users flag."""
    rows = [
        _make_row(user_email="pedro@v4company.com"),
        _make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email=""),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "multiple_users_detected" not in flag_codes
    assert "auto_apply_detected" in flag_codes


def test_flag_structural_change_positive():
    """REMOVE em CAMPAIGN → flag emitida."""
    rows = [_make_row(operation="REMOVE", resource_type="CAMPAIGN")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "structural_change" in flag_codes


def test_flag_structural_change_negative():
    """UPDATE em CAMPAIGN não trigger structural_change."""
    rows = [_make_row(operation="UPDATE", resource_type="CAMPAIGN")]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    flag_codes = [f.code for f in result.flags]
    assert "structural_change" not in flag_codes


def test_aggregation_by_user_with_auto_apply_collapse():
    """Auto-apply rows aggregam em bucket sintético 'auto-apply'."""
    rows = [
        _make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email=""),
        _make_row(client_type="GOOGLE_ADS_RECOMMENDATIONS", user_email=""),
        _make_row(user_email="pedro@v4company.com"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    assert result.summary.by_user["auto-apply"] == 2
    assert result.summary.by_user["pedro@v4company.com"] == 1


def test_aggregation_by_resource_type_counter():
    """by_resource_type conta corretamente."""
    rows = [
        _make_row(resource_type="CAMPAIGN"),
        _make_row(resource_type="CAMPAIGN"),
        _make_row(resource_type="AD_GROUP"),
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=100)
    assert result.summary.by_resource_type["CAMPAIGN"] == 2
    assert result.summary.by_resource_type["AD_GROUP"] == 1


def test_truncation_limit_exceeded():
    """50 rows + limit=10 → truncated=True, returned 10."""
    rows = [
        _make_row(change_date_time=f"2026-05-20 10:{i:02d}:00", resource_id=str(i))
        for i in range(50)
    ]
    result = detect_drift(rows, responsible_user_emails=[], limit=10)
    assert result.truncated is True
    assert len(result.drift_changes) == 10
    assert result.summary.total_drift_changes == 50


def test_total_drift_vs_total_in_window_invariant():
    """total_in_window >= total_drift_changes sempre."""
    rows = [
        _make_row(user_email="wellinton@v4company.com"),
        _make_row(user_email="pedro@v4company.com"),
    ]
    result = detect_drift(rows, responsible_user_emails=["wellinton@v4company.com"], limit=100)
    assert result.summary.total_changes_in_window >= result.summary.total_drift_changes
    assert result.summary.total_changes_in_window == 2
    assert result.summary.total_drift_changes == 1


# === Boundary parser tests (3) ===


def test_dict_to_change_event_row_minimum():
    """Parser handles minimum dict (missing fields → defaults)."""
    d: dict = {"change_date_time": "2026-05-20 10:13:00", "user_email": "p@v4.com"}
    row = dict_to_change_event_row(d)
    assert row.change_date_time == "2026-05-20 10:13:00"
    assert row.user_email == "p@v4.com"
    assert row.changed_fields == ()
    assert row.campaign_id is None
    assert row.ad_group_id is None


def test_dict_to_change_event_row_changed_fields_list_to_tuple():
    """changed_fields list converte pra tuple (frozen dataclass requirement)."""
    d = {"changed_fields": ["a.b", "c.d"]}
    row = dict_to_change_event_row(d)
    assert row.changed_fields == ("a.b", "c.d")
    assert isinstance(row.changed_fields, tuple)


def test_dict_to_change_event_row_preserves_optional_ids():
    """campaign_id/ad_group_id preservados quando presentes."""
    d = {"campaign_id": "123", "ad_group_id": "456"}
    row = dict_to_change_event_row(d)
    assert row.campaign_id == "123"
    assert row.ad_group_id == "456"


def test_dict_to_change_event_row_handles_none_changed_fields():
    """Parser defensive: changed_fields=None upstream → tuple() (não TypeError)."""
    d = {"changed_fields": None}
    row = dict_to_change_event_row(d)
    assert row.changed_fields == ()
