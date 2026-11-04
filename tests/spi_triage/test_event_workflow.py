"""Offline contract tests: never contact n8n, Telegram, or the SPI worker."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = 'docs/n8n/spi/triage-workflow.json'
sys.path.insert(0, str(ROOT / 'scripts/n8n'))
spec = importlib.util.spec_from_file_location('spi_event_sync', ROOT / 'scripts/n8n/sync_spi.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class EventWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = json.loads((ROOT / RELATIVE).read_text())
        self.mapping = {'worker': {'id': 'existing-worker-id', 'name': 'SPI worker internal'}}

    def test_authenticated_immediate_webhook_and_linear_pipeline(self):
        w = self.workflow
        nodes = {n['name']: n for n in w['nodes']}
        self.assertFalse(any('schedule' in n['type'].lower() for n in w['nodes']))
        trigger = nodes['Dispatch Triage Job']
        self.assertEqual(trigger['id'], '9c393df1-a66f-41bf-acaf-b2b66f31a393')
        self.assertEqual(trigger['type'], 'n8n-nodes-base.webhook')
        self.assertEqual(trigger['parameters'], {
            'httpMethod': 'POST', 'path': 'spi-incident-triage-dispatch',
            'authentication': 'headerAuth', 'responseMode': 'onReceived', 'options': {}})
        chain = ['Dispatch Triage Job', 'Claim Triage Job', 'Select Claimed Job',
                 'Match Open SPI', 'Collect Evidence', 'Analyze Incident', 'Publish SPI']
        self.assertEqual(set(nodes), set(chain))
        self.assertEqual(set(w['connections']), set(chain[:-1]))
        for source, target in zip(chain, chain[1:]):
            self.assertEqual(w['connections'][source], {
                'main': [[{'node': target, 'type': 'main', 'index': 0}]]})
        self.assertEqual(nodes['Select Claimed Job']['parameters']['jsCode'],
                         'return items.filter(item => Boolean(item.json.job_id));')
        for name, endpoint in [('Claim Triage Job', 'claim'), ('Match Open SPI', 'match'),
                               ('Collect Evidence', 'collect'), ('Analyze Incident', 'analyze'),
                               ('Publish SPI', 'publish')]:
            node = nodes[name]
            p = node['parameters']
            self.assertEqual(p['url'], 'http://spi-triage.automation.svc:8080/' + endpoint)
            self.assertEqual(p['method'], 'POST')
            self.assertEqual(p['genericAuthType'], 'httpHeaderAuth')
            self.assertEqual(p['authentication'], 'genericCredentialType')
            self.assertEqual(p['options']['timeout'], 20000 if endpoint == 'claim' else 900000)
            self.assertEqual(p['jsonBody'], '={{ JSON.stringify({}) }}' if endpoint == 'claim'
                             else '={{ JSON.stringify({job_id: $json.job_id}) }}')
            self.assertEqual(node['credentials'], trigger['credentials'])
            self.assertFalse(node.get('retryOnFail', False))
        self.assertEqual(w['settings'], {'executionOrder': 'v1', 'timezone': 'Europe/Moscow',
                                        'executionTimeout': 3600, 'saveExecutionProgress': False,
                                        'saveDataSuccessExecution': 'none',
                                        'saveDataErrorExecution': 'none',
                                        'saveManualExecutions': False})

    def test_native_webhook_input_must_not_be_persisted(self):
        """Native Webhook includes authentication headers in transient output.

        Header authentication does not redact those headers. Disable all workflow
        execution persistence; this does not hide live editor/transient output.
        """
        settings = self.workflow['settings']
        for key in ('saveDataSuccessExecution', 'saveDataErrorExecution'):
            self.assertEqual(settings[key], 'none')
        for key in ('saveManualExecutions', 'saveExecutionProgress'):
            self.assertIs(settings[key], False)

    def test_render_reuses_worker_identity_without_mutating_template(self):
        original = copy.deepcopy(self.workflow)
        rendered = sync.render(self.workflow, self.mapping)
        for node in rendered['nodes']:
            if 'credentials' in node:
                self.assertEqual(node['credentials'], {'httpHeaderAuth': self.mapping['worker']})
        self.assertEqual(self.workflow, original)
        with self.assertRaisesRegex(RuntimeError, 'Missing private SPI credential mapping: worker'):
            sync.render(self.workflow, {})

    def run_sync(self, pages):
        with tempfile.TemporaryDirectory() as config:
            Path(config, 'spi-credentials.json').write_text(json.dumps(self.mapping))
            with patch.object(sync, 'CONFIG', Path(config)), patch.object(sync, 'api', side_effect=pages) as api:
                result = sync.sync(RELATIVE)
                return result, api.call_args_list

    def test_sync_updates_existing_id_on_later_page_without_activation(self):
        result, calls = self.run_sync([
            {'data': [], 'nextCursor': 'next/page'},
            {'data': [{'name': self.workflow['name'], 'id': 'original-id', 'active': False}]},
            {'id': 'original-id', 'name': self.workflow['name']},
        ])
        self.assertEqual(result['id'], 'original-id')
        self.assertEqual(calls[1].args, ('GET', 'workflows?limit=250&cursor=next%2Fpage'))
        method, path, body = calls[-1].args
        self.assertEqual((method, path), ('PUT', 'workflows/original-id'))
        self.assertEqual(set(body), {'name', 'nodes', 'connections', 'settings'})
        self.assertEqual(body['nodes'], sync.render(self.workflow, self.mapping)['nodes'])

    def test_sync_refuses_active_or_ambiguous_workflows_before_write(self):
        for entries in [
            [{'name': self.workflow['name'], 'id': 'original-id', 'active': True}],
            [{'name': self.workflow['name'], 'id': str(i), 'active': False} for i in range(2)],
        ]:
            with self.subTest(entries=entries), self.assertRaises(RuntimeError):
                self.run_sync([{'data': entries}])

    def test_sync_refuses_missing_original_without_write(self):
        with tempfile.TemporaryDirectory() as config:
            Path(config, 'spi-credentials.json').write_text(json.dumps(self.mapping))
            with patch.object(sync, 'CONFIG', Path(config)), patch.object(
                    sync, 'api', side_effect=[{'data': [], 'nextCursor': 'next'},
                                              {'data': []}]) as api:
                with self.assertRaisesRegex(RuntimeError, 'refusing creation'):
                    sync.sync(RELATIVE)
                self.assertEqual(api.call_count, 2)
                self.assertTrue(all(call.args[0] == 'GET' for call in api.call_args_list))

    def test_sync_refuses_duplicate_names_across_pages(self):
        entry = {'name': self.workflow['name'], 'id': 'original-id', 'active': False}
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous workflow name'):
            self.run_sync([{'data': [entry], 'nextCursor': 'next'}, {'data': [dict(entry, id='other')]}])


if __name__ == '__main__':
    unittest.main()
