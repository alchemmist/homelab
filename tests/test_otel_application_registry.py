import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('application_registry', Path(__file__).resolve().parents[1] / 'scripts/otel-application-registry.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)


class ApplicationRegistryTests(unittest.TestCase):
    def deployment(self):
        return {'kind': 'Deployment', 'metadata': {'name': 'app', 'namespace': 'apps'}, 'spec': {'template': {'metadata': {'annotations': {}}, 'spec': {'containers': [{'name': 'app', 'image': 'upstream:v1', 'env': [{'name': 'OTEL_EXPORTER_OTLP_HEADERS', 'value': 'never-save-credential'}, {'name': 'PASSWORD', 'value': 'never-save-password'}], 'args': ['--tracing.endpoint=never-save-endpoint']} ]}}}}

    def test_no_environment_or_argument_values_saved(self):
        report = registry.summarize([self.deployment()])
        text = json.dumps(report)
        self.assertNotIn('never-save-', text)
        source = report['sources'][0]
        self.assertTrue(source['configurationHintPresent'])
        self.assertFalse(source['internalSdkTraceDeliveryVerified'])
        self.assertFalse(report['internalSdkCoverageComplete'])

    def test_enable_otel_switch_is_only_a_hint_even_when_value_false(self):
        obj = self.deployment()
        obj['spec']['template']['spec']['containers'][0]['env'] = [{'name': 'ENABLE_OTEL_TRACES', 'value': 'False'}]
        report = registry.summarize([obj])
        self.assertIn('ENABLE_OTEL_TRACES', report['sources'][0]['tracingEnvironmentNames'])
        self.assertFalse(report['sources'][0]['internalSdkTraceDeliveryVerified'])

    def test_owned_job_not_double_counted_but_standalone_job_included(self):
        obj = self.deployment()
        job = {'kind': 'Job', 'metadata': {'namespace': 'apps', 'name': 'once'}, 'spec': {'template': obj['spec']['template']}}
        self.assertEqual(registry.summarize([job])['sourceCount'], 1)
        job['metadata']['ownerReferences'] = [{'kind': 'CronJob', 'name': 'timer'}]
        self.assertEqual(registry.summarize([job])['sourceCount'], 0)

    def test_managed_pod_image_digest_retained_without_template_double_count(self):
        pod = {'kind': 'Pod', 'metadata': {'namespace': 'apps', 'name': 'app-123', 'ownerReferences': [{'kind': 'ReplicaSet'}]}, 'spec': {}, 'status': {'phase': 'Running', 'containerStatuses': [{'name': 'app', 'imageID': 'upstream@sha256:abc', 'ready': True}]}}
        report = registry.summarize([self.deployment(), pod])
        self.assertEqual(report['sourceCount'], 1)
        self.assertEqual(report['podIncarnations'][0]['imageID'], 'upstream@sha256:abc')
        self.assertFalse(report['podIncarnations'][0]['deliveryVerified'])
