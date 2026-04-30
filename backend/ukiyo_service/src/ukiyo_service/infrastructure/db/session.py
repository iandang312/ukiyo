from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.db.models import User


logger = logging.getLogger(__name__)


DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_USER_EMAIL = "dev@local"


_settings = get_settings()

engine = create_async_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def ensure_dev_user(session: AsyncSession) -> User:
    stmt = (
        pg_insert(User)
        .values(id=DEV_USER_ID, email=DEV_USER_EMAIL, password_hash="")
        .on_conflict_do_nothing(index_elements=[User.id])
    )
    result = await session.execute(stmt)
    await session.commit()

    if result.rowcount and result.rowcount > 0:
        logger.info("dev user seeded id=%s email=%s", DEV_USER_ID, DEV_USER_EMAIL)
    else:
        logger.info("dev user already present id=%s", DEV_USER_ID)

    user = await session.get(User, DEV_USER_ID)
    assert user is not None
    return user
