"""PolicyAssist -- internal guidance chat tool.

Reference client for the monitoring service. Wave 1 hardening:

* Flask signed-cookie session gives each browser a stable sid.
* HistoryStore isolates per-session conversation, trimmed to
  HISTORY_MAX_TURNS turns before every LLM call.
* Monitoring instrumentation preserved from the prototype+monitoring
  bridge -- no changes to the traced_llm_call surface.

Remaining SINs (retries, caching, validation, red-banner errors) land in
later slices; this file will grow -- keep the top-of-file section list
in sync so a reader can find each concern in ~10 seconds.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from flask import Flask, render_template, request, session
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from monitoring import instrument_app, traced_llm_call
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


@app.route("/")
def index() -> str:
    sid = _ensure_sid()
    return render_template("index.html", history=history_store.raw(sid))


@app.route("/ask", methods=["POST"])
def ask() -> dict[str, Any]:
    sid = _ensure_sid()
    question: str = request.json["question"]  # type: ignore[index]

    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=[SYSTEM_PROMPT_BLOCK])
    ]
    for entry in history_store.get_context(sid):
        messages.append(HumanMessage(content=entry["question"]))
        messages.append(AIMessage(content=entry["answer"]))
    messages.append(HumanMessage(content=question))

    with traced_llm_call(model=MODEL) as span:
        response = llm.invoke(messages)
        _hoist_cache_metrics(response)
        span.record_usage(response)

    answer = response.content
    history_store.append(sid, question, answer)

    return {"answer": answer}


if __name__ == "__main__":
    app.run(port=5000)
