"""Tests for OpenTelemetry read boundaries and PKI wiring."""

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name) -> ModuleType:
    """Test behavior for load."""
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), ROOT / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReadBoundaryTests(unittest.TestCase):
    """Check the store read-boundary repair rules."""

    def test_only_known_read_limit_can_be_removed(self) -> None:
        """Only known read limit can be removed."""
        repair = load("otel-store-read-boundary")
        arguments = ["store", "--max-time=-12h", "--consistency-delay=30m"]
        assert repair.unclamped(arguments) == ["store", "--consistency-delay=30m"]
        with pytest.raises(ValueError):
            repair.unclamped(["store", "--max-time=-1d"])

    def test_application_reader_has_no_ca_host_or_write_permissions(self) -> None:
        """Application reader has no ca host or write permissions."""
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
        """Rbac evaluation error is not certified as denial."""
        pki = load("otel-application-pki")
        with (
            patch.object(
                pki.BOOTSTRAP,
                "kube",
                return_value={"status": {"allowed": False, "evaluationError": "unavailable"}},
            ),
            pytest.raises(ValueError),
        ):
            pki.assess("secrets", "get", "otel-root-ca")
