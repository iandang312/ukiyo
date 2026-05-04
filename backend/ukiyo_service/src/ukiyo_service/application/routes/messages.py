"""SSE chat endpoint.

POST /conversations/{id}/messages streams the assistant response via SSE
and, on success, persists the user message and the assistant message in a
single transaction together with tokens / cost / latency. Phase 6 wires
classifier + selector into the request path; Phase 7 adds hysteresis on
the prior intent vector to skip classification on conversational
follow-ups; Phase 8 adds a manual pin branch that bypasses both. Phase 9
adds a daily token-cap precheck before any paid call; Phase 10 wraps the
provider stream loop so failures emit a clean SSE `error` event and
persist the user message only (no partial assistant row).
"""
from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

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


async def _used_tokens_today(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Sum tokens_in + tokens_out across all messages in this user's
    conversations created since today's UTC midnight.

    `messages.created_at` is timestamptz so the explicit UTC date range is
    well-defined regardless of the Postgres session timezone. NULL token
    columns (e.g. user rows that don't carry token counts) are treated as
    zero so they don't poison the sum.
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    tomorrow_start = today_start + timedelta(days=1)

    stmt = (
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(Message.tokens_in, 0)
                    + func.coalesce(Message.tokens_out, 0)
                ),
                0,
            )
        )
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.user_id == user_id,
            Message.created_at >= today_start,
            Message.created_at < tomorrow_start,
        )
    )
    return int((await db.execute(stmt)).scalar_one())


def _next_utc_midnight_iso() -> str:
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (today_start + timedelta(days=1)).isoformat()


_PROVIDER_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("gpt-", "o1-", "o3-"), "openai"),
    (("claude-",), "anthropic"),
    (("gemini-",), "google"),
)


def _provider_for_model(model: str) -> str:
    for prefixes, name in _PROVIDER_PREFIXES:
        if model.startswith(prefixes):
            return name
    return "unknown"


def _classify_provider_error(exc: BaseException) -> tuple[str, str]:
    """Map a provider exception to (code, user_message).

    `code` is short and machine-readable: HTTP status if the SDK exception
    exposes one, else the exception class name. `user_message` is one of a
    fixed set of canned strings so we never echo raw provider error text
    (may include API keys, internal URLs, or PII).
    """
    status_code = getattr(exc, "status_code", None)
    if not isinstance(status_code, int):
        status_code = None
    code = str(status_code) if status_code is not None else type(exc).__name__

    if status_code == 429:
        message = (
            "The model is currently rate-limited. Please try again in a moment."
        )
    elif status_code is not None and 500 <= status_code < 600:
        message = "The model provider is temporarily unavailable."
    elif status_code in (401, 403):
        message = (
            "Authentication with the model provider failed. Contact support."
        )
    else:
        # Class-name heuristic for SDKs whose exceptions don't expose
        # status_code (or for plain RuntimeErrors raised mid-stream).
        class_name = type(exc).__name__.lower()
        if "ratelimit" in class_name:
            message = (
                "The model is currently rate-limited. "
                "Please try again in a moment."
            )
        elif "connection" in class_name or "unavailable" in class_name:
            message = "The model provider is temporarily unavailable."
        elif "auth" in class_name or "permission" in class_name:
            message = (
                "Authentication with the model provider failed. "
                "Contact support."
            )
        else:
            message = "The model provider returned an error."
    return code, message


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

    # Phase 9: daily token-cap precheck. Slots between ownership check (so
    # we don't reveal cap state to strangers via 404-vs-429 timing) and the
    # routing tree (so we reject before any embed/classify/provider call).
    # We check once at request entry — a single in-flight turn can push
    # usage over without triggering a second 429; we don't pre-estimate the
    # new turn's tokens.
    cap = get_settings().DAILY_TOKEN_CAP
    used = await _used_tokens_today(db, user.id)
    if used >= cap:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "cap": cap,
                "used": used,
                "resets_at": _next_utc_midnight_iso(),
            },
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

        # Build the user_msg up front so the Phase 10 error path can persist
        # it without rebuilding state. The assistant row is only built in the
        # success branch.
        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=body.content,
            created_at=user_created_at,
        )

        assistant_content_parts: list[str] = []
        tokens_in = 0
        tokens_out = 0

        try:
            async for chunk in provider.stream(llm_messages, model):
                if chunk.delta:
                    assistant_content_parts.append(chunk.delta)
                    yield _sse_event("delta", {"content": chunk.delta})
                if chunk.tokens_in is not None:
                    tokens_in = chunk.tokens_in
                if chunk.tokens_out is not None:
                    tokens_out = chunk.tokens_out
        except Exception as exc:
            # Phase 10: provider error after the SSE response opened. Emit a
            # clean `error` event, persist the user message only (no partial
            # assistant row, no hysteresis update, no updated_at bump — a
            # failed turn shouldn't promote the conversation to the top of
            # the sidebar), and return cleanly. We don't re-raise — that
            # would drop the connection mid-stream and the frontend can't
            # tell a provider error from a network blip.
            code, user_message = _classify_provider_error(exc)
            yield _sse_event(
                "error",
                {
                    "provider": _provider_for_model(model),
                    "code": code,
                    "user_message": user_message,
                },
            )
            db.add(user_msg)
            await db.commit()
            return

        latency_ms = int((time.perf_counter() - started) * 1000)
        cost = cost_usd(model, tokens_in, tokens_out)

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
