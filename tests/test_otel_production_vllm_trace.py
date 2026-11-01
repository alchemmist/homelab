import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TRACE = '1' * 32
PARENT = '2' * 16


def module():
    spec = importlib.util.spec_from_file_location('trace_verify', ROOT / 'scripts/otel-application-trace-verify.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def document():
    def resource(service, span):
        return {'resource': {'attributes': [{'key': 'service.name', 'value': {'stringValue': service}}]}, 'scopeSpans': [{'spans': [span]}]}
    return {'resourceSpans': [resource('homelab-live-vllm-probe', {'traceId': TRACE, 'spanId': PARENT, 'name': 'homelab.synthetic.production-vllm-request'}),
                             resource('vllm', {'traceId': TRACE, 'spanId': '3' * 16, 'parentSpanId': PARENT, 'name': 'llm_request'})]}


class VllmProductionTraceTests(unittest.TestCase):
    def test_real_application_resource_and_parent_are_required(self):
        self.assertTrue(module().summarize_production_vllm(document(), TRACE, PARENT)['success'])
        for kind in ['service', 'parent', 'name', 'duplicate']:
            data = document()
            child = data['resourceSpans'][1]['scopeSpans'][0]['spans'][0]
            if kind == 'service':data['resourceSpans'][1]['resource']['attributes'][0]['value']['stringValue'] = 'traefik'
            if kind == 'parent':child['parentSpanId'] = '4' * 16
            if kind == 'name':child['name'] = 'ingress'
            if kind == 'duplicate':data['resourceSpans'].append(copy.deepcopy(data['resourceSpans'][1]))
            self.assertFalse(module().summarize_production_vllm(data, TRACE, PARENT)['success'])

    def test_synthetic_prompt_in_backend_fails_privacy(self):
        data = document()
        data['private'] = 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED'
        result = module().summarize_production_vllm(data, TRACE, PARENT)
        self.assertFalse(result['success'])
        self.assertTrue(result['syntheticPromptFoundInBackend'])
