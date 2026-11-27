"""One closed rehearsal slot. No network implementation, publisher or credentials."""

import time
from dataclasses import dataclass, field
from hashlib import sha256
from ipaddress import IPv4Network
from threading import Lock

from ci.quality.public_http01_scan import ReadChildren, ReadPage, scan_namespace
from ci.quality.public_path_rule import path_rule
from services.public_entry.solver_lease import SolverLease


@dataclass(frozen=True, repr=False)
class _MalformedSnapshotError(TypeError):
    """Signal that a closed snapshot lost its expected Traefik shape."""


SCOPE_ERROR = "ambiguous or invalid namespace gate scope"


@dataclass(frozen=True, repr=False)
class Presentation:
    """Create a fresh slot for a changed identity/destination, never reuse its lease."""

    namespace: str
    host: str
    uid: str
    token: str
    destination: str
    window_ns: int


def _http_of(snapshot: dict[str, object]) -> dict[str, object]:
    """Narrow a closed snapshot to its Traefik HTTP config; never-default to one."""
    http = snapshot["http"]
    if not isinstance(http, dict):
        raise _MalformedSnapshotError
    return http


def _matches(slot: Presentation, snapshot: dict[str, object]) -> bool:
    key = "acme-fixture-" + sha256(slot.uid.encode()).hexdigest()
    rule = path_rule(slot.host, "/.well-known/acme-challenge/" + slot.token, "Exact")
    routers = snapshot["routers"]
    if not isinstance(routers, dict):
        raise _MalformedSnapshotError
    router = routers.get(key, {})
    if not isinstance(router, dict):
        raise _MalformedSnapshotError
    services = snapshot.get("services", {})
    if not isinstance(services, dict):
        raise _MalformedSnapshotError
    return (
        router.get("rule") == rule
        and router.get("service") == key
        and services.get(key)
        == {"loadBalancer": {"servers": [{"url": slot.destination}]}}
    )


@dataclass(frozen=True, repr=False)
class ScannedSlot(Presentation):
    """One rehearsal slot whose observations arrive via full namespace scans."""

    _lease: SolverLease = field(init=False, compare=False)

    def __post_init__(self) -> None:
        """Create the independent lease for this slot only."""
        object.__setattr__(self, "_lease", SolverLease(self.window_ns))

    def witness(self) -> str | None:
        """Return the current proof token, if this slot still owns it."""
        return self._lease.witness(self.uid)

    def refresh(
        self,
        approved_hosts: frozenset[str],
        read_page: ReadPage,
        read_children: ReadChildren,
        pod_network: IPv4Network,
    ) -> bool:
        """Scan the namespace now, then renew or revoke only this slot."""
        """Begin before page one; a complete snapshot alone may confirm or revoke.

        The callbacks must perform new scoped reads, not return cached reports.
        An interrupted read propagates after invalidating just its own ticket.
        The lease of a prior success is neither refreshed nor reset on failure.
        """
        ticket = self._lease.begin()
        try:
            snapshot = _http_of(
                scan_namespace(
                    self.namespace, approved_hosts, read_page, read_children, pod_network
                )
            )
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

    def __init__(self, namespace: str, slots: tuple[Presentation, ...]) -> None:
        """Validate the fixed scope and start with no committed table."""
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
            raise ValueError(SCOPE_ERROR)
        self._lock = Lock()
        self._pending: object | None = None
        self._current: dict[Presentation, tuple[object, int]] = {}

    def refresh(
        self, read_page: ReadPage, read_children: ReadChildren, pod_network: IPv4Network
    ) -> bool:
        """Run one round; interrupted scans never recommit the stored table."""
        with self._lock:
            round_id = object()
            start = time.monotonic_ns()
            self._pending = round_id
        try:
            snap = _http_of(
                scan_namespace(
                    self._namespace,
                    frozenset(s.host for s in self._slots),
                    read_page,
                    read_children,
                    pod_network,
                )
            )
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

    def witness(self, slot: Presentation) -> object | None:
        """Return the committed proof token for a live slot, else nothing."""
        with self._lock:
            rec = self._current.get(slot)
            return rec[0] if rec and time.monotonic_ns() < rec[1] else None
