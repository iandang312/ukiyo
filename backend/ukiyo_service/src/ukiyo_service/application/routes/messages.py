"""SSE chat endpoint.

POST /conversations/{id}/messages streams the assistant response via SSE
and, on success, persists the user message and the assistant message in a
single transaction together with tokens / cost / latency. Phase 6 wires the
classifier + selector into the request path: the chosen model, bucket, and
confidence ride the first SSE event and persist on the assistant row.
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from ukiyo_service.application.deps import get_current_user, get_db
from ukiyo_service.domain.routing import classify, select_model
from ukiyo_service.infrastructure.db.models import Conversation, Message, User
from ukiyo_service.infrastructure.llm import (
    Message as LLMMessage,
    cost_usd,
    get_provider,
)


router = APIRouter(prefix="/conversations", tags=["messages"])


class MessageIn(BaseModel):
    content: str


def _sse_event(name: str, data: dict[str, object]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@router.post("/{conversation_id}/messages")
async def post_message(
    conversation_id: uuid.UUID,
    body: MessageIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    started = time.perf_counter()
    # Stamp the user message at request entry. The model's `server_default=now()`
    # would otherwise tie both rows to the same transaction-start timestamp,
    # making `ORDER BY created_at` non-deterministic between user and assistant.
    user_created_at = datetime.now(timezone.utc)

    conv_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user.id,
    )
    conversation = (await db.execute(conv_stmt)).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        )

    # Phase 8 will replace this guard with `if not auto_route_enabled or
    # pinned_model: use pinned_model`. Keeping the shape so that branch slots
    # in cleanly. Today the else branch is unreachable — auto_route_enabled
    # defaults true and no endpoint flips it.
    bucket_scores: dict[str, float] = {}
    if conversation.auto_route_enabled and not conversation.pinned_model:
        bucket_scores = await classify(body.content, db)
    choice = select_model(bucket_scores)
    model = choice.model

    history_stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    history = list((await db.execute(history_stmt)).scalars().all())
    llm_messages: list[LLMMessage] = [
        LLMMessage(role=m.role, content=m.content) for m in history  # type: ignore[arg-type]
    ]
    llm_messages.append(LLMMessage(role="user", content=body.content))

    provider = get_provider(model)

    # On generalist fallback (no bucket cleared the floor) the meta event
    # reports confidence as null so the UI badge reads as "no routing decision"
    # rather than a misleading sub-floor float. The DB still keeps the raw
    # score on the row for analytics.
    meta_confidence = choice.confidence if choice.bucket is not None else None

    async def event_stream() -> AsyncIterator[bytes]:
        yield _sse_event(
            "meta",
            {
                "surface": "chat",
                "model": model,
                "bucket": choice.bucket,
                "confidence": meta_confidence,
            },
        )

        assistant_content_parts: list[str] = []
        tokens_in = 0
        tokens_out = 0

        async for chunk in provider.stream(llm_messages, model):
            if chunk.delta:
                assistant_content_parts.append(chunk.delta)
                yield _sse_event("delta", {"content": chunk.delta})
            if chunk.tokens_in is not None:
                tokens_in = chunk.tokens_in
            if chunk.tokens_out is not None:
                tokens_out = chunk.tokens_out

        latency_ms = int((time.perf_counter() - started) * 1000)
        cost = cost_usd(model, tokens_in, tokens_out)

        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=body.content,
            created_at=user_created_at,
        )
        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content="".join(assistant_content_parts),
            model_used=model,
            bucket_scores=choice.bucket_scores,
            intent_confidence=choice.confidence,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc),
        )
        db.add_all([user_msg, assistant_msg])
        # TODO(phase-7): update conversation.last_intent_vector +
        # last_intent_bucket here so hysteresis can short-circuit the next
        # turn's classify call.
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        await db.commit()

        yield _sse_event(
            "done",
            {
                "message_id": str(assistant_msg.id),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": str(cost),
                "latency_ms": latency_ms,
            },
        )

    return StreamingResponse(event_stream(), media_type="text/event-stream")
