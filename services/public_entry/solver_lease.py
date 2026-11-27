"""In-memory, single-presentation age/replay rehearsal. Not a serving component.

The verifier is trusted to actually complete a fresh authoritative scan after
begin(). A nonce is correlation, not authentication or proof of freshness.
Never serialize this object's state or treat a cached report as a new scan.
"""

import secrets
import time
from threading import Lock


class SolverLease:
    """One slot per independently approved Host/path; never store response bodies."""

    def __init__(self, window_ns: int):
        if type(window_ns) is not int or window_ns <= 0:
            raise ValueError("positive fixture age budget required")
        self._window = window_ns
        self._lock = Lock()
        self._pending = None
        self._current = None

    def begin(self) -> str:
        """Start one observation round, superseding any previous outstanding one."""
        with self._lock:
            ticket = secrets.token_hex(32)
            self._pending = (ticket, time.monotonic_ns() + self._window)
            return ticket

    def complete(self, ticket: str, uid: str | None) -> bool:
        """None means confirmed absence/denial, not read failure. No age on receipt."""
        with self._lock:
            if self._pending is None or self._pending[0] != ticket:
                return False
            _, deadline = self._pending
            self._pending = None
            self._current = None
            if time.monotonic_ns() >= deadline or uid is None:
                return False
            if not isinstance(uid, str) or not uid:
                raise ValueError("invalid confirmed Challenge UID")
            self._current = (ticket, uid, deadline)
            return True

    def abort(self, ticket: str) -> None:
        """An interrupted read cannot grant, revoke or extend an existing lease."""
        with self._lock:
            if self._pending is not None and self._pending[0] == ticket:
                self._pending = None

    def witness(self, uid: str) -> str | None:
        """Check at admission; recheck the same witness immediately before writing."""
        with self._lock:
            if self._current is not None:
                ticket, current_uid, deadline = self._current
                if current_uid == uid and time.monotonic_ns() < deadline:
                    return ticket
            return None
