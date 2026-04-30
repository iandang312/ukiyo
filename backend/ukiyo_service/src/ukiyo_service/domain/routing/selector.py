from __future__ import annotations

from dataclasses import dataclass

from ukiyo_service.config import get_settings


CONFIDENCE_FLOOR = 0.55


@dataclass(frozen=True)
class ModelChoice:
    model: str
    bucket: str | None
    confidence: float
    bucket_scores: dict[str, float]


def select_model(scores: dict[str, float]) -> ModelChoice:
    """Pick a model from per-bucket scores.

    Below the confidence floor the generalist model handles the prompt and
    `bucket` is None. Above it, the top-scoring bucket maps to its model via
    `Settings.BUCKET_MODEL_MAP`. The full score dict is always echoed back
    so the caller can persist it and emit it on the SSE meta event.
    """
    settings = get_settings()
    bucket_scores = dict(scores)

    if not bucket_scores:
        return ModelChoice(
            model=settings.GENERALIST_MODEL,
            bucket=None,
            confidence=0.0,
            bucket_scores={},
        )

    top_bucket = max(bucket_scores, key=bucket_scores.__getitem__)
    confidence = bucket_scores[top_bucket]

    if confidence < CONFIDENCE_FLOOR:
        return ModelChoice(
            model=settings.GENERALIST_MODEL,
            bucket=None,
            confidence=confidence,
            bucket_scores=bucket_scores,
        )

    return ModelChoice(
        model=settings.BUCKET_MODEL_MAP[top_bucket],
        bucket=top_bucket,
        confidence=confidence,
        bucket_scores=bucket_scores,
    )
