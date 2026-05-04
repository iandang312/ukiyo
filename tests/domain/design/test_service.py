from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.domain.design.service import (
    CanvasDelta,
    CanvasDone,
    generate_full,
    generate_scoped,
)
from ukiyo_service.infrastructure.db.models import (
    Conversation,
    Design,
    DesignVersion,
)
from ukiyo_service.infrastructure.db.session import (
    DEV_USER_ID,
    ensure_dev_user,
)
from ukiyo_service.infrastructure.llm import Chunk


pytestmark = pytest.mark.asyncio(loop_scope="session")


class _FakeProvider:
    """Yields one chunk per pre-canned delta, then a trailing usage chunk.
    Mirrors `_FakeStreamProvider` in tests/routes/test_messages.py — same
    contract: mid-chunks have only `delta`, trailing chunk has empty delta
    + finish_reason + token totals."""

    def __init__(
        self,
        deltas: list[str],
        tokens_in: int = 30,
        tokens_out: int = 50,
    ) -> None:
        self._deltas = deltas
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls = 0  # how many times .stream() was started

    async def stream(
        self, messages: Any, model: str, **opts: Any
    ) -> AsyncIterator[Chunk]:
        self.calls += 1
        for d in self._deltas:
            yield Chunk(
                delta=d, finish_reason=None, tokens_in=None, tokens_out=None
            )
        yield Chunk(
            delta="",
            finish_reason="stop",
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
        )


class _FakeMultiProvider:
    """Each call to .stream() consumes the next list from `responses`. Lets
    a test simulate "first attempt returns full doc, retry returns
    fragment" scenarios."""

    def __init__(
        self,
        responses: list[list[str]],
        tokens_in: int = 30,
        tokens_out: int = 50,
    ) -> None:
        self._responses = responses
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls = 0

    async def stream(
        self, messages: Any, model: str, **opts: Any
    ) -> AsyncIterator[Chunk]:
        idx = self.calls
        self.calls += 1
        deltas = self._responses[idx]
        for d in deltas:
            yield Chunk(
                delta=d, finish_reason=None, tokens_in=None, tokens_out=None
            )
        yield Chunk(
            delta="",
            finish_reason="stop",
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
        )


@pytest_asyncio.fixture
async def design(db: AsyncSession) -> Design:
    """Create a conversation + design owned by the dev user. The design has
    no current_version_id yet — `generate_full` will populate it."""
    await ensure_dev_user(db)
    conv = Conversation(user_id=DEV_USER_ID, title="canvas test")
    db.add(conv)
    await db.flush()
    d = Design(conversation_id=conv.id, user_id=DEV_USER_ID)
    db.add(d)
    await db.flush()
    return d


def _find_uid_for_tag(html: str, tag_name: str, *, content_substr: str | None = None) -> int:
    """Walk the persisted HTML, return the data-uid of the first element
    matching `tag_name` (and optionally containing `content_substr`)."""
    parser = LexborHTMLParser(html)
    counter = 0
    for el in parser.root.traverse(include_text=False):
        if el.tag == tag_name:
            if content_substr is None or content_substr in (el.html or ""):
                return counter
        counter += 1
    raise AssertionError(f"no <{tag_name}> found in HTML")


async def _drain(gen) -> tuple[list[str], CanvasDone]:
    deltas: list[str] = []
    done: CanvasDone | None = None
    async for ev in gen:
        if isinstance(ev, CanvasDelta):
            deltas.append(ev.text)
        elif isinstance(ev, CanvasDone):
            done = ev
    assert done is not None, "service must yield exactly one CanvasDone"
    return deltas, done


# --- generate_full --------------------------------------------------------


