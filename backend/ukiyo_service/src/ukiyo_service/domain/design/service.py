"""Canvas-surface generation service.

Streams a design through an LLM provider, validates the response shape,
splices in scoped edits, bakes in the click-capture helper + CSP, and
persists a new `design_versions` row + advances `designs.current_version_id`.

Exposes two coroutines that the route layer iterates as async generators
of `CanvasDelta` (mid-stream content) and `CanvasDone` (final persisted
version + token totals). The route translates these into SSE events.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ukiyo_service.domain.design.prompts import (
    CANVAS_SCOPED_EDIT_PROMPT,
    CANVAS_SYSTEM_PROMPT,
)
from ukiyo_service.domain.design.tagging import resolve, tag_html
from ukiyo_service.infrastructure.db.models import Design, DesignVersion
from ukiyo_service.infrastructure.llm import LLMProvider, Message as LLMMessage


# `connect-src 'none'` is load-bearing — kills outbound fetch even for
# inline scripts the LLM might insert. The Tailwind CDN host is allowed
# under script-src/style-src so the system prompt's CDN reference works;
# Tailwind's runtime is JIT-CSS-only (no XHR), so connect-src stays sealed.
_CSP_META = (
    '<meta http-equiv="Content-Security-Policy" content='
    '"default-src \'none\'; '
    "script-src 'unsafe-inline' https://cdn.tailwindcss.com; "
    "style-src 'unsafe-inline' https://cdn.tailwindcss.com; "
    "img-src https: data:; "
    "font-src https: data:; "
    "connect-src 'none';"
    '">'
)

# The click handler is the original Phase 12 contract — kept byte-for-byte
# so existing tests / persisted versions still grep for "addEventListener('click'"
# and "ukiyo:select". The `message` listener is a Phase 13 addition: the
# canvas drawer needs the clicked element's bounding rect to position the
# scoped-edit overlay. Round-trip via postMessage is required because
# sandbox="allow-scripts" (without allow-same-origin) prevents the parent
# from accessing the iframe's document directly. Old versions persisted
# before this commit lack the rect handler — the frontend falls back to a
# centered overlay if no rect_reply arrives.
_HELPER_SCRIPT = (
    "<script>\n"
    "document.addEventListener('click', e => {\n"
    "  e.preventDefault();\n"
    "  const el = e.target.closest('[data-uid]');\n"
    "  if (el) parent.postMessage("
    "{type:'ukiyo:select', uid: el.dataset.uid, tag: el.tagName}, '*');\n"
    "}, true);\n"
    "window.addEventListener('message', e => {\n"
    "  const d = e.data;\n"
    "  if (!d || d.type !== 'ukiyo:rect_request') return;\n"
    "  const el = document.querySelector('[data-uid=\"' + d.uid + '\"]');\n"
    "  if (!el) return;\n"
    "  const r = el.getBoundingClientRect();\n"
    "  parent.postMessage({type:'ukiyo:rect_reply', uid: d.uid, "
    "rect: {x: r.x, y: r.y, width: r.width, height: r.height}}, '*');\n"
    "});\n"
    "</script>"
)


@dataclass(frozen=True)
class CanvasDelta:
    text: str


@dataclass(frozen=True)
class CanvasDone:
    version: DesignVersion
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class _StreamResult:
    """Sentinel emitted at the end of one provider stream — carries the
    full accumulated text and token totals so callers can decide whether
    to retry."""

    text: str
    tokens_in: int
    tokens_out: int


CanvasEvent = CanvasDelta | CanvasDone


def _looks_like_full_doc(html: str) -> bool:
    lowered = html.lstrip().lower()
    return lowered.startswith("<!doctype") or "<html" in lowered[:200]


def _looks_like_fragment(html: str) -> bool:
    """A fragment must not contain `<html` or `<body>` tags. Lowercase the
    haystack so the LLM emitting `<HTML>` doesn't slip through."""
    lowered = html.lower()
    return "<html" not in lowered and "<body" not in lowered


def _bake_canvas_html(html: str) -> str:
    """Tag with data-uids, then inject CSP + helper into <head>.

    The tagger always parses through lexbor, which synthesizes
    `<html><head></head><body>...` even if the LLM omitted them. So a
    `</head>` close tag is reliably present in the post-tag string.
    """
    tagged = tag_html(html)
    injection = _CSP_META + _HELPER_SCRIPT
    if "</head>" in tagged:
        return tagged.replace("</head>", injection + "</head>", 1)
    # Defensive: parser couldn't synthesize a head (should not happen for
    # text input). Prepend the injection so it still applies.
    return injection + tagged


