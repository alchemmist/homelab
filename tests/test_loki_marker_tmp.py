"""Tests for the Loki marker scratch-directory policy."""

import subprocess
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


class LokiMarkerScratchTests(unittest.TestCase):
    def test_loki_only_writable_bounded_scratch_preserves_security_and_data(self) -> None:
        rendered = "\n---\n".join(
            subprocess.check_output(
                ["helm", "template", name, str(ROOT / "charts" / name),
                 *(["--set-string", "storagePhase=local"] if name == "loki" else [])], text=True
            )
            for name in ("loki", "tempo")
        )
        deployments = {
            d["metadata"]["name"]: d
            for d in yaml.safe_load_all(rendered)
            if d and d["kind"] == "Deployment"
        }
        for name, d in deployments.items():
            spec = d["spec"]["template"]["spec"]
            c = spec["containers"][0]
            assert c["securityContext"]["readOnlyRootFilesystem"]
            assert not c["securityContext"]["allowPrivilegeEscalation"]
            assert spec["securityContext"]["runAsNonRoot"]
            assert spec["securityContext"]["runAsUser"] == 10001
            mounts = {v["name"]: v for v in c["volumeMounts"]}
            volumes = {v["name"]: v for v in spec["volumes"]}
            assert mounts["data"]["mountPath"] == "/var/lib/otel"
            assert mounts["tls"]["readOnly"]
            if name == "otel-loki":
                assert volumes["data"]["hostPath"]["path"] == "/var/lib/private/homelab-otel-loki"
                assert mounts["marker-tmp"]["mountPath"] == "/tmp"
                assert volumes["marker-tmp"]["emptyDir"] == {"sizeLimit": "1Gi"}
            else:
                assert volumes["data"] == {"name": "data", "persistentVolumeClaim": {"claimName": yaml.safe_load((ROOT / "deploy/storage/tempo-drill/pvc.yaml").read_text())["metadata"]["name"]}}
                assert "marker-tmp" not in mounts
                assert "marker-tmp" not in volumes

    def test_loki_storage_phases(self) -> None:
        chart = ROOT / "charts/loki"
        claim = yaml.safe_load((ROOT / "deploy/storage/loki-drill/pvc.yaml").read_text())["metadata"]["name"]
        for phase in ("local", "paused", "shared", "typo"):
            with self.subTest(phase=phase):
                result = subprocess.run(["helm", "template", "loki", str(chart), "-f", str(chart / "alert-graphs.values.yaml"), "--set-string", f"storagePhase={phase}", "--show-only", "templates/deployment.yaml"], text=True, capture_output=True)
                if phase == "typo":
                    assert result.returncode != 0
                    assert "storagePhase must be" in result.stderr
                    continue
                assert result.returncode == 0, result.stderr
                dep = yaml.safe_load(result.stdout)["spec"]
                assert dep["replicas"] == (0 if phase == "paused" else 1)
                assert dep["strategy"]["type"] == "Recreate"
                pod = dep["template"]["spec"]
                data = next(v for v in pod["volumes"] if v["name"] == "data")
                if phase != "shared":
                    assert data["hostPath"]["path"] == "/var/lib/private/homelab-otel-loki"
                    assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-1"}
                    continue
                assert data == {"name": "data", "persistentVolumeClaim": {"claimName": claim}}
                assert pod["nodeSelector"] == {"kubernetes.io/os": "linux"}
                affinity = pod["affinity"]["nodeAffinity"]
                terms = affinity["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
                assert len(terms) == 1
                assert {"key": "kubernetes.io/hostname", "operator": "In", "values": ["socrat-0", "socrat-1"]} in terms[0]["matchExpressions"]
                assert {"weight": 100, "preference": {"matchExpressions": [{"key": "kubernetes.io/hostname", "operator": "In", "values": ["socrat-1"]}]}} in affinity["preferredDuringSchedulingIgnoredDuringExecution"]
