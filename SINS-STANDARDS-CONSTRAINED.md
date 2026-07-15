# PolicyAssist — Standards Compliance: Hackathon Scope

This document takes the full standards analysis in `SINS-STANDARDS.md` and filters it through the hackathon brief. The brief is a 2-day engineering sprint. Its three stated priorities are **API cost**, **wrong answers**, and **resilience**. The deliverable is working, demonstrable code — not a governance submission.

The filter rule applied here is simple:

> **Keep** any standards requirement that maps to a code change a team of 2–4 engineers can ship in 2 days.
> **Defer** any requirement that needs a Security Advisor, legal team, procurement officer, or formal assurance process — these are real obligations but they are not engineering tasks.

The deferred items are listed at the end with the reason, so nothing is forgotten.

---

## What the brief says the Head of Digital actually cares about

| Priority | Brief language | Standards grounding |
|---|---|---|
| 1. API bill | *"Finance modelled the rollout naively... around £14,200 a month"* | Service Standard Point 11: understand total cost of ownership |
| 2. Wrong answers | *"An officer acting on an incorrect welfare-check interval is not a hypothetical risk, it's a headline"* | Service Standard Point 14: monitor outcomes; AI Playbook: hallucination risk |
| 3. Resilience | *"6,000 queries a day means the 7am shift change hits the service at once"* | Service Standard Point 14: operate a reliable service |

Everything below maps to one of these three, plus the specific engineering directions the brief names.

---

## In-scope standards items (can be addressed in code this sprint)

---

### 1. Cost visibility and prompt caching

**Standards basis:** GDS Service Standard Point 11 — *"Understand total cost of ownership."* GDS TCoP Point 11 — purchasing strategy.

**Brief language:** *"You cannot manage what you cannot see. Log tokens and estimated £ per request."* Prompt caching is explicitly listed as a starting point: *"The manual is identical on every request. Anthropic's caching pricing changes the economics of exactly this pattern."*

**What to do:**
- Log `input_tokens`, `output_tokens`, and estimated £ cost on every `/ask` request (available in the LangChain/Anthropic response object)
- Implement Anthropic prompt caching on the system prompt — the manual content is static across all requests and is the dominant cost driver
- Calculate and present: projected monthly bill at 6,000 queries/day before and after caching

**Why this is the highest-priority engineering task:** The brief says the naive projection is £14,200/month. Prompt caching reduces cached token costs by ~90%. The brief explicitly asks teams to show the revised number. This is both the quickest win and the most presentable result.

---

### 2. Session management — fix the shared history

**Standards basis:** Service Standard Point 9 — *"Collect, process and store data securely in a way which respects users' privacy."* TCoP Point 7 — privacy by design. NCSC LLM guidance — queries visible to provider; limit what is sent.

**Brief language:** *"A global shared history is both a privacy problem and a token bomb. Per-user sessions, a rolling window, or summarisation all change the cost curve and the behaviour."*

