"""Offline migration gates; never claim runtime hostNetwork CNI acceptance."""

import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from services.rustfs_gateway.gateway import Reader

ROOT = Path(__file__).resolve().parents[1]

GATEWAY_DOC_COUNT = 3


class Namespace(unittest.TestCase):
    """Rendered RustFS namespace boundaries and the fixed S3 destination."""

    def render(self, namespace) -> str:
        return subprocess.check_output(
            [
                "helm",
                "template",
                "rustfs",
                str(ROOT / "charts/rustfs"),
                "-n",
                "rustfs",
                "-f",
                str(ROOT / "charts/rustfs/values-foundation-live.yaml"),
                "--set",
                "browserRoutes.enabled=true",
                "--set",
                "gateway.namespace=" + namespace,
            ],
            text=True,
        )

    def test_placements_and_isolation(self) -> None:
        """Keep gateway, storage, and browser namespaces isolated."""
        for ns in ("rustfs", "identity"):
            text = self.render(ns)
            docs = text.split("---")
            gateway = [d for d in docs if "metadata: {name: rustfs-gateway" in d]
            assert len(gateway) == GATEWAY_DOC_COUNT
            for d in gateway:
                assert "namespace: " + ns in d
                assert "rustfs-root" not in d
                assert "rustfs-oidc" not in d
                assert "persistentVolumeClaim:" not in d
            reader = next(d for d in docs if "name: rustfs-evidence-browser" in d)
            assert "namespace: " + ns in reader
            auth = next(d for d in docs if "name: rustfs-console-browser" in d)
            assert "namespace: identity" in auth
            assert (
                "namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: "
                + ns
                + "}}\n          podSelector: {matchLabels: {app: rustfs-gateway}}"
                in text
            )
            assert (
                "namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: rustfs}}\n          podSelector: {matchLabels: {app: rustfs}}"
                in text
            )
            assert "0.0.0.0/0" not in text
            storage = next(d for d in docs if "kind: Deployment" in d and "  name: rustfs\n" in d)
            assert "namespace: identity" not in storage
            assert "rustfs-root" in storage
        with self.assertRaises(subprocess.CalledProcessError):
            self.render("default")

    def test_fixed_destination(self) -> None:
        """Require the in-cluster S3 endpoint and reject other origins."""
        env = {
            "AUTH_URL": "https://rustfs.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/nginx",
            "S3_ACCESS_KEY": "offline",
            "S3_SECRET_KEY": "offline",
        }
        with patch.dict(os.environ, env, clear=True):
            assert Reader().s3 == "http://rustfs.rustfs.svc.cluster.local:9000"
            for endpoint in (
                "http://rustfs:9000",
                "http://127.0.0.1:9000",
                "https://public.example",
                "http://rustfs.rustfs.svc.cluster.local:9000/evil",
            ):
                with patch.dict(os.environ, S3_ENDPOINT=endpoint):
                    with self.assertRaises(ValueError):
                        Reader()
