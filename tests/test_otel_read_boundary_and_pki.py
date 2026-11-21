"""Tests for OpenTelemetry read boundaries and PKI wiring."""

import importlib.util
from pathlib import Path
from types import ModuleType
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadBoundaryTests(unittest.TestCase):
    def test_only_known_read_limit_can_be_removed(self) -> None:
        repair = load("otel-store-read-boundary")
        arguments = ["store", "--max-time=-12h", "--consistency-delay=30m"]
        assert repair.unclamped(arguments) == ["store", "--consistency-delay=30m"]
        with self.assertRaises(ValueError):
            repair.unclamped(["store", "--max-time=-1d"])

    def test_application_reader_has_no_ca_host_or_write_permissions(self) -> None:
        pki = load("otel-application-pki")
        resources = pki.resources()
        certificates = [item for item in resources if item["kind"] == "Certificate"]
        assert {c["spec"]["commonName"] for c in certificates} == {
            "otel-app-" + app
            for app in ("harbor", "litellm", "vllm", "open-webui", "lms", "wishlist")
        }
        for certificate in certificates:
            assert certificate["spec"]["usages"] == ["digital signature", "client auth"]
            assert certificate["spec"]["privateKey"]["rotationPolicy"] == "Always"
        role = next(item for item in resources if item["kind"] == "Role")
        rule = role["rules"][0]
        assert rule["verbs"] == ["get"]
        assert "otel-root-ca" not in rule["resourceNames"]
        assert "otel-tls-socrat-0" not in rule["resourceNames"]
        assert set(rule["resourceNames"]) == {c["spec"]["secretName"] for c in certificates}

    def test_rbac_evaluation_error_is_not_certified_as_denial(self) -> None:
        pki = load("otel-application-pki")
        with patch.object(
            pki.BOOTSTRAP,
            "kube",
            return_value={"status": {"allowed": False, "evaluationError": "unavailable"}},
        ):
            with self.assertRaises(ValueError):
                pki.assess("secrets", "get", "otel-root-ca")
