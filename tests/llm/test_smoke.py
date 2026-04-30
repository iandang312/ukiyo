"""Live integration smoke tests for each provider.

Each test asks for a tiny one-sentence response and asserts the merged-Chunk
contract: at least one delta chunk, then exactly one trailing chunk with
finish_reason set and tokens populated.

Skip behavior: each test skips automatically if its provider's API key is
empty in the loaded Settings, so a developer with only one key set can still
run a partial suite (and a CI without keys runs nothing here).
"""
from __future__ import annotations

import pytest

from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.llm.base import Chunk, Message
from ukiyo_service.infrastructure.llm.registry import get_provider

_settings = get_settings()


def _assert_well_formed_stream(chunks: list[Chunk]) -> None:
    assert len(chunks) >= 2, f"expected >=1 delta + 1 final chunk, got {len(chunks)}"

    *deltas, final = chunks

    assert any(c.delta for c in deltas), "no text delta chunks were yielded"
    for c in deltas:
        assert c.finish_reason is None
        assert c.tokens_in is None
        assert c.tokens_out is None

    assert final.delta == ""
    assert final.finish_reason in ("stop", "length")
    assert final.tokens_in is not None and final.tokens_in > 0
    assert final.tokens_out is not None and final.tokens_out > 0


@pytest.mark.skipif(not _settings.OPENAI_API_KEY, reason="OPENAI_API_KEY not set")
async def test_openai_stream_is_well_formed() -> None:
    provider = get_provider("gpt-4o")
    chunks = [
        c
        async for c in provider.stream(
            [Message(role="user", content="Say hi in five words.")],
            model="gpt-4o",
            max_tokens=20,
        )
    ]
    _assert_well_formed_stream(chunks)


@pytest.mark.skipif(
    not _settings.ANTHROPIC_API_KEY, reason="ANTHROPIC_API_KEY not set"
)
async def test_anthropic_stream_is_well_formed() -> None:
    provider = get_provider("claude-sonnet-4-6")
    chunks = [
        c
        async for c in provider.stream(
            [Message(role="user", content="Say hi in five words.")],
            model="claude-sonnet-4-6",
            max_tokens=20,
        )
    ]
    _assert_well_formed_stream(chunks)


@pytest.mark.skipif(not _settings.GOOGLE_API_KEY, reason="GOOGLE_API_KEY not set")
async def test_google_stream_is_well_formed() -> None:
    provider = get_provider("gemini-2.5-pro")
    chunks = [
        c
        async for c in provider.stream(
            [Message(role="user", content="Say hi in five words.")],
            model="gemini-2.5-pro",
            max_tokens=50,
        )
    ]
    _assert_well_formed_stream(chunks)
