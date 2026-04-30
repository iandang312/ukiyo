"""Seed `bucket_exemplars` from data/bucket_exemplars.json.

Truncate-then-insert in a single transaction, so re-running after a JSON
tweak just wipes and replaces. A crash mid-flight rolls back to the prior
state.

Run locally (with .env pointing at localhost:5432):
    python scripts/seed_buckets.py

Run inside the compose stack:
    docker compose exec ukiyo_service python scripts/seed_buckets.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy import delete, func, select

from ukiyo_service.infrastructure.db.models import BucketExemplar
from ukiyo_service.infrastructure.db.session import AsyncSessionLocal
from ukiyo_service.infrastructure.embeddings import (
    EMBEDDING_DIMENSIONS,
    embed_batch,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_PATH = REPO_ROOT / "data" / "bucket_exemplars.json"

logger = logging.getLogger("seed_buckets")


def _load_rows(json_path: Path) -> list[dict[str, str]]:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{json_path} must be a non-empty JSON list")

    rows: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"row {i} is not an object")
        bucket = item.get("bucket")
        text = item.get("text")
        if not isinstance(bucket, str) or not bucket:
            raise ValueError(f"row {i} missing or empty 'bucket'")
        if not isinstance(text, str) or not text:
            raise ValueError(f"row {i} missing or empty 'text'")
        rows.append({"bucket": bucket, "text": text})
    return rows


async def seed(json_path: Path) -> dict[str, int]:
    rows = _load_rows(json_path)
    logger.info("loaded %d rows from %s", len(rows), json_path)

    vectors = await embed_batch([r["text"] for r in rows])
    if len(vectors) != len(rows):
        raise RuntimeError(
            f"embed_batch returned {len(vectors)} vectors for {len(rows)} inputs"
        )
    for i, v in enumerate(vectors):
        if len(v) != EMBEDDING_DIMENSIONS:
            raise RuntimeError(
                f"row {i} embedding dim={len(v)}, expected {EMBEDDING_DIMENSIONS}"
            )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(BucketExemplar))
            session.add_all(
                [
                    BucketExemplar(
                        bucket=r["bucket"], text=r["text"], embedding=v
                    )
                    for r, v in zip(rows, vectors, strict=True)
                ]
            )

        per_bucket = await session.execute(
            select(BucketExemplar.bucket, func.count())
            .group_by(BucketExemplar.bucket)
            .order_by(BucketExemplar.bucket)
        )
        counts = {bucket: n for bucket, n in per_bucket.all()}

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Truncate and reseed bucket_exemplars from JSON."
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"path to JSON file (default: {DEFAULT_JSON_PATH})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    counts = asyncio.run(seed(args.json))
    total = sum(counts.values())
    print(f"seeded {total} bucket_exemplars: {counts}")


if __name__ == "__main__":
    main()
