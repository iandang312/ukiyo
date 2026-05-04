from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ukiyo_service.application.routes import (
    conversations,
    designs,
    health,
    me,
    messages,
)
from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.db.session import (
    AsyncSessionLocal,
    ensure_dev_user,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with AsyncSessionLocal() as session:
        await ensure_dev_user(session)
        # Phase 12: prune handoff rows that expired more than a day ago,
        # so the table doesn't grow forever across restarts. Cheap one-shot
        # query at boot — periodic cleanup is deferred to Phase 16.
        try:
            removed = await designs.cleanup_expired_handoffs(session)
            if removed:
                logger.info(
                    "design_handoffs cleanup removed %d expired rows", removed
                )
        except Exception:  # noqa: BLE001
            # Cleanup must not block app startup — log and continue.
            logger.exception("design_handoffs cleanup failed")
    yield


app = FastAPI(title="Ukiyo", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(me.router)
app.include_router(conversations.router)
app.include_router(conversations.models_router)
app.include_router(messages.router)
app.include_router(designs.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Ukiyo Service is running"}
