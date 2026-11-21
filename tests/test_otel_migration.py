"""Tests for the OpenTelemetry migration script."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "otel_preflight", ROOT / "scripts/otel-migration-preflight.py"
)
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)
GIB = 1024**3
# The operational policy was deliberately retired in 258374b6. Pure evaluator tests
# use its archived fixture, never restore it to the production configuration path.
POLICY_FIXTURE = ROOT / "tests/fixtures/retired-otel/policy.json"


class _PolicyNode(TypedDict):
    components: dict[str, int]
    projectedAdditionalDiskBytes: int


class _Policy(TypedDict, total=False):
    nodes: dict[str, _PolicyNode]
    diskProjectionVerified: bool
    backupVerified: bool
    backupEvidence: str
    historyRoundtripVerified: bool
    historySourceIntegrityVerified: bool
    historySourceIntegrityEvidence: str
    sourceRegistryVerified: bool


class _Inventory(TypedDict):
    schemaVersion: int
    nodes: dict[str, dict[str, object]]
    targets: list[dict[str, object]]
    prometheus: list[dict[str, object]]


def fixtures() -> tuple[_Policy, _Inventory]:
    """Test behavior for fixtures."""
    policy = json.loads((POLICY_FIXTURE).read_text())
    for key in (
        "diskProjectionVerified",
        "backupVerified",
        "historyRoundtripVerified",
        "historySourceIntegrityVerified",
        "sourceRegistryVerified",
    ):
        policy[key] = True
    inventory: _Inventory = {
        "schemaVersion": 1,
        "nodes": {
            node: {
                "hostname": node,
                "observedAt": 1000,
                "diskTotalBytes": 1000 * GIB,
                "diskAvailableBytes": 500 * GIB,
                "memoryAvailableBytes": 16 * GIB,
            }
            for node in policy["nodes"]
        },
        "targets": [{"health": "up"}],
        "prometheus": [{"version": "v3.15.0"}],
    }
    return policy, inventory


class MigrationPreflightTests(unittest.TestCase):
    """Guard OpenTelemetry migration preflight invariants."""
    def test_retired_operational_policy_is_not_resurrected(self) -> None:
        """Retired operational policy is not resurrected."""

        assert not PREFLIGHT.DEFAULT_POLICY.exists()

    def test_ready_with_verified_prerequisites_and_capacity(self) -> None:
        """Ready with verified prerequisites and capacity."""

        policy, inventory = fixtures()
        assert PREFLIGHT.evaluate(policy, inventory, now=1000)["readyForCutover"]

    def test_historical_default_policy_never_authorizes_cutover(self) -> None:
        """Historical default policy never authorizes cutover."""

        _, inventory = fixtures()
        policy = json.loads(POLICY_FIXTURE.read_text())
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        assert not result["readyForCutover"]
        assert len([error for error in result["errors"] if "prerequisite" in error]) == 4

    def test_source_corruption_cannot_be_hidden_by_old_roundtrip_success(self) -> None:
        """Source corruption cannot be hidden by old roundtrip success."""

        for mode in ("missing", "false"):
            policy, inventory = fixtures()
            if mode == "missing":
                del policy["historySourceIntegrityVerified"]
            else:
                policy["historySourceIntegrityVerified"] = False
            result = PREFLIGHT.evaluate(policy, inventory, now=1000)
            assert not result["readyForCutover"]
            assert "Unverified prerequisite: historySourceIntegrityVerified" in result["errors"]

    def test_integrity_gate_links_to_the_unrepaired_source_incident(self) -> None:
        """Integrity gate links to the unrepaired source incident."""

        policy = json.loads(POLICY_FIXTURE.read_text())
        assert not policy["historySourceIntegrityVerified"]
        evidence = json.loads((ROOT / policy["historySourceIntegrityEvidence"]).read_text())
        assert not evidence["sourceIntegrityVerified"]
        assert evidence["badChunkCount"] == 1
        assert not evidence["productionHistoryModified"]
        assert not evidence["checksumChecksBypassed"]

    def test_historical_backup_receipt_format_is_consistent(self) -> None:
        """Historical backup receipt format is consistent."""

        policy = json.loads(POLICY_FIXTURE.read_text())
        assert policy["backupVerified"]
        receipt = json.loads((ROOT / policy["backupEvidence"]).read_text())
        assert receipt["verified"]
        assert receipt["snapshotIncludesHead"]
        assert receipt["controllerStateRestored"]
        assert not receipt["originalsDeleted"]
        assert receipt["replicaHost"] == "socrat-3"
        assert len(receipt["archiveSha256"]) == 4
        assert receipt["reports"]["prometheus-snapshot.tar.gz"]["blockCount"] > 0

    def test_missing_node_and_unhealthy_target_fail(self) -> None:
        """Missing node and unhealthy target fail."""

        policy, inventory = fixtures()
        del inventory["nodes"]["socrat-2"]
        inventory["targets"][0]["health"] = "down"
        assert len(PREFLIGHT.evaluate(policy, inventory, now=1000)["errors"]) == 2

    def test_disk_peak_uses_stricter_reserve(self) -> None:
        """Disk peak uses stricter reserve."""

        policy, inventory = fixtures()
        policy["nodes"]["socrat-0"]["projectedAdditionalDiskBytes"] = 301 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        assert any("disk space" in error for error in result["errors"])

    def test_known_memory_pressure_blocks_new_stack(self) -> None:
        """Known memory pressure blocks new stack."""

        policy, inventory = fixtures()
        inventory["nodes"]["socrat-1"]["memoryAvailableBytes"] = 4 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        assert any("socrat-1: insufficient" in error for error in result["errors"])

    def test_cluster_collectors_move_without_reducing_budgets(self) -> None:
        """Cluster collectors move without reducing budgets."""

        policy, inventory = fixtures()
        zero = policy["nodes"]["socrat-0"]["components"]
        one = policy["nodes"]["socrat-1"]["components"]
        assert zero == {"agent": 256 * 1024 ** 2, "clusterCollector": GIB, "traceGateway": GIB, "hostNodeExporter": 64 * 1024 ** 2}
        assert one == {"agent": 256 * 1024 ** 2, "loki": 2 * GIB, "tempo": 2 * GIB, "hostNodeExporter": 64 * 1024 ** 2}
        inventory["nodes"]["socrat-1"]["memoryAvailableBytes"] = 5 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        assert result["readyForCutover"]
        assert result["capacity"]["socrat-0"]["memoryRequiredBytes"] == 2880 * 1024 ** 2
        assert result["capacity"]["socrat-1"]["memoryRequiredBytes"] == 4928 * 1024 ** 2

    def test_relocated_collectors_still_require_memory_on_socrat_0(self) -> None:
        """Relocated collectors still require memory on socrat 0."""

        policy, inventory = fixtures()
        inventory["nodes"]["socrat-0"]["memoryAvailableBytes"] = 2 * GIB
        result = PREFLIGHT.evaluate(policy, inventory, now=1000)
        assert any("socrat-0: insufficient" in error for error in result["errors"])

    def test_stale_future_and_hostname_mismatch_fail(self) -> None:
        """Stale future and hostname mismatch fail."""

        for updates in ({"observedAt": 1}, {"observedAt": 2000}, {"hostname": "unexpected"}):
            policy, inventory = fixtures()
            inventory["nodes"]["socrat-0"].update(updates)
            assert not PREFLIGHT.evaluate(policy, inventory, now=1000)["readyForCutover"]

    def test_invalid_capacity_fails_closed(self) -> None:
        """Invalid capacity fails closed."""

        for invalid in (-1, float("nan"), float("inf"), True, "1000", None):
            policy, inventory = fixtures()
            inventory["nodes"]["socrat-0"]["memoryAvailableBytes"] = invalid
            assert not PREFLIGHT.evaluate(policy, inventory, now=1000)["readyForCutover"]

    def test_negative_budget_is_rejected(self) -> None:
        """Negative budget is rejected."""

        policy, inventory = fixtures()
        policy["nodes"]["socrat-1"]["components"]["tempo"] = -1
        with self.assertRaises(ValueError):
            PREFLIGHT.evaluate(policy, inventory, now=1000)

    def test_empty_and_old_inventory_fail(self) -> None:
        """Empty and old inventory fail."""

        policy, inventory = fixtures()
        inventory["targets"] = []
        inventory["prometheus"] = []
        assert not PREFLIGHT.evaluate(policy, inventory, now=1000)["readyForCutover"]
        inventory["schemaVersion"] = 0
        with self.assertRaises(ValueError):
            PREFLIGHT.evaluate(policy, inventory, now=1000)

    def test_evaluate_does_not_change_inputs(self) -> None:
        """Evaluate does not change inputs."""

        policy, inventory = fixtures()
        before = copy.deepcopy((policy, inventory))
        PREFLIGHT.evaluate(policy, inventory, now=1000)
        assert (policy, inventory) == before

    def test_inventory_files_are_private_and_not_overwritten(self) -> None:
        """Inventory files are private and not overwritten."""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            PREFLIGHT.save(path, {"test": 1})
            assert path.stat().st_mode & 511 == 384
            with self.assertRaises(FileExistsError):
                PREFLIGHT.save(path, {"test": 2})
            assert json.loads(path.read_text()) == {"test": 1}

    def test_monitor_inventory_does_not_export_credentials(self) -> None:
        """Monitor inventory does not export credentials."""

        monitor = {
            "kind": "ServiceMonitor",
            "metadata": {"namespace": "monitoring", "name": "test"},
            "spec": {
                "endpoints": [
                    {"interval": "5s", "authorization": {"credentials": {"name": "private-token"}}}
                ]
            },
        }
        result = PREFLIGHT.monitor_summary({"items": [monitor]})
        assert result[0]["requiresAuthentication"]
        assert "private-token" not in json.dumps(result)

    def test_contract_preserves_archive_and_tv_defaults(self) -> None:
        """Contract preserves archive and tv defaults."""

        contract = json.loads(POLICY_FIXTURE.read_text())["contract"]
        assert not contract["replaceProductionHistory"]
        assert not contract["modifyCascadePolicy"]
        assert contract["historicalDownsampled"] == "native-thanos-preserved"
        assert contract["dashboardRefresh"] == "5s"


if __name__ == "__main__":
    unittest.main()
