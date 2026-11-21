"""Tests for the 3x-ui workload configuration."""

import os
from pathlib import Path
import shutil
import subprocess
import unittest

try:
    import yaml
except ImportError:
    yaml = None


CHART = Path(__file__).resolve().parents[1] / "charts/x-ui"
HELM = os.environ.get("HELM_BIN") or shutil.which("helm")


@unittest.skipUnless(HELM and yaml, "Helm and PyYAML are required for chart rendering")
class XuiWorkloadTests(unittest.TestCase):
    """Tests or helper for XuiWorkloadTests."""
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [HELM, "template", "x-ui", str(CHART), "--namespace", "x-ui"],
            check=True,
            capture_output=True,
            text=True,
        )
        cls.documents = list(yaml.safe_load_all(result.stdout))
        cls.deployment = next(item for item in cls.documents if item["kind"] == "Deployment")
        cls.pod = cls.deployment["spec"]["template"]["spec"]
        cls.containers = {item["name"]: item for item in cls.pod["containers"]}
        cls.volumes = {item["name"]: item["hostPath"] for item in cls.pod["volumes"]}

    def test_single_workload_cannot_create_concurrent_database_writers(self):
        assert [
            item["metadata"]["name"] for item in self.documents if item["kind"] == "Deployment"
        ] == ["x-ui"]
        assert self.deployment["spec"]["replicas"] == 1
        assert self.deployment["spec"]["strategy"] == {"type": "Recreate"}
        assert set(self.containers) == {"primary"}
        assert self.pod["hostNetwork"]
        assert self.pod["dnsPolicy"] == "Default"
        assert self.pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-2"}

    def test_existing_database_and_runtime_paths_remain_isolated(self):
        expected = {
            "primary": {
                "/etc/x-ui": "/srv/x-ui-lab/db",
                "/root/cert": "/srv/x-ui-lab/cert",
                "/root/.acme.sh": "/srv/x-ui-lab/acme",
            },
        }
        for name, paths in expected.items():
            with self.subTest(container=name):
                mounts = self.containers[name]["volumeMounts"]
                assert {
                    mount["mountPath"]: self.volumes[mount["name"]]["path"] for mount in mounts
                } == paths
                database = next(mount for mount in mounts if mount["mountPath"] == "/etc/x-ui")
                assert self.volumes[database["name"]]["type"] == "Directory"

    def test_versions_and_probe_endpoints_are_preserved(self):
        expected = {
            "primary": (
                "1628adbd9bed680d25d6f714bef4a20f132105f4612ea294952f6665dad32e5b",
                "127.0.0.1",
                18082,
                12096,
                32087,
            ),
        }
        names = []
        for name, (digest, host, panel, subscription, trojan) in expected.items():
            with self.subTest(container=name):
                container = self.containers[name]
                assert container["image"] == "ghcr.io/mhsanaei/3x-ui@sha256:" + digest
                ports = {port["name"]: port["containerPort"] for port in container["ports"]}
                names.extend(ports)
                assert set(ports.values()) == {panel, subscription, trojan}
                for probe, endpoint in [("startupProbe", panel), ("readinessProbe", trojan)]:
                    socket = container[probe]["tcpSocket"]
                    assert socket["host"] == host
                    assert ports[socket["port"]] == endpoint
        assert len(names) == len(set(names))
        assert all(len(name) <= 15 for name in names)

    def test_service_selects_unified_pod_and_primary_ports(self):
        service = next(item for item in self.documents if item["kind"] == "Service")
        assert (
            service["spec"]["selector"] == self.deployment["spec"]["template"]["metadata"]["labels"]
        )
        ports = {
            port["name"]: port["containerPort"] for port in self.containers["primary"]["ports"]
        }
        assert {port["port"]: ports[port["targetPort"]] for port in service["spec"]["ports"]} == {
            2053: 18082,
            2096: 12096,
            10443: 32087,
        }


if __name__ == "__main__":
    unittest.main()
