"""Anthropic streaming adapter.

Anthropic separates `system` from the messages list and requires `max_tokens`.
We hoist any role="system" entries into the `system=` parameter (joined with
\\n\\n if multiple) and rely on the SDK's get_final_message() helper to surface
stop_reason + usage in one place — naturally fitting the merged trailing-Chunk
contract.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from ukiyo_service.config import get_settings

from .base import Chunk, FinishReason, Message

_STOP_MAP: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "stop",
    "max_tokens": "length",
}


def _split_messages(
    messages: list[Message],
) -> tuple[str | None, list[dict[str, str]]]:
    system_parts: list[str] = []
    chat: list[dict[str, str]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
        else:
            chat.append({"role": m.role, "content": m.content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, chat


def _map_stop(reason: str | None) -> FinishReason | None:
    if reason is None:
        return None
    return _STOP_MAP.get(reason, "stop")


class AnthropicProvider:
    def __init__(self) -> None:
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            settings = get_settings()
            if not settings.ANTHROPIC_API_KEY:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set; configure it in .env "
                    "before calling the Anthropic provider."
                )
            self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    async def stream(
        self,
        messages: list[Message],
        model: str,
        **opts: Any,
    ) -> AsyncIterator[Chunk]:
        max_tokens = opts.pop("max_tokens", 4096)
        client = self._get_client()
        system, chat = _split_messages(messages)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": chat,
            "max_tokens": max_tokens,
            **opts,
        }
        if system is not None:
            kwargs["system"] = system
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield Chunk(
                            delta=text,
                            finish_reason=None,
                            tokens_in=None,
                            tokens_out=None,
                        )
                final = await stream.get_final_message()
        except Exception:
            yield Chunk(
                delta="",
                finish_reason="error",
                tokens_in=None,
                tokens_out=None,
            )
            raise
        yield Chunk(
            delta="",
            finish_reason=_map_stop(final.stop_reason) or "stop",
            tokens_in=final.usage.input_tokens,
            tokens_out=final.usage.output_tokens,
        )
