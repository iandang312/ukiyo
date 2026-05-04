"""Google Gemini streaming adapter.

google-genai uses role="user"|"model" (not "assistant") and carries
`system_instruction` in a separate config object. usage_metadata on each
streamed chunk is cumulative — we keep the latest values and emit one merged
trailing Chunk after the iterator drains.

Every call attaches the `google_search` grounding tool. Today Gemini is only
used by the research bucket (`gemini-2.5-flash`), where live web grounding +
inline citations is the entire reason we picked Gemini in the first place.
If Gemini is ever assigned to a non-research bucket and grounding becomes
unwanted, parameterize this — but don't pre-empt the YAGNI tax.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from google import genai
from google.genai import types

from ukiyo_service.config import get_settings

from .base import Chunk, FinishReason, Message


def _to_google(
    messages: list[Message],
) -> tuple[str | None, list[types.Content]]:
    system_parts: list[str] = []
    contents: list[types.Content] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
            continue
        role = "model" if m.role == "assistant" else "user"
        contents.append(
            types.Content(role=role, parts=[types.Part.from_text(text=m.content)])
        )
    system = "\n\n".join(system_parts) if system_parts else None
    return system, contents


def _map_finish(reason: Any) -> FinishReason | None:
    if reason is None:
        return None
    name = getattr(reason, "name", str(reason)).upper()
    if name in ("STOP", "FINISH_REASON_STOP"):
        return "stop"
    if name == "MAX_TOKENS":
        return "length"
    if name in ("FINISH_REASON_UNSPECIFIED", "UNSPECIFIED"):
        return None
    return "error"


def _extract_text(event: Any) -> str:
    # event.text is a convenience property that can raise on certain finish
    # reasons (SAFETY, etc.); walk parts ourselves to stay defensive.
    if not getattr(event, "candidates", None):
        return ""
    candidate = event.candidates[0]
    content = getattr(candidate, "content", None)
    if content is None or not getattr(content, "parts", None):
        return ""
    out: list[str] = []
    for part in content.parts:
        text = getattr(part, "text", None)
        if text:
            out.append(text)
    return "".join(out)


class GoogleProvider:
    def __init__(self) -> None:
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            settings = get_settings()
            if not settings.GOOGLE_API_KEY:
                raise RuntimeError(
                    "GOOGLE_API_KEY is not set; configure it in .env "
                    "before calling the Google provider."
                )
            self._client = genai.Client(api_key=settings.GOOGLE_API_KEY)
        return self._client

    async def stream(
        self,
        messages: list[Message],
        model: str,
        **opts: Any,
    ) -> AsyncIterator[Chunk]:
        max_tokens = opts.pop("max_tokens", 4096)
        client = self._get_client()
        system, contents = _to_google(messages)
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            tools=[types.Tool(google_search=types.GoogleSearch())],
            **opts,
        )
        finish: FinishReason | None = None
        tokens_in: int | None = None
        tokens_out: int | None = None
        try:
            stream = await client.aio.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            )
            async for event in stream:
                text = _extract_text(event)
                if text:
                    yield Chunk(
                        delta=text,
                        finish_reason=None,
                        tokens_in=None,
                        tokens_out=None,
                    )
                if getattr(event, "candidates", None):
                    mapped = _map_finish(event.candidates[0].finish_reason)
                    if mapped is not None:
                        finish = mapped
                usage = getattr(event, "usage_metadata", None)
                if usage is not None:
                    if getattr(usage, "prompt_token_count", None) is not None:
                        tokens_in = usage.prompt_token_count
                    if getattr(usage, "candidates_token_count", None) is not None:
                        tokens_out = usage.candidates_token_count
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
