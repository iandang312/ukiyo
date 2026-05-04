from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.db.models import Conversation, User


pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_post_conversation_returns_chat_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    resp = await client.post("/conversations")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Chat: 1"
    assert body["auto_route_enabled"] is True
    assert body["pinned_model"] is None
    uuid.UUID(body["id"])  # parses


async def test_titles_increment_per_user(
    client: AsyncClient, db: AsyncSession
) -> None:
    titles = []
    for _ in range(3):
        resp = await client.post("/conversations")
        assert resp.status_code == 201
        titles.append(resp.json()["title"])
    assert titles == ["Chat: 1", "Chat: 2", "Chat: 3"]


async def test_list_conversations_orders_updated_at_desc(
    client: AsyncClient, db: AsyncSession
) -> None:
    a = (await client.post("/conversations")).json()
    b = (await client.post("/conversations")).json()
    c = (await client.post("/conversations")).json()

    # `now()` returns the outer transaction's start time, so all three rows
    # would otherwise share `updated_at`. Set explicit timestamps to assert
    # the route's ordering deterministically.
    base = datetime.now(timezone.utc)
    for offset, conv_id in [(1, a["id"]), (3, b["id"]), (2, c["id"])]:
        await db.execute(
            text("UPDATE conversations SET updated_at = :ts WHERE id = :id"),
            {"ts": base + timedelta(seconds=offset), "id": uuid.UUID(conv_id)},
        )
    await db.commit()

    resp = await client.get("/conversations")
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert ids == [b["id"], c["id"], a["id"]]


async def test_list_messages_empty_for_new_conversation(
    client: AsyncClient,
) -> None:
    conv = (await client.post("/conversations")).json()
    resp = await client.get(f"/conversations/{conv['id']}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_messages_404_for_unknown_conversation(
    client: AsyncClient,
) -> None:
    fake = uuid.uuid4()
    resp = await client.get(f"/conversations/{fake}/messages")
    assert resp.status_code == 404


async def test_list_messages_404_for_other_users_conversation(
    client: AsyncClient, db: AsyncSession
) -> None:
    other = User(email="someone-else@local", password_hash="")
    db.add(other)
    await db.flush()
    other_conv = Conversation(user_id=other.id, title="theirs")
    db.add(other_conv)
    await db.commit()

    resp = await client.get(f"/conversations/{other_conv.id}/messages")
    assert resp.status_code == 404


# --- Phase 8: PATCH /conversations/{id} + GET /models ----------------------


async def test_patch_sets_pinned_model_and_disables_auto_route(
    client: AsyncClient,
) -> None:
    settings = get_settings()
    conv = (await client.post("/conversations")).json()

    resp = await client.patch(
        f"/conversations/{conv['id']}",
        json={
            "pinned_model": settings.BUCKET_MODEL_MAP["design"],
            "auto_route_enabled": False,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pinned_model"] == settings.BUCKET_MODEL_MAP["design"]
    assert data["auto_route_enabled"] is False


async def test_patch_clears_pin_and_re_enables_auto_route(
    client: AsyncClient,
) -> None:
    settings = get_settings()
    conv = (await client.post("/conversations")).json()
    await client.patch(
        f"/conversations/{conv['id']}",
        json={
            "pinned_model": settings.GENERALIST_MODEL,
            "auto_route_enabled": False,
        },
    )

    resp = await client.patch(
        f"/conversations/{conv['id']}",
        json={"pinned_model": None, "auto_route_enabled": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pinned_model"] is None
    assert data["auto_route_enabled"] is True


async def test_patch_partial_update_only_touches_sent_fields(
    client: AsyncClient,
) -> None:
    """Sending just `auto_route_enabled` must not clobber `pinned_model`.

    Picker selection and the auto-route toggle are independent surfaces in
    the UI; the server has to respect that or the picker gets cleared every
    time the toggle moves."""
    settings = get_settings()
    conv = (await client.post("/conversations")).json()
    pin = settings.BUCKET_MODEL_MAP["coding"]
    await client.patch(
        f"/conversations/{conv['id']}",
        json={"pinned_model": pin, "auto_route_enabled": False},
    )

    resp = await client.patch(
        f"/conversations/{conv['id']}",
        json={"auto_route_enabled": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pinned_model"] == pin
    assert data["auto_route_enabled"] is True


async def test_patch_404_for_unknown_conversation(client: AsyncClient) -> None:
    resp = await client.patch(
        f"/conversations/{uuid.uuid4()}",
        json={"pinned_model": None, "auto_route_enabled": True},
    )
    assert resp.status_code == 404


async def test_patch_404_for_other_users_conversation(
    client: AsyncClient, db: AsyncSession
) -> None:
    other = User(email="someone-else-patch@local", password_hash="")
    db.add(other)
    await db.flush()
    other_conv = Conversation(user_id=other.id, title="theirs")
    db.add(other_conv)
    await db.commit()

    resp = await client.patch(
        f"/conversations/{other_conv.id}",
        json={"pinned_model": None, "auto_route_enabled": True},
    )
    assert resp.status_code == 404


async def test_patch_422_for_disallowed_model(client: AsyncClient) -> None:
    """The picker only ever surfaces generalist + bucket models; reject
    anything else so a stale frontend can't pin a model the routing layer
    doesn't know how to fall back from."""
    conv = (await client.post("/conversations")).json()
    resp = await client.patch(
        f"/conversations/{conv['id']}",
        json={
            "pinned_model": "gpt-3.5-turbo-instruct-not-real",
            "auto_route_enabled": False,
        },
    )
    assert resp.status_code == 422


async def test_get_models_returns_settings_shape(client: AsyncClient) -> None:
    settings = get_settings()
    resp = await client.get("/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["generalist"] == settings.GENERALIST_MODEL
    assert data["buckets"] == dict(settings.BUCKET_MODEL_MAP)
