"""Offline contracts for the private wishlist image optimizer."""

import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

OPTIMIZER_SYNC_WAVE_COUNT = 3
OPTIMIZER_PORT = 8081


class WishlistImages(unittest.TestCase):
    """Pinned chart contracts for the in-namespace image optimizer."""

    def test_private_resource_isolation_no_external_optimizer(self) -> None:
        """The optimizer stays cluster-internal, with no ingress or secret mount."""
        source = (ROOT / "charts/wishlist/templates/image-optimizer.yaml").read_text()
        assert "if .Values.images.enabled" in source
        assert source.count('argocd.argoproj.io/sync-wave: "-1"') == OPTIMIZER_SYNC_WAVE_COUNT
        for value in [
            "type: ClusterIP",
            "kind: NetworkPolicy",
            "egress: []",
            "automountServiceAccountToken: false",
            "readOnlyRootFilesystem: true",
            "runAsNonRoot: true",
            "/opt/image-optimizer/server.cjs",
        ]:
            assert value in source
        assert "kind: Ingress" not in source
        assert "hostPort:" not in source
        assert "secretRef:" not in source
        assert "persistentVolumeClaim:" not in source
        assert "name.startsWith('wishlist-image-')" in source
        assert "postStart:" in source
        assert "sizeLimit: 4Gi" in source
        ingress = (ROOT / "charts/wishlist/templates/ingress.yaml").read_text()
        assert "optimizer" not in ingress

    def test_app_image_and_same_namespace_only(self) -> None:
        """The optimizer image stays digest-pinned in the release namespace."""
        source = (ROOT / "charts/wishlist/templates/image-optimizer.yaml").read_text()
        assert ".Values.image.digest" in source
        assert "app.kubernetes.io/name: {{ .Chart.Name }}" in source
        assert "app.kubernetes.io/instance: {{ .Release.Name }}" in source
        assert "namespaceSelector:" not in source
        output = subprocess.check_output(
            [
                "helm",
                "template",
                "wishlist",
                str(ROOT / "charts/wishlist"),
                "-f",
                str(ROOT / "deploy/wishlist/values.yaml"),
                "--show-only",
                "templates/deployment.yaml",
                "--kubeconfig",
                "/dev/null",
            ],
            text=True,
        )
        pod = yaml.safe_load(output)["spec"]["template"]["spec"]
        [app] = [c for c in pod["containers"] if c["name"] == "wishlist"]
        assert [e for e in app["env"] if e["name"] == "IMAGE_OPTIMIZER_URL"] == [
            {"name": "IMAGE_OPTIMIZER_URL", "value": "http://wishlist-image-optimizer:8081"}
        ]
        assert [v for v in pod["volumes"] if v["name"] == "media-cache"] == [
            {"name": "media-cache", "emptyDir": {"sizeLimit": "2Gi"}}
        ]
        assert [m for m in app["volumeMounts"] if m["mountPath"] == "/data/media-cache"] == [
            {"name": "media-cache", "mountPath": "/data/media-cache"}
        ]
        assert [v for v in pod["volumes"] if v["name"] == "data"] == [
            {"name": "data", "persistentVolumeClaim": {"claimName": "wishlist-socrat5"}}
        ]

    def test_native_memory_limit_no_application_job_semaphore(self) -> None:
        """Memory and ephemeral storage stay native limits, with no CPU pin."""
        values = yaml.safe_load((ROOT / "charts/wishlist/values.yaml").read_text())["images"]
        assert values["optimizerPort"] == OPTIMIZER_PORT
        assert values["resources"]["limits"]["memory"] == "2Gi"
        assert values["resources"]["limits"]["ephemeral-storage"] == "4Gi"
        assert "cpu" not in values["resources"]["limits"]
