from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ukiyo_service.application.routes import conversations, health, messages
from ukiyo_service.infrastructure.db.session import (
    AsyncSessionLocal,
    ensure_dev_user,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    async with AsyncSessionLocal() as session:
        await ensure_dev_user(session)
    yield


app = FastAPI(title="Ukiyo", lifespan=lifespan)
app.include_router(health.router)
app.include_router(conversations.router)
app.include_router(messages.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Ukiyo Service is running"}
