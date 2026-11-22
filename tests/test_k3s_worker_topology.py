"""Tests for the k3s worker topology verification helper."""

import importlib.util
import sys
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / "ansible/roles/k3s_role_rebalance/files"
sys.path.insert(0, str(HELPERS))
spec = importlib.util.spec_from_file_location(
    "verify_worker_topology", HELPERS / "verify_worker_topology.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeEtcd:
    """In-memory etcd double for topology verification unit tests."""

    def __init__(self) -> None:
        """Seed the three committed voters as healthy, matching members."""
        self.data: dict[str, dict[str, object]] = {
            name: {"id": i, "learner": False} for i, name in enumerate(sorted(module.VOTERS), 1)
        }
        self.checked: list[str] = []
        self.mismatch: bool = False
        self.unhealthy: str | None = None

    def members(self) -> dict[str, dict[str, object]]:
        """Return the member map the way an etcd client would."""
        return self.data.copy()

    def health(self, name: str) -> None:
        """Record every health probe and raise for the scripted endpoint."""
        self.checked.append(name)
        if name == self.unhealthy:
            msg = "Unhealthy endpoint"
            raise RuntimeError(msg)

    def status(self, name: str) -> dict[str, object]:
        """Report a member id, optionally mismatched for identity checks."""
        return {"header": {"member_id": 999 if self.mismatch else self.data[name]["id"]}}


class WorkerTopologyTests(unittest.TestCase):
    """Unit contracts for the worker topology verifier."""

    def test_three_healthy_votes_without_worker_endpoint(self) -> None:
        """Accept exactly the three healthy committed voters."""
        client = FakeEtcd()
        result = module.verify(client)
        assert not result["changed"]
        assert client.checked == ["socrat-0", "socrat-1", "socrat-2"]

    def test_old_topology_is_rejected(self) -> None:
        """Reject a member map that already contains the worker endpoint."""
        client = FakeEtcd()
        client.data["socrat-3"] = client.data.pop("socrat-1")
        with pytest.raises(RuntimeError):
            module.verify(client)

    def test_learner_is_not_a_completed_migration(self) -> None:
        """Refuse while any promoted member is still a learner."""
        client = FakeEtcd()
        client.data["socrat-1"]["learner"] = True
        with pytest.raises(RuntimeError):
            module.verify(client)

    def test_endpoint_identity_must_match(self) -> None:
        """Reject status identities that disagree with the member map."""
        client = FakeEtcd()
        client.mismatch = True
        with pytest.raises(RuntimeError):
            module.verify(client)

    def test_unhealthy_voter_is_not_accepted(self) -> None:
        """Refuse while any scripted voter endpoint is unhealthy."""
        client = FakeEtcd()
        client.unhealthy = "socrat-2"
        with pytest.raises(RuntimeError):
            module.verify(client)

    def test_historical_rebalance_is_guarded_before_capacity_checks(self) -> None:
        """Keep the historical guard ordered before the pinned version task."""
        play = (ROOT / "ansible/playbooks/k3s-role-rebalance.yml").read_text()
        assert play.index("Refuse the superseded promotion") < play.index(
            "Require the pinned K3s version"
        )
        assert "/var/lib/homelab-k3s-rebalance/worker-topology" in play


if __name__ == "__main__":
    unittest.main()
