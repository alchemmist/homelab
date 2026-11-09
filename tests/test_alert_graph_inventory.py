"""Offline full rule coverage and condition-preservation regression."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
import yaml
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('alert_graphs', ROOT/'scripts/alert_graphs.py')
graphs = importlib.util.module_from_spec(spec); spec.loader.exec_module(graphs)


class AlertGraphInventoryTests(unittest.TestCase):
    def test_root_comparison_only(self):
        self.assertEqual(graphs.diagnostic('((rate(errors_total[5m]) / rate(requests_total[5m])) > 0.1)')[:2], ('(rate(errors_total[5m]) / rate(requests_total[5m]))', 0.1))
        self.assertEqual(graphs.diagnostic('up{note="x > y"} == 0')[:2], ('up{note="x > y"}',0))
        parts=graphs.operands('(x > 2) and on(node) (y < 3)')
        self.assertEqual([p[0] for p in parts],['x','y'])
        self.assertEqual(graphs.diagnostic('a != on(node) b')[0], 'a != on(node) b')

    def test_all_source_rules_have_real_panel_queries_and_priority(self):
        rows=json.loads((ROOT/'docs/monitoring/alert-graphs.inventory.json').read_text())
        self.assertEqual(len(rows),200)
        for row in rows:
            with self.subTest(alert=row['alert']):
                spec=row['graphs'];self.assertEqual(spec['version'],1)
                self.assertEqual(spec['graphs'][0]['id'],'primary')
                for graph in spec['graphs']:
                    dashboard=json.loads((ROOT/'charts/monitoring-k3s/alert-dashboards'/(graph['dashboard_uid']+'.json')).read_text())
                    panel=next(p for p in dashboard['panels'] if p['id']==graph['panel_id'])
                    self.assertTrue(panel['targets'])
                    self.assertTrue(all(t['datasource']['uid']=='prometheus' for t in panel['targets']))
                    if graph['id']=='condition':self.assertIn(row['expr'],[t['expr'] for t in panel['targets']])
        self.assertEqual(sum(r['owner']=='grafana-managed' for r in rows),7)

    def test_generated_files_are_current(self):
        run=subprocess.run(['python3','scripts/alert_graphs.py','--check'],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr+run.stdout)

    def test_actual_render_has_annotations_without_changing_conditions(self):
        expected=json.loads((ROOT/'docs/monitoring/alert-graphs.inventory.json').read_text())
        for owner in graphs.OWNERS:
            app=yaml.safe_load((ROOT/'deploy/argocd/apps'/(owner+'.yaml')).read_text())
            source=app['spec']['source'];helm=source['helm'];chart=ROOT/source['path']
            args=['helm','template',helm['releaseName'],str(chart),'--namespace',app['spec']['destination']['namespace']]
            for file in helm.get('valueFiles',[]):args += ['-f',str(chart/file)]
            rendered=subprocess.check_output(args,text=True,stderr=subprocess.DEVNULL)
            found=[]
            for doc in yaml.safe_load_all(rendered):
                if not isinstance(doc,dict) or doc.get('kind')!='PrometheusRule':continue
                for group in doc['spec']['groups']:
                    for rule in group['rules']:
                        if 'alert' not in rule:continue
                        found.append((doc['metadata']['name'],rule['alert'],str(rule['expr'])))
                        self.assertIn('spi_graphs',rule.get('annotations',{}),(owner,rule['alert']))
            wanted=[(r['resource'],r['alert'],r['expr']) for r in expected if r['owner']==owner]
            self.assertEqual(sorted(found),sorted(wanted),owner)


if __name__=='__main__':unittest.main()
