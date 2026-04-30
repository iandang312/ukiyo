from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.domain.routing import classify, select_model
from ukiyo_service.domain.routing.classifier import HEURISTIC_BOOST


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not set; skipping live classifier tests.",
    ),
]


async def test_coding_prompt_lands_in_coding_bucket(
    db: AsyncSession, seeded_exemplars: None
) -> None:
    scores = await classify(
        "how do I fix this stack trace?", db
    )

    assert set(scores.keys()) == {"coding", "design", "research"}
    top = max(scores, key=scores.__getitem__)
    assert top == "coding"


async def test_research_prompt_lands_in_research_bucket(
    db: AsyncSession, seeded_exemplars: None
) -> None:
    scores = await classify(
        "summarize the literature on attention", db
    )

    top = max(scores, key=scores.__getitem__)
    assert top == "research"


async def test_design_prompt_lands_in_design_bucket(
    db: AsyncSession, seeded_exemplars: None
) -> None:
    scores = await classify(
        "design a calm color palette", db
    )

    top = max(scores, key=scores.__getitem__)
    assert top == "design"


async def test_ambiguous_prompt_falls_below_floor(
    db: AsyncSession, seeded_exemplars: None
) -> None:
    scores = await classify("hi", db)
    choice = select_model(scores)

    assert max(scores.values()) < 0.55
    assert choice.bucket is None


async def test_triple_backtick_fence_boosts_coding(
    db: AsyncSession, seeded_exemplars: None
) -> None:
    """End-to-end check that the fence heuristic lifts coding meaningfully.

    Exact +0.10 is locked in `test_heuristics.py`. Live, the fenced and
    unfenced prompts have different embeddings, so the delta is
    `embedding_shift + HEURISTIC_BOOST` — assert the boost dominates any
    plausible embedding noise rather than the literal +0.10.
    """
    base = "i need help with this thing"
    fenced = base + "\n```\nx = 1\n```"

    scores_plain = await classify(base, db)
    scores_fenced = await classify(fenced, db)

    delta = scores_fenced["coding"] - scores_plain["coding"]
    assert delta > HEURISTIC_BOOST / 2, (
        f"fence should clearly boost coding; got delta={delta:.4f}"
    )


async def test_returns_one_score_per_seeded_bucket(
    db: AsyncSession, seeded_exemplars: None
) -> None:
    scores = await classify("anything at all", db)

    assert set(scores.keys()) == {"coding", "design", "research"}
    assert all(isinstance(v, float) for v in scores.values())


async def test_scores_within_reasonable_bounds(
    db: AsyncSession, seeded_exemplars: None
) -> None:
    """Cosine similarity sits in [-1, 1]; with a +0.10 boost the upper bound is 1.10."""
    scores = await classify(
        "build a wireframe with a color system and link some papers", db
    )

    for bucket, score in scores.items():
        assert -1.0 <= score <= 1.10, f"{bucket}={score} out of plausible range"
