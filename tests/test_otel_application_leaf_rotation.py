import base64
import copy
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location('leaf_rotation', ROOT / 'scripts/otel-application-leaf-rotation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LeafRotationTests(unittest.TestCase):
    def certificate(self):
        return {'metadata': {'name': 'otel-app-tls-litellm', 'namespace': 'cattle-monitoring-system', 'generation': 1},
                'spec': {'duration': '2160h'}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}

    def test_native_manual_renewal_preserves_existing_conditions_and_spec(self):
        module = load()
        before = self.certificate()
        untouched = copy.deepcopy(before)
        conditions = module.renewal_conditions(before)
        self.assertEqual(before, untouched)
        self.assertEqual(conditions[0], before['status']['conditions'][0])
        self.assertEqual(conditions[1]['type'], 'Issuing')
        self.assertEqual(conditions[1]['reason'], 'ManuallyTriggered')
        self.assertEqual(conditions[1]['observedGeneration'], 1)

    def test_wrong_identity_unready_and_overlapping_issuance_are_rejected(self):
        module = load()
        for kind in ['wrong-name', 'wrong-namespace', 'unready', 'already-issuing']:
            cert = self.certificate()
            if kind == 'wrong-name':cert['metadata']['name'] = 'otel-root-ca'
            if kind == 'wrong-namespace':cert['metadata']['namespace'] = 'llm'
            if kind == 'unready':cert['status']['conditions'][0]['status'] = 'False'
            if kind == 'already-issuing':cert['status']['conditions'].append({'type':'Issuing','status':'True'})
            with self.assertRaises(ValueError):module.renewal_conditions(cert)

    def test_inspection_selects_only_public_pem_not_private_key(self):
        module = load()
        calls = []
        def kube(*args):
            calls.append(args)
            return {'certificatePemBase64': base64.b64encode(b'-----BEGIN CERTIFICATE-----\nsynthetic\n-----END CERTIFICATE-----').decode()}
        response = subprocess.CompletedProcess([], 0, b'-----BEGIN PUBLIC KEY-----\nsynthetic\n-----END PUBLIC KEY-----', b'')
        with patch.object(module.subprocess, 'run', return_value=response):
            identity = module.public_certificate_identity(kube, 'llm')
        self.assertEqual(len(identity['publicKeySHA256']), 64)
        self.assertIn('tls.crt', calls[0][-1])
        self.assertNotIn('tls.key', calls[0][-1])
        self.assertTrue(calls[0][-1].startswith('go-template='))

    def test_explicit_vllm_identity_and_default_litellm_are_separate(self):
        module = load()
        cert = self.certificate()
        cert['metadata']['name'] = 'otel-app-tls-vllm'
        self.assertEqual(module.renewal_conditions(cert, 'vllm')[-1]['type'], 'Issuing')
        with self.assertRaises(ValueError):module.renewal_conditions(cert)
        with self.assertRaises(ValueError):module.leaf_name('otel-root-ca')
        self.assertEqual(module.leaf_name('litellm'), 'otel-app-tls-litellm')

    def test_private_key_is_never_accepted_as_public_certificate(self):
        module = load()
        with self.assertRaises(ValueError):
            module.public_certificate_identity(lambda *args: {'certificatePemBase64': base64.b64encode(b'-----BEGIN PRIVATE KEY-----').decode()}, 'llm')
