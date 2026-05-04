"""Design handoff endpoints (Phase 12) + design hydration / revert (Phase 13).

`POST /designs/{design_id}/versions/{version_id}/handoffs` issues an opaque
8-char code (10-min TTL, single-use) pinned to the version. Auth: session.

`POST /handoffs/redeem` consumes a code and returns the version's HTML.
Auth is the code itself — no `Depends(get_current_user)` so the companion
Figma plugin doesn't need a session. Atomic check-and-mark prevents
double-redeem; 404 covers consumed/expired/never-existed indistinguishably
(differentiating leaks brute-force info on the 32^8 code space).

Rate limiting on `/handoffs/redeem` is implemented in-process — module-
level rolling-window dict, no new dep. ~10/min and ~100/day per IP per
CONTEXT.md decision #19. Single-process for v1; Phase 16 + a real prod
deployment will revisit for distributed safety.

Phase 13 adds:
- `GET /conversations/{conversation_id}/design` — single-shot hydration for
  the canvas drawer. Returns the (1:1) design + all versions inline so the
  frontend doesn't paginate. 404 if no design has been opened on the
  conversation yet. Owned by the route layer here rather than
  conversations.py because it's design-shaped, not conversation-shaped.
- `PATCH /designs/{design_id}` — flip `current_version_id` to revert the
  active version. Editing afterwards still appends at the end of the
  timeline (linear-UI-over-DAG-storage per CONTEXT.md decision #17 — the
  parent_version_id gets set to whatever is current at edit time).
"""
from __future__ import annotations

import secrets
import time
import uuid
from collections import deque
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.application.deps import get_current_user, get_db
from ukiyo_service.infrastructure.db.models import (
    Conversation,
    Design,
    DesignHandoff,
    DesignVersion,
    User,
)


router = APIRouter(tags=["designs"])


# 32-char alphabet, paste-friendly: no 0/O/I/1 (CONTEXT.md decision #19).
_HANDOFF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_HANDOFF_CODE_LENGTH = 8
_HANDOFF_TTL = timedelta(minutes=10)


# --- request / response shapes -------------------------------------------


class IssueHandoffOut(BaseModel):
    code: str
    expires_at: datetime


class RedeemHandoffIn(BaseModel):
    code: str


class RedeemHandoffOut(BaseModel):
    html: str
    version_number: int
    design_title: str | None
    design_id: uuid.UUID


