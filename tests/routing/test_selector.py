from __future__ import annotations

import pytest

from ukiyo_service.config import get_settings
from ukiyo_service.domain.routing import (
    CONFIDENCE_FLOOR,
    ModelChoice,
    select_model,
)


def test_top_bucket_above_floor_picks_mapped_model() -> None:
    settings = get_settings()
    scores = {"coding": 0.82, "design": 0.30, "research": 0.40}

    choice = select_model(scores)

    assert choice.bucket == "coding"
    assert choice.model == settings.BUCKET_MODEL_MAP["coding"]
    assert choice.confidence == pytest.approx(0.82)
    assert choice.bucket_scores == scores


def test_below_floor_routes_to_generalist_with_null_bucket() -> None:
    settings = get_settings()
    scores = {"coding": 0.40, "design": 0.30, "research": 0.20}

    choice = select_model(scores)

    assert choice.bucket is None
    assert choice.model == settings.GENERALIST_MODEL
    assert choice.confidence == pytest.approx(0.40)
    assert choice.bucket_scores == scores


def test_exact_floor_value_is_above_threshold() -> None:
    settings = get_settings()
    scores = {"design": CONFIDENCE_FLOOR, "coding": 0.10}

    choice = select_model(scores)

    assert choice.bucket == "design"
    assert choice.model == settings.BUCKET_MODEL_MAP["design"]


def test_just_below_floor_falls_back_to_generalist() -> None:
    settings = get_settings()
    scores = {"design": CONFIDENCE_FLOOR - 0.0001, "coding": 0.10}

    choice = select_model(scores)

    assert choice.bucket is None
    assert choice.model == settings.GENERALIST_MODEL


def test_empty_scores_returns_generalist_at_zero_confidence() -> None:
    settings = get_settings()

    choice = select_model({})

    assert choice == ModelChoice(
        model=settings.GENERALIST_MODEL,
        bucket=None,
        confidence=0.0,
        bucket_scores={},
    )


def test_returned_bucket_scores_is_a_copy() -> None:
    """select_model must not bind callers to its input dict."""
    scores = {"research": 0.90, "coding": 0.10}

    choice = select_model(scores)
    scores["research"] = 0.0

    assert choice.bucket_scores["research"] == pytest.approx(0.90)


def test_research_top_bucket_routes_to_research_model() -> None:
    settings = get_settings()
    scores = {"coding": 0.20, "design": 0.30, "research": 0.91}

    choice = select_model(scores)

    assert choice.bucket == "research"
    assert choice.model == settings.BUCKET_MODEL_MAP["research"]


def test_design_top_bucket_routes_to_design_model() -> None:
    settings = get_settings()
    scores = {"coding": 0.20, "design": 0.77, "research": 0.30}

    choice = select_model(scores)

    assert choice.bucket == "design"
    assert choice.model == settings.BUCKET_MODEL_MAP["design"]


def test_model_choice_is_frozen() -> None:
    choice = select_model({"coding": 0.9})
    with pytest.raises(Exception):
        choice.model = "other-model"  # type: ignore[misc]
