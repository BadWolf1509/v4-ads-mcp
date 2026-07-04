"""Unit tests for _csv_safe — CSV formula-injection mitigation (export_csv_rows).

Excel/Sheets treat a leading =, +, -, @ (or tab) as a formula trigger. A
manager_email/operation/error_message/provider_request_id value starting with
one of these chars would execute as a formula when the exported CSV is opened
in Excel (classic CSV injection). Prefixing with `'` neutralizes it.
"""

import pytest

from src.db.repositories.audit_log import _csv_safe


@pytest.mark.parametrize(
    "raw",
    [
        "=cmd|'/c calc'!A1",
        "=1+1",
        "+1234567890",
        "-2+3",
        "@SUM(1+1)",
        "\tmalicious",
    ],
)
def test_csv_safe_prefixes_formula_trigger_chars(raw: str) -> None:
    out = _csv_safe(raw)
    assert out.startswith("'")
    assert out == "'" + raw


@pytest.mark.parametrize(
    "raw",
    [
        "normal operation name",
        "erro comum: campanha nao encontrada",
        "req-abc-123",
        "gestor@v4company.com",
        "",
    ],
)
def test_csv_safe_leaves_normal_values_untouched(raw: str) -> None:
    assert _csv_safe(raw) == raw
