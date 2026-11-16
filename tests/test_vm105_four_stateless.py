"""Placement-only boundaries and guarded worker handoff; offline, no credentials."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

R = Path(__file__).resolve().parents[1]


def render(chart, values, namespace):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml') as f:
        yaml.safe_dump(values, f); f.flush()
        raw = subprocess.check_output(['helm','template',chart,str(R/'charts'/chart),'-n',namespace,'-f',f.name], text=True)
    return {(x['kind'], x['metadata']['name']): x for x in yaml.safe_load_all(raw) if x}


def values(chart):
    v = yaml.safe_load((R/'charts'/chart/'values.yaml').read_text())
    # Production overrides here are top-level keys; maintain explicit queue map.
    for k, x in yaml.safe_load((R/'deploy'/chart/'values.yaml').read_text()).items():
        if isinstance(x, dict) and isinstance(v.get(k), dict): v[k].update(x)
        else: v[k] = x
    return v


class PlacementTests(unittest.TestCase):
    def test_monori_only_frontend_changes(self):
        new = values('monori'); old = copy.deepcopy(new); old['frontNodeName'] = 'socrat-0'
        a, b = render('monori', old, 'monori'), render('monori', new, 'monori')
        self.assertEqual([k for k in a if a[k] != b[k]], [('Deployment','monori')])
        for name in ['monori-back','monori-sync']:
            self.assertEqual(b['Deployment',name]['spec']['template']['spec']['nodeSelector'], {'kubernetes.io/hostname':'socrat-0'})
        pod = b['Deployment','monori']['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname':'socrat-5'})
        self.assertNotIn('volumes', pod)

    def test_spi_only_queue_ui_changes_not_backend_jobs_rbac_or_network_policy(self):
        new = values('spi-triage'); old = copy.deepcopy(new)
        old['queueUI']['nodeName'] = 'socrat-3'; old['queueUI']['hostAliases'] = []
        a, b = render('spi-triage', old, 'automation'), render('spi-triage', new, 'automation')
        self.assertEqual([k for k in a if a[k] != b[k]], [('Deployment','spi-queue-ui')])
        pod = b['Deployment','spi-queue-ui']['spec']['template']['spec']
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname':'socrat-5'})
        self.assertEqual(pod['hostAliases'], [{'ip':'10.43.218.222','hostnames':['auth.socrat.alchemmist.xyz']}])
        self.assertFalse(pod['automountServiceAccountToken'])

    def test_worker_single_recreate_no_pvc_auth_and_write_modes_preserved(self):
        for folder, expected in [('blog-updates','false'),('wiki-openapi','true')]:
            docs = list(yaml.safe_load_all((R/'deploy'/folder/'worker.yaml').read_text()))
            d = next(x for x in docs if x and x['kind']=='Deployment')
            self.assertEqual(d['spec']['replicas'], 1)
            self.assertEqual(d['spec']['strategy'], {'type':'Recreate'})
            pod = d['spec']['template']['spec']
            self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname':'socrat-5'})
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertFalse(any('persistentVolumeClaim' in v or 'hostPath' in v for v in pod['volumes']))
            env = {e['name']:e.get('value') for e in pod['containers'][0]['env']}
            self.assertEqual(env['WRITE_ENABLED'], expected)
            if folder=='wiki-openapi':
                cron = next(x for x in docs if x and x['kind']=='CronJob')
                self.assertEqual(cron['spec']['jobTemplate']['spec']['template']['spec']['nodeSelector'], {'kubernetes.io/hostname':'socrat-1'})

    def test_endpoint_slice_null_is_a_valid_empty_drain(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('worker_handoff', R/'scripts/vm105-stateless-handoff.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        for value in [{'items':[]}, {'items':[{'endpoints':None}]}, {'items':[{'endpoints':[]}]}]:
            self.assertFalse(module.has_ready_endpoints(value))
        self.assertTrue(module.has_ready_endpoints({'items':[{'endpoints':[{'addresses':['10.0.0.1'],'conditions':{'ready':True}}]}]}))
        self.assertFalse(module.has_ready_endpoints({'items':[{'endpoints':[{'addresses':['10.0.0.1'],'conditions':{'ready':False}}]}]}))

    def test_drain_is_two_exact_services_only_and_finally_restores(self):
        p = R/'deploy/migrations/vm105-four-stateless-20261116/drain-services.yaml'
        docs = [x for x in yaml.safe_load_all(p.read_text()) if x]
        self.assertEqual({x['metadata']['name'] for x in docs}, {'blog-updates-worker','wiki-openapi-worker'})
        for x in docs:
            self.assertEqual(x['kind'], 'Service'); self.assertEqual(x['metadata']['namespace'], 'automation')
            self.assertEqual(x['spec']['selector']['homelab.io/migration-drain'], 'no-serving-pods')
        source = (R/'scripts/vm105-stateless-handoff.py').read_text()
        for required in ['idle(old_name)', 'finally:', 'canonicalServiceRestored', '/proc/1/task', 'endpointslices']:
            self.assertIn(required, source)
        for forbidden in ['--force', '--grace-period=0', '/create-pr', 'delete', 'workflow_entity']:
            self.assertNotIn(forbidden, source)


if __name__ == '__main__': unittest.main()
