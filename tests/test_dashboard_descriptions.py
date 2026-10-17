import importlib.util
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / 'ansible/files/dashboard_descriptions.py'
SPEC = importlib.util.spec_from_file_location('dashboard_descriptions', SOURCE)
DESCRIPTIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DESCRIPTIONS)


class DashboardDescriptionsTest(unittest.TestCase):
    def test_nested_panels_get_descriptions_without_changing_queries(self):
        target = {'expr': 'up{job="example"}'}
        dashboard = {'uid': 'example', 'panels': [
            {'id': 1, 'type': 'row', 'panels': [
                {'id': 2, 'type': 'timeseries', 'targets': [target]},
            ]},
            {'id': 3, 'type': 'text'},
        ]}
        DESCRIPTIONS.apply_descriptions(dashboard, {'example': {'2': 'Whether the service can be scraped.'}})
        panel = dashboard['panels'][0]['panels'][0]
        self.assertEqual(panel['description'], 'Whether the service can be scraped.')
        self.assertEqual(panel['targets'], [target])
        self.assertNotIn('description', dashboard['panels'][1])

    def test_new_panel_without_description_blocks_rendering(self):
        dashboard = {'uid': 'example', 'panels': [{'id': 2, 'type': 'stat'}]}
        with self.assertRaisesRegex(ValueError, 'example, panel 2'):
            DESCRIPTIONS.apply_descriptions(dashboard, {'example': {}})

    def test_known_unit_correction_keeps_other_display_settings(self):
        dashboard = {'uid': '6be0s85Mk', 'panels': [
            {'id': 4, 'type': 'timeseries', 'fieldConfig': {'defaults': {'unit': 'ms', 'min': 0}}},
        ]}
        DESCRIPTIONS.apply_descriptions(dashboard, {'6be0s85Mk': {'4': 'HTTP request duration in seconds.'}})
        self.assertEqual(dashboard['panels'][0]['fieldConfig']['defaults'], {'unit': 's', 'min': 0})


if __name__ == '__main__':
    unittest.main()
