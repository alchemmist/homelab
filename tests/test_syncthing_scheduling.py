"""Offline scheduling contracts for the Syncthing chart's private GUI."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get("HELM_BIN") or shutil.which("helm")


@unittest.skipUnless(HELM and yaml, "Helm and PyYAML are required")
class SyncthingSchedulingTests(unittest.TestCase):
    """Render the local chart and keep node eligibility tied to sidecar config."""

    def render(self, overrides) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            values = Path(directory) / "values.json"
            values.write_text(
                json.dumps(
                    {
                        "nodeSelector": {},
                        **overrides,
                        "privateGui": {
                            "enabled": True,
                            "gatewayOnlyNodes": [],
                            **overrides.get("privateGui", {}),
                        },
                    }
                )
            )
            return subprocess.run(
                [HELM, "template", "syncthing", str(ROOT / "charts/syncthing"), "-f", str(values)],
                capture_output=True,
                text=True,
                timeout=30,
            )

    def resources(self, overrides) -> list[dict[str, object]]:
        result = self.render(overrides)
        assert result.returncode == 0, result.stderr
        return [item for item in yaml.safe_load_all(result.stdout) if item]

    def test_only_nodes_with_sidecar_configuration_are_eligible(self) -> None:
        """Admit only nodes that have a rendered sidecar configuration."""
        for overrides in [
            {},
            {
                "privateGui": {
                    "nodes": [
                        {
                            "nodeName": "socrat-7",
                            "host": "7.socrat.example.org",
                            "wgIP": "10.250.0.7",
                        }
                    ]
                }
            },
        ]:
            with self.subTest(overrides=overrides):
                resources = self.resources(overrides)
                pod = next(
                    item
                    for item in resources
                    if item["kind"] == "Deployment" and item["metadata"]["name"] == "syncthing"
                )["spec"]["template"]["spec"]
                configuration = next(item for item in resources if item["kind"] == "ConfigMap")[
                    "data"
                ]
                terms = pod["affinity"]["nodeAffinity"][
                    "requiredDuringSchedulingIgnoredDuringExecution"
                ]["nodeSelectorTerms"]
                eligible = set()
                for term in terms:
                    selector = term["matchFields"][0]
                    assert selector["key"] == "metadata.name"
                    assert selector["operator"] == "In"
                    assert len(selector["values"]) == 1
                    eligible.update(selector["values"])
                assert eligible == {
                    name.removesuffix(".conf") for name in configuration if name.endswith(".conf")
                }
                assert "socrat-3" not in eligible

    def test_explicit_node_selector_remains_an_additional_constraint(self) -> None:
        """Keep an explicit node selector beside the required node affinity."""
        resources = self.resources(
            {"nodeSelector": {"homelab.io/storage": "true", "kubernetes.io/hostname": "socrat-0"}}
        )
        pod = next(
            item
            for item in resources
            if item["kind"] == "Deployment" and item["metadata"]["name"] == "syncthing"
        )["spec"]["template"]["spec"]
        assert pod["nodeSelector"] == {
            "homelab.io/storage": "true",
            "kubernetes.io/hostname": "socrat-0",
        }
        assert "nodeAffinity" in pod["affinity"]

    def test_public_gui_does_not_require_private_node_configuration(self) -> None:
        """Leave affinity unset when the private GUI is disabled."""
        resources = self.resources({"privateGui": {"enabled": False, "nodes": []}})
        pod = next(
            item
            for item in resources
            if item["kind"] == "Deployment" and item["metadata"]["name"] == "syncthing"
        )["spec"]["template"]["spec"]
        assert "affinity" not in pod

    def test_private_gui_rejects_empty_enrollment(self) -> None:
        """Refuse a private GUI that has no configured node."""
        result = self.render({"privateGui": {"nodes": []}})
        assert result.returncode != 0
        assert "privateGui requires at least one configured node" in result.stderr


if __name__ == "__main__":
    unittest.main()
