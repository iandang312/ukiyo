"""Provider-agnostic streaming primitives.

Phase 3 (chat endpoint) iterates `provider.stream(messages, model)` and gets
normalized `Chunk` objects regardless of which SDK is underneath.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Literal, Protocol

Role = Literal["user", "assistant", "system"]
FinishReason = Literal["stop", "length", "error"]


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class Chunk:
    """One streamed unit from a provider.

    Streaming contract (uniform across providers):
    - Mid-stream chunks: `delta` is a non-empty text increment;
      `finish_reason`, `tokens_in`, `tokens_out` are all None.
    - Trailing chunk (always emitted exactly once on success): `delta` is "",
      `finish_reason` is set, `tokens_in` and `tokens_out` are populated.
      Adapters merge provider-specific finish + usage events into this chunk.
    - Mid-stream provider error: adapter yields one final chunk with
      `finish_reason="error"` and re-raises the underlying exception.
    """

    delta: str
    finish_reason: FinishReason | None
    tokens_in: int | None
    tokens_out: int | None


class LLMProvider(Protocol):
    def stream(
        self,
        messages: list[Message],
        model: str,
        **opts: object,
    ) -> AsyncIterator[Chunk]:
        ...


class UnknownModelError(ValueError):
    def __init__(self, model: str) -> None:
        super().__init__(f"No provider registered for model {model!r}")
        self.model = model
