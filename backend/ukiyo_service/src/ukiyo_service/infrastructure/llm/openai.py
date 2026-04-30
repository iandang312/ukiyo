"""OpenAI streaming adapter.

Maps the OpenAI Chat Completions streaming API onto the unified Chunk contract.
We pass `stream_options={"include_usage": True}` so the trailing usage chunk
arrives in-band; we buffer the finish_reason from the penultimate chunk and the
usage from the final chunk into one merged trailing Chunk.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ukiyo_service.config import get_settings

from .base import Chunk, FinishReason, Message

_FINISH_MAP: dict[str, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "tool_calls": "stop",
    "function_call": "stop",
    "content_filter": "error",
}


def _to_openai_messages(messages: list[Message]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _map_finish(reason: str | None) -> FinishReason | None:
    if reason is None:
        return None
    return _FINISH_MAP.get(reason, "stop")


class OpenAIProvider:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            settings = get_settings()
            if not settings.OPENAI_API_KEY:
                raise RuntimeError(
                    "OPENAI_API_KEY is not set; configure it in .env "
                    "before calling the OpenAI provider."
                )
            self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._client

    async def stream(
        self,
        messages: list[Message],
        model: str,
        **opts: Any,
    ) -> AsyncIterator[Chunk]:
        max_tokens = opts.pop("max_tokens", 4096)
        client = self._get_client()
        finish: FinishReason | None = None
        tokens_in: int | None = None
        tokens_out: int | None = None
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=_to_openai_messages(messages),
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **opts,
            )
            async for event in stream:
                if event.choices:
                    choice = event.choices[0]
                    delta = choice.delta.content or ""
                    if delta:
                        yield Chunk(
                            delta=delta,
                            finish_reason=None,
                            tokens_in=None,
                            tokens_out=None,
                        )
                    if choice.finish_reason is not None:
                        finish = _map_finish(choice.finish_reason)
                if event.usage is not None:
                    tokens_in = event.usage.prompt_tokens
                    tokens_out = event.usage.completion_tokens
        except Exception:
            yield Chunk(
                delta="",
                finish_reason="error",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            raise
        yield Chunk(
            delta="",
            finish_reason=finish or "stop",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
