from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.embeddings import client as embeddings_client
from ukiyo_service.infrastructure.embeddings import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EmbeddingsConfigError,
    embed,
    embed_batch,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXEMPLARS_PATH = REPO_ROOT / "data" / "bucket_exemplars.json"

LIVE_REQUIRES_KEY = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; skipping live OpenAI call.",
)


def _fake_response(vectors: list[list[float]]):
    """Build a stand-in for openai.types.CreateEmbeddingResponse."""
    data = [
        SimpleNamespace(index=i, embedding=v, object="embedding")
        for i, v in enumerate(vectors)
    ]
    return SimpleNamespace(
        data=data,
        model=EMBEDDING_MODEL,
        object="list",
        usage=SimpleNamespace(prompt_tokens=0, total_tokens=0),
    )


@pytest.fixture
def mocked_openai(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace the cached AsyncOpenAI client with a mock so no real HTTP is made."""
    create_mock = AsyncMock()

    fake_client = SimpleNamespace(
        embeddings=SimpleNamespace(create=create_mock),
    )

    embeddings_client._client.cache_clear()
    monkeypatch.setattr(embeddings_client, "_client", lambda: fake_client)
    return create_mock


# ---------- unit / smoke tests ----------


@pytest.mark.asyncio
async def test_embed_batch_makes_a_single_http_call(mocked_openai: AsyncMock) -> None:
    expected = [[0.1] * EMBEDDING_DIMENSIONS for _ in range(3)]
    mocked_openai.return_value = _fake_response(expected)

    out = await embed_batch(["a", "b", "c"])

    assert out == expected
    assert mocked_openai.await_count == 1
    call = mocked_openai.await_args
    assert call.kwargs["model"] == EMBEDDING_MODEL
    assert call.kwargs["input"] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_embed_returns_a_single_vector(mocked_openai: AsyncMock) -> None:
    expected = [0.42] * EMBEDDING_DIMENSIONS
    mocked_openai.return_value = _fake_response([expected])

    out = await embed("hello world")

    assert out == expected
    assert mocked_openai.await_args.kwargs["input"] == ["hello world"]


@pytest.mark.asyncio
async def test_embed_batch_with_empty_input_short_circuits(
    mocked_openai: AsyncMock,
) -> None:
    out = await embed_batch([])

    assert out == []
    mocked_openai.assert_not_called()


@pytest.mark.asyncio
async def test_embed_batch_rejects_oversized_input(mocked_openai: AsyncMock) -> None:
    with pytest.raises(ValueError, match="2048"):
        await embed_batch(["x"] * 2049)
    mocked_openai.assert_not_called()


@pytest.mark.asyncio
async def test_missing_api_key_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bypass `.env` loading entirely — Settings.env_file would otherwise
    # repopulate OPENAI_API_KEY from disk after monkeypatch.delenv.
    monkeypatch.setattr(
        embeddings_client,
        "get_settings",
        lambda: SimpleNamespace(OPENAI_API_KEY=""),
    )
    embeddings_client._client.cache_clear()

    try:
        with pytest.raises(EmbeddingsConfigError, match="OPENAI_API_KEY"):
            await embed("hi")
    finally:
        embeddings_client._client.cache_clear()


# ---------- bucket exemplars JSON shape ----------


def test_bucket_exemplars_json_is_well_formed() -> None:
    raw = EXEMPLARS_PATH.read_text(encoding="utf-8")
    entries = json.loads(raw)

    assert isinstance(entries, list)
    assert 30 <= len(entries) <= 60, f"expected 30-60 entries, got {len(entries)}"

    by_bucket: dict[str, list[str]] = {}
    for entry in entries:
        assert set(entry.keys()) == {"bucket", "text"}, entry
        assert isinstance(entry["bucket"], str) and entry["bucket"]
        assert isinstance(entry["text"], str) and entry["text"].strip()
        by_bucket.setdefault(entry["bucket"], []).append(entry["text"])

    assert set(by_bucket.keys()) == {"coding", "design", "research"}
    for bucket, texts in by_bucket.items():
        assert 10 <= len(texts) <= 20, (
            f"bucket {bucket!r} has {len(texts)} exemplars; want 10-20"
        )
        assert len(set(texts)) == len(texts), f"bucket {bucket!r} has duplicates"


# ---------- live integration tests (gated on real key) ----------


@LIVE_REQUIRES_KEY
@pytest.mark.asyncio
async def test_live_embed_returns_correct_dimensions() -> None:
    embeddings_client._client.cache_clear()
    get_settings.cache_clear()

    vector = await embed("hello world")

    assert isinstance(vector, list)
    assert len(vector) == EMBEDDING_DIMENSIONS
    assert all(isinstance(x, float) for x in vector)


@LIVE_REQUIRES_KEY
@pytest.mark.asyncio
async def test_live_embed_batch_returns_one_vector_per_input() -> None:
    embeddings_client._client.cache_clear()
    get_settings.cache_clear()

    vectors = await embed_batch(["alpha", "beta", "gamma"])

    assert len(vectors) == 3
    assert all(len(v) == EMBEDDING_DIMENSIONS for v in vectors)
    # Different inputs should produce different vectors.
    assert vectors[0] != vectors[1]
