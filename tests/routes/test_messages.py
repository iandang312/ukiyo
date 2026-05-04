from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
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


class _FakeFailingProvider:
    """Yields one delta then raises mid-stream. Phase 10 expects the route
    to catch this, emit an SSE `error` event, and persist the user message
    only — no partial assistant row, no hysteresis update."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def stream(
        self, messages: Any, model: str, **opts: Any
    ) -> AsyncIterator[Chunk]:
        yield Chunk(
            delta="partial",
            finish_reason=None,
            tokens_in=None,
            tokens_out=None,
        )
        raise self._exc


def _install_failing_provider(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> None:
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.get_provider",
        lambda model: _FakeFailingProvider(exc),
    )


@pytest.fixture
def low_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    """Patch the route module's `get_settings` to return a copy with a low
    DAILY_TOKEN_CAP. Using `model_copy` keeps the LRU-cached real settings
    instance untouched so other tests aren't affected by ordering."""
    cap = 100
    real = get_settings()
    custom = real.model_copy(update={"DAILY_TOKEN_CAP": cap})
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.get_settings",
        lambda: custom,
    )
    return cap


async def _seed_token_usage(
    db: AsyncSession, conversation_id: uuid.UUID, total: int
) -> None:
    """Insert one assistant row with the requested total token usage so the
    cap-precheck query has something to sum."""
    db.add(
        Message(
            conversation_id=conversation_id,
            role="assistant",
            content="seed",
            tokens_in=total // 2,
            tokens_out=total - total // 2,
        )
    )
    await db.commit()


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
    # Phase 6: classify is stubbed to {} in conftest, so select_model returns
    # the empty-bucket fallback. The DB keeps the raw shape (empty dict, 0.0)
    # — the meta event normalizes confidence to None on fallback, but persisted
    # rows preserve the floor score so analytics can distinguish "no buckets"
    # from "buckets all sub-floor".
    assert rows[1]["bucket_scores"] == {}
    assert rows[1]["intent_confidence"] == 0.0


async def test_post_message_404_for_unknown_conversation(
    client: AsyncClient, stub_provider: _FakeStreamProvider
) -> None:
    fake_id = uuid.uuid4()
    resp = await client.post(
        f"/conversations/{fake_id}/messages", json={"content": "hi"}
    )
    assert resp.status_code == 404


# --- Phase 9: daily token-cap precheck ------------------------------------


