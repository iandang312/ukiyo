from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.db.models import Base


def _db_reachable(url: str) -> bool:
    async def _probe() -> bool:
        eng = create_async_engine(url)
        try:
            async with eng.connect() as conn:
                await conn.exec_driver_sql("SELECT 1")
            return True
        except Exception:
            return False
        finally:
            await eng.dispose()

    try:
        return asyncio.run(_probe())
    except Exception:
        return False


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    url = get_settings().DATABASE_URL
    if not _db_reachable(url):
        pytest.skip(f"database not reachable at {url}")
    return url


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url, future=True)
    async with eng.begin() as conn:
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS citext")
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await eng.dispose()


@pytest_asyncio.fixture
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Per-test session bound to a connection wrapped in an outer transaction.

    Session uses `join_transaction_mode="create_savepoint"` so calls to
    `session.commit()` release a SAVEPOINT instead of committing the outer
    transaction. The outer transaction is rolled back at teardown — nothing
    persists across tests.
    """
    async with engine.connect() as conn:
        outer = await conn.begin()
        Session = async_sessionmaker(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        async with Session() as session:
            try:
                yield session
            finally:
                await session.close()
        await outer.rollback()
