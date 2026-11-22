"""Offline chart contract; no cluster API or credentials."""

import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("helm"), "helm unavailable")
class AlertGraphsChartTests(unittest.TestCase):
    """Tests for the alert graphs chart template."""

    def render(self, enabled=False, extra=()) -> subprocess.CompletedProcess[str]:
        """Run helm template for the chart, optionally with alert graphs enabled."""
        args = [
            "helm",
            "template",
            "kube-prometheus-stack",
            "charts/grafana",
            "--namespace",
            "cattle-monitoring-system",
        ]
        if enabled:
            args += [
                "--set",
                "alertGraphs.enabled=true",
                "--set",
                "alertGraphs.existingSecret=graph-test-only",
                "--set",
                "gateway.digest=sha256:" + "a" * 64,
                "--set",
                "grafana.imageRenderer.enabled=true",
                "--set",
                "grafana.imageRenderer.image.sha=" + "b" * 64,
                "--set",
                "alertGraphs.panels.service-health:12[0]=service",
            ]
        return subprocess.run(args + list(extra), cwd=ROOT, capture_output=True, text=True)

    def test_disabled_has_no_resources(self) -> None:
        """Default render produces no alert-graphs resources."""
        result = self.render()
        assert result.returncode == 0, result.stderr
        assert "name: socrat-alert-graphs" not in result.stdout

    def test_enabled_isolated_role(self) -> None:
        """Enabled render ships an isolated, digest-pinned gateway deployment."""
        result = self.render(True)
        assert result.returncode == 0, result.stderr
        assert "/app/graph_gateway.py" in result.stdout
        assert "name: socrat-alert-graphs" in result.stdout
        assert "automountServiceAccountToken: false" in result.stdout
        assert "readOnlyRootFilesystem: true" in result.stdout
        assert "checksum/policy:" in result.stdout
        assert "@sha256:sha256:" not in result.stdout
        assert "@sha256:" + "b" * 64 in result.stdout
        assert "mountPath: /data" not in result.stdout
        assert "SPI_S3_WRITER_FILE" not in result.stdout

    def test_release_values_render_real_valid_images(self) -> None:
        """Release values render valid immutable images and renderer limits."""
        result = self.render(
            False,
            [
                "-f",
                "charts/grafana/alert-graphs.policy.values.yaml",
                "-f",
                "charts/grafana/alert-graphs.runtime.values.yaml",
                "-f",
                "deploy/grafana/values.yaml",
            ],
        )
        assert result.returncode == 0, result.stderr
        assert "@sha256:sha256:" not in result.stdout
        import re

        import yaml

        for doc in yaml.safe_load_all(result.stdout):
            if not isinstance(doc, dict) or doc.get("kind") != "Deployment":
                continue
            for container in doc["spec"]["template"]["spec"]["containers"]:
                if container["name"] in ("gateway", "grafana-image-renderer"):
                    assert re.search(r"@sha256:[a-f0-9]{64}$", container["image"])
                if container["name"] == "grafana-image-renderer":
                    assert str(container["resources"]["limits"]["cpu"]) == "4"
                    assert container["resources"]["limits"]["memory"] == "2Gi"

    def test_monitoring_helpers_use_one_portable_home_placement(self) -> None:
        """Gateway and monitoring proxy share placement on portable home nodes."""
        import yaml

        result = self.render(
            extra=[
                "-f",
                "charts/grafana/alert-graphs.policy.values.yaml",
                "-f",
                "charts/grafana/alert-graphs.runtime.values.yaml",
                "-f",
                "deploy/grafana/values.yaml",
                "--show-only",
                "templates/alert-graphs.yaml",
            ]
        )
        assert result.returncode == 0, result.stderr
        (dep,) = [d for d in yaml.safe_load_all(result.stdout) if d and d["kind"] == "Deployment"]
        assert dep["spec"].get("replicas", 1) == 1
        proxy = yaml.safe_load((ROOT / "deploy/monitoring/rancher-values.yaml").read_text())[
            "monitoringProxy"
        ]

        def term(nodes) -> dict[str, object]:
            return {
                "matchExpressions": [
                    {"key": "kubernetes.io/hostname", "operator": "In", "values": nodes}
                ]
            }

        for spec in [dep["spec"]["template"]["spec"], proxy]:
            assert spec["nodeSelector"] == {"kubernetes.io/os": "linux"}
            assert spec["affinity"]["nodeAffinity"] == {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [term(["socrat-0", "socrat-1"])]
                },
                "preferredDuringSchedulingIgnoredDuringExecution": [
                    {"weight": 100, "preference": term(["socrat-0"])}
                ],
            }

    def test_requires_immutable_image(self) -> None:
        """Non-digest gateway images are rejected as non-immutable."""
        result = self.render(True, ["--set", "gateway.digest=latest"])
        assert result.returncode != 0
        assert "immutable" in result.stderr

    def test_requires_renderer(self) -> None:
        """Enabling alert graphs without the remote imageRenderer fails renders."""
        result = self.render(True, ["--set", "grafana.imageRenderer.enabled=false"])
        assert result.returncode != 0
        assert "remote imageRenderer" in result.stderr

    def test_bot_sources_are_exact_only(self) -> None:
        """Bot source CIDRs must be exact /32 or /128 addresses."""
        result = self.render(True, ["--set", "alertGraphs.botSourceCIDRs[0]=10.0.0.0/8"])
        assert result.returncode != 0
        assert "exact /32 or /128" in result.stderr
        result = self.render(True, ["--set", "alertGraphs.botSourceCIDRs[0]=10.250.0.2/32"])
        assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    unittest.main()