def _splice_subtree(
    current_html: str, uid: int, new_fragment_html: str
) -> str:
    """Replace the subtree at `uid` in `current_html` with `new_fragment_html`.

    Uses lexbor's in-place `replace_with(node)` (the string overload
    HTML-escapes its input — that's why we go through a node). When the
    fragment has multiple top-level siblings we wrap them in a `<div>` so
    the call always has a single root to substitute.
    """
    parser = LexborHTMLParser(current_html)
    target = None
    counter = 0
    for el in parser.root.traverse(include_text=False):
        if counter == uid:
            target = el
            break
        counter += 1
    if target is None:
        raise ValueError(f"data-uid {uid} not found in current document")

    frag_parser = LexborHTMLParser(f"<div>{new_fragment_html}</div>")
    wrapper = frag_parser.body.child if frag_parser.body else None
    if wrapper is None:
        raise ValueError("could not parse new fragment HTML")

    element_children = []
    c = wrapper.child
    while c is not None:
        if c.tag and not c.tag.startswith("-"):
            element_children.append(c)
        c = c.next

    if len(element_children) == 1:
        target.replace_with(element_children[0])
    else:
        # Multi-root or text-only fragment — keep the wrapper div so all
        # of it lands in the target's slot.
        target.replace_with(wrapper)

    return parser.html or ""


def _extract_body_inner(full_doc_html: str) -> str:
    """Pull body's inner HTML from a full doc. Used by the fallback-splice
    path when the LLM ignored the fragment instruction twice — we still
    want to splice *something* meaningful instead of raising."""
    parser = LexborHTMLParser(full_doc_html)
    body = parser.body
    if body is None:
        return full_doc_html
    parts: list[str] = []
    c = body.child
    while c is not None:
        if c.html:
            parts.append(c.html)
        c = c.next
    return "".join(parts)


async def _stream_one_attempt(
    provider: LLMProvider,
    messages: list[LLMMessage],
    model: str,
    *,
    emit_deltas: bool,
) -> AsyncIterator[CanvasDelta | _StreamResult]:
    """Drive one provider stream. Yields `CanvasDelta` per token chunk
    when `emit_deltas` is True (suppressed on retries so the user doesn't
    see the bad first attempt overwritten in the iframe), then exactly one
    trailing `_StreamResult` carrying the accumulated text + token totals."""
    parts: list[str] = []
    tokens_in = 0
    tokens_out = 0
    async for chunk in provider.stream(messages, model):
        if chunk.delta:
            parts.append(chunk.delta)
            if emit_deltas:
                yield CanvasDelta(text=chunk.delta)
        if chunk.tokens_in is not None:
            tokens_in = chunk.tokens_in
        if chunk.tokens_out is not None:
            tokens_out = chunk.tokens_out
    yield _StreamResult(
        text="".join(parts), tokens_in=tokens_in, tokens_out=tokens_out
    )


async def _next_version_number(db: AsyncSession, design_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(DesignVersion.version_number), 0)).where(
        DesignVersion.design_id == design_id
    )
    return int((await db.execute(stmt)).scalar_one()) + 1