async def test_generate_full_persists_version_with_uids_and_helper(
    db: AsyncSession, design: Design
) -> None:
    full_doc = (
        "<!doctype html><html><head><title>t</title></head><body>"
        '<div class="card"><p>hello</p></div>'
        "</body></html>"
    )
    provider = _FakeProvider([full_doc])

    deltas, done = await _drain(
        generate_full(
            db=db,
            design=design,
            prompt="build a card",
            provider=provider,
            model="gpt-4o",
        )
    )

    assert "".join(deltas) == full_doc
    assert isinstance(done.version, DesignVersion)
    assert done.tokens_in == 30 and done.tokens_out == 50

    # Persisted HTML carries data-uids on every original element. The
    # CSP <meta> and helper <script> are injected after tagging and are
    # intentionally tagless — they're not user-editable.
    persisted = done.version.html
    parser = LexborHTMLParser(persisted)
    tagged_uids: list[int] = []
    for el in parser.root.traverse(include_text=False):
        is_csp_meta = (
            el.tag == "meta"
            and el.attributes.get("http-equiv") == "Content-Security-Policy"
        )
        is_helper_script = el.tag == "script" and "ukiyo:select" in (el.html or "")
        if is_csp_meta or is_helper_script:
            assert "data-uid" not in el.attributes
            continue
        assert "data-uid" in el.attributes, f"<{el.tag}> missing data-uid"
        tagged_uids.append(int(el.attributes["data-uid"]))

    # And the user-content uids are still a contiguous 0..N-1 sequence —
    # injection didn't shift them.
    assert tagged_uids == list(range(len(tagged_uids)))

    # Helper script + click handler are baked in.
    assert "ukiyo:select" in persisted
    assert "addEventListener('click'" in persisted

    # Design's current_version_id was advanced.
    assert design.current_version_id == done.version.id
    assert done.version.version_number == 1
    assert done.version.parent_version_id is None
    assert done.version.edit_scope_selector is None
    assert done.version.model_used == "gpt-4o"


async def test_generate_full_emits_csp_with_connect_src_none(
    db: AsyncSession, design: Design
) -> None:
    """Defense in depth — `connect-src 'none'` is the load-bearing CSP rule
    (kills outbound fetch even from injected scripts). Lock it with a
    test so a future tweak to the CSP can't silently drop it."""
    full_doc = (
        "<!doctype html><html><head></head><body><p>x</p></body></html>"
    )
    provider = _FakeProvider([full_doc])

    _, done = await _drain(
        generate_full(
            db=db,
            design=design,
            prompt="anything",
            provider=provider,
            model="gpt-4o",
        )
    )

    persisted = done.version.html
    assert 'http-equiv="Content-Security-Policy"' in persisted
    assert "connect-src 'none'" in persisted


async def test_generate_full_wraps_bare_fragment_response(
    db: AsyncSession, design: Design
) -> None:
    """If the LLM ignores the system prompt and returns a bare fragment
    instead of a full doc, the service degrades by wrapping rather than
    failing."""
    provider = _FakeProvider(["<div><p>no doctype here</p></div>"])

    _, done = await _drain(
        generate_full(
            db=db,
            design=design,
            prompt="anything",
            provider=provider,
            model="gpt-4o",
        )
    )

    persisted = done.version.html.lower()
    assert "<!doctype html>" in persisted
    assert "<html" in persisted
    assert "no doctype here" in persisted


async def test_generate_full_increments_version_number_across_turns(
    db: AsyncSession, design: Design
) -> None:
    full_doc = "<!doctype html><html><body><p>v</p></body></html>"
    provider = _FakeProvider([full_doc])

    _, first = await _drain(
        generate_full(
            db=db, design=design, prompt="v1",
            provider=provider, model="gpt-4o",
        )
    )
    _, second = await _drain(
        generate_full(
            db=db, design=design, prompt="v2",
            provider=provider, model="gpt-4o",
        )
    )

    assert first.version.version_number == 1
    assert second.version.version_number == 2
    assert second.version.parent_version_id == first.version.id
    assert design.current_version_id == second.version.id


# --- generate_scoped ------------------------------------------------------


async def _seed_canvas_v1(db: AsyncSession, design: Design) -> DesignVersion:
    """Seed a v1 with a known structure so scoped-edit tests have a
    deterministic uid layout to target."""
    full_doc = (
        "<!doctype html><html><head></head><body>"
        '<header><h1>Original Title</h1></header>'
        '<main><div id="card"><p>original-card-text</p></div></main>'
        '<footer><span>foot</span></footer>'
        "</body></html>"
    )
    provider = _FakeProvider([full_doc])
    _, done = await _drain(
        generate_full(
            db=db, design=design, prompt="seed",
            provider=provider, model="gpt-4o",
        )
    )
    return done.version


