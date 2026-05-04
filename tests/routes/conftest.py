from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.application.deps import get_db
from ukiyo_service.application.main import app
from ukiyo_service.infrastructure.db.session import ensure_dev_user


@pytest.fixture(autouse=True)
def _stub_routing_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default route tests to no-op embed + empty classifier so they never
    hit OpenAI.

    Phase 7 made `messages.py` embed the prompt itself (so it can also feed
    hysteresis), then call `classify_from_embedding`. Both call sites would
    otherwise burn embedding tokens in CI. Tests that need a specific vector
    or bucket scores override these with their own `monkeypatch.setattr(...)`
    — the later patch wins.
    """

    async def _empty_embed(text: str) -> list[float]:
        return [0.0] * 1536

    async def _empty_classify(
        prompt_vec: list[float],
        session: Any,
        *,
        prompt_for_heuristics: str,
    ) -> dict[str, float]:
        return {}

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.embed",
        _empty_embed,
    )
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify_from_embedding",
        _empty_classify,
    )


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
