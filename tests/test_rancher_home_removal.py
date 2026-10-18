import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTION_SPEC = importlib.util.spec_from_file_location('dashboard_descriptions', ROOT / 'ansible/files/dashboard_descriptions.py')
DESCRIPTIONS = importlib.util.module_from_spec(DESCRIPTION_SPEC)
DESCRIPTION_SPEC.loader.exec_module(DESCRIPTIONS)
SPEC = importlib.util.spec_from_file_location('rancher_renderer', ROOT / 'ansible/roles/monitoring_rancher/files/name_node_series.py')
RENDERER = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {'dashboard_descriptions': DESCRIPTIONS}):
    SPEC.loader.exec_module(RENDERER)


class RancherHomeRemovalTest(unittest.TestCase):
    def render(self, resources):
        output = io.StringIO()
        with patch.object(RENDERER, 'RANCHER_DASHBOARD_UIDS', set()), \
                patch.object(RENDERER, 'apply_descriptions') as describe, \
                patch.object(sys, 'stdin', io.StringIO(yaml.safe_dump_all(resources))), \
                patch.object(sys, 'stdout', output):
            RENDERER.main()
        return list(yaml.safe_load_all(output.getvalue())), describe

    def home(self):
        return {'kind': 'ConfigMap', 'metadata': {'name': 'home'}, 'data': {
            'home.json': json.dumps({'uid': 'rancher-home-1', 'title': 'Home'}),
        }}

    def test_drops_home_only_configmap_without_loading_its_descriptions(self):
        resource = {'kind': 'Service', 'metadata': {'name': 'preserved'}}
        rendered, describe = self.render([self.home(), resource])
        self.assertEqual(rendered, [resource])
        describe.assert_not_called()
        self.assertNotIn('rancher-home-1', RENDERER.RANCHER_DASHBOARD_UIDS)

    def test_preserves_other_dashboard_in_shared_configmap(self):
        resource = self.home()
        dashboard = {'uid': 'diagnostic', 'title': 'Diagnostic', 'panels': []}
        resource['data']['diagnostic.json'] = json.dumps(dashboard)
        rendered, describe = self.render([resource])
        self.assertEqual(len(rendered), 1)
        self.assertEqual(set(rendered[0]['data']), {'diagnostic.json'})
        self.assertEqual(json.loads(rendered[0]['data']['diagnostic.json']), dashboard)
        self.assertEqual(rendered[0]['metadata']['annotations']['grafana_folder'], '/tmp/dashboards/Kubernetes Diagnostics')
        describe.assert_called_once_with(dashboard)

    def test_preserves_unrelated_data_and_binary_data(self):
        for field, data in [('data', {'settings.txt': 'keep'}), ('binaryData', {'payload': 'a2VlcA=='})]:
            with self.subTest(field=field):
                resource = self.home()
                resource.setdefault(field, {}).update(data)
                rendered, describe = self.render([resource])
                self.assertEqual(len(rendered), 1)
                self.assertEqual(rendered[0][field], data)
                self.assertNotIn('home.json', rendered[0]['data'])
                describe.assert_not_called()

    def test_missing_required_dashboard_still_blocks_rendering(self):
        with patch.object(RENDERER, 'RANCHER_DASHBOARD_UIDS', {'required'}), \
                patch.object(sys, 'stdin', io.StringIO(yaml.safe_dump(self.home()))), \
                patch.object(sys, 'stdout', io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'missing Rancher dashboards: required'):
                RENDERER.main()


if __name__ == '__main__':
    unittest.main()
