"""Production trace checks for the OpenTelemetry Open WebUI setup."""

import copy
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
TRACE = "1" * 32
PARENT = "2" * 16


class _Attribute(TypedDict):
    key: str
    value: dict[str, str]


class _Resource(TypedDict):
    attributes: list[_Attribute]


class _Span(TypedDict, total=False):
    traceId: str
    spanId: str
    parentSpanId: str
    name: str
    kind: str


class _ResourceSpan(TypedDict):
    resource: _Resource
    scopeSpans: list[dict[str, list[_Span]]]


def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "trace_verify", ROOT / "scripts/otel-application-trace-verify.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def document() -> dict[str, list[_ResourceSpan]]:
    def resource(service, span) -> _ResourceSpan:
        return {
            "resource": {
                "attributes": [{"key": "service.name", "value": {"stringValue": service}}]
            },
            "scopeSpans": [{"spans": [span]}],
        }

    return {
        "resourceSpans": [
            resource(
                "homelab-live-open-webui-probe",
                {
                    "traceId": TRACE,
                    "spanId": PARENT,
                    "name": "homelab.synthetic.production-open-webui-request",
                },
            ),
            resource(
                "open-webui",
                {
                    "traceId": TRACE,
                    "spanId": "3" * 16,
                    "parentSpanId": PARENT,
                    "name": "GET /api/version",
                    "kind": "SPAN_KIND_SERVER",
                },
            ),
        ]
    }


class OpenWebuiProductionTraceTests(unittest.TestCase):
    """Verify production Open WebUI trace summaries require real resources."""

    def test_real_application_server_resource_and_parent_are_required(self) -> None:
        """Real application server resource and parent are required."""
        result = module().summarize_production_open_webui(document(), TRACE, PARENT)
        assert result["success"]
        assert not result["productionOpenWebuiInferencePathVerified"]
        assert not result["allApplicationSdkCoverageComplete"]
        for kind in ["service", "parent", "name", "duplicate", "kind", "missing-kind"]:
            data = document()
            child = data["resourceSpans"][1]["scopeSpans"][0]["spans"][0]
            if kind == "service":
                data["resourceSpans"][1]["resource"]["attributes"][0]["value"]["stringValue"] = (
                    "traefik"
                )
            if kind == "parent":
                child["parentSpanId"] = "4" * 16
            if kind == "name":
                child["name"] = "ingress"
            if kind == "duplicate":
                data["resourceSpans"].append(copy.deepcopy(data["resourceSpans"][1]))
            if kind == "kind":
                child["kind"] = "SPAN_KIND_INTERNAL"
            if kind == "missing-kind":
                child.pop("kind")
            assert not module().summarize_production_open_webui(data, TRACE, PARENT)["success"]