**What to do (pick one, brief says you don't need all):**
- Per-user sessions (session cookie → per-user log file, or in-memory dict keyed by session ID)
- Rolling window (keep only last N exchanges per user, discarding older ones)
- History summarisation (collapse old turns into a summary message to preserve context cheaply)

**Why this matters to the standards:** The shared `chat_log.json` means one officer's queries — potentially including case details or passenger descriptions — appear in every other officer's context window. That is a direct breach of the privacy principle from Service Standard Point 9. It also means token counts grow without bound, compounding the cost problem.

---

### 3. Evals — how do you know an answer is right?

**Standards basis:** Service Standard Point 14 — *"Monitor outcomes for users and ethical issues such as bias, not just technical faults."* AI Playbook — *"Humans must validate high-risk decisions influenced by AI."* AI Playbook — hallucination risk.

**Brief language:** *"Build a golden set of question/answer pairs from the manual and score the system against it. Make it runnable on demand — or wire it into a CI pipeline so a prompt change that degrades accuracy fails the build."*

**Brief question:** *"How do you know an answer is right? How would you know if an answer was wrong — and what does one wrong answer cost in this context?"*

**What to do:**
- Extract 10–20 question/answer pairs directly from `manual.txt` (e.g. welfare check interval, cash declaration threshold, DHO referral triggers)
- Write a scoring script that runs each question through the model and checks whether the answer contains the correct fact
- Make it runnable: `python eval.py` should print pass/fail for each case and an overall score
- Stretch: wire it into a pre-commit hook or CI step so a system prompt change that degrades accuracy is caught before deployment

**Why this is in scope:** The brief names this explicitly. An officer acting on a wrong welfare check interval is a real risk — the manual says every 30 minutes, and if the model says 45 minutes an officer may be in breach. An eval set makes that failure detectable. It takes a few hours to build and is highly demonstrable.

---

### 4. Reliability — error handling, timeouts, retries

**Standards basis:** Service Standard Point 14 — *"Minimise service downtime and have a plan to deal with it when it does happen."* Service Standard Point 14 — *"carry out quality assurance testing regularly."*

**Brief language:** *"Retries with backoff, timeouts, graceful degradation when the API is down, and an answer to the 7am thundering-herd question."* Currently: *"API failure = HTTP 500."*

**What to do:**
- Wrap `llm.invoke()` in a try/except; return a structured JSON error and surface a user-visible message in the UI rather than a blank hang
- Add a request timeout to the Anthropic call
- Add retry with exponential backoff for transient failures (rate limits, 529s)
- Address the thundering-herd question: Flask's development server is single-threaded. At 7am shift change with concurrent requests, the current server will queue them serially. Answer: use a WSGI server (gunicorn) with multiple workers, or at minimum document this as a known constraint

---

### 5. API key security

**Standards basis:** Service Standard Point 9 — *"Perform due diligence on the security of third-party software."* TCoP Point 6 — *"make things secure."*

**Brief language:** *"The developer's API key handling deserves a close look."*

**Current code:**
```python
api_key=os.environ.get("ANTHROPIC_API_KEY", "PASTE-YOUR-KEY-HERE")
```

**What to do:**
- Remove the fallback string; fail fast at startup if the env var is missing (already done in the improved `app.py` — verify it holds)
- Ensure the key is never logged (check that Flask's debug output, the cost log, and `chat_log.json` do not capture the key)
- Do not commit the key to version control; add `.env` to `.gitignore` if using a dotenv approach

---

### 6. Debug mode off / production server

**Standards basis:** TCoP Point 6 — *"make things secure."* Service Standard Point 9 — secure by design.

**Brief language:** This is implicit in "make it production-grade." The brief says the team should be able to hand back *"a system"*, not a demo.

**Current code:**
```python
app.run(debug=True, port=5000)
```

`debug=True` enables the Werkzeug interactive debugger, which gives any user who triggers an exception an in-browser Python shell. This is a remote code execution vulnerability.

**What to do:**
- Remove `debug=True` or gate it on an environment variable (`DEBUG=true` in dev only)
- Run under gunicorn for the presentation: `gunicorn -w 4 app:app` handles concurrent requests and has no debugger

---

### 7. Prompt injection — basic input handling

**Standards basis:** NCSC — *"Prompt injection is now OWASP's #1 vulnerability in generative AI applications."* NCSC — *"cannot be fully prevented; design must assume residual risk."*

**Brief language:** *"Security — what an attacker could do via the chat box."*

**What to do (2-day scope — partial mitigation only):**
- The system prompt already constrains the model to answer from the manual only — this is the single most effective defence, and it's already in place
- Add a maximum question length (e.g. 500 characters) to limit the surface area for injection attempts
- Log every question and answer with a timestamp for anomaly detection — not a prevention, but makes attacks detectable after the fact

**What NOT to claim:** Full prompt injection prevention is not achievable in a sprint. NCSC is explicit that it cannot be fully mitigated. The correct framing is: *we have implemented partial mitigations and accept residual risk.* Note this openly in the Day 2 presentation.

---

### 8. Dependency pinning

**Standards basis:** Service Standard Point 14 — operate a reliable service. Implied by "production-grade."

**What to do:** Pin version ranges in `requirements.txt` (already done in the improved version — verify). A production system must be reproducibly installable.

---

### 9. The update problem

**Standards basis:** Service Standard Point 14 — operate a reliable service over time.

**Brief language:** *"The manual gets revised. What is the workflow from 'v4.3 published' to 'PolicyAssist answers from v4.3', and what does it do to your cache and your evals?"*

**What to do:** This is partly a design question, partly an implementation question:
- **Cache:** Anthropic's prompt cache is keyed on exact content. Any edit to `manual.txt` invalidates the cache entirely — the first request after an update pays full uncached cost, then the cache rebuilds. Document this behaviour; do not treat it as a bug.
- **Evals:** If the manual changes, the golden eval set must be reviewed. If a policy changes (e.g. welfare check interval moves from 30 to 20 minutes), the eval must be updated before deploying the new manual or the eval will incorrectly flag the correct new answer as a failure.
- **Workflow:** Propose a simple update procedure: edit `manual.txt` → run `eval.py` → if score holds, restart the service. This is the minimum viable update workflow and is worth naming explicitly in the Day 2 presentation.

---

## Deferred — real obligations, not engineering tasks

These items from the full standards analysis are genuine requirements but require a Security Advisor, legal team, or procurement officer. They are out of scope for a 2-day engineering sprint and should be explicitly named as "handover items" in the Day 2 presentation.

| Item | Why deferred | Who owns it |
|---|---|---|
| Data classification assessment (OFFICIAL vs OFFICIAL-SENSITIVE) | Requires a Security Advisor to assess the manual and query content | Home Office Security Advisor |
| Anthropic data processing agreement review | Legal/commercial review of whether query data is used for training, and data residency | Legal / commercial team |
| Data Protection Impact Assessment (DPIA) | UK GDPR Art. 35 — required before processing personal data at scale | Data Protection Officer |
| Algorithmic Transparency Recording Standard (ATRS) registration | Mandatory for Home Office; governance process, not a code change | AI governance / senior responsible owner |
| Formal authentication (SSO + 2FA via Home Office identity infrastructure) | Requires integration with enterprise identity systems; cannot be built from scratch in 2 days | Platform / infrastructure team |
| Encryption at rest for conversation store | Requires server-level configuration, not application code | Infrastructure / hosting team |
| Formal procurement through Crown Commercial Service | The Anthropic API contract needs to be on a CCS framework | Commercial team |
| NCSC Cloud Security Principles assessment of Anthropic | Formal supplier assessment; requires documentation and sign-off | Security / commercial team |
| Spend assurance (GDS/CDDO gateway if >£1m) | Governance process | Head of Digital / programme team |
| Open source code publishing | Policy decision on what is operationally sensitive; legal review of licence | Legal / security |

**Note for the Day 2 presentation:** Naming these explicitly is more credible than ignoring them. The brief asks: *"what you would do next if you had a third day."* Several of these are the answer to that question.

---

## Two-day priority order

Based on the brief's stated concerns and the time constraint:

| Day | Focus | Rationale |
|---|---|---|
| Day 1 AM | Cost instrumentation + prompt caching | Quickest path to the number the Head of Digital asked for; highly presentable; directly answers brief question 2 |
| Day 1 PM | Session management | Fixes the biggest combined cost + privacy problem; required to make caching meaningful per-user |
| Day 2 AM | Evals | Makes "wrong answers" a measurable, defensible claim rather than an assertion; directly answers brief question 1 |
| Day 2 PM | Reliability (error handling, gunicorn, retries) + presentation prep | Rounds out "production-grade"; addresses the 7am thundering-herd question; debug mode off |

Security (prompt injection mitigations, key handling) should be woven in as each area is touched rather than treated as a separate track — it takes less time that way and produces more coherent code.
