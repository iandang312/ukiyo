from __future__ import annotations

from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode


@dataclass(frozen=True)
class ResolvedSubtree:
    uid: int
    html: str
    tag: str


def _iter_elements(root: LexborNode):
    """Preorder DFS over element nodes only.

    Lexbor synthesizes an `<html><head></head><body>...` wrapper around any
    fragment input, so a "5-element div fragment" parses as html/head/body +
    5 user elements. The walk is deterministic regardless: same input HTML
    always yields the same uid for the same node.
    """
    yield from root.traverse(include_text=False)


def tag_html(html: str) -> str:
    """Assign deterministic preorder data-uid attributes to every element.

    Strips any pre-existing data-uid first — the LLM may emit them since the
    scoped-edit prompt context shows them, and we never trust client values.
    """
    parser = LexborHTMLParser(html)
    counter = 0
    for el in _iter_elements(parser.root):
        if "data-uid" in el.attributes:
            del el.attributes["data-uid"]
        el.attrs["data-uid"] = str(counter)
        counter += 1
    return parser.html or ""


def resolve(uid: int, html: str) -> ResolvedSubtree:
    """Walk the document deterministically and return the subtree at `uid`.

    Re-runs the same preorder DFS used by `tag_html` so callers don't need
    to pre-tag the HTML — any input parses to the same uid scheme. Raises
    ValueError on missing uid so the splice path can't silently no-op.
    """
    if uid < 0:
        raise ValueError(f"data-uid must be non-negative, got {uid}")

    parser = LexborHTMLParser(html)
    counter = 0
    for el in _iter_elements(parser.root):
        if counter == uid:
            return ResolvedSubtree(uid=uid, html=el.html or "", tag=el.tag)
        counter += 1

    raise ValueError(f"data-uid {uid} not found in document")
