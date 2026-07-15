"""PolicyAssist — reference client for the monitoring service.

Minimum-viable Flask app carried over from the prototype at
``~/Documents/my-work/weeks/w09/breakoutroom3work/policyassist/``.
Instrumented with the local ``monitoring`` package so every ``/ask``
call ships an OTLP span to the configured backend.

App-level improvements (prompt caching, per-user sessions, retries,
gunicorn switch) are out of scope for this workstream — see plan.md §2.7.
"""
