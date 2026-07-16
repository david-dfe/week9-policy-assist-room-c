"""Per-session history store for PolicyAssist.

Stores one JSON file per session id under a configurable root directory.
Writes are serialised with a POSIX advisory lock (fcntl.flock) so
concurrent gunicorn workers don't clobber each other. Trimming to the
last HISTORY_MAX_TURNS turns happens in get_context() so callers never
see the strategy.

The session id is treated as a filesystem-safe token: only [A-Za-z0-9_-]
is allowed. Path traversal ('..', '/') raises ValueError.
"""

from __future__ import annotations

import fcntl
import json
import re
from pathlib import Path

from policyassist.config import HISTORY_MAX_TURNS

_SID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_sid(sid: str) -> None:
    if not _SID_RE.fullmatch(sid):
        raise ValueError(f"invalid session id: {sid!r}")


class HistoryStore:
    """File-per-session JSON history under a single root directory."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, sid: str) -> Path:
        _validate_sid(sid)
        return self._root / f"{sid}.json"

    def raw(self, sid: str) -> list[dict[str, str]]:
        path = self._path(sid)
        if not path.exists():
            return []
        with path.open("r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                data: list[dict[str, str]] = json.load(f)
                return data
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def get_context(self, sid: str) -> list[dict[str, str]]:
        history = self.raw(sid)
        if HISTORY_MAX_TURNS <= 0:
            return history
        return history[-HISTORY_MAX_TURNS:]

    def append(self, sid: str, question: str, answer: str) -> None:
        path = self._path(sid)
        # Open r+ if exists so we can lock and read-modify-write atomically.
        # Otherwise create empty and lock.
        if path.exists():
            with path.open("r+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    data = json.load(f)
                    data.append({"question": question, "answer": answer})
                    f.seek(0)
                    f.truncate()
                    json.dump(data, f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        else:
            with path.open("w") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump([{"question": question, "answer": answer}], f, indent=2)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