async def _persist_version(
    *,
    db: AsyncSession,
    design: Design,
    html: str,
    prompt: str,
    parent_version_id: uuid.UUID | None,
    edit_scope_selector: str | None,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> DesignVersion:
    version_number = await _next_version_number(db, design.id)
    version = DesignVersion(
        design_id=design.id,
        parent_version_id=parent_version_id,
        version_number=version_number,
        html=html,
        prompt=prompt,
        edit_scope_selector=edit_scope_selector,
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.add(version)
    await db.flush()  # populate version.id before we reference it on the design
    design.current_version_id = version.id
    return version


async def generate_full(
    *,
    db: AsyncSession,
    design: Design,
    prompt: str,
    provider: LLMProvider,
    model: str,
    history: list[LLMMessage] | None = None,
) -> AsyncIterator[CanvasEvent]:
    """Full-document canvas turn. Yields `CanvasDelta` events while the
    provider streams, then a single `CanvasDone` once the version is
    persisted and `design.current_version_id` is advanced.

    DB writes are flushed but not committed — the caller (route layer)
    owns the transaction so user/assistant message rows + the design
    version + the design row update all land together.
    """
    llm_messages: list[LLMMessage] = [
        LLMMessage(role="system", content=CANVAS_SYSTEM_PROMPT),
    ]
    if history:
        llm_messages.extend(history)
    llm_messages.append(LLMMessage(role="user", content=prompt))

    full_text = ""
    tokens_in = 0
    tokens_out = 0
    async for ev in _stream_one_attempt(
        provider, llm_messages, model, emit_deltas=True
    ):
        if isinstance(ev, CanvasDelta):
            yield ev
        else:
            full_text, tokens_in, tokens_out = ev.text, ev.tokens_in, ev.tokens_out

    # If the LLM ignored the system prompt and emitted a bare fragment,
    # wrap it in a minimal scaffold rather than failing — same degrade
    # philosophy as the scoped fallback.
    if not _looks_like_full_doc(full_text):
        full_text = (
            "<!doctype html><html><head>"
            '<script src="https://cdn.tailwindcss.com"></script>'
            f"</head><body>{full_text}</body></html>"
        )

    final_html = _bake_canvas_html(full_text)

    version = await _persist_version(
        db=db,
        design=design,
        html=final_html,
        prompt=prompt,
        parent_version_id=design.current_version_id,
        edit_scope_selector=None,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )

    yield CanvasDone(version=version, tokens_in=tokens_in, tokens_out=tokens_out)


async def generate_scoped(
    *,
    db: AsyncSession,
    design: Design,
    current_version: DesignVersion,
    edit_scope_uid: int,
    prompt: str,
    provider: LLMProvider,
    model: str,
    history: list[LLMMessage] | None = None,
) -> AsyncIterator[CanvasEvent]:
    """Scoped subtree edit. Loads the current version's HTML, resolves the
    target subtree, instructs the LLM to return *only* a replacement
    fragment, retries once on full-doc-shaped responses, and falls back to
    splicing whatever was returned (extracting body content) on the second
    failure rather than raising. Persists the spliced + re-tagged result
    as a new version with `parent_version_id = current_version.id`.
    """
    current_html = current_version.html
    subtree = resolve(edit_scope_uid, current_html)

    base_messages: list[LLMMessage] = [
        LLMMessage(role="system", content=CANVAS_SCOPED_EDIT_PROMPT),
    ]
    if history:
        base_messages.extend(history)
    context_user = (
        f"Current full document:\n```html\n{current_html}\n```\n\n"
        f"Target subtree (data-uid={edit_scope_uid}, <{subtree.tag}>):\n"
        f"```html\n{subtree.html}\n```\n\n"
        f"User instruction: {prompt}"
    )
    first_messages = list(base_messages) + [
        LLMMessage(role="user", content=context_user)
    ]

    fragment = ""
    tokens_in = 0
    tokens_out = 0
    async for ev in _stream_one_attempt(
        provider, first_messages, model, emit_deltas=True
    ):
        if isinstance(ev, CanvasDelta):
            yield ev
        else:
            fragment, tokens_in, tokens_out = ev.text, ev.tokens_in, ev.tokens_out

    if not _looks_like_fragment(fragment):
        # Retry once with stricter instructions. Suppress the retry's
        # mid-stream deltas — the user already saw the (wrong) first
        # attempt; re-streaming a different version on top would just
        # cause iframe churn. The route renders the iframe on `done`
        # anyway, so suppression has no UX cost in v1.
        retry_messages = list(first_messages) + [
            LLMMessage(
                role="user",
                content=(
                    "Your previous response included <html> or <body> tags. "
                    "Output ONLY the replacement subtree as a fragment — no "
                    "<html>, no <head>, no <body>, no <!doctype>. Just the "
                    "new element."
                ),
            ),
        ]
        retry_text = ""
        retry_in = 0
        retry_out = 0
        async for ev in _stream_one_attempt(
            provider, retry_messages, model, emit_deltas=False
        ):
            if isinstance(ev, _StreamResult):
                retry_text, retry_in, retry_out = (
                    ev.text,
                    ev.tokens_in,
                    ev.tokens_out,
                )

        # Retry tokens are additive — the bill includes both calls.
        tokens_in += retry_in
        tokens_out += retry_out

        if _looks_like_fragment(retry_text):
            fragment = retry_text
        else:
            # Both attempts ignored the fragment instruction. Degrade by
            # extracting body inner content and splicing that — the user
            # gets *something* in the requested slot rather than a 500.
            fragment = _extract_body_inner(retry_text)

    spliced = _splice_subtree(current_html, edit_scope_uid, fragment)
    final_html = _bake_canvas_html(spliced)

    version = await _persist_version(
        db=db,
        design=design,
        html=final_html,
        prompt=prompt,
        parent_version_id=current_version.id,
        edit_scope_selector=str(edit_scope_uid),
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )

    yield CanvasDone(version=version, tokens_in=tokens_in, tokens_out=tokens_out)
