# PolicyAssist

Internal chat tool for querying the Border Force Operational Manual.
Built as a proof of concept for the pilot with the Heathrow T5 team.

**Status:** works on my machine. The pilot went well so apparently
800 officers are getting it next quarter. Handing this over as-is —
good luck! — Dan

## Running it

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
python app.py
```

Then open http://localhost:5000

---

# Team notes

Core sin: **whole manual + whole shared history re-sent every `/ask`** → £14,200.

## Top problems

- **Cost:** manual re-sent every call; no token/£ logging; priciest model hardcoded
- **Correctness:** no tests, no evals, no manual versioning
- **Resilience:** no retries/timeouts/error handling; race in `save_history`; Flask dev server
- **Privacy:** `chat_log.json` shared across all users; no auth; `debug=True` = RCE

## Approaches

| Idea | Pros | Cons | Do? |
|---|---|---|---|
| **Prompt caching** on the manual block (`cache_control`) | Cache reads ~10% of input price; one-field change; 5-min TTL comfortably covers the 7am herd; transparent to the model so no quality risk | 5-min TTL means quiet gaps re-warm at full price; any manual edit invalidates the whole cache; doesn't help output tokens or shrink history | **Yes** — biggest £ per hour |
| **Per-user sessions** (drop `chat_log.json`) | Fixes privacy leak, unbounded history *and* the concurrent-write race in one change; session cookie + dict is <1hr work | Rolling window loses long context; summarisation adds a small LLM call per flush | **Yes** — must-do for privacy |
| **Golden-set evals** (10-15 Q&A + runner) | Prerequisite for defending any other change; addresses "wrong answers" worry directly; runnable in CI as a gate | Only as strong as the pairs we write; substring scoring is weak vs LLM-as-judge (but LLM judge = extra call per eval) | **Yes** — no defensible change without this |
| **Cheaper model** (Haiku default, escalate to Sonnet) | ~1/5 input price; compounds with caching (cheap × cached = very cheap); brief explicitly encourages dev on cheap models | Quality risk on high-stakes answers (welfare intervals); a router costs its own LLM call so naive routing loses | Try Haiku behind the eval; keep Sonnet if score drops |
| **RAG** (chunk manual + retrieve top-k) | Scales past the context window; enables per-answer citations; retrieval log = built-in audit trail | Retrieval quality is a new failure mode ("missed chunk"); embedding + store + eval axis = real complexity; overkill for a 700-word manual | Day 3 — mention as "next" on the honest ledger |
| **Response cache** (Q→A memoisation) | Zero cost + sub-second latency on hits; helps 7am herd | Exact-match hits rare; near-match needs embeddings anyway; manual updates → stale = wrong answer, ICO-visible | Skip; revisit if we do RAG |
| **Streaming responses** | Perceived latency drop; fewer "did it hang?" retries; SDK supports it natively | Zero effect on £; a bit of frontend SSE plumbing | If time on D2 PM |

## Plan
 ### Decisions
 - response and prompt caching chosen - prevents sending the manual in full everytime
 - sends whole chat log every time - Per user only, not shared context- honest ledger -compact out of scope? 
 - consider ttl - cost benefit?
 - Code quality - GDS standards, accessibility(?)WCAG2.2, Honest ledger - code quality management tool
 - Test quality of output
 - Golden set of questions/answers
 - Error handling gracefully/backoffs
 - No security - make some - authentication? implement oauth from border forces active directory/gov one login/etc etc 
 - update - version updates invalidate cache, New sections? Assess against existing evals. - inaccuracy fails the build so the dev update evals

- **D1 PM:** caching + £ logging + before/after slide
- **D2 AM:** per-user sessions + golden evals
- **D2 PM:** Haiku behind eval, then prep pres
- **Honest ledger:** no RAG, no auth, no load test — would do next



## Open questions

1. Real manual size? (RAG calculus changes at ~50k tokens)
2. Manual-update channel? (drives cache invalidation)
3. Who signs off the golden Q&A pairs?
4. When does RAG become appropriate?

