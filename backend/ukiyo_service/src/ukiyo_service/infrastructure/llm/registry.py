"""Model name -> provider lookup.

Recognized prefixes:
- gpt-, o1-, o3-  -> OpenAI
- claude-         -> Anthropic
- gemini-         -> Google (always with `google_search` grounding; see google.py)

Provider instances are cached per-process so SDK clients (and their connection
pools) are reused across requests. Provider modules are imported lazily so the
registry doesn't pull in every SDK at startup.
"""
from __future__ import annotations

from .base import LLMProvider, UnknownModelError

_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-")
_ANTHROPIC_PREFIXES = ("claude-",)
_GOOGLE_PREFIXES = ("gemini-",)

_INSTANCES: dict[str, LLMProvider] = {}


def _provider_key(model: str) -> str:
    if model.startswith(_OPENAI_PREFIXES):
        return "openai"
    if model.startswith(_ANTHROPIC_PREFIXES):
        return "anthropic"
    if model.startswith(_GOOGLE_PREFIXES):
        return "google"
    raise UnknownModelError(model)


def get_provider(model: str) -> LLMProvider:
    key = _provider_key(model)
    cached = _INSTANCES.get(key)
    if cached is not None:
        return cached
    if key == "openai":
        from .openai import OpenAIProvider

        instance: LLMProvider = OpenAIProvider()
    elif key == "anthropic":
        from .anthropic import AnthropicProvider

        instance = AnthropicProvider()
    else:
        from .google import GoogleProvider

        instance = GoogleProvider()
    _INSTANCES[key] = instance
    return instance
