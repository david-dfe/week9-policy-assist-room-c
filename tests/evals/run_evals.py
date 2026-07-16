#!/usr/bin/env python3
"""Run the golden-set evals against the real Anthropic API.

Usage:

    python tests/evals/run_evals.py [--golden PATH] [--threshold FLOAT] [--json]

Costs real money (~£0.05 per full run at Sonnet 4.5). Prints a pass/fail
table plus overall pass rate. Exits non-zero if the pass rate is below
the threshold read from `policyassist.config.EVAL_PASS_THRESHOLD` (or
overridden via ``--threshold``).

**Privacy (CLAUDE.md §9.1):** the runner NEVER persists raw
question/answer text to a committed file. Response text lives in memory
for the pass/fail table (and the optional ``--json`` blob that CI stores
as a build artefact only). It never touches the app's `chat_log/`
history store.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_GOLDEN_PATH = Path(__file__).parent / "golden.yaml"
_REGEX_PREFIX = "re:"


class _MessageLike(Protocol):
    content: Any


InvokeFn = Callable[[str], _MessageLike]


# ---------------------------------------------------------------------------
# Pure helpers -- covered by tests/evals/test_runner.py
# ---------------------------------------------------------------------------


def match_any(response_text: str, patterns: list[str]) -> tuple[bool, str | None]:
    """Return ``(matched, pattern)`` for the first pattern that matches.

    - Case-insensitive substring by default.
    - Patterns prefixed with ``re:`` are treated as regex (also case-insensitive).
    - Returns ``(False, None)`` if the list is empty or nothing matches.
    """
    if not patterns:
        return False, None
    haystack_ci = response_text.casefold()
    for pattern in patterns:
        if pattern.startswith(_REGEX_PREFIX):
            body = pattern[len(_REGEX_PREFIX) :]
            if re.search(body, response_text, flags=re.IGNORECASE):
                return True, pattern
        else:
            if pattern.casefold() in haystack_ci:
                return True, pattern
    return False, None


def load_golden(path: Path) -> list[dict[str, Any]]:
    """Load ``golden.yaml`` and validate it deserialises to a list of dicts."""
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a list of entries at the top level")
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}[{i}]: expected a mapping, got {type(entry).__name__}")
    return data


def score(results: list[dict[str, Any]]) -> tuple[int, int, float]:
    """Aggregate results into ``(passes, total, pass_ratio)``."""
    total = len(results)
    passes = sum(1 for r in results if r.get("pass"))
    ratio = (passes / total) if total else 0.0
    return passes, total, ratio


def run_entries(
    entries: list[dict[str, Any]],
    invoke: InvokeFn,
) -> list[dict[str, Any]]:
    """Invoke ``invoke(question)`` for each entry and score the response."""
    results: list[dict[str, Any]] = []
    for entry in entries:
        entry_id = str(entry.get("id", "<unknown>"))
        question = str(entry.get("question", ""))
        patterns_raw = entry.get("expect_any") or []
        patterns = [str(p) for p in patterns_raw]

        response = invoke(question)
        content = response.content if isinstance(response.content, str) else str(response.content)
        matched, pattern = match_any(content, patterns)

        results.append(
            {
                "id": entry_id,
                "question": question,
                "pass": matched,
                "matched": pattern,
                "response": content,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Live-LLM plumbing -- exercised only when the CLI is invoked, never in unit tests.
# ---------------------------------------------------------------------------


def _build_live_invoke() -> InvokeFn:
    """Build an ``invoke`` closure that talks to the real Anthropic API.

    Imports happen lazily so the offline unit tests never trigger the
    langchain/anthropic import chain (or require ``SECRET_KEY`` etc.).
    """
    # Deferred imports: keep the offline test path cheap and env-free.
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import HumanMessage, SystemMessage

    from policyassist.app import MAX_TOKENS, MODEL, SYSTEM_PROMPT_BLOCK
    from policyassist.config import LLM_TIMEOUT_SECONDS

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Source the repo `.env` before running evals."
        )

    llm = ChatAnthropic(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        api_key=api_key,
        timeout=LLM_TIMEOUT_SECONDS,
    )

    def _invoke(question: str) -> Any:
        # Evals are stateless: no history, matching the plan's spec.
        messages = [
            SystemMessage(content=[SYSTEM_PROMPT_BLOCK]),
            HumanMessage(content=question),
        ]
        return llm.invoke(messages)

    return _invoke


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _format_table(results: list[dict[str, Any]]) -> str:
    header = f"{'id':<40} {'pass':<6} reason"
    sep = "-" * len(header)
    lines = [header, sep]
    for r in results:
        entry_id = r["id"][:40]
        verdict = "PASS" if r["pass"] else "FAIL"
        if r["pass"]:
            reason = f"matched {r['matched']!r}"
        else:
            snippet = r["response"].strip().replace("\n", " ")
            if len(snippet) > 80:
                snippet = snippet[:77] + "..."
            reason = f"no match; got: {snippet}"
        lines.append(f"{entry_id:<40} {verdict:<6} {reason}")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PolicyAssist golden-set evals against the real LLM."
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=DEFAULT_GOLDEN_PATH,
        help="Path to golden.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override pass-rate threshold (default: policyassist.config.EVAL_PASS_THRESHOLD)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (for CI artefacts).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    # Deferred import so the CLI can still print --help without env vars set.
    from policyassist.config import EVAL_PASS_THRESHOLD

    threshold = args.threshold if args.threshold is not None else EVAL_PASS_THRESHOLD

    entries = load_golden(args.golden)
    invoke = _build_live_invoke()
    results = run_entries(entries, invoke=invoke)
    passes, total, ratio = score(results)

    if args.json:
        payload = {
            "threshold": threshold,
            "passes": passes,
            "total": total,
            "pass_ratio": ratio,
            "results": [
                {
                    "id": r["id"],
                    "pass": r["pass"],
                    "matched": r["matched"],
                    # Response text is present in the artefact but not in
                    # any file committed by the runner. CI stores the JSON
                    # as a workflow artefact only.
                    "response": r["response"],
                }
                for r in results
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(_format_table(results))
        print()
        pct = ratio * 100
        print(f"Overall: {passes} / {total} ({pct:.1f}%)  threshold={threshold:.2f}")

    return 0 if (total > 0 and ratio >= threshold) else 1


if __name__ == "__main__":
    raise SystemExit(main())
