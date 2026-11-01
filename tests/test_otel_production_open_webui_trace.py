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
    return {'resourceSpans': [resource('homelab-live-open-webui-probe', {'traceId': TRACE, 'spanId': PARENT, 'name': 'homelab.synthetic.production-open-webui-request'}),
                             resource('open-webui', {'traceId': TRACE, 'spanId': '3' * 16, 'parentSpanId': PARENT, 'name': 'GET /api/version', 'kind': 'SPAN_KIND_SERVER'})]}


class OpenWebuiProductionTraceTests(unittest.TestCase):
    def test_real_application_server_resource_and_parent_are_required(self):
        result = module().summarize_production_open_webui(document(), TRACE, PARENT)
        self.assertTrue(result['success'])
        self.assertFalse(result['productionOpenWebuiInferencePathVerified'])
        self.assertFalse(result['allApplicationSdkCoverageComplete'])
        for kind in ['service', 'parent', 'name', 'duplicate', 'kind', 'missing-kind']:
            data = document()
            child = data['resourceSpans'][1]['scopeSpans'][0]['spans'][0]
            if kind == 'service':data['resourceSpans'][1]['resource']['attributes'][0]['value']['stringValue'] = 'traefik'
            if kind == 'parent':child['parentSpanId'] = '4' * 16
            if kind == 'name':child['name'] = 'ingress'
            if kind == 'duplicate':data['resourceSpans'].append(copy.deepcopy(data['resourceSpans'][1]))
            if kind == 'kind':child['kind'] = 'SPAN_KIND_INTERNAL'
            if kind == 'missing-kind':child.pop('kind')
            self.assertFalse(module().summarize_production_open_webui(data, TRACE, PARENT)['success'])
