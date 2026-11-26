"""Offline model-only projection: originals/references/budgets never rewritten."""
import copy
import unittest
from unittest.mock import Mock
from analysis_context import project_metric_series, compact_analysis_context
from core import digest, Failure
from integrations import Model
import test_triage as fixture


def context():
    return {'alert': fixture.event(), 'preliminary_match': {'candidates': [{'number': 16, 'body': 'Existing report.'}]},
            'evidence': {'queries': [{'source': 'prometheus_metrics', 'path': '/api/datasources/proxy/uid/prometheus/api/v1/query_range',
             'parameters': {'query': 'fixture_metric'}, 'result': {'format': 'observed_metric_summary_v1',
              'series': [{'labels': {'id': 'unit-'+str(i), 'node': 'fixture-node'}, 'first': {'time': 1, 'value': i},
                          'last': {'time': 2, 'value': i}, 'minimum': i, 'maximum': i, 'sample_count': 2} for i in range(100)],
              'truncated_series': 7, 'limitation': 'No matching series or zero values do not establish service health.'}}],
             'artifact_context': {'index': [{'id': 'E001', 'path': 'metrics.json'}, {'id': 'E002', 'path': 'logs.json'}]},
             'missing': ['No trace collected.']}}


class AnalysisContextProjectionTests(unittest.TestCase):
    def test_complete_snapshot_and_all_references_untouched(self):
        data = context(); original = copy.deepcopy(data); out = project_metric_series(data, 16)
        self.assertEqual(data, original)
        self.assertEqual(out['preliminary_match'], original['preliminary_match'])
        self.assertEqual(out['evidence']['artifact_context'], original['evidence']['artifact_context'])
        self.assertEqual(out['evidence']['missing'], original['evidence']['missing'])
        query = out['evidence']['queries'][0]; before = original['evidence']['queries'][0]
        self.assertEqual(query['path'], before['path']); self.assertEqual(query['parameters'], before['parameters'])
        result = query['result']; meta = result['model_series_projection']
        self.assertEqual(result['series'], before['result']['series'][:16])
        self.assertEqual((meta['original_series_count'], meta['selected_series_count'], meta['omitted_series_count']), (100, 16, 84))
        self.assertEqual(meta['original_series_sha256'], digest(before['result']['series']))
        self.assertEqual(result['truncated_series'], 7)
        self.assertIn('not reviewed', meta['limitation']); self.assertIn('not relevance ranking', meta['selection'])

    def test_unknown_result_and_source_not_projected(self):
        for result in [[], None, {}, {'format': 'other', 'series': list(range(100))}]:
            data = context(); data['evidence']['queries'][0]['result'] = result
            self.assertIs(project_metric_series(data, 1), data)
        data = context(); data['evidence']['queries'][0]['source'] = 'loki_logs'
        self.assertIs(project_metric_series(data, 1), data)

    def test_no_bundle_and_small_query_no_change(self):
        data = context(); del data['evidence']['artifact_context']; self.assertIs(project_metric_series(data, 1), data)
        data = context(); data['evidence']['queries'][0]['result']['series'] = []
        self.assertIs(project_metric_series(data, 1), data)
        for limit in [0, 17, True, 1.5]:
            with self.assertRaises(ValueError): project_metric_series(context(), limit)

    def test_adaptive_projection_uses_complete_budget_and_calls_model_only_once(self):
        data = context(); model = Model(Mock(), 'unused'); captured = []
        for row in data['evidence']['queries'][0]['result']['series']:
            # Small scalar fields/cardinality, not one huge excerptable string.
            row['labels'].update({f'label_{i}': 'fixture-value-'+str(i)*4 for i in range(15)})
        evidence = copy.deepcopy(data['evidence']); artifact = evidence.pop('artifact_context')
        evidence['bundle'] = {'model_context': artifact}
        original = copy.deepcopy((data['alert'], data['preliminary_match'], evidence))
        class Captured(Exception): pass
        def call(task, projected, schema, deadline):
            captured.append(projected)
            self.assertLessEqual(model.budget_reservation(model.payload(task, projected, schema)), 30000)
            self.assertEqual(projected['evidence']['queries'][0]['result']['compaction']['omitted_series_count'], 0)
            self.assertEqual(len(projected['evidence']['queries'][0]['result']['series']), 100)
            raise Captured()
        model.call = call
        with self.assertRaises(Captured): model.analyze(data['alert'], data['preliminary_match'], evidence)
        self.assertEqual(len(captured), 1); self.assertEqual(original, (data['alert'], data['preliminary_match'], evidence))
        model.http.request.assert_not_called()

    def test_irreducible_protected_metadata_stays_fatal_without_paid_request(self):
        data = context(); data['alert']['path'] = ['x'*120000]*5
        evidence = data['evidence']; artifact = evidence.pop('artifact_context'); evidence['bundle'] = {'model_context': artifact}
        model = Model(Mock(), 'unused')
        with self.assertRaises(Failure) as caught: model.analyze(data['alert'], data['preliminary_match'], evidence)
        self.assertEqual(caught.exception.code, 'LLM_CONTEXT_METADATA_TOO_LARGE'); model.http.request.assert_not_called()

