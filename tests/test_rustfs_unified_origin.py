"""Offline-only gates for the staged, not activated, unified browser edge."""

import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class UnifiedOrigin(unittest.TestCase):
    """Guarded route priority and the inactive unified-origin default."""

    def test_routes_are_guarded_and_exactly_prioritized(self) -> None:
        """Require browser, outpost, evidence, gateway, and isolation contracts."""
        text = subprocess.check_output(
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
                "browserRoutes.unifiedOrigin=true",
            ],
            text=True,
        )
        docs = text.split("---")
        console = next(d for d in docs if "name: rustfs-console-browser" in d)
        self.assertIn("argocd-rustfs-browser-auth@kubernetescrd", console)
        self.assertIn("service: {name: rustfs-console-http, port: {number: 80}}", console)
        self.assertNotIn("number: 9000", console)
        middleware = next(d for d in docs if "kind: Middleware" in d)
        self.assertIn("namespace: argocd", middleware)
        self.assertIn("homelab.alchemmist.xyz/edge-transport: argocd", middleware)
        self.assertIn("trustForwardHeader: false", middleware)
        self.assertIn(
            "https://rustfs.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/traefik", middleware
        )
        outpost = next(d for d in docs if "name: rustfs-authentik-browser" in d)
        self.assertIn("router.priority: '200'", outpost)
        self.assertNotIn("path: /\n", outpost)
        reader = next(d for d in docs if "name: rustfs-evidence-browser" in d)
        self.assertIn("router.priority: '150'", reader)
        self.assertIn("path: /spi/v1/", reader)
        self.assertIn("host: rustfs.socrat.alchemmist.xyz", reader)
        gateway = next(d for d in docs if "name: gateway\n" in d)
        self.assertIn(
            "https://rustfs.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/nginx", gateway
        )
        policy = next(d for d in docs if "name: rustfs-isolation" in d)
        import yaml

        parsed = yaml.safe_load(policy)
        for ingress in parsed["spec"]["ingress"]:
            for peer in ingress["from"]:
                self.assertNotEqual(
                    peer.get("podSelector", {})
                    .get("matchLabels", {})
                    .get("app.kubernetes.io/name"),
                    "traefik",
                )
            self.assertTrue({p["port"] for p in ingress["ports"]} <= {9000, 9001})
        self.assertNotIn("0.0.0.0/0", text)

    def test_activation_remains_off(self) -> None:
        """Keep the unified browser origin absent unless explicitly enabled."""
        text = subprocess.check_output(
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
                "browserRoutes.unifiedOrigin=false",
            ],
            text=True,
        )
        self.assertNotIn("name: rustfs-browser-auth", text)
        self.assertNotIn("kind: Middleware", text)
        self.assertIn(
            "https://spi-evidence.socrat.alchemmist.xyz/outpost.goauthentik.io/auth/nginx", text
        )
