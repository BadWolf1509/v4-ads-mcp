from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.google_ads.access import AccountAccessDeniedError
from src.governance import dry_run


@pytest.mark.asyncio
async def test_create_pending_denies_without_grant():
    conn = AsyncMock()
    with (
        patch(
            "src.governance.dry_run.ensure_account_access",
            AsyncMock(side_effect=AccountAccessDeniedError("x")),
        ),
        pytest.raises(AccountAccessDeniedError),
    ):
        await dry_run.create_pending(
            conn,
            manager_id=uuid4(),
            session_id=uuid4(),
            customer_id="999",
            operation_type="update_campaign_status",
            payload={},
            blast_summary="...",
        )
    conn.execute.assert_not_called()  # no token minted without access
