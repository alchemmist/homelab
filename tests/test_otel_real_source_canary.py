"""Tests for the OpenTelemetry real-source canary."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "real_canary", ROOT / "ansible/scripts/otel-real-source-canary.py"
)
CANARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CANARY)


class RealSourceCanaryTests(unittest.TestCase):
    """Verify real-source canary discovery uses private files only."""

    def test_source_assets_and_discovery_use_private_files(self) -> None:
        """Source assets and discovery use private files."""
        original = {
            "authorization": {"credentials_file": "/etc/otel/source-auth/ns/name/key"},
            "kubernetes_sd_configs": [{"role": "endpoints"}],
            "replacement": "$$1",
        }
        result = CANARY.rewrite_assets(
            original,
            {"/etc/otel/source-auth/ns/name/key": "/private/credential"},
            Path("/private/kubeconfig"),
        )
        assert result["authorization"]["credentials_file"] == "/private/credential"
        assert result["kubernetes_sd_configs"][0]["kubeconfig_file"] == "/private/kubeconfig"
        assert result["replacement"] == "$$1"
        assert "kubeconfig_file" not in original["kubernetes_sd_configs"][0]

    def test_existing_discovery_auth_is_never_silently_replaced(self) -> None:
        """Existing discovery auth is never silently replaced."""
        with self.assertRaises(ValueError):
            CANARY.rewrite_assets(
                {"kubernetes_sd_configs": [{"api_server": "https://other"}]},
                {},
                Path("/private/kubeconfig"),
            )

    def test_expected_target_identity_covers_every_label(self) -> None:
        """Expected target identity covers every label."""
        item = {
            "scrapePool": "owned",
            "health": "up",
            "labels": {"job": "source", "instance": "node", "namespace": "test"},
        }
        expected = CANARY.expected_targets({"activeTargets": [item]}, {"owned"})
        assert expected == {CANARY.fingerprint({**item["labels"], "__name__": "up"})}
        with self.assertRaises(ValueError):
            CANARY.expected_targets({"activeTargets": [item, item]}, {"owned"})
        with self.assertRaises(ValueError):
            CANARY.expected_targets({"activeTargets": [{**item, "health": "down"}]}, {"owned"})

    def test_cleanup_refuses_non_canary_workspaces(self) -> None:
        """Cleanup refuses non canary workspaces."""
        with self.assertRaises(ValueError):
            CANARY.cleanup_workspace(Path("/tmp/production-history"))
