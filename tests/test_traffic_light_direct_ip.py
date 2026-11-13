"""Live source expressions, stock exporter isolation, and gray-vs-down contracts."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DASH = json.loads((ROOT/'charts/monitoring-k3s/dashboards/traffic-light.json').read_text())

def panel(n):
    return next(p for p in DASH['panels'] if p['id']==n)

def series(name, value, labels='job="node-exporter",node="socrat-4"', samples=20):
    return {'series':name+'{'+labels+'}', 'values':str(value)+('x'+str(samples) if samples else '')}

class DirectIpTest(unittest.TestCase):
    def test_rendered_probe_and_existing_authenticated_pipeline(self):
        rendered=subprocess.check_output(['helm','template','monitoring-k3s',str(ROOT/'charts/monitoring-k3s'),'--namespace','cattle-monitoring-system'],text=True)
        docs=[d for d in yaml.safe_load_all(rendered) if d]
        def obj(kind,name):return next(d for d in docs if d['kind']==kind and d['metadata']['name']==name)
        pod=obj('Deployment','socrat-public-ip-probes')['spec']['template']['spec']
        self.assertTrue(pod['hostNetwork']);self.assertFalse(pod['automountServiceAccountToken'])
        self.assertEqual(pod['nodeSelector'],{'kubernetes.io/hostname':'socrat-0'})
        c=pod['containers'][0]
        self.assertIn('--web.listen-address=192.168.0.23:19116',c['args'])
        self.assertEqual(c['securityContext']['capabilities'],{'drop':['ALL']})
        self.assertFalse(c['securityContext']['allowPrivilegeEscalation'])
        cfg=yaml.safe_load(obj('ConfigMap','socrat-public-ip-probes')['data']['blackbox.yml'])
        self.assertEqual(cfg['modules']['direct_tcp']['tcp']['source_ip_address'],'192.168.0.23')
        self.assertNotIn('http',cfg['modules']['direct_tcp'])
        native=yaml.safe_load(obj('ConfigMap','socrat-tv-native-metrics')['data']['collector.yaml'])
        jobs=native['receivers']['prometheus']['config']['scrape_configs']
        direct=[j for j in jobs if j['job_name'].startswith('public-ip-')]
        self.assertEqual(len(direct),3)
        self.assertEqual({j['params']['target'][0] for j in direct},{'109.173.40.247:443','109.120.141.60:443','91.189.82.238:443'})
        self.assertTrue(all(j['static_configs'][0]['targets']==['192.168.0.23:19116'] for j in direct))
        self.assertEqual(native['exporters']['otlp']['tls']['cert_file'],'/tls/tls.crt')
        self.assertEqual({j['job_name'] for j in jobs if j not in direct},{'socrat-n8n-activity','socrat-argocd'})
        self.assertIn('checksum/native-pipeline',obj('Deployment','socrat-n8n-activity')['spec']['template']['metadata']['annotations'])

    def test_host4_is_a_real_kubernetes_worker_again(self):
        e=panel(926)['targets'][0]['expr']
        self.assertIn('kube_node_status_condition',e)
        self.assertIn('node="socrat-4"',e)
        self.assertIn('timestamp(',e)
        self.assertIn('or vector(-2)',e)

    @unittest.skipUnless(shutil.which('promtool'),'promtool required')
    def test_actual_panel_expressions_down_pressure_stale_and_no_vpn_coupling(self):
        cases=[]
        def add(expr,data,value,when='3m'):
            cases.append({'interval':'15s','input_series':data,'promql_expr_test':[{'expr':expr,'eval_time':when,'exp_samples':[{'labels':'{}','value':value}]}]})
        e=panel(926)['targets'][0]['expr']
        ready=lambda value,samples=20:series('kube_node_status_condition',value,'node="socrat-4",condition="Ready",status="true"',samples)
        add(e,[ready(1)],0)
        add(e,[ready(0)],2)
        add(e,[ready(1),series('kube_node_status_condition',1,'node="socrat-4",condition="MemoryPressure",status="true"')],1)
        add(e,[],-2)
        add(e,[ready(1,0)],-2)
        for pid,sid in [(905,'edge-home'),(906,'edge-vps'),(928,'edge-moscow')]:
            e=panel(pid)['targets'][0]['expr']
            lab=f'job="public-ip-probes",service_id="{sid}",probe_observer="socrat-0",probe_path="direct-home-wan"'
            add(e,[series('up',1,lab),series('probe_success',1,lab)],0)
            add(e,[series('up',1,lab),series('probe_success',0,lab)],2)
            add(e,[series('up',0,lab),series('probe_success',1,lab)],-2)
            add(e,[series('up',1,lab)],-2)
            add(e,[series('up',1,lab),series('probe_success',1,lab,samples=0)],-2)
            add(e,[],-2)
            # Even firing old VPN/edge alerts cannot override a direct green.
            add(e,[series('up',1,lab),series('probe_success',1,lab),series('ALERTS',1,'alertname="SocratServiceEdgeVpsUnavailable",alertstate="firing",service_id="edge-vps"')],0)
            # Legacy in-cluster probe alone cannot falsely supply direct telemetry.
            add(e,[series('probe_success',1,f'job="service-probes",service_id="{sid}"')],-2)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'cases.yml';p.write_text(yaml.safe_dump({'rule_files':[],'evaluation_interval':'15s','tests':cases}))
            r=subprocess.run(['promtool','test','rules',str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
