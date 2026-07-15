"""PolicyAssist — internal guidance chat tool.

Reference client for the monitoring service. Carried over from the
prototype with three minimum-viable changes to wire in observability:

1. ``instrument_app("policyassist")`` at module load.
2. ``llm.invoke()`` wrapped in ``traced_llm_call(...)``.
3. ``MODEL`` and ``MAX_TOKENS`` extracted as module constants so the
   monitoring wrapper and the LLM constructor share one source of truth.

All other prototype behaviour (global shared history, no session
isolation, no caching, no retries, HTTP 500 on API failure) is
preserved intentionally — those live in a separate PolicyAssist
app workstream and are not this workstream's job.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from monitoring import instrument_app, traced_llm_call

MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1024
LOG_FILE = Path(__file__).parent / "chat_log.json"
MANUAL_PATH = Path(__file__).parent / "manual.txt"

app = Flask(__name__)
instrument_app(service_name="policyassist")

llm = ChatAnthropic(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    api_key=os.environ["ANTHROPIC_API_KEY"],
)

MANUAL = MANUAL_PATH.read_text()

SYSTEM_PROMPT = (
    "You are PolicyAssist, an internal assistant for Border Force officers. "
    "Answer questions using ONLY the operational manual below. "
    "If the manual does not cover the question, say so and advise the officer "
    "to contact the Duty Higher Officer. Be concise and practical.\n\n"
    "=== BORDER FORCE OPERATIONAL MANUAL (EXTRACT) ===\n\n" + MANUAL
)


def load_history() -> list[dict[str, str]]:
    if LOG_FILE.exists():
        with LOG_FILE.open() as f:
            data: list[dict[str, str]] = json.load(f)
            return data
    return []


def save_history(history: list[dict[str, str]]) -> None:
    with LOG_FILE.open("w") as f:
        json.dump(history, f, indent=2)


@app.route("/")
def index() -> str:
    return render_template("index.html", history=load_history())


@app.route("/ask", methods=["POST"])
def ask() -> dict[str, Any]:
    question: str = request.json["question"]  # type: ignore[index]

    history = load_history()
    messages: list[SystemMessage | HumanMessage | AIMessage] = [
        SystemMessage(content=SYSTEM_PROMPT)
    ]
    for entry in history:
        messages.append(HumanMessage(content=entry["question"]))
        messages.append(AIMessage(content=entry["answer"]))
    messages.append(HumanMessage(content=question))

    with traced_llm_call(model=MODEL) as span:
        response = llm.invoke(messages)
        span.record_usage(response)

    answer = response.content
    history.append({"question": question, "answer": answer})
    save_history(history)

    return {"answer": answer}


if __name__ == "__main__":
    app.run(port=5000)
