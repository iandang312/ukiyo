from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from ukiyo_service.infrastructure.db.models import BucketExemplar
from ukiyo_service.infrastructure.embeddings import embed_batch


REPO_ROOT = Path(__file__).resolve().parents[2]
EXEMPLARS_PATH = REPO_ROOT / "data" / "bucket_exemplars.json"


@pytest_asyncio.fixture(scope="session")
async def seeded_exemplars(engine: AsyncEngine) -> AsyncIterator[None]:
    """Embed `data/bucket_exemplars.json` once and insert into the DB.

    Skips the consuming test if `OPENAI_API_KEY` is missing — this is the
    same gate Agent B / Agent C used for live tests. Seeded rows live in
    the session-scoped engine; per-test `db` sessions see them through the
    outer transaction.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set; skipping live classifier tests.")

    rows = json.loads(EXEMPLARS_PATH.read_text(encoding="utf-8"))
    vectors = await embed_batch([r["text"] for r in rows])

    Session = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with Session() as session:
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

    yield

    async with Session() as session:
        async with session.begin():
            await session.execute(delete(BucketExemplar))
