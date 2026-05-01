from __future__ import annotations

import pytest
from httpx import AsyncClient

from ukiyo_service.infrastructure.db.session import DEV_USER_EMAIL, DEV_USER_ID


pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_me_returns_dev_user(client: AsyncClient) -> None:
    resp = await client.get("/me")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": str(DEV_USER_ID), "email": DEV_USER_EMAIL}


async def test_cors_preflight_health_allows_dev_origin(
    client: AsyncClient,
) -> None:
    resp = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "GET" in resp.headers.get("access-control-allow-methods", "")


async def test_cors_disallows_unknown_origin(client: AsyncClient) -> None:
    resp = await client.get(
        "/health", headers={"Origin": "http://evil.example"}
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers
