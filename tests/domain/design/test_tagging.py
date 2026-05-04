from __future__ import annotations

import pytest
from selectolax.lexbor import LexborHTMLParser

from ukiyo_service.domain.design.tagging import (
    ResolvedSubtree,
    resolve,
    tag_html,
)


def _uids_in_order(html: str) -> list[int]:
    """Walk the result with the same preorder DFS the tagger uses and pull
    each element's data-uid attribute. Returns the uids in document order
    so tests can assert both presence and ordering."""
    parser = LexborHTMLParser(html)
    out: list[int] = []
    for el in parser.root.traverse(include_text=False):
        uid = el.attributes.get("data-uid")
        assert uid is not None, f"element <{el.tag}> missing data-uid"
        out.append(int(uid))
    return out


class TestTagHtml:
    def test_assigns_preorder_uids(self) -> None:
        html = (
            "<!doctype html><html><body>"
            "<div><p>one</p><span>two</span></div>"
            "<footer>three</footer>"
            "</body></html>"
        )
        result = tag_html(html)

        # Whatever the parser synthesizes, uids must be sequential 0..N-1
        # in document order.
        uids = _uids_in_order(result)
        assert uids == list(range(len(uids)))

        # Sanity: at least our 5 user elements (div, p, span, footer, plus
        # whatever lexbor synthesizes for html/head/body) are tagged.
        assert len(uids) >= 5

    def test_strips_existing_uids(self) -> None:
        html = (
            '<!doctype html><html><body>'
            '<div data-uid="99"><p data-uid="42">x</p></div>'
            "</body></html>"
        )
        result = tag_html(html)

        # The LLM-supplied uids must not survive.
        assert 'data-uid="99"' not in result
        assert 'data-uid="42"' not in result

        # And the result is a clean 0..N-1 sequence.
        uids = _uids_in_order(result)
        assert uids == list(range(len(uids)))

    def test_skips_text_nodes(self) -> None:
        # Plenty of text content between elements; the counter should advance
        # once per element, not per text node.
        html = (
            "<!doctype html><html><body>"
            "lead text"
            "<p>alpha bravo charlie</p>"
            "trailing text"
            "<p>delta echo</p>"
            "</body></html>"
        )
        result = tag_html(html)
        uids = _uids_in_order(result)

        # html, head, body, p, p — five element nodes regardless of the text.
        assert uids == [0, 1, 2, 3, 4]

    def test_round_trip_is_idempotent(self) -> None:
        # Running tag_html twice must produce the same uid scheme — the
        # second pass strips the first pass's uids before re-assigning.
        html = "<!doctype html><html><body><div><p>x</p></div></body></html>"
        once = tag_html(html)
        twice = tag_html(once)
        assert _uids_in_order(once) == _uids_in_order(twice)


class TestResolve:
    def test_returns_subtree_html(self) -> None:
        html = (
            "<!doctype html><html><body>"
            '<div class="card"><p>only-in-the-card</p></div>'
            "<footer>foot</footer>"
            "</body></html>"
        )
        tagged = tag_html(html)

        # Find the uid of the div.card by walking the result.
        parser = LexborHTMLParser(tagged)
        div_uid = None
        for el in parser.root.traverse(include_text=False):
            if el.tag == "div":
                div_uid = int(el.attributes["data-uid"])
                break
        assert div_uid is not None

        sub = resolve(div_uid, tagged)
        assert isinstance(sub, ResolvedSubtree)
        assert sub.uid == div_uid
        assert sub.tag == "div"
        # Subtree should contain its own content but not the sibling footer.
        assert "only-in-the-card" in sub.html
        assert "foot" not in sub.html

    def test_missing_uid_raises_value_error(self) -> None:
        html = "<!doctype html><html><body><p>x</p></body></html>"
        tagged = tag_html(html)
        with pytest.raises(ValueError, match="not found"):
            resolve(9999, tagged)

    def test_negative_uid_raises_value_error(self) -> None:
        html = "<!doctype html><html><body><p>x</p></body></html>"
        with pytest.raises(ValueError, match="non-negative"):
            resolve(-1, html)

    def test_resolve_works_on_untagged_html(self) -> None:
        # resolve() re-runs the deterministic walk, so it doesn't require
        # the input to already carry data-uid attributes.
        html = (
            "<!doctype html><html><body>"
            "<section><h1>title</h1></section>"
            "</body></html>"
        )
        # uid 0=html, 1=head, 2=body, 3=section, 4=h1
        sub = resolve(4, html)
        assert sub.tag == "h1"
        assert "title" in sub.html
