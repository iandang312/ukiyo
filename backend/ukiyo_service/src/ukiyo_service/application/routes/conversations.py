"""Conversation CRUD endpoints (Phase 3).

Owns the dev user's conversations and read-only history. SSE streaming for
new messages lives in `messages.py`. `PATCH /conversations/{id}` (Phase 8)
sets / clears manual model overrides; `GET /models` exposes the routing
config for the frontend picker.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.application.deps import get_current_user, get_db
from ukiyo_service.config import get_settings
from ukiyo_service.infrastructure.db.models import Conversation, Message, User


router = APIRouter(prefix="/conversations", tags=["conversations"])
# `GET /models` lives next to conversations conceptually but at a top-level
# path. Using a second unprefixed router keeps both endpoints in this file
# without forcing `/conversations/models`.
models_router = APIRouter(tags=["models"])


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    auto_route_enabled: bool
    pinned_model: str | None
    created_at: datetime
    updated_at: datetime


class ConversationPatch(BaseModel):
    # Both optional so the frontend can flip auto-route without re-sending
    # the pin and vice versa. Stickiness (CONTEXT.md decision #6) is the
    # *frontend's* job — the server doesn't auto-flip auto_route_enabled
    # when pinned_model changes.
    pinned_model: str | None = None
    auto_route_enabled: bool | None = None


class ModelsOut(BaseModel):
    generalist: str
    buckets: dict[str, str]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    model_used: str | None
    bucket_scores: dict[str, Any] | None
    intent_confidence: float | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: Decimal | None
    latency_ms: int | None
    created_at: datetime


@router.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    count_stmt = (
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.user_id == user.id)
    )
    existing = (await db.execute(count_stmt)).scalar_one()
    conversation = Conversation(
        user_id=user.id,
        title=f"Chat: {existing + 1}",
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageOut],
)
async def list_messages(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Message]:
    conv_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    )
    conv = (await db.execute(conv_stmt)).scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        )
    msg_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await db.execute(msg_stmt)
    return list(result.scalars().all())


def _allowed_pinned_models() -> set[str]:
    settings = get_settings()
    return {settings.GENERALIST_MODEL, *settings.BUCKET_MODEL_MAP.values()}


@router.patch(
    "/{conversation_id}",
    response_model=ConversationOut,
)
async def patch_conversation(
    conversation_id: uuid.UUID,
    body: ConversationPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Conversation:
    conv_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    )
    conv = (await db.execute(conv_stmt)).scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        )

    # `exclude_unset` distinguishes "field absent" from "field set to null".
    # Required so a request can clear `pinned_model` (-> null) without also
    # being forced to send `auto_route_enabled`, and vice versa.
    patch = body.model_dump(exclude_unset=True)

    if "pinned_model" in patch and patch["pinned_model"] is not None:
        if patch["pinned_model"] not in _allowed_pinned_models():
            # 422 directly: starlette renamed `HTTP_422_UNPROCESSABLE_ENTITY`
            # to `..._CONTENT` in 1.0 and the old name now warns. The integer
            # works on both.
            raise HTTPException(
                status_code=422,
                detail="pinned_model not in the configured model set",
            )
        conv.pinned_model = patch["pinned_model"]
    elif "pinned_model" in patch:
        conv.pinned_model = None

    if "auto_route_enabled" in patch:
        conv.auto_route_enabled = bool(patch["auto_route_enabled"])

    await db.commit()
    await db.refresh(conv)
    return conv


@models_router.get("/models", response_model=ModelsOut)
async def get_models(
    user: User = Depends(get_current_user),
) -> ModelsOut:
    """Source-of-truth for the frontend model picker.

    Returns the configured generalist + per-bucket models. Reads `Settings`
    so env-driven overrides flow through without leaking the env shape.
    """
    settings = get_settings()
    return ModelsOut(
        generalist=settings.GENERALIST_MODEL,
        buckets=dict(settings.BUCKET_MODEL_MAP),
    )