class DesignVersionOut(BaseModel):
    """One row of the canvas drawer's version timeline. `html` is included
    inline because the timeline lets the user revert without a follow-up
    fetch — and because v1 hydrates everything in one round-trip per the
    CONTEXT.md "single-shot hydration" pattern. If versions get heavy we
    can split this into a metadata-only list + lazy `GET /versions/{id}`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    html: str
    prompt: str | None
    edit_scope_selector: str | None
    parent_version_id: uuid.UUID | None
    model_used: str | None
    tokens_in: int | None
    tokens_out: int | None
    created_at: datetime


class DesignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    title: str | None
    current_version_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    versions: list[DesignVersionOut]


class DesignPatch(BaseModel):
    """Phase 13 revert. Only `current_version_id` is mutable today —
    `title` could land later but isn't part of v1 UX, so leaving it out
    keeps the surface area small."""

    current_version_id: uuid.UUID


# --- in-process rate limiter ---------------------------------------------
#
# Two windows enforced together: ~10 requests in any 60-second window AND
# ~100 requests in any 24-hour window per source IP. Both windows share one
# deque per IP; trim-then-count on each request.

_REDEEM_WINDOW_SHORT_SECONDS = 60.0
_REDEEM_WINDOW_LONG_SECONDS = 60.0 * 60.0 * 24.0
_REDEEM_LIMIT_SHORT = 10
_REDEEM_LIMIT_LONG = 100

_redeem_history: dict[str, deque[float]] = {}
# Sweep empty deques every Nth request so abandoned IPs don't accumulate.
# Keyed off a single counter — fine for v1 single-process traffic.
_REDEEM_SWEEP_INTERVAL = 256
_redeem_request_counter = 0


def _now() -> float:
    """Indirection for tests — monkeypatching `time.time` directly is
    awkward because deque entries from earlier tests would still be live.
    Tests can replace this to advance the rolling window."""
    return time.time()


def _check_redeem_rate_limit(client_ip: str) -> None:
    """Trim the IP's history, count remaining, raise 429 if over either
    window. Sweeps empty-deque keys periodically as a memory hygiene
    measure — single-process v1 only."""
    global _redeem_request_counter

    now = _now()
    bucket = _redeem_history.setdefault(client_ip, deque())

    # Trim entries older than the longest window. The shorter window's
    # count is implicit in the deque tail.
    cutoff_long = now - _REDEEM_WINDOW_LONG_SECONDS
    while bucket and bucket[0] < cutoff_long:
        bucket.popleft()

    # Counts.
    long_count = len(bucket)
    cutoff_short = now - _REDEEM_WINDOW_SHORT_SECONDS
    short_count = sum(1 for ts in bucket if ts >= cutoff_short)

    if short_count >= _REDEEM_LIMIT_SHORT or long_count >= _REDEEM_LIMIT_LONG:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many redemption attempts; please slow down",
        )

    bucket.append(now)

    # Periodic empty-deque cleanup.
    _redeem_request_counter += 1
    if _redeem_request_counter % _REDEEM_SWEEP_INTERVAL == 0:
        _sweep_redeem_history()


def _sweep_redeem_history() -> None:
    """Drop IPs whose deques are empty after trimming. O(n) over the dict
    — only runs every _REDEEM_SWEEP_INTERVAL requests."""
    now = _now()
    cutoff_long = now - _REDEEM_WINDOW_LONG_SECONDS
    empty: list[str] = []
    for ip, bucket in _redeem_history.items():
        while bucket and bucket[0] < cutoff_long:
            bucket.popleft()
        if not bucket:
            empty.append(ip)
    for ip in empty:
        _redeem_history.pop(ip, None)


def _reset_redeem_history_for_tests() -> None:
    """Test-only helper: wipe the limiter state so tests don't bleed into
    each other. Exposed under a leading underscore to discourage non-test
    callers from depending on it."""
    _redeem_history.clear()
    global _redeem_request_counter
    _redeem_request_counter = 0


# --- code generation -----------------------------------------------------


def _generate_handoff_code() -> str:
    """8 chars from the 32-char paste-friendly alphabet via secrets.choice
    — `random` is not safe for security tokens. ~32^8 ≈ 1.1T entries; with
    rate limiting the brute-force cost is high enough for a one-way export."""
    return "".join(
        secrets.choice(_HANDOFF_ALPHABET) for _ in range(_HANDOFF_CODE_LENGTH)
    )


# --- endpoints -----------------------------------------------------------


@router.post(
    "/designs/{design_id}/versions/{version_id}/handoffs",
    response_model=IssueHandoffOut,
    status_code=status.HTTP_201_CREATED,
)
async def issue_handoff(
    design_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IssueHandoffOut:
    """Mint an opaque 10-min single-use code pinned to one design version.

    404 if the design isn't owned by the caller, or if the version doesn't
    belong to that design. The code is shown once — the frontend's "Open
    in Figma" modal displays it and never re-fetches it.
    """
    design = (
        await db.execute(
            select(Design).where(
                Design.id == design_id, Design.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="design not found",
        )

    version = (
        await db.execute(
            select(DesignVersion).where(
                DesignVersion.id == version_id,
                DesignVersion.design_id == design_id,
            )
        )
    ).scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="design version not found",
        )

    expires_at = datetime.now(timezone.utc) + _HANDOFF_TTL
    # Tiny collision retry — chance is negligible (32^8) but cheap to guard.
    for _ in range(3):
        code = _generate_handoff_code()
        existing = (
            await db.execute(
                select(DesignHandoff.code).where(DesignHandoff.code == code)
            )
        ).scalar_one_or_none()
        if existing is None:
            break
    else:
        # Three collisions in a row would imply the table is enormous or
        # secrets is broken — either way, surface it.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not allocate a unique handoff code",
        )

    handoff = DesignHandoff(
        code=code,
        design_version_id=version_id,
        user_id=user.id,
        expires_at=expires_at,
    )
    db.add(handoff)
    await db.commit()

    return IssueHandoffOut(code=code, expires_at=expires_at)


@router.post(
    "/handoffs/redeem",
    response_model=RedeemHandoffOut,
)
async def redeem_handoff(
    body: RedeemHandoffIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedeemHandoffOut:
    """Consume a handoff code and return the pinned design version's HTML.

    No `get_current_user` dep — the code itself is the bearer credential.
    The atomic UPDATE...RETURNING prevents double-redeem and TOCTOU races
    (two plugins racing on the same code see one success, one 404). 404
    covers consumed / expired / never-existed without distinguishing —
    differentiating would leak brute-force progress on the code space.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_redeem_rate_limit(client_ip)

    consume_stmt = text(
        "UPDATE design_handoffs "
        "SET consumed_at = now() "
        "WHERE code = :code "
        "  AND consumed_at IS NULL "
        "  AND expires_at > now() "
        "RETURNING design_version_id"
    )
    row = (
        await db.execute(consume_stmt, {"code": body.code})
    ).first()
    if row is None:
        # Don't differentiate consumed / expired / unknown.
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="handoff code not valid",
        )
    version_id = row[0]

    # Load the version + parent design (need title and design_id). One JOIN
    # so we don't pay a second round-trip for the design row.
    stmt = (
        select(DesignVersion, Design)
        .join(Design, Design.id == DesignVersion.design_id)
        .where(DesignVersion.id == version_id)
    )
    found = (await db.execute(stmt)).first()
    if found is None:
        # Version was deleted between the consume and the load — treat as
        # the same opaque 404 the brute-forcer sees.
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="handoff code not valid",
        )
    version, design = found
    await db.commit()

    return RedeemHandoffOut(
        html=version.html,
        version_number=version.version_number,
        design_title=design.title,
        design_id=design.id,
    )


