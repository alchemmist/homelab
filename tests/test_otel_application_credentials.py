import importlib.util
import base64
import copy
import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ApplicationCredentialTests(unittest.TestCase):
    def test_cross_namespace_or_ca_key_mirror_is_rejected(self):
        module = load('otel-application-credentials')
        good = {'application': 'litellm', 'namespace': 'llm', 'secret': 'otel-app-tls-litellm'}
        module.validate_destination(good)
        for field, value in [('namespace', 'cattle-monitoring-system'), ('secret', 'otel-root-ca'), ('application', 'unknown')]:
            bad = {**good, field: value}
            with self.assertRaises(ValueError):
                module.validate_destination(bad)

    def test_unrelated_workload_cannot_be_reloaded(self):
        module = load('otel-application-credentials')
        with self.assertRaises(ValueError):
            module.validate_destination({'application': 'litellm', 'namespace': 'llm', 'secret': 'otel-app-tls-litellm', 'reloadDeployments': ['vllm']})

    def test_rendered_mirror_code_matches_maintained_source(self):
        resources = list(yaml.safe_load_all((ROOT / 'deploy/monitoring/otel-application-credentials.yaml').read_text()))
        config = next(resource for resource in resources if resource['kind'] == 'ConfigMap')
        self.assertEqual(config['data']['mirror.py'], (ROOT / 'scripts/otel-application-credentials.py').read_text())
        for destination in json.loads(config['data']['destinations.json']):
            self.assertEqual(destination['reloadDeployments'], [])
        for role in (resource for resource in resources if resource['kind'] == 'Role'):
            for rule in role['rules']:
                self.assertEqual(rule['resources'], ['secrets'])
                self.assertEqual(set(rule['verbs']), {'get', 'patch'})
                self.assertTrue(rule['resourceNames'])
                self.assertTrue(all(name.startswith('otel-app-tls-') for name in rule['resourceNames']))

    def test_native_ingress_has_no_second_sampler_or_other_signal_owner(self):
        config = yaml.safe_load((ROOT / 'deploy/monitoring/otel/application-ingress.yaml').read_text())
        self.assertEqual(set(config['service']['pipelines']), {'traces'})
        self.assertNotIn('tail_sampling', config['processors'])
        self.assertEqual(config['exporters']['otlp/global-sampler']['endpoint'], '10.250.0.1:44317')
        self.assertEqual(config['exporters']['otlp/global-sampler']['sending_queue']['queue_size'], 64 * 1024**2)
        protocol = config['receivers']['otlp']['protocols']
        self.assertEqual(set(protocol), {'http'})
        self.assertEqual(protocol['http']['endpoint'], '10.250.0.3:44318')
        self.assertIn('client_ca_file', protocol['http']['tls'])
        self.assertNotIn('insecure', str(config).lower())

    def test_privacy_is_identical_and_runs_before_persistent_export_queue(self):
        config = yaml.safe_load((ROOT / 'deploy/monitoring/otel/application-ingress.yaml').read_text())
        gateway = yaml.safe_load((ROOT / 'deploy/monitoring/otel/trace-gateway.yaml').read_text())
        self.assertEqual(config['processors']['transform/privacy'], gateway['processors']['transform/privacy'])
        self.assertEqual(config['service']['pipelines']['traces']['processors'], ['memory_limiter', 'transform/privacy', 'batch'])

    def test_backend_sdk_proof_requires_child_and_negative_content_test(self):
        module = load('otel-application-trace-verify')
        trace_id = 'ab' * 16
        parent_id = 'cd' * 8
        document = {'resourceSpans': [{'resource': {'attributes': [{'key': 'service.name', 'value': {'stringValue': 'homelab-litellm-sdk-canary'}}]},
                    'scopeSpans': [{'spans': [{'traceId': trace_id, 'spanId': parent_id, 'name': 'homelab.synthetic.litellm-sdk-validation'},
                    {'traceId': trace_id, 'spanId': 'ef' * 8, 'parentSpanId': parent_id, 'name': 'litellm_request'}]}]}]}
        proof = module.summarize(document, trace_id, parent_id)
        self.assertTrue(proof['success'])
        self.assertFalse(proof['productionApplicationSdkCoverageVerified'])
        bad = copy.deepcopy(document)
        bad['resourceSpans'][0]['scopeSpans'][0]['spans'][1]['prompt'] = 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED'
        self.assertFalse(module.summarize(bad, trace_id, parent_id)['success'])
        no_child = copy.deepcopy(document)
        no_child['resourceSpans'][0]['scopeSpans'][0]['spans'].pop()
        self.assertFalse(module.summarize(no_child, trace_id, parent_id)['success'])
        for span in document['resourceSpans'][0]['scopeSpans'][0]['spans']:
            for key in ['traceId', 'spanId', 'parentSpanId']:
                if key in span:
                    span[key] = base64.b64encode(bytes.fromhex(span[key])).decode()
        self.assertTrue(module.summarize(document, trace_id, parent_id)['success'])