async def test_generate_scoped_replaces_only_target_subtree(
    db: AsyncSession, design: Design
) -> None:
    v1 = await _seed_canvas_v1(db, design)
    # Find the uid of the div#card so we can target it.
    div_uid = _find_uid_for_tag(
        v1.html, "div", content_substr="original-card-text"
    )

    fragment = '<div id="card" class="bg-red-500"><p>NEW-card-text</p></div>'
    provider = _FakeProvider([fragment])

    _, done = await _drain(
        generate_scoped(
            db=db,
            design=design,
            current_version=v1,
            edit_scope_uid=div_uid,
            prompt="make the card red",
            provider=provider,
            model="gpt-4o",
        )
    )

    persisted = done.version.html
    # Targeted subtree changed.
    assert "NEW-card-text" in persisted
    assert "original-card-text" not in persisted
    assert "bg-red-500" in persisted
    # Untouched subtrees survived.
    assert "Original Title" in persisted
    assert "foot" in persisted

    # Bookkeeping.
    assert done.version.version_number == 2
    assert done.version.parent_version_id == v1.id
    assert done.version.edit_scope_selector == str(div_uid)
    assert design.current_version_id == done.version.id


async def test_generate_scoped_retries_on_full_doc_response(
    db: AsyncSession, design: Design
) -> None:
    """When the first attempt returns a full doc instead of a fragment,
    the service retries once with stricter instructions and uses the
    second result if it's a clean fragment."""
    v1 = await _seed_canvas_v1(db, design)
    div_uid = _find_uid_for_tag(
        v1.html, "div", content_substr="original-card-text"
    )

    bad_full_doc = (
        "<!doctype html><html><body>"
        '<div id="card"><p>SHOULD-NOT-LAND</p></div>'
        "</body></html>"
    )
    good_fragment = '<div id="card"><p>RETRIED-text</p></div>'
    provider = _FakeMultiProvider([[bad_full_doc], [good_fragment]])

    _, done = await _drain(
        generate_scoped(
            db=db,
            design=design,
            current_version=v1,
            edit_scope_uid=div_uid,
            prompt="make it short",
            provider=provider,
            model="gpt-4o",
        )
    )

    assert provider.calls == 2, "service must retry exactly once"
    persisted = done.version.html
    assert "RETRIED-text" in persisted
    assert "SHOULD-NOT-LAND" not in persisted
    # Other subtrees still intact.
    assert "Original Title" in persisted

    # Token totals are additive across the two provider calls.
    assert done.tokens_in == 60
    assert done.tokens_out == 100


async def test_generate_scoped_falls_back_when_retry_also_returns_full_doc(
    db: AsyncSession, design: Design
) -> None:
    """Both attempts ignored the fragment instruction. Don't raise — splice
    body-inner content into the requested scope so the user gets *something*
    rather than a 500."""
    v1 = await _seed_canvas_v1(db, design)
    div_uid = _find_uid_for_tag(
        v1.html, "div", content_substr="original-card-text"
    )

    full_doc_a = (
        "<!doctype html><html><body>"
        '<section id="card"><p>FALLBACK-from-doc-a</p></section>'
        "</body></html>"
    )
    full_doc_b = (
        "<!doctype html><html><body>"
        '<section id="card"><p>FALLBACK-from-doc-b</p></section>'
        "</body></html>"
    )
    provider = _FakeMultiProvider([[full_doc_a], [full_doc_b]])

    _, done = await _drain(
        generate_scoped(
            db=db,
            design=design,
            current_version=v1,
            edit_scope_uid=div_uid,
            prompt="make it bigger",
            provider=provider,
            model="gpt-4o",
        )
    )

    assert provider.calls == 2
    persisted = done.version.html
    # Body-inner from the *second* attempt is what gets spliced.
    assert "FALLBACK-from-doc-b" in persisted
    # Original target subtree is gone.
    assert "original-card-text" not in persisted
    # No raise — version was created and is the new current_version.
    assert done.version.version_number == 2
    assert design.current_version_id == done.version.id


async def test_generate_scoped_uses_first_attempt_when_already_a_fragment(
    db: AsyncSession, design: Design
) -> None:
    """Sanity check the no-retry path — single provider call when the
    first response is already a clean fragment."""
    v1 = await _seed_canvas_v1(db, design)
    div_uid = _find_uid_for_tag(
        v1.html, "div", content_substr="original-card-text"
    )
    provider = _FakeMultiProvider(
        [['<div id="card"><p>FIRST-TRY</p></div>']]
    )

    _, _ = await _drain(
        generate_scoped(
            db=db,
            design=design,
            current_version=v1,
            edit_scope_uid=div_uid,
            prompt="x",
            provider=provider,
            model="gpt-4o",
        )
    )

    assert provider.calls == 1