# --- Phase 13: hydration + revert ----------------------------------------


@router.get(
    "/conversations/{conversation_id}/design",
    response_model=DesignOut,
)
async def get_conversation_design(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DesignOut:
    """Single-shot hydration for the canvas drawer.

    v1's 1:1 design-per-conversation invariant (CONTEXT.md decision #13)
    means the frontend doesn't need a separate "list designs" endpoint —
    the canvas drawer always opens against the current conversation's one
    design. Returns 404 distinctly when:
      - the conversation isn't yours / doesn't exist
      - the conversation exists but no canvas turn has run on it yet
    Both are 404 because exposing "this conversation exists but has no
    design" leaks little — the frontend treats both as "drawer is empty".
    Versions come back ordered by version_number ASC so the timeline
    renders top-to-bottom in chronological order without client sorting.
    """
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        )

    design = (
        await db.execute(
            select(Design).where(Design.conversation_id == conversation_id)
        )
    ).scalar_one_or_none()
    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no design on this conversation yet",
        )

    versions = list(
        (
            await db.execute(
                select(DesignVersion)
                .where(DesignVersion.design_id == design.id)
                .order_by(DesignVersion.version_number.asc())
            )
        )
        .scalars()
        .all()
    )

    return DesignOut(
        id=design.id,
        conversation_id=design.conversation_id,
        title=design.title,
        current_version_id=design.current_version_id,
        created_at=design.created_at,
        updated_at=design.updated_at,
        versions=[DesignVersionOut.model_validate(v) for v in versions],
    )


@router.patch(
    "/designs/{design_id}",
    response_model=DesignOut,
)
async def patch_design(
    design_id: uuid.UUID,
    body: DesignPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DesignOut:
    """Set `current_version_id` to revert the active version.

    The DAG is preserved (we only touch the pointer, never delete or
    re-parent versions). When the user edits after a revert, the canvas
    branch in messages.py reads `design.current_version_id` to decide
    `parent_version_id` for the new version — so a forked version arrives
    with the correct DAG parentage but still appears at the end of the
    linear timeline (CONTEXT.md decision #17).
    """
    design = (
        await db.execute(
            select(Design).where(
                Design.id == design_id, Design.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if design is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="design not found",
        )

    target = (
        await db.execute(
            select(DesignVersion).where(
                DesignVersion.id == body.current_version_id,
                DesignVersion.design_id == design_id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        # 422 (not 404) — the caller asked for a real, structured action
        # but referenced a version that doesn't belong to this design.
        # Differentiating this from the 404 above lets the frontend tell
        # "design vanished" from "tried to revert to wrong version".
        raise HTTPException(
            status_code=422,
            detail="version does not belong to this design",
        )

    design.current_version_id = target.id
    await db.commit()
    await db.refresh(design)

    versions = list(
        (
            await db.execute(
                select(DesignVersion)
                .where(DesignVersion.design_id == design.id)
                .order_by(DesignVersion.version_number.asc())
            )
        )
        .scalars()
        .all()
    )

    return DesignOut(
        id=design.id,
        conversation_id=design.conversation_id,
        title=design.title,
        current_version_id=design.current_version_id,
        created_at=design.created_at,
        updated_at=design.updated_at,
        versions=[DesignVersionOut.model_validate(v) for v in versions],
    )


# --- startup cleanup sweep -----------------------------------------------


async def cleanup_expired_handoffs(db: AsyncSession) -> int:
    """Delete handoff rows that expired more than a day ago. Wired into
    the FastAPI lifespan handler so the table doesn't accumulate stale
    rows across restarts. Returns rowcount for observability — caller
    decides whether to log it.

    v1 plan per the brief; Phase 16 + a real deployment may move to a
    periodic asyncio task, especially once the table grows past a few
    thousand rows.
    """
    result = await db.execute(
        text(
            "DELETE FROM design_handoffs "
            "WHERE expires_at < now() - interval '1 day'"
        )
    )
    await db.commit()
    return result.rowcount or 0


# --- internals exposed for tests -----------------------------------------

__all__: Iterable[str] = (
    "router",
    "cleanup_expired_handoffs",
    "_reset_redeem_history_for_tests",
)