async def test_post_message_429s_when_over_daily_cap(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    low_cap: int,
) -> None:
    conv = (await client.post("/conversations")).json()
    await _seed_token_usage(db, uuid.UUID(conv["id"]), total=low_cap)

    resp = await client.post(
        f"/conversations/{conv['id']}/messages", json={"content": "hi"}
    )
    assert resp.status_code == 429, resp.text
    detail = resp.json()["detail"]
    assert detail["cap"] == low_cap
    assert detail["used"] >= low_cap

    # `resets_at` parses as a tz-aware ISO-8601 timestamp at UTC midnight.
    parsed = datetime.fromisoformat(detail["resets_at"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0  # type: ignore[union-attr]
    assert (parsed.hour, parsed.minute, parsed.second, parsed.microsecond) == (
        0,
        0,
        0,
        0,
    )


async def test_post_message_under_cap_succeeds(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    low_cap: int,
) -> None:
    conv = (await client.post("/conversations")).json()
    await _seed_token_usage(db, uuid.UUID(conv["id"]), total=low_cap - 10)

    raw = await _drain_sse(
        client, f"/conversations/{conv['id']}/messages", {"content": "hi"}
    )
    events = _parse_sse(raw)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"


async def test_cap_check_runs_before_embed(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
    low_cap: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cheap canary: with usage already over cap, the 429 must fire before
    `embed` is called. Proves the precheck short-circuits the routing tree."""

    async def _exploding_embed(text: str) -> list[float]:
        raise AssertionError(
            "embed must not run when the daily cap is already exceeded"
        )

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.embed",
        _exploding_embed,
    )

    conv = (await client.post("/conversations")).json()
    await _seed_token_usage(db, uuid.UUID(conv["id"]), total=low_cap)

    resp = await client.post(
        f"/conversations/{conv['id']}/messages", json={"content": "hi"}
    )
    assert resp.status_code == 429


# --- Phase 10: provider error surfacing -----------------------------------


async def test_provider_error_emits_sse_error_event(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_failing_provider(monkeypatch, RuntimeError("provider blew up"))

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "boom"},
    )
    events = _parse_sse(raw)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "error"
    assert "done" not in names

    error = events[-1][1]
    assert set(error.keys()) == {"provider", "code", "user_message"}
    # Generalist is `claude-sonnet-4-6` so the provider tag is "anthropic".
    assert error["provider"] == "anthropic"
    assert isinstance(error["code"], str) and error["code"]
    assert isinstance(error["user_message"], str) and error["user_message"]


async def test_provider_error_persists_user_only(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_failing_provider(monkeypatch, RuntimeError("provider blew up"))

    conv = (await client.post("/conversations")).json()
    await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "boom"},
    )

    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == uuid.UUID(conv["id"]))
                .order_by(Message.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    assert [r.role for r in rows] == ["user"]
    assert rows[0].content == "boom"
    assert rows[0].tokens_in is None and rows[0].tokens_out is None

    # Hysteresis state must be untouched on a failed turn so the next turn
    # doesn't stick on a model that didn't actually answer.
    conv_row = (
        await db.execute(
            select(Conversation).where(Conversation.id == uuid.UUID(conv["id"]))
        )
    ).scalar_one()
    assert conv_row.last_intent_vector is None
    assert conv_row.last_intent_bucket is None


async def test_provider_error_user_message_is_sanitized(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw provider error text may contain API keys / internal URLs / PII.
    The route must map to a canned `user_message` and never echo `str(exc)`."""
    secret = "sk-FAKE_KEY_FRAGMENT_DO_NOT_LEAK"
    _install_failing_provider(
        monkeypatch, RuntimeError(f"upstream said: {secret}")
    )

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "boom"},
    )
    events = _parse_sse(raw)
    error = events[-1][1]
    assert secret not in error["user_message"]
    # Defense in depth: the secret shouldn't appear anywhere in the stream
    # (code field is `RuntimeError`, user_message is the canned default).
    assert secret not in raw


# --- Phase 12: canvas surface ---------------------------------------------


from selectolax.lexbor import LexborHTMLParser  # noqa: E402

from ukiyo_service.infrastructure.db.models import Design, DesignVersion  # noqa: E402


def _stub_design_provider(
    monkeypatch: pytest.MonkeyPatch,
    deltas: list[str],
    tokens_in: int = 30,
    tokens_out: int = 50,
) -> _FakeStreamProvider:
    """Replace `get_provider` for the design model so canvas turns stream
    a deterministic full doc instead of hitting the real provider."""
    fake = _FakeStreamProvider(deltas, tokens_in=tokens_in, tokens_out=tokens_out)
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.get_provider",
        lambda model: fake,
    )
    return fake


_FULL_DOC = (
    "<!doctype html><html><head></head><body>"
    '<header><h1>Pricing</h1></header>'
    '<main><div class="card"><p>card-text</p></div></main>'
    "</body></html>"
)


