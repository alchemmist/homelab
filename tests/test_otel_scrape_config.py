import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('scrape_config', ROOT / 'scripts/otel-scrape-config.py')
SCRAPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRAPE)


def fixtures():
    cluster = {'job_name': 'serviceMonitor/llm/vllm/0', 'scrape_interval': '30s',
               'kubernetes_sd_configs': [{'role': 'pod'}],
               'relabel_configs': [{'source_labels': ['app'], 'regex': '(vllm)$', 'replacement': '$1', 'target_label': 'job'}],
               'metric_relabel_configs': [{'source_labels': ['__name__'], 'regex': 'junk.*', 'action': 'drop'}]}
    node = {'job_name': 'serviceMonitor/monitoring/nodes/0', 'kubernetes_sd_configs': [{'role': 'endpoints'}],
            'relabel_configs': [{'target_label': 'job', 'replacement': 'node-exporter'}]}
    source = {'global': {'external_labels': {'prometheus': 'legacy-context'}, 'evaluation_interval': '30s'},
              'scrape_configs': [cluster, node, {'job_name': 'empty-pool'}]}
    active = [{'scrapePool': cluster['job_name'], 'health': 'up', 'labels': {'job': 'vllm', 'instance': 'vllm:8000'}}]
    for index, name in enumerate(SCRAPE.NODES):
        active.append({'scrapePool': node['job_name'], 'health': 'up',
                       'labels': {'job': 'node-exporter', 'instance': name + ':9100', 'pod': 'legacy-' + str(index)},
                       'discoveredLabels': {'__meta_kubernetes_pod_node_name': name}})
    return source, {'activeTargets': active}


class ScrapeConfigTests(unittest.TestCase):
    def test_public_edge_refresh_is_narrow_and_preserves_original(self):
        job = {'job_name': 'serviceMonitor/cattle-monitoring-system/monitoring-service-probes/26',
               'params': {'module': ['tcp_connect'], 'target': ['192.0.2.1:443']},
               'relabel_configs': [{'target_label': 'service_id', 'replacement': 'edge-vps'}]}
        other = {'job_name': 'unrelated', 'params': {'target': ['192.0.2.1:443']}}
        original = {'scrape_configs': [job, other]}
        before = copy.deepcopy(original)
        result = SCRAPE.refresh_public_edge_probe(original)
        self.assertEqual(original, before)
        self.assertEqual(result['scrape_configs'][0]['params']['target'], ['109.120.141.60:443'])
        self.assertEqual(result['scrape_configs'][1], other)
        self.assertEqual(SCRAPE.refresh_public_edge_probe(result), result)


    def test_ownership_discovery_labels_and_relabeling_are_preserved(self):
        source, targets = fixtures()
        before = copy.deepcopy(source)
        outputs, contract = SCRAPE.compile_config(source, targets)
        cluster = outputs['cluster']['scrape_configs'][0]
        self.assertEqual(cluster['kubernetes_sd_configs'], before['scrape_configs'][0]['kubernetes_sd_configs'])
        self.assertEqual(cluster['metric_relabel_configs'], before['scrape_configs'][0]['metric_relabel_configs'])
        self.assertEqual(cluster['relabel_configs'][0]['replacement'], '$$1')
        self.assertEqual(cluster['relabel_configs'][0]['regex'], '(vllm)$$')
        self.assertEqual(cluster['scrape_interval'], '5s')
        self.assertEqual(cluster['scrape_timeout'], '4s')
        self.assertNotIn('external_labels', outputs['cluster']['global'])
        self.assertEqual(source, before)
        for index, node in enumerate(SCRAPE.NODES):
            job = outputs[node]['scrape_configs'][0]
            self.assertNotIn('kubernetes_sd_configs', job)
            self.assertNotIn('relabel_configs', job)
            self.assertEqual(job['static_configs'][0]['targets'], ['127.0.0.1:19100'])
            self.assertEqual(job['static_configs'][0]['labels'], targets['activeTargets'][index + 1]['labels'])
        self.assertEqual(contract['excludedEmptyPools'], ['empty-pool'])
        self.assertTrue(contract['legacyTargetIdentityAliasesRequireAcceptance'])
        self.assertFalse(contract['readyForCutover'])

    def test_secret_selector_becomes_a_file_not_a_masked_credential(self):
        source, targets = fixtures()
        source['scrape_configs'][0]['authorization'] = {'type': 'Bearer', 'credentials': '<secret>'}
        monitors = {'serviceMonitor/llm/vllm': {'metadata': {'namespace': 'llm'}, 'spec': {
            'endpoints': [{'authorization': {'credentials': {'name': 'metrics-auth', 'key': 'api-key'}, 'type': 'Bearer'}}]}}}
        outputs, contract = SCRAPE.compile_config(source, targets, monitors)
        authorization = outputs['cluster']['scrape_configs'][0]['authorization']
        self.assertEqual(authorization, {'type': 'Bearer', 'credentials_file': '/etc/otel/source-auth/llm/metrics-auth/api-key'})
        self.assertNotIn('<secret>', json.dumps(outputs))
        self.assertEqual(contract['requiredSecretKeys'][0]['secret'], 'metrics-auth')
        self.assertFalse(contract['secretAssetSynchronizationRuntimeVerified'])

    def test_unattributed_inline_secret_is_rejected(self):
        source, targets = fixtures()
        source['scrape_configs'][0]['authorization'] = {'credentials': '<secret>'}
        with self.assertRaisesRegex(ValueError, 'monitor'):
            SCRAPE.compile_config(source, targets)

    def test_unknown_owner_and_missing_node_fail_closed(self):
        for mutate in ['owner', 'node']:
            source, targets = fixtures()
            if mutate == 'owner':
                targets['activeTargets'][0]['labels']['job'] = 'unregistered'
            else:
                targets['activeTargets'].pop()
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                SCRAPE.compile_config(source, targets)

    def test_validation_assets_are_inert_and_do_not_mutate_the_real_config(self):
        document = {'authorization': {'credentials_file': '/etc/otel/source-auth/ns/name/token'},
                    'tls_config': {'ca_file': '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'},
                    'replacement': '$$1'}
        before = copy.deepcopy(document)
        result = SCRAPE.validation_config(document)
        self.assertEqual(result['authorization']['credentials_file'], '${env:OTEL_VALIDATION_ASSET_DIR}/token')
        self.assertEqual(result['tls_config']['ca_file'], '${env:OTEL_TLS_DIR}/ca.crt')
        self.assertEqual(result['replacement'], '$$1')
        self.assertEqual(document, before)

    def test_unsafe_file_dependency_is_rejected(self):
        with self.assertRaises(ValueError):
            SCRAPE.assets({'credentials_file': '/etc/otel/source-auth/../outside'})
        with self.assertRaises(ValueError):
            SCRAPE.assets({'credentials_file': '/etc/shadow'})
