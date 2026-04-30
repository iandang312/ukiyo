"""LLM provider abstraction.

Usage:

    from ukiyo_service.infrastructure.llm import get_provider, Message

    provider = get_provider("claude-sonnet-4-6")
    async for chunk in provider.stream(
        [Message(role="user", content="hello")],
        model="claude-sonnet-4-6",
    ):
        print(chunk.delta)
"""
from .base import Chunk, FinishReason, LLMProvider, Message, Role, UnknownModelError
from .cost import cost_usd
from .registry import get_provider

__all__ = [
    "Chunk",
    "FinishReason",
    "LLMProvider",
    "Message",
    "Role",
    "UnknownModelError",
    "cost_usd",
    "get_provider",
]
