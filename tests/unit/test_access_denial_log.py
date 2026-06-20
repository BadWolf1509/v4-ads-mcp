"""A negação de acesso Google deve emitir log.warning (evento de segurança visível)."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from structlog.testing import capture_logs

from src.google_ads import access


@pytest.mark.asyncio
async def test_denial_emits_warning_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        access.manager_account_access, "can_manager_access", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(access.audit_log, "record", AsyncMock(return_value=1))

    with capture_logs() as logs, pytest.raises(access.AccountAccessDeniedError):
        await access.ensure_account_access(
            MagicMock(),
            manager_id=uuid4(),
            customer_id="1234567890",
            session_id=uuid4(),
            operation_name="get_campaign_performance",
            level="read",
        )

    events = [e for e in logs if e["event"] == "account_access_denied"]
    assert len(events) == 1
    assert events[0]["customer_id"] == "1234567890"
    assert events[0]["operation"] == "get_campaign_performance"
