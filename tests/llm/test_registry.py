from __future__ import annotations

import pytest

from ukiyo_service.infrastructure.llm.base import UnknownModelError
from ukiyo_service.infrastructure.llm.registry import get_provider


def test_gpt_prefix_routes_to_openai() -> None:
    from ukiyo_service.infrastructure.llm.openai import OpenAIProvider

    assert isinstance(get_provider("gpt-4o"), OpenAIProvider)


def test_o1_prefix_routes_to_openai() -> None:
    from ukiyo_service.infrastructure.llm.openai import OpenAIProvider

    assert isinstance(get_provider("o1-preview"), OpenAIProvider)


def test_o3_prefix_routes_to_openai() -> None:
    from ukiyo_service.infrastructure.llm.openai import OpenAIProvider

    assert isinstance(get_provider("o3-mini"), OpenAIProvider)


def test_claude_prefix_routes_to_anthropic() -> None:
    from ukiyo_service.infrastructure.llm.anthropic import AnthropicProvider

    assert isinstance(get_provider("claude-sonnet-4-6"), AnthropicProvider)


def test_gemini_prefix_routes_to_google() -> None:
    from ukiyo_service.infrastructure.llm.google import GoogleProvider

    assert isinstance(get_provider("gemini-2.5-pro"), GoogleProvider)


def test_unknown_model_raises_unknown_model_error() -> None:
    with pytest.raises(UnknownModelError) as excinfo:
        get_provider("llama-3-70b")
    assert excinfo.value.model == "llama-3-70b"


def test_provider_instances_are_cached_per_provider() -> None:
    a = get_provider("gpt-4o")
    b = get_provider("gpt-4o-mini")
    assert a is b


def test_different_providers_are_distinct_instances() -> None:
    openai_p = get_provider("gpt-4o")
    anthropic_p = get_provider("claude-sonnet-4-6")
    google_p = get_provider("gemini-2.5-pro")
    assert openai_p is not anthropic_p
    assert anthropic_p is not google_p
    assert openai_p is not google_p
