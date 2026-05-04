"""Hysteresis policy: decide whether to reuse the conversation's prior model.

Pure function over two embedding vectors and the prior bucket label.
CONTEXT.md decision #4: stick when the new prompt's intent vector is close
to the prior turn's vector (cosine >= threshold) AND we have a recorded
prior bucket. The original spec also says "current top bucket equals prior
bucket" — but when hysteresis fires we *skip* classification for the turn,
so that check collapses into the cosine test (high cosine -> similar
intent -> assume same bucket). Explicit re-classification just to confirm
would defeat the latency win.
"""
from __future__ import annotations

import math


HYSTERESIS_THRESHOLD = 0.85


def should_reuse_prior_model(
    prompt_vec: list[float],
    last_vec: list[float],
    last_bucket: str,
    *,
    threshold: float = HYSTERESIS_THRESHOLD,
) -> bool:
    if not last_bucket:
        return False
    return _cosine(prompt_vec, last_vec) >= threshold


def _cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
