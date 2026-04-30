from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.infrastructure.db.models import User
from ukiyo_service.infrastructure.db.session import (
    DEV_USER_EMAIL,
    DEV_USER_ID,
    ensure_dev_user,
)


pytestmark = pytest.mark.asyncio


async def test_ensure_dev_user_seeds_on_empty_db(db: AsyncSession) -> None:
    user = await ensure_dev_user(db)

    assert user.id == DEV_USER_ID
    assert user.email.lower() == DEV_USER_EMAIL

    count = await db.execute(select(User).where(User.id == DEV_USER_ID))
    assert count.scalars().one() is not None


async def test_ensure_dev_user_is_idempotent(db: AsyncSession) -> None:
    a = await ensure_dev_user(db)
    b = await ensure_dev_user(db)
    c = await ensure_dev_user(db)

    assert a.id == b.id == c.id == DEV_USER_ID

    result = await db.execute(select(User).where(User.id == DEV_USER_ID))
    assert len(result.scalars().all()) == 1
