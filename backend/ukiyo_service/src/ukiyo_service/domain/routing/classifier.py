from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.infrastructure.db.models import BucketExemplar
from ukiyo_service.infrastructure.embeddings import embed


TOP_K = 5
HEURISTIC_BOOST = 0.10


CODING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"```"),
    re.compile(r"\bdef\s", re.IGNORECASE),
    re.compile(r"\bfunction\s", re.IGNORECASE),
    # Python-style traceback line: `File "x.py", line 42, in foo`
    re.compile(r'File\s+"[^"]+",\s*line\s+\d+', re.IGNORECASE),
    # Python traceback header
    re.compile(r"Traceback \(most recent call last\)", re.IGNORECASE),
    # JVM/.NET-style frame: `at com.foo.Bar.baz(Bar.java:42)`
    re.compile(r"\bat\s+[\w.$]+\([^)]*\)", re.IGNORECASE),
)

RESEARCH_PATTERN: re.Pattern[str] = re.compile(
    r"\b(research|papers|citation|sources|literature)\b", re.IGNORECASE
)

DESIGN_PATTERN: re.Pattern[str] = re.compile(
    r"\b(wireframe|layout|UX|color|design system|Figma)\b", re.IGNORECASE
)


async def classify(prompt: str, session: AsyncSession) -> dict[str, float]:
    """Score every bucket present in `bucket_exemplars` for this prompt.

    For each bucket, take the top-K nearest exemplars by cosine similarity
    and average them, then add additive heuristic boosts. Returned dict is
    `{bucket_name: score}`.
    """
    query_vec = await embed(prompt)

    distinct_buckets = await session.execute(
        select(BucketExemplar.bucket).distinct()
    )
    buckets = sorted(b for (b,) in distinct_buckets.all())

    distance = BucketExemplar.embedding.cosine_distance(query_vec)
    scores: dict[str, float] = {}
    for bucket in buckets:
        result = await session.execute(
            select(distance)
            .where(BucketExemplar.bucket == bucket)
            .order_by(distance)
            .limit(TOP_K)
        )
        distances = [d for (d,) in result.all()]
        if not distances:
            continue
        similarities = [1.0 - d for d in distances]
        scores[bucket] = sum(similarities) / len(similarities)

    return _apply_heuristic_boosts(prompt, scores)


def _apply_heuristic_boosts(
    prompt: str, scores: dict[str, float]
) -> dict[str, float]:
    boosted = dict(scores)
    if "coding" in boosted and any(p.search(prompt) for p in CODING_PATTERNS):
        boosted["coding"] += HEURISTIC_BOOST
    if "research" in boosted and RESEARCH_PATTERN.search(prompt):
        boosted["research"] += HEURISTIC_BOOST
    if "design" in boosted and DESIGN_PATTERN.search(prompt):
        boosted["design"] += HEURISTIC_BOOST
    return boosted
