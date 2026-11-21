"""Production trace checks for the OpenTelemetry vLLM setup."""

import copy
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import NotRequired, TypedDict

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


class _Document(TypedDict):
    resourceSpans: list[_ResourceSpan]
    private: NotRequired[str]


def module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "trace_verify", ROOT / "scripts/otel-application-trace-verify.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def document() -> _Document:
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
                "homelab-live-vllm-probe",
                {
                    "traceId": TRACE,
                    "spanId": PARENT,
                    "name": "homelab.synthetic.production-vllm-request",
                },
            ),
            resource(
                "vllm",
                {
                    "traceId": TRACE,
                    "spanId": "3" * 16,
                    "parentSpanId": PARENT,
                    "name": "llm_request",
                },
            ),
        ]
    }


class VllmProductionTraceTests(unittest.TestCase):
    """Verify production vLLM trace summaries require real resources."""
    def test_real_application_resource_and_parent_are_required(self) -> None:
        assert module().summarize_production_vllm(document(), TRACE, PARENT)["success"]
        for kind in ["service", "parent", "name", "duplicate"]:
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
            assert not module().summarize_production_vllm(data, TRACE, PARENT)["success"]

    def test_synthetic_prompt_in_backend_fails_privacy(self) -> None:
        data = document()
        data["private"] = "OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED"
        result = module().summarize_production_vllm(data, TRACE, PARENT)
        assert not result["success"]
        assert result["syntheticPromptFoundInBackend"]
