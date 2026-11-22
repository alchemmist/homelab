"""Tests for the k3s etcd rebalance helpers."""

import importlib.util
import unittest
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "etcd_members",
    Path(__file__).resolve().parents[1] / "ansible/roles/k3s_role_rebalance/files/etcd_members.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeEtcd:
    """In-memory etcd double for the rebalance contracts."""

    def __init__(self) -> None:
        """Seed the committed membership as healthy and agreeing."""
        self.membership: dict[str, dict[str, object]] = {
            name: {
                "id": index + 1,
                "id_hex": format(index + 1, "x"),
                "learner": False,
                "peer_urls": [MODULE.PEERS[name]],
            }
            for index, name in enumerate(MODULE.ENDPOINTS)
        }
        self.leader: int = 2
        self.healthy: set[str] = {"socrat-0", "socrat-1", "socrat-3"}
        self.calls: list[tuple[list[str], str | None]] = []
        self.fail_remove: bool = False
        self.ambiguous_remove: bool = False

    def members(self) -> dict[str, dict[str, object]]:
        """Return the member map like an etcd client would."""
        return dict(self.membership)

    def health(self, name: str) -> None:
        """Raise for any endpoint outside the scripted healthy set."""
        if name not in self.healthy:
            msg = "unhealthy"
            raise RuntimeError(msg)

    def status(self, name: str) -> dict[str, object]:
        """Report the member identity and the scripted leader."""
        return {
            "header": {"member_id": self.membership[name]["id"]},
            "leader": self.leader,
        }

    def call(self, args: list[str], endpoint: str | None = None, structured: object = True) -> None:
        """Apply one etcdctl invocation and record its arguments."""
        self.calls.append((args, endpoint, structured))
        if args[0] == "move-leader":
            self.leader = int(args[1], 16)
        elif args[:2] == ["member", "remove"]:
            if self.fail_remove:
                msg = "failed"
                raise RuntimeError(msg)
            del self.membership["socrat-1"]
            if self.ambiguous_remove:
                msg = "response lost"
                raise RuntimeError(msg)


class RebalanceTest(unittest.TestCase):
    """Verify etcd rebalance safety checks before any member removal."""

    def test_final_verification_never_removes_an_unexpected_member(self) -> None:
        """Fail the final verification before any unexpected removal."""
        client = FakeEtcd()
        with pytest.raises(RuntimeError):
            MODULE.verify_final(client)
        assert client.calls == []
        assert "socrat-1" in client.membership

    def test_offline_socrat_2_allows_guarded_removal(self) -> None:
        """Remove socrat-1 only with the guarded leader move first."""
        client = FakeEtcd()
        result = MODULE.remove_socrat_1(client)
        assert result["changed"]
        assert set(result["members"]) == MODULE.FINAL
        assert client.calls == [
            (["move-leader", "1"], MODULE.ENDPOINTS["socrat-1"], False),
            (["member", "remove", "2"], None, False),
        ]

    def test_target_membership_is_idempotent(self) -> None:
        """Treat the target membership as already converged."""
        client = FakeEtcd()
        del client.membership["socrat-1"]
        assert not MODULE.remove_socrat_1(client)["changed"]
        assert client.calls == []

    def test_unhealthy_required_member_blocks_mutation(self) -> None:
        """Refuse mutation while any required member is unhealthy."""
        for name in ("socrat-0", "socrat-1", "socrat-3"):
            client = FakeEtcd()
            client.healthy.remove(name)
            with pytest.raises(RuntimeError):
                MODULE.remove_socrat_1(client)
            assert client.calls == []

    def test_learner_blocks_mutation(self) -> None:
        """Refuse mutation while any member is still a learner."""
        client = FakeEtcd()
        client.membership["socrat-3"]["learner"] = True
        with pytest.raises(RuntimeError):
            MODULE.remove_socrat_1(client)
        assert client.calls == []

    def test_unknown_membership_blocks_mutation(self) -> None:
        """Refuse mutation on unexpected membership."""
        client = FakeEtcd()
        client.membership["unknown"] = client.membership.pop("socrat-3")
        with pytest.raises(RuntimeError):
            MODULE.remove_socrat_1(client)
        assert client.calls == []

    def test_failed_removal_requires_operator_action(self) -> None:
        """Surface failed removals as operator action items."""
        client = FakeEtcd()
        client.fail_remove = True
        with pytest.raises(RuntimeError, match="restore its staged configuration"):
            MODULE.remove_socrat_1(client)
        assert "socrat-1" in client.membership

    def test_lost_success_response_is_verified(self) -> None:
        """Recover a lost success response through final verification."""
        client = FakeEtcd()
        client.ambiguous_remove = True
        assert MODULE.remove_socrat_1(client)["changed"]


if __name__ == "__main__":
    unittest.main()
