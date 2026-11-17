"""Check OpenTelemetry bootstrap command output handling offline."""

import importlib.util
import unittest
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest


def module() -> ModuleType:
    """Load the bootstrap module without invoking its main entrypoint."""
    spec = importlib.util.spec_from_file_location(
        "bootstrap_output",
        Path(__file__).resolve().parents[1] / "scripts/otel-production-bootstrap.py",
    )
    if not isinstance(spec, ModuleSpec) or spec.loader is None:
        message = "otel bootstrap module spec is unavailable"
        raise RuntimeError(message)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class CommandOutputTests(unittest.TestCase):
    """Kube stdout must not change delete retry or JSON parsing behavior."""

    def test_successful_delete_is_not_retried_due_to_text_output(self) -> None:
        """Assert text from a successful delete is not parsed or retried."""
        helper = module()
        with patch.object(
            helper.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout='job.batch "owned" deleted\n'),
        ) as call:
            assert helper.kube("-n", "llm", "delete", "job", "owned", "--wait=false") is None
            assert call.call_count == 1

    def test_failed_delete_still_fails_closed_without_response_disclosure(self) -> None:
        """Assert a failed delete omits the captured response text."""
        helper = module()
        with (
            patch.object(
                helper.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1, stdout="sensitive response"),
            ),
            pytest.raises(RuntimeError, match="sensitive response omitted"),
        ):
            helper.kube("delete", "job", "owned")

    def test_resource_named_delete_does_not_disable_json_parsing(self) -> None:
        """Assert a resource named delete still returns parsed JSON."""
        helper = module()
        with patch.object(
            helper.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout='{"kind":"Pod"}'),
        ):
            parsed = helper.kube("-n", "llm", "get", "pod", "delete", "-o", "json")
            assert parsed == {"kind": "Pod"}
