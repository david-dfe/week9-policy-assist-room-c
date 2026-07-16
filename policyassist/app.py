"""PolicyAssist -- internal guidance chat tool.

Reference client for the monitoring service. Wave 1 hardening:

* Flask signed-cookie session gives each browser a stable sid.
* HistoryStore isolates per-session conversation, trimmed to
  HISTORY_MAX_TURNS turns before every LLM call.
* Monitoring instrumentation preserved from the prototype+monitoring
  bridge -- no changes to the traced_llm_call surface.

Wave 2A adds reliability guards on ``/ask``:

* Slice D -- hand-rolled input validation at the top of ``ask()``, returns
  400 JSON errors instead of letting bad input reach the LLM.
* Slice E -- ``llm.invoke`` runs inside ``try/except``; anthropic transport
  errors are mapped to 502 / 504 with a JSON ``{"error": "..."}`` body so
  the browser can render a red banner (see ``templates/index.html``).
* Slice F -- retry transient failures (connection, rate-limit, 5xx) with
  jittered exponential backoff. Non-retryable 4xx (bad prompt, auth) fail
  fast. The retry loop lives INSIDE ``traced_llm_call`` so one outer span
  records the final outcome; retries are not top-level spans.

Remaining SINs (caching landed in Slice C) land in later slices; this
file will grow -- keep the top-of-file section list in sync so a reader
can find each concern in ~10 seconds.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import anthropic
from flask import Flask, jsonify, render_template, request, session
from flask.wrappers import Response
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from tenacity import (
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from monitoring import instrument_app, traced_llm_call
from policyassist.config import (
    LLM_MAX_RETRIES,
    LLM_TIMEOUT_SECONDS,
    MAX_QUESTION_LENGTH,
)
from policyassist.history import HistoryStore

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1024

_HISTORY_ROOT = Path(
    os.environ.get(
        "POLICYASSIST_HISTORY_ROOT",
        str(Path(__file__).parent / "chat_log"),
    )
)
MANUAL_PATH = Path(__file__).parent / "manual.txt"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]

instrument_app(service_name="policyassist")

llm = ChatAnthropic(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    api_key=os.environ["ANTHROPIC_API_KEY"],
    timeout=LLM_TIMEOUT_SECONDS,
)

history_store = HistoryStore(_HISTORY_ROOT)

MANUAL = MANUAL_PATH.read_text()

SYSTEM_PROMPT = (
    "You are PolicyAssist, an internal assistant for Border Force officers. "
    "Answer questions using ONLY the operational manual below. "
    "If the manual does not cover the question, say so and advise the officer "
    "to contact the Duty Higher Officer. Be concise and practical.\n\n"
    "=== BORDER FORCE OPERATIONAL MANUAL (EXTRACT) ===\n\n" + MANUAL
)

# Mark the operational-manual portion of the system prompt for Anthropic
# ephemeral prompt caching. langchain-anthropic propagates the
# ``cache_control`` marker when the SystemMessage content is passed as a
# list of typed blocks (confirmed by the 2026-07-16 C1 spike).
SYSTEM_PROMPT_BLOCK: dict[str, Any] = {
    "type": "text",
    "text": SYSTEM_PROMPT,
    "cache_control": {"type": "ephemeral"},
}


# ---------------------------------------------------------------------------
# Slice F: retry policy
# ---------------------------------------------------------------------------
#
# We retry only on genuinely transient upstream failures:
#   - APIConnectionError  (includes APITimeoutError -- network / socket)
#   - RateLimitError      (429; upstream asked us to slow down)
#   - APIStatusError with 5xx (server-side; likely 529 overloaded)
#
# We do NOT retry BadRequestError, AuthenticationError, PermissionDeniedError
# etc -- those are 4xx that won't get better by retrying, so fail fast.
#
# NB: BadRequestError inherits from APIStatusError, so a plain
# ``retry_if_exception_type(APIStatusError)`` would incorrectly retry it.
# The predicate below narrows to 5xx (and 429, which subclasses APIStatusError).


def _should_retry(exc: BaseException) -> bool:
    """Retry predicate: transient upstream errors only."""
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        status = getattr(exc, "status_code", None)
        return isinstance(status, int) and status >= 500
    return False


# Wait strategy is exposed as a module-level attribute so tests can swap
# it for ``wait_none()`` -- production keeps the jittered exponential.
_RETRY_WAIT = wait_exponential_jitter(initial=1, max=8)


def _invoke_with_retry(messages: list[Any]) -> Any:
    """Call ``llm.invoke(messages)`` with tenacity-backed retries.

    The retry loop is defined inline so tests can monkeypatch either
    ``llm`` or ``_RETRY_WAIT`` after import.
    """
    for attempt in Retrying(
        stop=stop_after_attempt(LLM_MAX_RETRIES),
        wait=_RETRY_WAIT,
        retry=retry_if_exception(_should_retry),
        reraise=True,
    ):
        with attempt:
            return llm.invoke(messages)
    # Unreachable: Retrying always either returns or reraises.
    raise RuntimeError("unreachable")  # pragma: no cover


def _hoist_cache_metrics(response: Any) -> None:
    """Copy nested langchain-anthropic cache metrics to the top level.

    langchain-anthropic surfaces cache reads under
    ``usage_metadata["input_token_details"]["cache_read"]``, but
    ``monitoring/cost.py:usage_from_response`` looks for
    ``cache_read_input_tokens`` at the top level. Copy across, but do
    NOT overwrite a top-level value already set by the native SDK shape.
    """
    meta = getattr(response, "usage_metadata", None)
    if not isinstance(meta, dict):
        return
    details = meta.get("input_token_details")
    if not isinstance(details, dict):
        return
    for src, dst in (
        ("cache_read", "cache_read_input_tokens"),
        ("cache_creation", "cache_creation_input_tokens"),
    ):
        if dst in meta:
            continue
        val = details.get(src)
        if val is None:
            continue
        meta[dst] = int(val)


def _ensure_sid() -> str:
    sid = session.get("sid")
    if not sid:
        sid = uuid4().hex
        session["sid"] = sid
    return sid


def _validation_error(message: str) -> tuple[Response, int]:
    """Return a 400 JSON error response for a rejected /ask payload."""
    return jsonify({"error": message}), 400


@app.route("/")
def index() -> str:
    sid = _ensure_sid()
    return render_template("index.html", history=history_store.raw(sid))


@app.route("/ask", methods=["POST"])
def ask() -> tuple[Response, int] | dict[str, Any]:
    # -------------------------------------------------------------------
    # Slice D: validation runs BEFORE _ensure_sid() so a malformed
    # request does not churn the session cookie.
    # -------------------------------------------------------------------
    payload = request.get_json(silent=True)
    if payload is None:
        return _validation_error("request body must be JSON")
    if not isinstance(payload, dict) or "question" not in payload:
        return _validation_error("missing 'question'")
    question_raw = payload["question"]
    if not isinstance(question_raw, str):
        return _validation_error("'question' must be a string")
    question = question_raw.strip()
    if not question:
        return _validation_error("'question' must not be empty")
    if len(question) > MAX_QUESTION_LENGTH:
        return _validation_error(f"'question' exceeds {MAX_QUESTION_LENGTH} chars")

    sid = _ensure_sid()

    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=[SYSTEM_PROMPT_BLOCK])
    ]
    for entry in history_store.get_context(sid):
        messages.append(HumanMessage(content=entry["question"]))
        messages.append(AIMessage(content=entry["answer"]))
    messages.append(HumanMessage(content=question))

    # -------------------------------------------------------------------
    # Slice E + F: retry transient failures inside the outer span, then
    # map remaining anthropic transport errors to user-facing HTTP codes.
    # traced_llm_call already records the exception on the span.
    # -------------------------------------------------------------------
    try:
        with traced_llm_call(model=MODEL) as span:
            response = _invoke_with_retry(messages)
            _hoist_cache_metrics(response)
            span.record_usage(response)
    except anthropic.APITimeoutError:
        return (
            jsonify({"error": "The service is slow to respond. Please try again."}),
            504,
        )
    except (
        anthropic.APIConnectionError,
        anthropic.APIStatusError,
        anthropic.APIError,
    ):
        return (
            jsonify({"error": "Upstream service unavailable. Please try again."}),
            502,
        )

    answer = response.content
    history_store.append(sid, question, answer)

    return {"answer": answer}


if __name__ == "__main__":
    app.run(port=5000)
