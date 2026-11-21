"""Safety checks for the production OpenTelemetry deployment."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name) -> ModuleType:
    """Test behavior for module."""
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / (name + ".py")
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ProductionSafetyTests(unittest.TestCase):
    """Check production bootstrap token roles and CA key access."""
    def test_host_token_roles_are_named_and_cannot_read_ca_private_key(self) -> None:
        """Host token roles are named and cannot read ca private key."""

        boot = module("otel-production-bootstrap")
        resources = boot.resources({"requiredSecretKeys": []}, "10.43.1.2", {})
        roles = [
            r
            for r in resources
            if r["kind"] == "Role" and r["metadata"]["name"].startswith("otel-host-")
        ]
        assert {r["metadata"]["name"] for r in roles} == {
            "otel-host-" + node for node in boot.NODES
        }
        for role in roles:
            for rule in role["rules"]:
                assert "*" not in rule["verbs"]
                assert "otel-root-ca" not in rule.get("resourceNames", [])
                if rule["resources"] == ["serviceaccounts/token"]:
                    assert rule["resourceNames"] == [role["metadata"]["name"]]

    def test_verified_private_wireguard_addresses_are_not_interchanged(self) -> None:
        """Verified private wireguard addresses are not interchanged."""

        boot = module("otel-production-bootstrap")
        assert boot.NODES["socrat-0"] == "10.250.0.1"
        assert boot.NODES["socrat-2"] == "10.250.0.2"

    def test_native_overlay_does_not_turn_on_legacy_scraping(self) -> None:
        """Native overlay does not turn on legacy scraping."""

        import yaml

        values = yaml.safe_load(
            (ROOT / "deploy/monitoring/otel-production-values.yaml").read_text()
        )
        spec = values["prometheus"]["prometheusSpec"]
        assert spec["listenLocal"]
        assert spec["enableOTLPReceiver"]
        assert spec["otlp"]["translationStrategy"] == "NoTranslation"
        for key in [
            "serviceMonitorSelector",
            "podMonitorSelector",
            "scrapeConfigSelector",
            "probeSelector",
        ]:
            assert (
                spec[key]["matchLabels"]["homelab.alchemmist.xyz/scrape-owner"]
                == "retired-legacy-prometheus"
            )
        assert spec["evaluationInterval"] == "5s"
