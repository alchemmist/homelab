"""Source contracts for the owner-approved15Nov VM application handoff."""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def document(path):
    return yaml.safe_load((ROOT / path).read_text())


class VMApplicationPlacementTests(unittest.TestCase):
    """Verify vm application placement keeps original claims."""

    def test_n8n_uses_original_vm_claim_without_repointing_recovery_storage(self) -> None:
        values = document("charts/n8n/values.yaml")
        assert values["nodeName"] == "socrat-5"
        assert values["persistence"]["claimName"] == "n8n-socrat5"
        assert values["secretName"] == "n8n-secrets"
        assert values["replicaCount"] in [0, 1]
        assert values["recoveryStorage"]["name"] == "n8n-recovery-20261114"
        assert values["recoveryStorage"]["nodeName"] == "socrat-1"
        assert (
            values["recoveryStorage"]["path"]
            == "/home/alchemmist/.local/share/homelab/n8n-recovery-20261114/data"
        )

    def test_pr_agent_uses_vm_and_preserves_secret_identity(self) -> None:
        values = document("charts/pr-agent/values.yaml")
        assert values["nodeName"] == "socrat-5"
        assert values["secretName"] == "pr-agent"
        assert values["replicaCount"] == 1

    def test_rancher_single_replica_recovery_preserves_native_oidc_trust(self) -> None:
        values = document("deploy/platform/rancher/values.yaml")
        role = document("ansible/roles/rancher_placement/defaults/main.yml")
        assert values["replicas"] == 1
        assert values["antiAffinity"] == "preferred"
        assert values["extraNodeSelectorTerms"] == [
            {"key": "kubernetes.io/hostname", "operator": "In", "values": ["socrat-5"]}
        ]
        assert "nodeSelector" not in values
        assert role["rancher_placement_nodes"] == ["socrat-5"]
        assert role["rancher_replicas"] == 1
        assert role["rancher_chart_version"] == "2.15.3"
        assert not values["ingress"]["enabled"]

        assert values["extraEnv"] == [
            {"name": "SSL_CERT_FILE", "value": "/var/lib/ca-certificates/ca-bundle.pem"}
        ]
        assert role["rancher_ssl_cert_file"] == values["extraEnv"][0]["value"]
        assert "CATTLE_INSECURE_SKIP_VERIFY" not in str(values)
