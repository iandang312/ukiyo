from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.db.models import Message
from ukiyo_service.infrastructure.llm import Chunk


pytestmark = pytest.mark.asyncio(loop_scope="session")


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name: str | None = None
        data: dict[str, Any] | None = None
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        assert name is not None and data is not None, block
        events.append((name, data))
    return events


class _FakeStreamProvider:
    def __init__(
        self,
        deltas: list[str],
        tokens_in: int = 10,
        tokens_out: int = 5,
    ) -> None:
        self._deltas = deltas
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out

    async def stream(
        self, messages: Any, model: str, **opts: Any
    ) -> AsyncIterator[Chunk]:
        for d in self._deltas:
            yield Chunk(delta=d, finish_reason=None, tokens_in=None, tokens_out=None)
        yield Chunk(
            delta="",
            finish_reason="stop",
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
        )


@pytest.fixture
def stub_provider(monkeypatch: pytest.MonkeyPatch) -> _FakeStreamProvider:
    fake = _FakeStreamProvider(["Hello", " ", "world"], tokens_in=12, tokens_out=8)
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.get_provider",
        lambda model: fake,
    )
    return fake


async def _drain_sse(client: AsyncClient, url: str, body: dict[str, Any]) -> str:
    raw = b""
    async with client.stream("POST", url, json=body) as resp:
        assert resp.status_code == 200, await resp.aread()
        async for chunk in resp.aiter_bytes():
            raw += chunk
    return raw.decode("utf-8")


async def test_post_message_emits_meta_delta_done_in_order(
    client: AsyncClient, db: AsyncSession, stub_provider: _FakeStreamProvider
) -> None:
    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "hi"},
    )
    events = _parse_sse(raw)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert names.count("delta") == 3

    meta = events[0][1]
    assert meta == {
        "surface": "chat",
        "model": get_settings().GENERALIST_MODEL,
        "bucket": None,
        "confidence": None,
    }

    deltas = [data["content"] for name, data in events if name == "delta"]
    assert "".join(deltas) == "Hello world"

    done = events[-1][1]
    assert done["tokens_in"] == 12
    assert done["tokens_out"] == 8
    assert done["latency_ms"] >= 0
    assert isinstance(done["cost_usd"], str)
    uuid.UUID(done["message_id"])


async def test_post_message_persists_user_and_assistant_in_one_transaction(
    client: AsyncClient, db: AsyncSession, stub_provider: _FakeStreamProvider
) -> None:
    conv = (await client.post("/conversations")).json()
    await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "hi"},
    )

    rows_resp = await client.get(f"/conversations/{conv['id']}/messages")
    assert rows_resp.status_code == 200
    rows = rows_resp.json()
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "hi"
    assert rows[1]["content"] == "Hello world"
    assert rows[1]["model_used"] == get_settings().GENERALIST_MODEL
    assert rows[1]["tokens_in"] == 12
    assert rows[1]["tokens_out"] == 8
    assert rows[1]["cost_usd"] is not None
    assert rows[1]["latency_ms"] is not None
    # Single-transaction guarantee: bucket fields stay null this phase.
    assert rows[1]["bucket_scores"] is None
    assert rows[1]["intent_confidence"] is None


async def test_post_message_404_for_unknown_conversation(
    client: AsyncClient, stub_provider: _FakeStreamProvider
) -> None:
    fake_id = uuid.uuid4()
    resp = await client.post(
        f"/conversations/{fake_id}/messages", json={"content": "hi"}
    )
    assert resp.status_code == 404


async def test_provider_error_persists_no_partial_assistant_message(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ErrorProvider:
        async def stream(
            self, messages: Any, model: str, **opts: Any
        ) -> AsyncIterator[Chunk]:
            yield Chunk(
                delta="partial",
                finish_reason=None,
                tokens_in=None,
                tokens_out=None,
            )
            raise RuntimeError("provider blew up")

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.get_provider",
        lambda model: ErrorProvider(),
    )

    conv = (await client.post("/conversations")).json()
    try:
        async with client.stream(
            "POST",
            f"/conversations/{conv['id']}/messages",
            json={"content": "boom"},
        ) as resp:
            async for _ in resp.aiter_bytes():
                pass
    except Exception:
        pass

    # Defensive: fall back to direct DB inspection — the GET may itself error
    # if the session is in a bad state.
    await db.rollback()
    stmt = select(Message).where(Message.conversation_id == uuid.UUID(conv["id"]))
    rows = list((await db.execute(stmt)).scalars().all())
    assert rows == []
