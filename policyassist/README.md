# PolicyAssist

PolicyAssist is the reference client for the monitoring service in this
repo: a Flask chat app that answers Border Force officers' questions
against an operational manual using Claude. See the root
[`README.md`](../README.md) for install and run instructions -- this
document only covers PolicyAssist-specific procedures.

## Manual update workflow

The operational manual lives in [`policyassist/manual.txt`](manual.txt).
It is embedded verbatim into the cached system prompt at process start,
so any edit changes both the answers the model gives and (potentially)
which golden-set entries should pass. Follow this procedure whenever the
manual changes:

1. **Branch.** Create a docs branch off `main`:

   ```
   git switch -c docs/manual-vN
   ```

2. **Edit `policyassist/manual.txt`.** Keep the SECTION / clause
   numbering scheme -- the golden set references those numbers.

3. **Run the eval suite locally against the new manual:**

   ```
   uv run python tests/evals/run_evals.py
   ```

   Expect some entries to change verdict -- a new policy means a new
   correct answer.

4. **Update `tests/evals/golden.yaml`.** For each affected entry, adjust
   `expect_any` to match the new policy. Add entries for wholly new
   policies; remove entries whose policy has been dropped. Every fact
   MUST be traceable to a specific clause in the updated manual -- if
   you can't point to the clause, drop the entry rather than
   fabricate it.

5. **Re-run evals.** The overall pass rate must be at or above
   `EVAL_PASS_THRESHOLD` (default `0.85`, set in
   `policyassist/config.py`) before you open a PR:

   ```
   uv run python tests/evals/run_evals.py
   ```

6. **Open the PR.** In the description, ask the reviewer to trigger the
   `evals` workflow so a fresh live run is recorded as a CI artefact:

   ```
   gh workflow run evals
   ```

   (Or use the Actions UI -> "evals" -> "Run workflow".) Link the
   resulting artefact in the PR before merge.

7. **After merge, note the deploy in `ai-log.md`:**

   > manual updated to vN; first requests after deploy pay uncached
   > prices while Anthropic rebuilds the ephemeral cache. Not an
   > anomaly.

### Why the workflow is manual (not on every PR)

Each eval run calls the real Anthropic API and costs about £0.05. On
every PR that would compound, and most PRs do not touch the manual or
the system prompt. The workflow is therefore `workflow_dispatch` only.
See `.github/workflows/evals.yml`.

### Privacy note (CLAUDE.md §9.1)

The eval runner never persists raw questions or answers to a committed
file. Its `--json` output is written to stdout and captured only as a
CI workflow artefact (30-day retention). Do not redirect the output
into a file that gets committed.

## Handover items -- explicitly out of scope for this sprint

These items came out of the risk analysis in
[`plan-policyassist.md`](../plan-policyassist.md) and are intentionally
deferred so the next writer of `ai-log.md` does not treat them as bugs.

- **Home Office SSO / 2FA.** Real authentication (WebAuthn, PIV, or
  equivalent) has not been wired in; sessions are Flask signed cookies.
- **Encryption at rest for the conversation store.** `chat_log/` files
  are plain JSON on the container filesystem. Encrypted volumes /
  application-layer encryption is a separate workstream.
- **Data Protection Impact Assessment (DPIA)** covering officer query
  content sent to a third-party LLM. Required before any real-officer
  pilot.
- **Algorithmic Transparency Recording Standard (ATRS)** registration.
  Government policy requires the tool be registered before public-
  facing deployment.
- **Anthropic Data Processing Agreement review and data-residency
  assessment.** Requests currently traverse Anthropic's default
  routing.
- **Formal procurement through the Crown Commercial Service (CCS)
  framework.** The current setup uses a direct API key, which is
  acceptable for prototyping only.
- **Full prompt-injection prevention.** The NCSC's stance is that this
  is not currently achievable for LLM-based systems; we log anomaly
  signals but do not attempt hard prevention.

Anything picked up from this list must be tracked as its own workstream
with a plan document; do not silently expand the current sprint scope.
