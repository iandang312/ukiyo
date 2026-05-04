"""Phase 6: routing wired into POST /conversations/{id}/messages.

`classify` is stubbed per-test so we exercise the routing contract (bucket
scores -> ModelChoice -> meta event + DB row) without burning embedding
tokens or needing seeded `bucket_exemplars` in the test DB. The classifier
itself has its own unit tests under `tests/routing/`.
"""
from __future__ import annotations

import json
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
        tokens_in: int = 7,
        tokens_out: int = 4,
    ) -> None:
        self._deltas = deltas
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.last_model: str | None = None

    async def stream(
        self, messages: Any, model: str, **opts: Any
    ) -> AsyncIterator[Chunk]:
        self.last_model = model
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
    fake = _FakeStreamProvider(["ok"])
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.get_provider",
        lambda model: fake,
    )
    return fake


def _stub_classify(
    monkeypatch: pytest.MonkeyPatch, scores: dict[str, float]
) -> None:
    async def _fake(prompt: str, session: Any) -> dict[str, float]:
        return dict(scores)

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify",
        _fake,
    )


async def _post_and_collect(
    client: AsyncClient, conv_id: str, content: str
) -> list[tuple[str, dict[str, Any]]]:
    raw = b""
    async with client.stream(
        "POST",
        f"/conversations/{conv_id}/messages",
        json={"content": content},
    ) as resp:
        assert resp.status_code == 200, await resp.aread()
        async for chunk in resp.aiter_bytes():
            raw += chunk
    return _parse_sse(raw.decode("utf-8"))


async def test_coding_prompt_routes_to_coding_model(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    _stub_classify(monkeypatch, {"coding": 0.78, "research": 0.31, "design": 0.22})

    conv = (await client.post("/conversations")).json()
    events = await _post_and_collect(
        client, conv["id"], "def fizzbuzz(n):\n    pass\n# fix this"
    )

    assert events[0][0] == "meta"
    meta = events[0][1]
    assert meta["surface"] == "chat"
    assert meta["bucket"] == "coding"
    assert meta["model"] == settings.BUCKET_MODEL_MAP["coding"]
    assert meta["confidence"] == pytest.approx(0.78)
    # Provider lookup matches the routed model — not the generalist.
    assert stub_provider.last_model == settings.BUCKET_MODEL_MAP["coding"]


async def test_research_prompt_routes_to_research_model(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    _stub_classify(monkeypatch, {"coding": 0.21, "research": 0.83, "design": 0.34})

    conv = (await client.post("/conversations")).json()
    events = await _post_and_collect(
        client,
        conv["id"],
        "what does the literature say about transformer scaling laws",
    )

    meta = events[0][1]
    assert meta["bucket"] == "research"
    assert meta["model"] == settings.BUCKET_MODEL_MAP["research"]
    assert meta["confidence"] == pytest.approx(0.83)
    assert stub_provider.last_model == settings.BUCKET_MODEL_MAP["research"]


async def test_design_prompt_routes_to_design_model(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    _stub_classify(monkeypatch, {"coding": 0.22, "research": 0.31, "design": 0.71})

    conv = (await client.post("/conversations")).json()
    events = await _post_and_collect(
        client, conv["id"], "wireframe for a SaaS pricing page"
    )

    meta = events[0][1]
    assert meta["bucket"] == "design"
    assert meta["model"] == settings.BUCKET_MODEL_MAP["design"]
    assert meta["confidence"] == pytest.approx(0.71)
    assert stub_provider.last_model == settings.BUCKET_MODEL_MAP["design"]


async def test_ambiguous_prompt_falls_back_to_generalist(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    # All three buckets sit below the 0.55 confidence floor.
    _stub_classify(monkeypatch, {"coding": 0.40, "research": 0.42, "design": 0.39})

    conv = (await client.post("/conversations")).json()
    events = await _post_and_collect(client, conv["id"], "hi")

    meta = events[0][1]
    assert meta["bucket"] is None
    assert meta["model"] == settings.GENERALIST_MODEL
    # confidence is normalized to None on fallback so the UI badge reads
    # "no routing decision" instead of a misleading sub-floor float.
    assert meta["confidence"] is None
    assert stub_provider.last_model == settings.GENERALIST_MODEL


async def test_assistant_row_persists_bucket_scores_and_confidence(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DB row keeps the raw `choice.confidence` even when the meta event
    normalizes it. Floor / fallback rows still surface in analytics."""
    scores = {"coding": 0.78, "research": 0.31, "design": 0.22}
    _stub_classify(monkeypatch, scores)

    conv = (await client.post("/conversations")).json()
    await _post_and_collect(client, conv["id"], "def add(a, b): return a + b")

    rows = list(
        (
            await db.execute(
                select(Message).where(Message.role == "assistant")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assistant = rows[0]
    assert assistant.bucket_scores == scores
    assert assistant.intent_confidence == pytest.approx(0.78)
    assert assistant.model_used == get_settings().BUCKET_MODEL_MAP["coding"]
