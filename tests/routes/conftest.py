from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.application.deps import get_db
from ukiyo_service.application.main import app
from ukiyo_service.infrastructure.db.session import ensure_dev_user


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """ASGI client wired to share the test's savepoint-rollback session.

    Lifespan is intentionally skipped (`ASGITransport` doesn't run it) so the
    real engine never touches the test DB; we seed the dev user manually on
    the test session instead.
    """
    await ensure_dev_user(db)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
