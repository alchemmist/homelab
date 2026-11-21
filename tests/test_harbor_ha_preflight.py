"""Exercise the Harbor staging gate with in-memory observations only."""

import copy
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "harbor_ha_preflight", ROOT / "scripts/harbor-ha-preflight.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HarborHAPreflightTests(unittest.TestCase):
    """Reject cutover when capacity, health, age, or disk reserve fails."""

    def setUp(self):
        self.policy = json.loads((ROOT / "deploy/harbor/ha-policy.json").read_text())
        self.otel = {"nodes": {}}  # committed floor works without the in-progress OTel files
        self.now = datetime.now(timezone.utc)
        self.observation = {
            "collectedAt": self.now.isoformat(),
            "nodes": {
                name: {
                    "availableMemoryBytes": 16 * module.GIB,
                    "diskAvailableBytes": 400 * module.GIB,
                    "diskTotalBytes": 500 * module.GIB,
                    "ready": True,
                    "pressures": [],
                    "unschedulable": False,
                    "taints": [],
                    "allocatableMemoryBytes": 24 * module.GIB,
                    "requestedMemoryBytes": 2 * module.GIB,
                }
                for name in self.policy["nodes"]
            },
        }

    def check(self):
        return module.check(self.policy, self.observation, self.otel, self.now)

    def test_capacity_is_not_cutover_permission(self) -> None:
        """Allow a passing capacity report while cutover stays unauthorized."""
        result = self.check()
        self.assertTrue(result["passed"])
        self.assertFalse(result["cutoverAuthorized"])

    def test_physical_memory_blocks_despite_scheduler_room(self) -> None:
        """Block on physical memory even when the scheduler still has room."""
        self.observation["nodes"]["socrat-3"]["availableMemoryBytes"] = module.GIB
        self.assertIn("physical-memory", self.check()["nodes"]["socrat-3"]["blockers"])

    def test_scheduler_blocks_despite_free_host_memory(self) -> None:
        """Block on scheduler memory even when the host still has free RAM."""
        self.observation["nodes"]["socrat-3"]["requestedMemoryBytes"] = 23 * module.GIB
        self.assertIn("scheduler-memory", self.check()["nodes"]["socrat-3"]["blockers"])

    def test_otel_budget_is_not_spent_twice(self) -> None:
        """Keep the committed external budget instead of adding it twice."""
        self.observation["nodes"]["socrat-1"]["availableMemoryBytes"] = 6 * module.GIB
        self.assertIn("physical-memory", self.check()["nodes"]["socrat-1"]["blockers"])

    def test_higher_live_otel_budget_is_preserved(self) -> None:
        """Let a larger supplied component budget replace the committed floor."""
        self.otel = {"nodes": {"socrat-1": {"components": {"future": 30 * module.GIB}}}}
        self.assertIn("physical-memory", self.check()["nodes"]["socrat-1"]["blockers"])

    def test_disk_after_staging_preserves_reserve(self) -> None:
        """Block when disk left after staging falls below the reserve."""
        self.observation["nodes"]["socrat-1"]["diskAvailableBytes"] = 150 * module.GIB
        self.assertIn("disk-reserve", self.check()["nodes"]["socrat-1"]["blockers"])

    def test_stale_and_future_observations_rejected(self) -> None:
        """Reject observations that are too old or dated after the check instant."""
        for seconds in [-901, 10]:
            self.observation["collectedAt"] = (self.now + timedelta(seconds=seconds)).isoformat()
            with self.assertRaises(ValueError):
                self.check()

    def test_missing_node_is_not_ignored(self) -> None:
        """Refuse a policy node that the observation omitted."""
        del self.observation["nodes"]["socrat-3"]
        with self.assertRaises(KeyError):
            self.check()

    def test_unhealthy_node_cordon_and_taint_block(self) -> None:
        """Block readiness, cordon, pressure, and NoSchedule independently."""
        for key, value in [
            ("ready", False),
            ("unschedulable", True),
            ("pressures", ["MemoryPressure"]),
            ("taints", [{"effect": "NoSchedule"}]),
        ]:
            baseline = copy.deepcopy(self.observation)
            self.observation["nodes"]["socrat-3"][key] = value
            self.assertFalse(self.check()["passed"])
            self.observation = baseline

    def test_quantity_units_and_conservative_init_accounting(self) -> None:
        """Parse binary quantities and count the largest init container."""
        self.assertEqual(module.quantity("1Gi"), module.GIB)
        self.assertEqual(module.quantity("1.5Gi"), int(1.5 * module.GIB))
        self.assertEqual(module.quantity("1024Ki"), module.MIB)
        pod = {
            "spec": {
                "containers": [{"resources": {"requests": {"memory": "100Mi"}}}],
                "initContainers": [{"resources": {"requests": {"memory": "200Mi"}}}],
                "overhead": {"memory": "10Mi"},
            }
        }
        self.assertEqual(module.requested_memory(pod), 310 * module.MIB)

    def test_reports_are_private_and_never_overwritten(self) -> None:
        """Create a private report and refuse to replace an existing file."""
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "report.json"
            module.save_exclusive(path, {"safe": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                module.save_exclusive(path, {"overwrite": True})
            self.assertEqual(json.loads(path.read_text()), {"safe": True})


if __name__ == "__main__":
    unittest.main()
