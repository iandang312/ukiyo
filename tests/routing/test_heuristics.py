from __future__ import annotations

import pytest

from ukiyo_service.domain.routing.classifier import (
    HEURISTIC_BOOST,
    _apply_heuristic_boosts,
)


def _base() -> dict[str, float]:
    return {"coding": 0.40, "design": 0.40, "research": 0.40}


def test_no_patterns_means_no_boost() -> None:
    assert _apply_heuristic_boosts("hello there", _base()) == _base()


def test_triple_backtick_boosts_coding_only() -> None:
    prompt = "Here is a snippet:\n```\nx = 1\n```"
    out = _apply_heuristic_boosts(prompt, _base())

    assert out["coding"] == pytest.approx(0.40 + HEURISTIC_BOOST)
    assert out["design"] == pytest.approx(0.40)
    assert out["research"] == pytest.approx(0.40)


def test_def_keyword_boosts_coding() -> None:
    out = _apply_heuristic_boosts("show me how to def a generator", _base())
    assert out["coding"] == pytest.approx(0.50)


def test_function_keyword_is_case_insensitive() -> None:
    out = _apply_heuristic_boosts("write a Function that returns 1", _base())
    assert out["coding"] == pytest.approx(0.50)


def test_def_keyword_is_case_insensitive() -> None:
    out = _apply_heuristic_boosts("DEF foo(): return 1", _base())
    assert out["coding"] == pytest.approx(0.50)


def test_python_traceback_boosts_coding() -> None:
    prompt = (
        'Traceback (most recent call last):\n'
        '  File "app.py", line 42, in handler\n'
        '    raise ValueError("nope")'
    )
    out = _apply_heuristic_boosts(prompt, _base())
    assert out["coding"] == pytest.approx(0.50)


def test_jvm_stack_frame_boosts_coding() -> None:
    prompt = "got NPE at com.acme.Order.handle(Order.java:42)"
    out = _apply_heuristic_boosts(prompt, _base())
    assert out["coding"] == pytest.approx(0.50)


def test_research_keywords_boost_research_only() -> None:
    out = _apply_heuristic_boosts(
        "find me primary sources on this topic", _base()
    )

    assert out["research"] == pytest.approx(0.50)
    assert out["coding"] == pytest.approx(0.40)
    assert out["design"] == pytest.approx(0.40)


@pytest.mark.parametrize(
    "word",
    ["research", "papers", "citation", "sources", "literature"],
)
def test_each_research_keyword_triggers_the_boost(word: str) -> None:
    out = _apply_heuristic_boosts(f"please cite {word} on this", _base())
    assert out["research"] == pytest.approx(0.50)


@pytest.mark.parametrize(
    "word",
    ["wireframe", "layout", "UX", "color", "design system", "Figma"],
)
def test_each_design_keyword_triggers_the_boost(word: str) -> None:
    out = _apply_heuristic_boosts(f"give me a {word} for the homepage", _base())
    assert out["design"] == pytest.approx(0.50)


def test_design_keywords_are_case_insensitive() -> None:
    out = _apply_heuristic_boosts("FIGMA export details please", _base())
    assert out["design"] == pytest.approx(0.50)


def test_repeated_pattern_in_same_bucket_only_boosts_once() -> None:
    """Two coding triggers in one prompt should not double-boost coding."""
    prompt = "```py\ndef foo(): pass\n```"  # both ``` and `def `
    out = _apply_heuristic_boosts(prompt, _base())

    assert out["coding"] == pytest.approx(0.50)


def test_boosts_stack_across_buckets() -> None:
    """A single prompt can boost multiple buckets — they stack."""
    prompt = (
        "Build a wireframe for the docs page and cite recent papers on "
        "information architecture. Here is starter code:\n```\nx = 1\n```"
    )
    out = _apply_heuristic_boosts(prompt, _base())

    assert out["coding"] == pytest.approx(0.50)
    assert out["design"] == pytest.approx(0.50)
    assert out["research"] == pytest.approx(0.50)


def test_boost_is_not_applied_when_bucket_missing() -> None:
    """If a bucket isn't in scores (no exemplars), the boost is dropped."""
    scores = {"design": 0.40}
    out = _apply_heuristic_boosts("```code```", scores)

    assert out == {"design": 0.40}


def test_heuristic_does_not_mutate_input() -> None:
    scores = _base()
    snapshot = dict(scores)
    _apply_heuristic_boosts("def foo()", scores)

    assert scores == snapshot
