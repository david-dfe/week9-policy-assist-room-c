# PolicyAssist — Code Review: Problems Found

Reviewed against: `/home/lab-admin/Documents/my-work/week9/hackathon/policyassist/`

---

## SIN 1 — Invalid model name

**File:** `app.py`, line 13  
**Severity:** Critical (app breaks on first request)

```python
# WRONG — this model does not exist
llm = ChatAnthropic(model="claude-sonnet-5", ...)
```

`claude-sonnet-5` is not a valid Anthropic model ID. The API will reject every request with a model-not-found error. The correct current model name is `claude-sonnet-4-6`. This would have been caught immediately in testing, which suggests this code has not been run against the live API recently.

---

## SIN 2 — All users share a single conversation history

**File:** `app.py`, lines 32–44 (`LOG_FILE = "chat_log.json"`)  
**Severity:** High (privacy + data integrity)

There is one `chat_log.json` for the entire deployment. Every officer's questions and answers are appended to the same file and replayed into every other officer's context window. This means:

- Officer A can inadvertently see Officer B's case questions (via the chat UI on page load)
- Sensitive case details from one officer contaminate another officer's conversation context
- There is no way to isolate or audit one officer's session separately

At 800 users this is a significant data-handling problem, not just a UX annoyance.

---

## SIN 3 — Unbounded conversation history (cost and context window risk)

**File:** `app.py`, lines 58–63  
**Severity:** High (operational cost + eventual failure)

Every API request sends the full manual (~1,200 tokens) **plus the entire conversation history to date**. There is no cap. As the shared log grows:

- Token count per request grows indefinitely
- API cost grows in proportion
- Eventually the combined prompt exceeds the model's context window (200k tokens for Sonnet), causing hard API errors that cannot be recovered without deleting the log file

A rough cost illustration:

| History depth | Tokens per request | Approx cost (Sonnet) |
|---|---|---|
| First question | ~1,400 | ~$0.002 |
| After 10 exchanges | ~2,900 | ~$0.004 |
| After 50 exchanges | ~9,400 | ~$0.013 |
| After 500 exchanges | ~86,000 | ~$0.12 |

With 800 officers and no history trimming, this will become expensive quickly.

---

## SIN 4 — Debug mode left on

**File:** `app.py`, line 75  
**Severity:** High (security vulnerability in production)

```python
app.run(debug=True, port=5000)
```

`debug=True` enables the Werkzeug interactive debugger. If an unhandled exception occurs, any user who can reach the server gets an in-browser Python shell with the ability to execute arbitrary code on the server. This is explicitly documented by Flask as "never to be used in production." A production deployment must use a proper WSGI server (e.g. gunicorn or waitress) and this line removed.

---

## SIN 5 — No input validation on the `/ask` endpoint

**File:** `app.py`, lines 52–71  
**Severity:** Medium (reliability)

```python
question = request.json["question"]
```

If the request body is missing, is not valid JSON, or does not contain the key `"question"`, this line raises an unhandled exception and returns an HTTP 500. There is no guard, no error message, and no feedback to the caller. Any network hiccup, browser quirk, or malformed request will produce a silent server error.

---

## SIN 6 — API key fallback baked into source code

**File:** `app.py`, line 16 (original)  
**Severity:** Medium (security + silent misconfiguration)

```python
api_key=os.environ.get("ANTHROPIC_API_KEY", "PASTE-YOUR-KEY-HERE"),
```

The hardcoded fallback means the application starts successfully even when the environment variable is not set — it will simply fail on the first API call with a cryptic authentication error rather than a clear startup message. More seriously, if a developer ever pastes a real key in place of the placeholder and commits the file to version control, a live credential is exposed.

---

## SIN 7 — Unpinned dependencies

**File:** `requirements.txt`  
**Severity:** Low-Medium (reproducibility)

```
flask
langchain-anthropic
```

No version constraints are specified. This means `pip install -r requirements.txt` installs whatever the latest versions are at the time of installation. A breaking change in either library will silently break the app on the next clean install, with no indication of which version previously worked.

---

## SIN 8 — No error handling surfaced to the user

**File:** `app.py`, lines 65–66 / `templates/index.html`, lines 50–59  
**Severity:** Low-Medium (user experience)

If the Claude API call fails (rate limit, outage, network error), the exception propagates as an HTTP 500. The browser-side JavaScript does not check for non-2xx responses, so the user sees no message — the "Ask" button re-enables and the question disappears with no answer and no explanation. At scale, API errors are not rare edge cases; they need a user-visible fallback.
App hangs.

## SIN 9 - No test suite

There are no gate evals.

---

## Summary table

| # | Problem | File | Severity |
|---|---|---|---|
| 1 | Invalid model name (`claude-sonnet-5`) | `app.py:13` | Critical |
| 2 | Shared history — no per-user sessions | `app.py:32` | High |
| 3 | Unbounded history — cost & context window | `app.py:58–63` | High |
| 4 | Debug mode on in production | `app.py:75` | High |
| 5 | No input validation on `/ask` | `app.py:52–71` | Medium |
| 6 | API key fallback in source code | `app.py:16` | Medium |
| 7 | Unpinned dependencies | `requirements.txt` | Low-Medium |
| 8 | No error handling surfaced to UI | `app.py:65` / `index.html` | Low-Medium |
