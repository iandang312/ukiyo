from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.application.routes import designs as designs_route
from ukiyo_service.infrastructure.db.models import (
    Conversation,
    Design,
    DesignHandoff,
    DesignVersion,
    User,
)
from ukiyo_service.infrastructure.db.session import DEV_USER_ID, ensure_dev_user


pytestmark = pytest.mark.asyncio(loop_scope="session")


# Reset the in-process rate limiter between tests so /redeem hammering in
# one test doesn't poison the next. (Module-level state survives pytest's
# per-test isolation otherwise.)
@pytest.fixture(autouse=True)
def _reset_rate_limiter() -> None:
    designs_route._reset_redeem_history_for_tests()


async def _seed_design_with_version(
    db: AsyncSession,
    *,
    user_id: uuid.UUID = DEV_USER_ID,
    title: str | None = "test design",
    html: str = "<!doctype html><html><body><p>v1</p></body></html>",
) -> tuple[Design, DesignVersion]:
    """Create a conversation + design + design_version owned by `user_id`."""
    await ensure_dev_user(db)
    conv = Conversation(user_id=user_id, title="canvas test")
    db.add(conv)
    await db.flush()
    design = Design(
        conversation_id=conv.id,
        user_id=user_id,
        title=title,
    )
    db.add(design)
    await db.flush()
    version = DesignVersion(
        design_id=design.id,
        version_number=1,
        html=html,
        prompt="seed",
    )
    db.add(version)
    await db.flush()
    design.current_version_id = version.id
    await db.commit()
    return design, version


# --- code generation ------------------------------------------------------


async def test_generate_handoff_code_uses_safe_alphabet() -> None:
    """Code generator must use the paste-friendly 32-char alphabet (no
    0/O/I/1) and `secrets.choice` for cryptographic strength."""
    for _ in range(20):
        code = designs_route._generate_handoff_code()
        assert len(code) == designs_route._HANDOFF_CODE_LENGTH
        for ch in code:
            assert ch in designs_route._HANDOFF_ALPHABET
            assert ch not in {"0", "O", "I", "1"}


# --- issue endpoint -------------------------------------------------------


async def test_issue_handoff_returns_code_and_expiry(
    client: AsyncClient, db: AsyncSession
) -> None:
    design, version = await _seed_design_with_version(db)
    resp = await client.post(
        f"/designs/{design.id}/versions/{version.id}/handoffs"
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body.keys()) == {"code", "expires_at"}

    code = body["code"]
    assert len(code) == 8
    for ch in code:
        assert ch in designs_route._HANDOFF_ALPHABET

    # Expiry parses and is ~10 minutes in the future (allow generous slack
    # for slow CI without making the assertion meaningless).
    expires = datetime.fromisoformat(body["expires_at"])
    delta = (expires - datetime.now(timezone.utc)).total_seconds()
    assert 540 <= delta <= 660, f"expires_at delta={delta}s, want ~600s"


async def test_issue_handoff_persists_row(
    client: AsyncClient, db: AsyncSession
) -> None:
    design, version = await _seed_design_with_version(db)
    resp = await client.post(
        f"/designs/{design.id}/versions/{version.id}/handoffs"
    )
    code = resp.json()["code"]

    row = (
        await db.execute(
            select(DesignHandoff).where(DesignHandoff.code == code)
        )
    ).scalar_one()
    assert row.design_version_id == version.id
    assert row.user_id == DEV_USER_ID
    assert row.consumed_at is None
    assert row.expires_at > datetime.now(timezone.utc)


async def test_issue_handoff_404_for_nonexistent_design(
    client: AsyncClient,
) -> None:
    fake_design = uuid.uuid4()
    fake_version = uuid.uuid4()
    resp = await client.post(
        f"/designs/{fake_design}/versions/{fake_version}/handoffs"
    )
    assert resp.status_code == 404


