from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.infrastructure.db.models import (
    BucketExemplar,
    Conversation,
    Message,
    User,
)


pytestmark = pytest.mark.asyncio


async def test_user_round_trip(db: AsyncSession) -> None:
    user = User(email="alice@example.com", password_hash="x")
    db.add(user)
    await db.flush()

    fetched = await db.get(User, user.id)
    assert fetched is not None
    assert fetched.email == "alice@example.com"
    assert fetched.created_at is not None


async def test_email_is_case_insensitive(db: AsyncSession) -> None:
    db.add(User(email="MixedCase@example.com", password_hash=""))
    await db.flush()

    result = await db.execute(
        select(User).where(User.email == "mixedcase@example.com")
    )
    assert result.scalar_one().email.lower() == "mixedcase@example.com"


async def test_conversation_and_message_round_trip(db: AsyncSession) -> None:
    user = User(email="bob@example.com", password_hash="")
    db.add(user)
    await db.flush()

    convo = Conversation(user_id=user.id, title="Chat: 1")
    db.add(convo)
    await db.flush()

    db.add_all(
        [
            Message(
                conversation_id=convo.id,
                role="user",
                content="hello",
            ),
            Message(
                conversation_id=convo.id,
                role="assistant",
                content="hi",
                model_used="claude-sonnet-4-6",
                bucket_scores={"coding": 0.7, "design": 0.1, "research": 0.2},
                intent_confidence=0.7,
                tokens_in=10,
                tokens_out=5,
                cost_usd=Decimal("0.000123"),
                latency_ms=420,
            ),
        ]
    )
    await db.flush()

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == convo.id)
        .order_by(Message.created_at)
    )
    rows = result.scalars().all()
    assert [m.role for m in rows] == ["user", "assistant"]
    assert rows[1].bucket_scores["coding"] == 0.7
    assert rows[1].cost_usd == Decimal("0.000123")


async def test_conversation_defaults(db: AsyncSession) -> None:
    user = User(email="carol@example.com", password_hash="")
    db.add(user)
    await db.flush()

    convo = Conversation(user_id=user.id)
    db.add(convo)
    await db.flush()
    await db.refresh(convo)

    assert convo.auto_route_enabled is True
    assert convo.pinned_model is None
    assert convo.last_intent_vector is None


async def test_bucket_exemplar_with_vector(db: AsyncSession) -> None:
    vec = [0.0] * 1536
    vec[0] = 1.0
    ex = BucketExemplar(bucket="coding", text="why is my recursion broken?", embedding=vec)
    db.add(ex)
    await db.flush()

    fetched = await db.get(BucketExemplar, ex.id)
    assert fetched is not None
    assert fetched.bucket == "coding"
    assert len(fetched.embedding) == 1536


async def test_message_cascade_on_conversation_delete(db: AsyncSession) -> None:
    user = User(email="dave@example.com", password_hash="")
    db.add(user)
    await db.flush()

    convo = Conversation(user_id=user.id, title="Chat: 1")
    db.add(convo)
    await db.flush()

    db.add(Message(conversation_id=convo.id, role="user", content="x"))
    await db.flush()
    convo_id = convo.id

    await db.delete(convo)
    await db.flush()

    result = await db.execute(
        select(Message).where(Message.conversation_id == convo_id)
    )
    assert result.scalars().first() is None


async def test_unique_email_constraint(db: AsyncSession) -> None:
    db.add(User(email="dup@example.com", password_hash=""))
    await db.flush()

    db.add(User(email="DUP@example.com", password_hash=""))
    with pytest.raises(Exception):
        await db.flush()
