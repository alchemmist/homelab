"""Source contracts for the owner-approved15Nov VM application handoff."""

from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _mapping(value: object) -> dict[str, object]:
    """Narrow a decoded values document to keyed mapping access."""
    assert isinstance(value, dict)
    return value


def _sequence(value: object) -> list[object]:
    """Narrow a decoded list of value entries for positional access."""
    assert isinstance(value, list)
    return value


def document(path) -> dict[str, object]:
    return _mapping(yaml.safe_load((ROOT / path).read_text()))


class VMApplicationPlacementTests(unittest.TestCase):
    def test_n8n_uses_original_vm_claim_without_repointing_recovery_storage(self) -> None:
        values = document("charts/n8n/values.yaml")
        self.assertEqual(values["nodeName"], "socrat-5")
        self.assertEqual(_mapping(values["persistence"])["claimName"], "n8n-socrat5")
        self.assertEqual(values["secretName"], "n8n-secrets")
        self.assertIn(values["replicaCount"], [0, 1])
        self.assertEqual(_mapping(values["recoveryStorage"])["name"], "n8n-recovery-20261114")
        self.assertEqual(_mapping(values["recoveryStorage"])["nodeName"], "socrat-1")
        self.assertEqual(
            _mapping(values["recoveryStorage"])["path"],
            "/home/alchemmist/.local/share/homelab/n8n-recovery-20261114/data",
        )

    def test_pr_agent_uses_vm_and_preserves_secret_identity(self) -> None:
        values = document("charts/pr-agent/values.yaml")
        self.assertEqual(values["nodeName"], "socrat-5")
        self.assertEqual(values["secretName"], "pr-agent")
        self.assertEqual(values["replicaCount"], 1)

    def test_rancher_single_replica_recovery_preserves_native_oidc_trust(self) -> None:
        values = document("deploy/platform/rancher/values.yaml")
        role = document("ansible/roles/rancher_placement/defaults/main.yml")
        self.assertEqual(values["replicas"], 1)
        self.assertEqual(values["antiAffinity"], "preferred")
        self.assertEqual(
            values["extraNodeSelectorTerms"],
            [{"key": "kubernetes.io/hostname", "operator": "In", "values": ["socrat-5"]}],
        )
        self.assertNotIn("nodeSelector", values)
        self.assertEqual(role["rancher_placement_nodes"], ["socrat-5"])
        self.assertEqual(role["rancher_replicas"], 1)
        self.assertEqual(role["rancher_chart_version"], "2.15.2")
        self.assertFalse(_mapping(values["ingress"])["enabled"])

        self.assertEqual(
            values["extraEnv"],
            [{"name": "SSL_CERT_FILE", "value": "/var/lib/ca-certificates/ca-bundle.pem"}],
        )
        self.assertEqual(
            role["rancher_ssl_cert_file"],
            _mapping(_sequence(values["extraEnv"])[0])["value"],
        )
        self.assertNotIn("CATTLE_INSECURE_SKIP_VERIFY", str(values))
