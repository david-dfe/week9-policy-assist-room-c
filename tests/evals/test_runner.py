"""Offline unit tests for the eval runner's scoring/parsing logic.

These tests must NEVER invoke the real Anthropic API. They exercise the
runner's pure helpers -- pattern matching, YAML loading, and the score
aggregator -- against canned responses.

The `evals` workflow (`.github/workflows/evals.yml`) is the only place
where live scoring runs, and it is gated on `workflow_dispatch`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.evals import run_evals


class _StubResponse:
    """Mimics the minimum surface of a langchain AIMessage."""

    def __init__(self, content: str) -> None:
        self.content = content


def test_substring_pattern_matches_case_insensitive() -> None:
    matched, pattern = run_evals.match_any(
        response_text="Welfare checks must be recorded every 30 minutes.",
        patterns=["30 MINUTES", "every 30"],
    )
    assert matched is True
    assert pattern == "30 MINUTES"


def test_regex_pattern_matches() -> None:
    matched, pattern = run_evals.match_any(
        response_text="Officers must review every thirty  minutes.",
        patterns=["re:every\\s+thirty\\s+min"],
    )
    assert matched is True
    assert pattern == "re:every\\s+thirty\\s+min"


def test_no_match_returns_fail() -> None:
    matched, pattern = run_evals.match_any(
        response_text="The manual does not cover this.",
        patterns=["30 minutes", "re:24\\s*hours"],
    )
    assert matched is False
    assert pattern is None


def test_empty_expect_any_treated_as_placeholder_and_fails() -> None:
    matched, pattern = run_evals.match_any(
        response_text="Anything at all.",
        patterns=[],
    )
    assert matched is False
    assert pattern is None


def test_load_golden_returns_list_of_dicts(tmp_path: Path) -> None:
    golden_file = tmp_path / "golden.yaml"
    golden_file.write_text('- id: sample\n  question: What?\n  expect_any:\n    - "answer"\n')
    entries = run_evals.load_golden(golden_file)
    assert isinstance(entries, list)
    assert entries == [
        {"id": "sample", "question": "What?", "expect_any": ["answer"]},
    ]


def test_load_golden_rejects_non_list(tmp_path: Path) -> None:
    golden_file = tmp_path / "bad.yaml"
    golden_file.write_text("not_a_list: true\n")
    with pytest.raises(ValueError, match="list"):
        run_evals.load_golden(golden_file)


def test_score_returns_pass_count_and_total() -> None:
    results = [
        {"id": "a", "pass": True, "matched": "x", "response": "x"},
        {"id": "b", "pass": False, "matched": None, "response": "y"},
        {"id": "c", "pass": True, "matched": "z", "response": "z"},
    ]
    passes, total, ratio = run_evals.score(results)
    assert passes == 2
    assert total == 3
    assert ratio == pytest.approx(2 / 3)


def test_score_handles_empty_result_list() -> None:
    passes, total, ratio = run_evals.score([])
    assert passes == 0
    assert total == 0
    assert ratio == 0.0


def test_run_uses_injected_llm_and_returns_structured_results(
    tmp_path: Path,
) -> None:
    """`run_entries` exercises scoring end-to-end with an injected LLM."""

    entries = [
        {"id": "hit", "question": "q1", "expect_any": ["yes"]},
        {"id": "miss", "question": "q2", "expect_any": ["nope"]},
    ]

    def fake_invoke(question: str) -> _StubResponse:
        return _StubResponse(content="YES, indeed." if question == "q1" else "sorry")

    results = run_evals.run_entries(entries, invoke=fake_invoke)
    ids = [r["id"] for r in results]
    passes = [r["pass"] for r in results]
    assert ids == ["hit", "miss"]
    assert passes == [True, False]
    # Response text must be captured for the CLI table, but responses are
    # ephemeral: they never get persisted by run_entries itself.
    assert results[0]["response"].startswith("YES")


def test_run_entries_skips_entries_without_expect_any() -> None:
    """Placeholder entries with no patterns must fail closed."""
    entries = [{"id": "placeholder", "question": "q", "expect_any": []}]

    def fake_invoke(_: str) -> _StubResponse:
        return _StubResponse(content="anything")

    results = run_evals.run_entries(entries, invoke=fake_invoke)
    assert results[0]["pass"] is False
    assert results[0]["matched"] is None
