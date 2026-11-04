import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scrape', ROOT / 'scripts/otel-scrape-config.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class LokiNativeScrapeTests(unittest.TestCase):
    def test_additive_idempotent_verified_mtls(self):
        original = {'scrape_configs': [{'job_name': 'existing', 'static_configs': []}]}
        before = copy.deepcopy(original)
        result = m.add_logging_self_monitoring(original)
        self.assertEqual(original, before)
        self.assertEqual(result['scrape_configs'][:-1], before['scrape_configs'])
        self.assertEqual(m.add_logging_self_monitoring(result), result)
        job = result['scrape_configs'][-1]
        self.assertEqual((job['scrape_interval'], job['scrape_timeout']), ('5s', '4s'))
        self.assertEqual(job['scheme'], 'https')
        self.assertFalse(job['tls_config']['insecure_skip_verify'])
        self.assertEqual(job['tls_config']['server_name'], 'otel-loki.cattle-monitoring-system.svc')
        self.assertEqual(job['static_configs'][0]['labels']['scrape_owner'], 'otel-cluster')
        self.assertEqual(job['tls_config']['cert_file'], '/etc/otel/tls/client.crt')
        self.assertEqual(job['tls_config']['key_file'], '/etc/otel/tls/client.key')

    def test_conflict_fails_closed(self):
        with self.assertRaises(ValueError):
            m.add_logging_self_monitoring({'scrape_configs': [{'job_name': 'otel-logging/loki'}]})


if __name__ == '__main__':
    unittest.main()
