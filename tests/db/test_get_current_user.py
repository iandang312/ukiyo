from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.application.deps import get_current_user
from ukiyo_service.infrastructure.db.session import (
    DEV_USER_ID,
    ensure_dev_user,
)


pytestmark = pytest.mark.asyncio


async def test_get_current_user_returns_seeded_dev_user(db: AsyncSession) -> None:
    await ensure_dev_user(db)

    user = await get_current_user(db)
    assert user.id == DEV_USER_ID


async def test_get_current_user_raises_when_not_seeded(db: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await get_current_user(db)
    assert exc.value.status_code == 401