async def test_canvas_surface_skips_routing(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A surface=='canvas' POST must NOT call embed or classify — both are
    irrelevant on the canvas branch and would burn paid tokens. Replace
    them with explosives so the test fails loudly if the branch leaks."""

    async def _exploding_embed(text: str) -> list[float]:
        raise AssertionError("embed must not run on canvas turns")

    async def _exploding_classify(prompt_vec, session, *, prompt_for_heuristics):
        raise AssertionError("classify must not run on canvas turns")

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.embed", _exploding_embed
    )
    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify_from_embedding",
        _exploding_classify,
    )
    _stub_design_provider(monkeypatch, [_FULL_DOC])

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "build a pricing card", "surface": "canvas"},
    )
    events = _parse_sse(raw)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"

    # And hysteresis state on the conversation is untouched — canvas
    # activity must not mis-bias the next chat-mode turn.
    conv_row = (
        await db.execute(
            select(Conversation).where(Conversation.id == uuid.UUID(conv["id"]))
        )
    ).scalar_one()
    assert conv_row.last_intent_vector is None
    assert conv_row.last_intent_bucket is None


async def test_canvas_surface_meta_event_shape(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_design_provider(monkeypatch, [_FULL_DOC])

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "build a card", "surface": "canvas"},
    )
    events = _parse_sse(raw)
    meta = events[0][1]

    assert set(meta.keys()) == {
        "surface", "model", "bucket", "design_id",
        "version_id", "parent_version_id", "version_number", "is_scoped_edit",
    }
    assert meta["surface"] == "canvas"
    assert meta["bucket"] == "design"
    assert meta["model"] == get_settings().BUCKET_MODEL_MAP["design"]
    assert meta["version_id"] is None  # not known until persist
    assert meta["parent_version_id"] is None  # first turn
    assert meta["version_number"] == 1
    assert meta["is_scoped_edit"] is False
    uuid.UUID(meta["design_id"])  # parses


async def test_canvas_surface_done_event_carries_version_id(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_design_provider(monkeypatch, [_FULL_DOC])

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client,
        f"/conversations/{conv['id']}/messages",
        {"content": "build a card", "surface": "canvas"},
    )
    events = _parse_sse(raw)
    done = events[-1][1]
    assert "version_id" in done
    uuid.UUID(done["version_id"])

    # And that version exists in the DB with the helper script + CSP baked.
    row = (
        await db.execute(
            select(DesignVersion).where(DesignVersion.id == uuid.UUID(done["version_id"]))
        )
    ).scalar_one()
    assert "ukiyo:select" in row.html
    assert "connect-src 'none'" in row.html


async def test_canvas_surface_creates_design_lazily_then_reuses(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First canvas turn on a conversation creates a Design row; second
    canvas turn reuses it (versions accumulate against the same design)."""
    _stub_design_provider(monkeypatch, [_FULL_DOC])

    conv = (await client.post("/conversations")).json()
    conv_id = uuid.UUID(conv["id"])

    await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {"content": "v1", "surface": "canvas"},
    )

    designs = list(
        (
            await db.execute(
                select(Design).where(Design.conversation_id == conv_id)
            )
        ).scalars().all()
    )
    assert len(designs) == 1
    first_design_id = designs[0].id

    # Second turn — provider stub has been "used"; re-stub a fresh one.
    _stub_design_provider(monkeypatch, [_FULL_DOC])
    await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {"content": "v2", "surface": "canvas"},
    )

    designs = list(
        (
            await db.execute(
                select(Design).where(Design.conversation_id == conv_id)
            )
        ).scalars().all()
    )
    assert len(designs) == 1
    assert designs[0].id == first_design_id

    # And there are now two versions, the second's parent is the first.
    versions = list(
        (
            await db.execute(
                select(DesignVersion)
                .where(DesignVersion.design_id == first_design_id)
                .order_by(DesignVersion.version_number.asc())
            )
        ).scalars().all()
    )
    assert [v.version_number for v in versions] == [1, 2]
    assert versions[1].parent_version_id == versions[0].id


