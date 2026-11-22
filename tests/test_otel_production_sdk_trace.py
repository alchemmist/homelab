"""Production trace checks for the OpenTelemetry SDK setup."""

import copy
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from typing import NotRequired, TypedDict

ROOT = Path(__file__).resolve().parents[1]


class _Attribute(TypedDict):
    key: str
    value: dict[str, str]


class _Resource(TypedDict):
    attributes: list[_Attribute]


class _ResourceSpan(TypedDict):
    resource: _Resource
    scopeSpans: list[dict[str, list[dict[str, str]]]]


class _Document(TypedDict):
    resourceSpans: list[_ResourceSpan]
    diagnostic: NotRequired[str]


def module() -> ModuleType:
    """Test behavior for module."""
    spec = importlib.util.spec_from_file_location(
        "production_sdk_verify", ROOT / "scripts/otel-application-trace-verify.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ProductionSdkTraceTests(unittest.TestCase):
    """Check the production SDK trace summarizer against fixtures."""

    def fixture(self) -> tuple[_Document, str, str]:
        """Return the trace fixture and span batches."""
        trace_id, parent_id = "ab" * 16, "cd" * 8

        def batch(service, spans) -> _ResourceSpan:
            return {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": service}}]
                },
                "scopeSpans": [{"spans": spans}],
            }

        root = {
            "traceId": trace_id,
            "spanId": parent_id,
            "name": "homelab.synthetic.live-sdk-validation",
        }
        child = {
            "traceId": trace_id,
            "spanId": "ef" * 8,
            "parentSpanId": parent_id,
            "name": "Received Proxy Server Request",
        }
        doc: _Document = {
            "resourceSpans": [
                batch("homelab-live-sdk-probe", [root]),
                batch("litellm", [child]),
            ]
        }
        return doc, trace_id, parent_id

    def test_real_service_child_correlates_but_does_not_certify_inference_or_all_apps(
        self,
    ) -> None:
        """Real service child correlates but does not certify inference or all apps."""
        doc, trace_id, parent_id = self.fixture()
        result = module().summarize_production_litellm(doc, trace_id, parent_id)
        assert result["success"]
        assert result["crossProcessW3cParentChildVerified"]
        assert not result["productionInferenceSuccessPathVerified"]
        assert not result["allApplicationSdkCoverageComplete"]

    def test_ingress_shared_probe_or_library_service_cannot_impersonate_production(
        self,
    ) -> None:
        """Ingress shared probe or library service cannot impersonate production."""
        for service in [
            "traefik",
            "homelab-live-sdk-probe",
            "homelab-litellm-sdk-canary",
        ]:
            doc, trace_id, parent_id = self.fixture()
            doc["resourceSpans"][1]["resource"]["attributes"][0]["value"]["stringValue"] = service
            assert not module().summarize_production_litellm(doc, trace_id, parent_id)["success"]

    def test_wrong_trace_or_missing_parent_does_not_prove_w3c(self) -> None:
        """Wrong trace or missing parent does not prove w3c."""
        for change in [{"traceId": "11" * 16}, {"parentSpanId": "22" * 8}]:
            doc, trace_id, parent_id = self.fixture()
            doc["resourceSpans"][1]["scopeSpans"][0]["spans"][0].update(change)
            assert not module().summarize_production_litellm(doc, trace_id, parent_id)["success"]

    def test_inference_requires_native_llm_span_and_does_not_invent_cross_app_parenting(
        self,
    ) -> None:
        """Inference requires native llm span and does not invent cross app parenting."""
        doc, trace_id, parent_id = self.fixture()
        helper = module()
        assert not helper.summarize_production_litellm(doc, trace_id, parent_id, inference=True)[
            "success"
        ]
        llm = {
            "traceId": trace_id,
            "spanId": "aa" * 8,
            "parentSpanId": "ef" * 8,
            "name": "litellm_request",
        }
        doc["resourceSpans"][1]["scopeSpans"][0]["spans"].append(llm)
        report = helper.summarize_production_litellm(doc, trace_id, parent_id, inference=True)
        assert report["productionInferenceSuccessPathVerified"]
        assert not report["productionLitellmHttpAuthRouterErrorPathVerified"]
        assert not report["nativeVllmDescendantInSameTraceVerified"]
        vllm: _ResourceSpan = {
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "vllm"}}]},
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": trace_id,
                            "spanId": "bb" * 8,
                            "parentSpanId": "aa" * 8,
                            "name": "llm_request",
                        }
                    ]
                }
            ],
        }
        doc["resourceSpans"].append(vllm)
        assert helper.summarize_production_litellm(doc, trace_id, parent_id, inference=True)[
            "nativeVllmDescendantInSameTraceVerified"
        ]

    def test_sensitive_marker_rejected_even_on_native_inference_path(self) -> None:
        """Sensitive marker rejected even on native inference path."""
        doc, trace_id, parent_id = self.fixture()
        doc["resourceSpans"][1]["scopeSpans"][0]["spans"].append(
            {
                "traceId": trace_id,
                "spanId": "aa" * 8,
                "parentSpanId": parent_id,
                "name": "litellm_request",
            }
        )
        doc["diagnostic"] = "OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED"
        report = module().summarize_production_litellm(doc, trace_id, parent_id, inference=True)
        assert not report["success"]
        assert report["sensitiveSyntheticContentFound"]

    def test_duplicate_ids_or_self_parenting_are_rejected(self) -> None:
        """Duplicate ids or self parenting are rejected."""
        doc, trace_id, parent_id = self.fixture()
        child = doc["resourceSpans"][1]["scopeSpans"][0]["spans"][0]
        for change in [{"spanId": parent_id}, {"parentSpanId": child["spanId"]}]:
            bad = copy.deepcopy(doc)
            bad["resourceSpans"][1]["scopeSpans"][0]["spans"][0].update(change)
            assert not module().summarize_production_litellm(bad, trace_id, parent_id)["success"]
