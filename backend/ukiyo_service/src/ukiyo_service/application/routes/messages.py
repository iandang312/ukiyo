"""SSE chat endpoint.

POST /conversations/{id}/messages streams the assistant response via SSE
and, on success, persists the user message and the assistant message in a
single transaction together with tokens / cost / latency. Phase 6 wires
classifier + selector into the request path; Phase 7 adds hysteresis on
the prior intent vector to skip classification on conversational
follow-ups; Phase 8 adds a manual pin branch that bypasses both.
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
from ukiyo_service.config import get_settings
from ukiyo_service.domain.routing import (
    classify_from_embedding,
    select_model,
    should_reuse_prior_model,
)
from ukiyo_service.infrastructure.db.models import Conversation, Message, User
from ukiyo_service.infrastructure.embeddings import embed
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

    # Routing decision tree (chat surface — Phase 12 will add a
    # `surface == 'canvas'` short-circuit above this block):
    #
    #   1. Pinned model    -> use it; skip embed + classify + hysteresis update.
    #   2. Hysteresis hit  -> reuse prior model; skip classify; still update
    #                         last_intent_* with the *new* embedding so the
    #                         stickiness window slides forward.
    #   3. Otherwise       -> classify(prompt_vec) -> select_model.
    prompt_vec: list[float] | None = None
    bucket_used: str | None = None  # what to write back to last_intent_bucket

    if conversation.pinned_model:
        model = conversation.pinned_model
        bucket: str | None = None
        confidence: float | None = None
        bucket_scores: dict[str, float] = {}
        raw_confidence: float | None = None
    else:
        prompt_vec = await embed(body.content)
        if (
            conversation.last_intent_vector is not None
            and conversation.last_intent_bucket is not None
            and should_reuse_prior_model(
                prompt_vec,
                list(conversation.last_intent_vector),
                conversation.last_intent_bucket,
            )
        ):
            bucket_used = conversation.last_intent_bucket
            model = get_settings().BUCKET_MODEL_MAP[bucket_used]
            # Classification skipped — `bucket_scores={}` and
            # `intent_confidence=None` on the row distinguish "no scoring this
            # turn" from "scored, all sub-floor" (which keeps a 0.0).
            bucket = None
            confidence = None
            bucket_scores = {}
            raw_confidence = None
        else:
            bucket_scores = await classify_from_embedding(
                prompt_vec, db, prompt_for_heuristics=body.content
            )
            choice = select_model(bucket_scores)
            model = choice.model
            bucket = choice.bucket
            # On generalist fallback (no bucket cleared the floor) the meta
            # event reports confidence as null so the UI badge reads as
            # "no routing decision" rather than a misleading sub-floor float.
            # The DB still keeps the raw score on the row for analytics.
            confidence = choice.confidence if choice.bucket is not None else None
            bucket_scores = choice.bucket_scores
            raw_confidence = choice.confidence
            bucket_used = choice.bucket  # may be None on generalist fallback

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

    async def event_stream() -> AsyncIterator[bytes]:
        yield _sse_event(
            "meta",
            {
                "surface": "chat",
                "model": model,
                "bucket": bucket,
                "confidence": confidence,
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
            bucket_scores=bucket_scores,
            intent_confidence=raw_confidence,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=latency_ms,
            created_at=datetime.now(timezone.utc),
        )
        db.add_all([user_msg, assistant_msg])

        # TODO(phase-12): gate this update on surface == 'chat'. Canvas turns
        # must not poison hysteresis with implicitly-design intent vectors.
        if prompt_vec is not None:
            # Pinned turns leave last_intent_* untouched (prompt_vec is None
            # because we never embedded) so re-enabling auto-route doesn't
            # carry forward a stale vector. Hysteresis stick-turns *do*
            # update — sliding the window forward keeps follow-ups inside
            # the threshold. On generalist fallback bucket_used is None,
            # which clears last_intent_bucket so the next turn won't
            # hysteresis against a stale label.
            conversation.last_intent_vector = prompt_vec
            conversation.last_intent_bucket = bucket_used
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
