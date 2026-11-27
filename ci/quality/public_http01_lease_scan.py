"""One closed rehearsal slot. No network implementation, publisher or credentials."""

import time
from dataclasses import dataclass, field
from hashlib import sha256
from threading import Lock

from ci.quality.public_http01_scan import scan_namespace
from ci.quality.public_path_rule import path_rule
from services.public_entry.solver_lease import SolverLease


@dataclass(frozen=True, repr=False)
class Presentation:
    """Create a fresh slot for a changed identity/destination, never reuse its lease."""

    namespace: str
    host: str
    uid: str
    token: str
    destination: str
    window_ns: int


def _matches(slot: Presentation, snapshot: dict) -> bool:
    key = "acme-fixture-" + sha256(slot.uid.encode()).hexdigest()
    rule = path_rule(slot.host, "/.well-known/acme-challenge/" + slot.token, "Exact")
    router = snapshot["routers"].get(key, {})
    return (
        router.get("rule") == rule
        and router.get("service") == key
        and snapshot.get("services", {}).get(key)
        == {"loadBalancer": {"servers": [{"url": slot.destination}]}}
    )


@dataclass(frozen=True, repr=False)
class ScannedSlot(Presentation):
    _lease: SolverLease = field(init=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_lease", SolverLease(self.window_ns))

    def witness(self):
        return self._lease.witness(self.uid)

    def refresh(self, approved_hosts, read_page, read_children, pod_network):
        """Begin before page one; a complete snapshot alone may confirm or revoke.

        The callbacks must perform new scoped reads, not return cached reports.
        An interrupted read propagates after invalidating just its own ticket.
        The lease of a prior success is neither refreshed nor reset on failure.
        """
        ticket = self._lease.begin()
        try:
            snapshot = scan_namespace(
                self.namespace, approved_hosts, read_page, read_children, pod_network
            )["http"]
            return self._lease.complete(ticket, self.uid if _matches(self, snapshot) else None)
        finally:
            # Harmless after completion; cannot cancel a newer round.
            self._lease.abort(ticket)


class NamespaceGate:
    """One process, fixed approved identities, one complete LIST per round.

    Swap the whole table under the same lock used for request-side reads. A
    newer begin permanently supersedes an older round even if the newer scan
    subsequently fails. An interrupted scan never renews the current table.
    """

    def __init__(self, namespace: str, slots: tuple[Presentation, ...]):
        self._namespace = namespace
        self._slots = tuple(slots)
        if (
            not namespace
            or any(
                s.namespace != namespace or type(s.window_ns) is not int or s.window_ns <= 0
                for s in self._slots
            )
            or len({s.uid for s in self._slots}) != len(self._slots)
            or len({(s.host, s.token) for s in self._slots}) != len(self._slots)
        ):
            raise ValueError("ambiguous or invalid namespace gate scope")
        self._lock = Lock()
        self._pending = None
        self._current = {}

    def refresh(self, read_page, read_children, pod_network):
        with self._lock:
            round_id = object()
            start = time.monotonic_ns()
            self._pending = round_id
        try:
            snap = scan_namespace(
                self._namespace,
                frozenset(s.host for s in self._slots),
                read_page,
                read_children,
                pod_network,
            )["http"]
            proposed = {
                s: (object(), start + s.window_ns) for s in self._slots if _matches(s, snap)
            }
            with self._lock:
                if self._pending is not round_id:
                    return False
                self._current = proposed
                return True  # table committed, not proof every slot is live
        finally:
            with self._lock:
                if self._pending is round_id:
                    self._pending = None

    def witness(self, slot: Presentation):
        with self._lock:
            rec = self._current.get(slot)
            return rec[0] if rec and time.monotonic_ns() < rec[1] else None
