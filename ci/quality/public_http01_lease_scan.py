"""One closed rehearsal slot. No network implementation, publisher or credentials."""

from dataclasses import dataclass, field
from hashlib import sha256

from ci.quality.public_http01_scan import scan_namespace
from ci.quality.public_path_rule import path_rule
from services.public_entry.solver_lease import SolverLease


@dataclass(frozen=True, repr=False)
class ScannedSlot:
    """Create a fresh slot for a changed identity/destination, never reuse its lease."""

    namespace: str
    host: str
    uid: str
    token: str
    destination: str
    window_ns: int
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
            key = "acme-fixture-" + sha256(self.uid.encode()).hexdigest()
            rule = path_rule(self.host, "/.well-known/acme-challenge/" + self.token, "Exact")
            router = snapshot["routers"].get(key, {})
            destination = snapshot.get("services", {}).get(key)
            matches = (
                router.get("rule") == rule
                and router.get("service") == key
                and destination == {"loadBalancer": {"servers": [{"url": self.destination}]}}
            )
            return self._lease.complete(ticket, self.uid if matches else None)
        finally:
            # Harmless after completion; cannot cancel a newer round.
            self._lease.abort(ticket)
