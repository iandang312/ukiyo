from __future__ import annotations

import logging
from decimal import Decimal

from ukiyo_service.infrastructure.llm.cost import cost_usd


def test_returns_decimal() -> None:
    result = cost_usd("claude-sonnet-4-6", 1000, 500)
    assert isinstance(result, Decimal)


def test_claude_sonnet_pricing() -> None:
    # 1M in + 1M out at $3 / $15 = $18
    assert cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == Decimal("18.000000")


def test_gpt_4o_pricing() -> None:
    # 1M in + 1M out at $2.50 / $10 = $12.50
    assert cost_usd("gpt-4o", 1_000_000, 1_000_000) == Decimal("12.500000")


def test_gemini_pricing() -> None:
    # 1M in + 1M out at $1.25 / $10 = $11.25
    assert cost_usd("gemini-2.5-pro", 1_000_000, 1_000_000) == Decimal("11.250000")


def test_gemini_flash_pricing() -> None:
    # 1M in + 1M out at $0.30 / $2.50 = $2.80 (token cost only — Google's
    # google_search grounding fee is not modeled here; first 1500 grounded
    # requests/day per project are free, then $35 / 1k after).
    assert cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000) == Decimal("2.800000")


def test_zero_tokens_zero_cost() -> None:
    assert cost_usd("claude-sonnet-4-6", 0, 0) == Decimal("0.000000")


def test_small_token_counts_quantize_to_six_places() -> None:
    # 100 in + 50 out at $3 / $15 = (300 + 750) / 1_000_000 = 0.001050
    assert cost_usd("claude-sonnet-4-6", 100, 50) == Decimal("0.001050")


def test_unknown_model_returns_zero_and_warns(
    caplog: logging.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = cost_usd("llama-3-70b", 1000, 500)
    assert result == Decimal("0")
    assert "llama-3-70b" in caplog.text
