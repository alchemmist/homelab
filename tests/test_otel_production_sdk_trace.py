import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('production_sdk_verify', ROOT / 'scripts/otel-application-trace-verify.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class ProductionSdkTraceTests(unittest.TestCase):
    def fixture(self):
        trace_id, parent_id = 'ab' * 16, 'cd' * 8
        def batch(service, spans):
            return {'resource': {'attributes': [{'key': 'service.name', 'value': {'stringValue': service}}]}, 'scopeSpans': [{'spans': spans}]}
        root = {'traceId': trace_id, 'spanId': parent_id, 'name': 'homelab.synthetic.live-sdk-validation'}
        child = {'traceId': trace_id, 'spanId': 'ef' * 8, 'parentSpanId': parent_id, 'name': 'Received Proxy Server Request'}
        return {'resourceSpans': [batch('homelab-live-sdk-probe', [root]), batch('litellm', [child])]}, trace_id, parent_id

    def test_real_service_child_correlates_but_does_not_certify_inference_or_all_apps(self):
        doc, trace_id, parent_id = self.fixture()
        result = module().summarize_production_litellm(doc, trace_id, parent_id)
        self.assertTrue(result['success'])
        self.assertTrue(result['crossProcessW3cParentChildVerified'])
        self.assertFalse(result['productionInferenceSuccessPathVerified'])
        self.assertFalse(result['allApplicationSdkCoverageComplete'])

    def test_ingress_shared_probe_or_library_service_cannot_impersonate_production(self):
        for service in ['traefik', 'homelab-live-sdk-probe', 'homelab-litellm-sdk-canary']:
            doc, trace_id, parent_id = self.fixture()
            doc['resourceSpans'][1]['resource']['attributes'][0]['value']['stringValue'] = service
            self.assertFalse(module().summarize_production_litellm(doc, trace_id, parent_id)['success'])

    def test_wrong_trace_or_missing_parent_does_not_prove_w3c(self):
        for change in [{'traceId': '11' * 16}, {'parentSpanId': '22' * 8}]:
            doc, trace_id, parent_id = self.fixture()
            doc['resourceSpans'][1]['scopeSpans'][0]['spans'][0].update(change)
            self.assertFalse(module().summarize_production_litellm(doc, trace_id, parent_id)['success'])

    def test_inference_requires_native_llm_span_and_does_not_invent_cross_app_parenting(self):
        doc, trace_id, parent_id = self.fixture()
        helper = module()
        self.assertFalse(helper.summarize_production_litellm(doc, trace_id, parent_id, inference=True)['success'])
        llm = {'traceId': trace_id, 'spanId': 'aa' * 8, 'parentSpanId': 'ef' * 8, 'name': 'litellm_request'}
        doc['resourceSpans'][1]['scopeSpans'][0]['spans'].append(llm)
        report = helper.summarize_production_litellm(doc, trace_id, parent_id, inference=True)
        self.assertTrue(report['productionInferenceSuccessPathVerified'])
        self.assertFalse(report['productionLitellmHttpAuthRouterErrorPathVerified'])
        self.assertFalse(report['nativeVllmDescendantInSameTraceVerified'])
        vllm = {'resource': {'attributes': [{'key': 'service.name', 'value': {'stringValue': 'vllm'}}]},
                'scopeSpans': [{'spans': [{'traceId': trace_id, 'spanId': 'bb' * 8, 'parentSpanId': 'aa' * 8, 'name': 'llm_request'}]}]}
        doc['resourceSpans'].append(vllm)
        self.assertTrue(helper.summarize_production_litellm(doc, trace_id, parent_id, inference=True)['nativeVllmDescendantInSameTraceVerified'])

    def test_sensitive_marker_rejected_even_on_native_inference_path(self):
        doc, trace_id, parent_id = self.fixture()
        doc['resourceSpans'][1]['scopeSpans'][0]['spans'].append({'traceId': trace_id, 'spanId': 'aa' * 8, 'parentSpanId': parent_id, 'name': 'litellm_request'})
        doc['diagnostic'] = 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED'
        report = module().summarize_production_litellm(doc, trace_id, parent_id, inference=True)
        self.assertFalse(report['success'])
        self.assertTrue(report['sensitiveSyntheticContentFound'])

    def test_duplicate_ids_or_self_parenting_are_rejected(self):
        doc, trace_id, parent_id = self.fixture()
        child = doc['resourceSpans'][1]['scopeSpans'][0]['spans'][0]
        for change in [{'spanId': parent_id}, {'parentSpanId': child['spanId']}]:
            bad = copy.deepcopy(doc)
            bad['resourceSpans'][1]['scopeSpans'][0]['spans'][0].update(change)
            self.assertFalse(module().summarize_production_litellm(bad, trace_id, parent_id)['success'])