async def test_canvas_assistant_message_links_to_version(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The assistant Message row produced by a canvas turn must carry
    design_version_id so the frontend can render an inline thumbnail / link
    back to the version."""
    _stub_design_provider(monkeypatch, [_FULL_DOC])

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {"content": "build a card", "surface": "canvas"},
    )
    done = _parse_sse(raw)[-1][1]

    msg = (
        await db.execute(
            select(Message).where(Message.id == uuid.UUID(done["message_id"]))
        )
    ).scalar_one()
    assert msg.role == "assistant"
    assert msg.design_version_id == uuid.UUID(done["version_id"])


async def test_canvas_scoped_edit_replaces_only_target(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed v1 via a full-doc canvas turn.
    _stub_design_provider(monkeypatch, [_FULL_DOC])
    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {"content": "v1", "surface": "canvas"},
    )
    v1_id = uuid.UUID(_parse_sse(raw)[-1][1]["version_id"])
    v1 = (
        await db.execute(select(DesignVersion).where(DesignVersion.id == v1_id))
    ).scalar_one()

    # Find the data-uid of the .card div in the persisted v1 HTML.
    parser = LexborHTMLParser(v1.html)
    counter = 0
    target_uid: int | None = None
    for el in parser.root.traverse(include_text=False):
        if el.tag == "div" and "card" in (el.attributes.get("class") or ""):
            target_uid = counter
            break
        counter += 1
    assert target_uid is not None

    # Scoped edit returns a fragment (not a full doc).
    fragment = '<div class="card bg-red-500"><p>NEW</p></div>'
    _stub_design_provider(monkeypatch, [fragment])
    raw = await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {
            "content": "make it red",
            "surface": "canvas",
            "edit_scope_uid": target_uid,
        },
    )
    events = _parse_sse(raw)
    meta = events[0][1]
    assert meta["is_scoped_edit"] is True
    assert meta["parent_version_id"] == str(v1_id)
    assert meta["version_number"] == 2

    v2_id = uuid.UUID(events[-1][1]["version_id"])
    v2 = (
        await db.execute(select(DesignVersion).where(DesignVersion.id == v2_id))
    ).scalar_one()
    assert "NEW" in v2.html
    assert "card-text" not in v2.html  # original gone
    assert "Pricing" in v2.html  # untouched


async def test_canvas_scoped_edit_422_without_existing_version(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scoped edit on a conversation that has never had a canvas turn
    must reject before opening the SSE stream."""
    _stub_design_provider(monkeypatch, [_FULL_DOC])
    conv = (await client.post("/conversations")).json()

    resp = await client.post(
        f"/conversations/{conv['id']}/messages",
        json={
            "content": "make it red",
            "surface": "canvas",
            "edit_scope_uid": 5,
        },
    )
    assert resp.status_code == 422


async def test_promote_to_canvas_fires_on_design_build_request(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    stub_provider: _FakeStreamProvider,
) -> None:
    """When the chat-surface classifier puts the prompt in design with high
    confidence AND the prompt mentions a build verb + UI noun, the meta
    event must include `promote_to_canvas: true`."""

    async def _design_classify(prompt_vec, session, *, prompt_for_heuristics):
        return {"design": 0.9, "coding": 0.1, "research": 0.1}

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify_from_embedding",
        _design_classify,
    )

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {"content": "design a pricing card"},  # build verb + UI noun
    )
    meta = _parse_sse(raw)[0][1]
    assert meta.get("promote_to_canvas") is True
    assert meta["bucket"] == "design"


async def test_promote_to_canvas_absent_on_generic_chat(
    client: AsyncClient,
    db: AsyncSession,
    stub_provider: _FakeStreamProvider,
) -> None:
    """Default conftest stub returns empty bucket scores → generalist
    fallback → bucket=None → no promote field."""
    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {"content": "what time is it in tokyo"},
    )
    meta = _parse_sse(raw)[0][1]
    assert "promote_to_canvas" not in meta


async def test_promote_to_canvas_absent_when_only_intent_matches(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    stub_provider: _FakeStreamProvider,
) -> None:
    """High-confidence design intent with no build verb / UI noun in the
    prompt must NOT promote — promotion is opt-in via wording."""

    async def _design_classify(prompt_vec, session, *, prompt_for_heuristics):
        return {"design": 0.9, "coding": 0.1, "research": 0.1}

    monkeypatch.setattr(
        "ukiyo_service.application.routes.messages.classify_from_embedding",
        _design_classify,
    )

    conv = (await client.post("/conversations")).json()
    raw = await _drain_sse(
        client, f"/conversations/{conv['id']}/messages",
        {"content": "what's a good color palette for a fintech brand"},
    )
    meta = _parse_sse(raw)[0][1]
    assert "promote_to_canvas" not in meta
