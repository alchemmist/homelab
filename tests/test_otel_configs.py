from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1] / 'deploy/monitoring/otel'


def config(name):
    return yaml.safe_load((ROOT / (name + '.yaml')).read_text())


class ObservabilityConfigTests(unittest.TestCase):
    def test_persistent_queues_have_byte_not_request_limits(self):
        for name, limit in [('agent', 128 * 2**20), ('cluster', 256 * 2**20), ('trace-gateway', 256 * 2**20)]:
            document = config(name)
            self.assertTrue(document['extensions']['file_storage']['fsync'])
            for exporter in document['exporters'].values():
                queue = exporter['sending_queue']
                self.assertEqual(queue['sizer'], 'bytes')
                self.assertEqual(queue['queue_size'], limit)
                self.assertEqual(queue['storage'], 'file_storage')

    def test_new_file_startup_records_and_historical_cut_are_separate(self):
        self.assertEqual(config('agent')['receivers']['filelog']['start_at'], 'beginning')
        for name in ['agent', 'cluster']:
            document = config(name)
            processors = document['service']['pipelines']['logs']['processors']
            self.assertLess(processors.index('filter/log-ingestion-cut'), len(processors) - 1)
            condition = document['processors']['filter/log-ingestion-cut']['logs']['log_record'][0]
            self.assertIn('time_unix_nano == 0', condition)
            self.assertIn('${env:OTEL_LOG_INGESTION_START_NS}', condition)

    def test_public_otlp_cannot_be_enabled_without_client_authentication(self):
        for name in ['cluster', 'trace-gateway']:
            for protocol in config(name)['receivers']['otlp']['protocols'].values():
                self.assertIn('${env:OTEL_BIND_IP}', protocol['endpoint'])
                self.assertTrue({'cert_file', 'key_file', 'client_ca_file'} <= set(protocol['tls']))
                self.assertTrue(set(protocol['tls']) <= {'cert_file', 'key_file', 'client_ca_file', 'reload_interval'})
                if 'reload_interval' in protocol['tls']:
                    self.assertEqual(protocol['tls']['reload_interval'], '1m')

    def test_retention_is_not_shortened(self):
        self.assertEqual(config('loki')['limits_config']['retention_period'], '336h')
        self.assertTrue(config('loki')['compactor']['retention_enabled'])
        self.assertEqual(config('tempo')['compactor']['compaction']['block_retention'], '168h')
        for name in ['loki', 'tempo']:
            self.assertEqual(config(name)['server']['http_tls_config']['client_auth_type'], 'RequireAndVerifyClientCert')

    def test_sampling_contract_includes_both_http_conventions(self):
        sampling = config('trace-gateway')['processors']['tail_sampling']
        self.assertEqual(sampling['decision_wait'], '30s')
        policies = {entry['name']: entry for entry in sampling['policies']}
        self.assertEqual(policies['errors']['status_code']['status_codes'], ['ERROR'])
        self.assertEqual(policies['slow']['latency']['threshold_ms'], 2000)
        self.assertEqual(policies['other']['probabilistic']['sampling_percentage'], 10)
        for name, key in [('http-5xx', 'http.response.status_code'), ('legacy-http-5xx', 'http.status_code')]:
            self.assertEqual(policies[name]['numeric_attribute'], {'key': key, 'min_value': 500, 'max_value': 599})
