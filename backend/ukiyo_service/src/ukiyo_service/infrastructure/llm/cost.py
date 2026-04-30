"""Static price table and cost computation.

Prices are USD per 1M tokens, (input, output). Verify against provider
pricing pages before relying on these for billing — they drift over time.
Unknown model names log a warning and return Decimal("0") so callers can
still write the message row without a crash.
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-4-6": (Decimal("3.00"), Decimal("15.00")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gemini-2.5-pro": (Decimal("1.25"), Decimal("10.00")),
}

_MILLION = Decimal("1000000")
_QUANTUM = Decimal("0.000001")


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    if model not in _PRICES:
        logger.warning(
            "No price entry for model %r; cost reported as $0.000000", model
        )
        return Decimal("0")
    in_price, out_price = _PRICES[model]
    raw = (Decimal(tokens_in) * in_price + Decimal(tokens_out) * out_price) / _MILLION
    return raw.quantize(_QUANTUM)
