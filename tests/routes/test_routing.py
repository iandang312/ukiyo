"""Phase 6 / 7 / 8: routing, hysteresis, and pinning wired into
POST /conversations/{id}/messages.

`embed` and `classify_from_embedding` are stubbed per-test so we exercise the
routing contract (bucket scores -> ModelChoice -> meta event + DB row) and
the hysteresis policy without burning embedding tokens or needing seeded
`bucket_exemplars` in the test DB. The classifier itself has its own unit
tests under `tests/routing/`.
"""
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
from ukiyo_service.infrastructure.db.models import Conversation, Message
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
    async def _fake(
        prompt_vec: list[float],
        session: Any,
        *,
        prompt_for_heuristics: str,
    ) -> dict[str, float]:
        return dict(scores)

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify_from_embedding",
        _fake,
    )


def _stub_embed(
    monkeypatch: pytest.MonkeyPatch, vector: list[float]
) -> None:
    async def _fake(text: str) -> list[float]:
        return list(vector)

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.embed",
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


# --- Phase 7: hysteresis ---------------------------------------------------


def _seed_intent(vector: list[float], bucket: str) -> dict[str, Any]:
    """Vector + bucket payload for stamping a conversation's prior intent.

    Used by the hysteresis tests to set `last_intent_*` on a fresh
    conversation row without going through a full streamed turn first.
    """
    return {"last_intent_vector": vector, "last_intent_bucket": bucket}


async def _stamp_conversation(
    db: AsyncSession, conv_id: str, **fields: Any
) -> None:
    """Patch a conversation row directly. The HTTP surface intentionally
    won't expose `last_intent_*`; tests need a back-door to seed it."""
    conv = (
        await db.execute(
            select(Conversation).where(Conversation.id == uuid.UUID(conv_id))
        )
    ).scalar_one()
    for k, v in fields.items():
        setattr(conv, k, v)
    await db.commit()


async def test_hysteresis_reuses_prior_model_on_close_followup(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """High-cosine follow-up: model sticks, classify is skipped, meta event
    reports `bucket: null, confidence: null`."""
    settings = get_settings()
    prior_vec = [1.0] + [0.0] * 1535  # unit vector along axis 0
    _stub_embed(monkeypatch, prior_vec)  # cosine to itself = 1.0 >= 0.85

    # If classify_from_embedding fires, fail loudly — hysteresis was supposed
    # to short-circuit it.
    async def _explode(*a: Any, **kw: Any) -> dict[str, float]:
        raise AssertionError(
            "classify_from_embedding should not run when hysteresis sticks"
        )

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify_from_embedding",
        _explode,
    )

    conv = (await client.post("/conversations")).json()
    await _stamp_conversation(
        db, conv["id"], **_seed_intent(prior_vec, "coding")
    )

    events = await _post_and_collect(client, conv["id"], "make it shorter")
    meta = events[0][1]

    assert meta["bucket"] is None
    assert meta["confidence"] is None
    assert meta["model"] == settings.BUCKET_MODEL_MAP["coding"]
    assert stub_provider.last_model == settings.BUCKET_MODEL_MAP["coding"]

    # Hysteresis row preserves "no scoring this turn" (None) — distinct from
    # "scored, all sub-floor" (which keeps a 0.0).
    row = (
        await db.execute(select(Message).where(Message.role == "assistant"))
    ).scalar_one()
    assert row.bucket_scores == {}
    assert row.intent_confidence is None


async def test_hysteresis_reclassifies_on_topic_shift(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Low-cosine new prompt: classify fires, model re-routes."""
    settings = get_settings()
    prior_vec = [1.0] + [0.0] * 1535
    new_vec = [0.0, 1.0] + [0.0] * 1534  # orthogonal to prior, cosine = 0
    _stub_embed(monkeypatch, new_vec)
    _stub_classify(
        monkeypatch, {"coding": 0.21, "research": 0.83, "design": 0.34}
    )

    conv = (await client.post("/conversations")).json()
    await _stamp_conversation(
        db, conv["id"], **_seed_intent(prior_vec, "coding")
    )

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


async def test_hysteresis_skipped_when_no_prior_intent(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First turn of a fresh conversation has no prior vector; classify must
    run even if the embed is identical to whatever the conftest default
    produces."""
    settings = get_settings()
    _stub_embed(monkeypatch, [1.0] + [0.0] * 1535)
    _stub_classify(
        monkeypatch, {"coding": 0.78, "research": 0.31, "design": 0.22}
    )

    conv = (await client.post("/conversations")).json()
    events = await _post_and_collect(client, conv["id"], "fix this code")
    meta = events[0][1]

    assert meta["bucket"] == "coding"
    assert meta["model"] == settings.BUCKET_MODEL_MAP["coding"]


async def test_chat_turn_persists_last_intent_for_next_turns_hysteresis(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a successful classified turn, the conversation row carries
    forward the embedding + bucket so the next turn can hysteresis."""
    chosen_vec = [0.0, 1.0] + [0.0] * 1534
    _stub_embed(monkeypatch, chosen_vec)
    _stub_classify(
        monkeypatch, {"coding": 0.78, "research": 0.31, "design": 0.22}
    )

    conv = (await client.post("/conversations")).json()
    await _post_and_collect(client, conv["id"], "fix this code")

    row = (
        await db.execute(
            select(Conversation).where(Conversation.id == uuid.UUID(conv["id"]))
        )
    ).scalar_one()
    assert row.last_intent_bucket == "coding"
    # pgvector reads back as a numpy array. Truthiness on an ndarray raises,
    # so check non-None explicitly before converting to list for comparison.
    assert row.last_intent_vector is not None
    assert list(row.last_intent_vector) == pytest.approx(chosen_vec)


# --- Phase 8: manual override ---------------------------------------------


async def test_pin_overrides_classify_and_skips_hysteresis_update(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pinned conversation: model = pin, classify never runs, embed never
    runs, last_intent_* stays untouched so unpinning doesn't carry forward
    a stale (pinned-turn) vector."""
    settings = get_settings()

    async def _explode_embed(text: str) -> list[float]:
        raise AssertionError(
            "embed should not run on pinned turns"
        )

    async def _explode_classify(*a: Any, **kw: Any) -> dict[str, float]:
        raise AssertionError(
            "classify_from_embedding should not run on pinned turns"
        )

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.embed", _explode_embed
    )
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify_from_embedding",
        _explode_classify,
    )

    conv = (await client.post("/conversations")).json()
    pin = settings.BUCKET_MODEL_MAP["design"]  # any allowed model
    await _stamp_conversation(
        db, conv["id"], pinned_model=pin, auto_route_enabled=False
    )

    events = await _post_and_collect(
        client, conv["id"], "def fizzbuzz(n): pass"
    )
    meta = events[0][1]

    assert meta["model"] == pin
    assert meta["bucket"] is None
    assert meta["confidence"] is None
    assert stub_provider.last_model == pin

    # last_intent_* untouched — the pin row stays clean.
    row = (
        await db.execute(
            select(Conversation).where(Conversation.id == uuid.UUID(conv["id"]))
        )
    ).scalar_one()
    assert row.last_intent_vector is None
    assert row.last_intent_bucket is None

    # Persisted assistant row: bucket_scores={}, confidence=None (matches the
    # hysteresis "no scoring this turn" shape).
    msg_row = (
        await db.execute(select(Message).where(Message.role == "assistant"))
    ).scalar_one()
    assert msg_row.bucket_scores == {}
    assert msg_row.intent_confidence is None
    assert msg_row.model_used == pin