async def test_issue_handoff_404_for_other_users_design(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A design owned by a different user must not be issuable by us."""
    other_user = User(email="other@local")
    db.add(other_user)
    await db.flush()
    design, version = await _seed_design_with_version(
        db, user_id=other_user.id
    )

    resp = await client.post(
        f"/designs/{design.id}/versions/{version.id}/handoffs"
    )
    assert resp.status_code == 404


async def test_issue_handoff_404_for_version_not_in_design(
    client: AsyncClient, db: AsyncSession
) -> None:
    """version_id that exists but belongs to a different design must 404."""
    design_a, _version_a = await _seed_design_with_version(
        db, title="design a"
    )
    _design_b, version_b = await _seed_design_with_version(
        db, title="design b"
    )
    # Try to issue against design_a using design_b's version_id.
    resp = await client.post(
        f"/designs/{design_a.id}/versions/{version_b.id}/handoffs"
    )
    assert resp.status_code == 404


# --- redeem endpoint ------------------------------------------------------


async def test_redeem_handoff_fresh_returns_html_and_metadata(
    client: AsyncClient, db: AsyncSession
) -> None:
    design, version = await _seed_design_with_version(
        db,
        title="my design",
        html="<!doctype html><html><body><p>HELLO</p></body></html>",
    )
    issue_resp = await client.post(
        f"/designs/{design.id}/versions/{version.id}/handoffs"
    )
    code = issue_resp.json()["code"]

    resp = await client.post("/handoffs/redeem", json={"code": code})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"html", "version_number", "design_title", "design_id"}
    assert "HELLO" in body["html"]
    assert body["version_number"] == 1
    assert body["design_title"] == "my design"
    assert uuid.UUID(body["design_id"]) == design.id


async def test_redeem_handoff_marks_consumed(
    client: AsyncClient, db: AsyncSession
) -> None:
    design, version = await _seed_design_with_version(db)
    code = (
        await client.post(
            f"/designs/{design.id}/versions/{version.id}/handoffs"
        )
    ).json()["code"]

    await client.post("/handoffs/redeem", json={"code": code})

    row = (
        await db.execute(
            select(DesignHandoff).where(DesignHandoff.code == code)
        )
    ).scalar_one()
    assert row.consumed_at is not None


async def test_redeem_handoff_consumed_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Replay must 404 — no double-redeem."""
    design, version = await _seed_design_with_version(db)
    code = (
        await client.post(
            f"/designs/{design.id}/versions/{version.id}/handoffs"
        )
    ).json()["code"]

    first = await client.post("/handoffs/redeem", json={"code": code})
    assert first.status_code == 200
    second = await client.post("/handoffs/redeem", json={"code": code})
    assert second.status_code == 404


async def test_redeem_handoff_expired_returns_404(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Insert a handoff row with `expires_at` already in the past, then
    redeem — the atomic UPDATE's `expires_at > now()` filter must miss
    it. Avoids the time-dependency of waiting 10 minutes."""
    design, version = await _seed_design_with_version(db)
    expired = DesignHandoff(
        code="EXPIREDX",  # 8 chars, all in the safe alphabet
        design_version_id=version.id,
        user_id=DEV_USER_ID,
        expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.add(expired)
    await db.commit()

    resp = await client.post(
        "/handoffs/redeem", json={"code": "EXPIREDX"}
    )
    assert resp.status_code == 404


async def test_redeem_handoff_unknown_returns_404(
    client: AsyncClient,
) -> None:
    """A code that was never issued must 404 (and look identical to the
    consumed/expired cases — no information leak about which buckets are
    populated)."""
    resp = await client.post(
        "/handoffs/redeem", json={"code": "NEVERMNT"}
    )
    assert resp.status_code == 404


async def test_redeem_handoff_404_responses_are_indistinguishable(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Detail body must be identical across consumed / expired / unknown
    so a brute-forcer can't infer which codes were ever valid."""
    # Seed and consume one code, seed an expired one, leave a third unused.
    design, version = await _seed_design_with_version(db)
    consumed_code = (
        await client.post(
            f"/designs/{design.id}/versions/{version.id}/handoffs"
        )
    ).json()["code"]
    await client.post("/handoffs/redeem", json={"code": consumed_code})

    db.add(
        DesignHandoff(
            code="EXPIREDY",
            design_version_id=version.id,
            user_id=DEV_USER_ID,
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await db.commit()

    bodies = []
    for code in (consumed_code, "EXPIREDY", "NEVERHAD"):
        resp = await client.post("/handoffs/redeem", json={"code": code})
        assert resp.status_code == 404
        bodies.append(resp.json())
    assert bodies[0] == bodies[1] == bodies[2]


# --- rate limiter ---------------------------------------------------------


async def test_redeem_handoff_rate_limited_at_threshold(
    client: AsyncClient,
) -> None:
    """11 redemption attempts in <60s from the same IP — the 11th is
    429. Use a known-bad code so each request hits the limiter and 404s,
    keeping the test independent of issuance state."""
    bad_code = "NOTACODE"  # 8 chars, all safe-alphabet
    for i in range(designs_route._REDEEM_LIMIT_SHORT):
        resp = await client.post("/handoffs/redeem", json={"code": bad_code})
        assert resp.status_code == 404, f"call {i + 1}: expected 404, got {resp.status_code}"
    # The 11th call exceeds the short-window limit.
    resp = await client.post("/handoffs/redeem", json={"code": bad_code})
    assert resp.status_code == 429


async def test_redeem_handoff_rate_limit_window_slides_via_clock(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once we've burned through the short-window limit, advancing the
    `_now()` clock past the 60s window must let new requests through.
    Monkeypatches the limiter's `_now` so the test doesn't sleep."""
    fake_now = [1_000_000.0]

    def _patched_now() -> float:
        return fake_now[0]

    monkeypatch.setattr(designs_route, "_now", _patched_now)
    # Re-reset history so the patched clock is the only timeline.
    designs_route._reset_redeem_history_for_tests()

    bad_code = "NOTACODE"
    for _ in range(designs_route._REDEEM_LIMIT_SHORT):
        await client.post("/handoffs/redeem", json={"code": bad_code})
    blocked = await client.post("/handoffs/redeem", json={"code": bad_code})
    assert blocked.status_code == 429

    # Advance past the short window; long window still permits 100/day.
    fake_now[0] += 61.0
    after_window = await client.post(
        "/handoffs/redeem", json={"code": bad_code}
    )
    assert after_window.status_code == 404, (
        "after the short window slides past, redemption attempts should "
        "be processed again (and 404 because the code is unknown)"
    )


# --- cleanup sweep --------------------------------------------------------


async def test_cleanup_expired_handoffs_deletes_old_rows(
    db: AsyncSession,
) -> None:
    design, version = await _seed_design_with_version(db)

    old = DesignHandoff(
        code="OLDLLLLL",
        design_version_id=version.id,
        user_id=DEV_USER_ID,
        expires_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    recent_expired = DesignHandoff(
        code="RECENTYY",
        design_version_id=version.id,
        user_id=DEV_USER_ID,
        # Expired 1 hour ago — within the 1-day grace window so cleanup
        # leaves it. Lets us test the "old enough" boundary.
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    fresh = DesignHandoff(
        code="FRESHHHH",
        design_version_id=version.id,
        user_id=DEV_USER_ID,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add_all([old, recent_expired, fresh])
    await db.commit()

    removed = await designs_route.cleanup_expired_handoffs(db)
    assert removed == 1

    remaining = list(
        (
            await db.execute(select(DesignHandoff.code).order_by(DesignHandoff.code))
        )
        .scalars()
        .all()
    )
    assert "OLDLLLLL" not in remaining
    assert "RECENTYY" in remaining
    assert "FRESHHHH" in remaining