class CompactionPipelineTests(unittest.TestCase):
    def test_roundtrip_every_row_label_time_extremum_and_null(self):
        data = context(); rows = data['evidence']['queries'][0]['result']['series']
        rows[0]['labels']['optional'] = ''; rows[1]['labels']['another'] = 'value'
        for i, row in enumerate(rows): row['labels']['pool'] = ('pool-a-' if i%2 else 'pool-b-') * 12
        rows[2]['first'] = None
        before = copy.deepcopy(data); out = compact_analysis_context(data, dictionary=True)
        q = out['evidence']['queries'][0]; table = q['result']; decoded = []
        self.assertIn('label_values', table)
        for values in table['series']:
            row = dict(zip(table['columns'], values))
            row['labels'] = {**table['common_labels'], **{k:(table['label_values'][v] if 'label_values' in table else v) for k,v in zip(table['label_columns'],row['labels']) if v is not None}}
            for k, t in table['shared_times'].items(): row[k] = {'time':t,'value':row[k]}
            decoded.append(row)
        self.assertEqual(decoded, rows); self.assertEqual(data, before)
        self.assertEqual(table['compaction']['source_summary_sha256'], digest(rows))
        self.assertEqual(table['truncated_series'], 7)
        self.assertEqual(out['evidence']['artifact_context'], before['evidence']['artifact_context'])
        self.assertEqual(q['path'], before['evidence']['queries'][0]['path'])
        self.assertEqual(q['parameters'], before['evidence']['queries'][0]['parameters'])

    def test_unknown_row_field_or_source_is_not_silently_dropped(self):
        data = context(); data['evidence']['queries'][0]['result']['series'][0]['unknown'] = 'important'
        self.assertEqual(compact_analysis_context(data), data)
        data = context(); data['evidence']['queries'][0]['source'] = 'loki_logs'
        self.assertEqual(compact_analysis_context(data), data)

    def test_peak_on_last_series_survives_no_prefix_or_health_claim(self):
        data = context(); rows = data['evidence']['queries'][0]['result']['series']; rows[-1]['maximum']=9999
        table = compact_analysis_context(data)['evidence']['queries'][0]['result']
        self.assertEqual(table['series'][-1][table['columns'].index('maximum')],9999)
        self.assertEqual(table['compaction']['omitted_series_count'],0)
        self.assertIn('do not establish health',table['compaction']['limitation'])

    def test_sensitive_label_keys_keep_keyed_structure_for_payload_redaction(self):
        data=context(); rows=data['evidence']['queries'][0]['result']['series']
        for row in rows: row['labels']['password']='not-a-real-secret-fixture'
        out=compact_analysis_context(data)
        self.assertEqual(out,data)
        body=Model(Mock(),'unused').payload('fixture',out,__import__('core').REPORT_SCHEMA)
        self.assertNotIn('not-a-real-secret-fixture',__import__('json').dumps(body))

    def test_long_table_identity_is_not_silently_excerpted(self):
        data=context(); rows=data['evidence']['queries'][0]['result']['series']
        for row in rows: row['labels']['id']='stable-'+('x'*900)
        compacted=compact_analysis_context(data)
        self.assertEqual(Model.bounded_context(compacted,300)['evidence']['queries'][0]['result'],compacted['evidence']['queries'][0]['result'])
