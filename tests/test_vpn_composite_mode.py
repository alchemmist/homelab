import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
P=next(p for p in json.loads((ROOT/'charts/monitoring-k3s/dashboards/traffic-light.json').read_text())['panels'] if p['id']==9)

def component(c,runtime=0,check=1,off=0,success=1,observed='0+15x20',extra=''):
    ip='10.250.0.40' if c=='relay' else '10.250.0.2'
    labels=f'job="node-exporter",instance="{ip}:9100",component="{c}"'+extra
    data={'runtime':str(runtime)+'x20','check_success':str(check)+'x20','off':str(off)+'x20','observation_success':str(success)+'x20','observed_timestamp_seconds':observed}
    return [{'series':'socrat_vpn_component_'+name+'{'+labels+'}','values':value} for name,value in data.items()]

class CompositeModeTest(unittest.TestCase):
    def test_contract_and_geometry(self):
        self.assertEqual(P['gridPos'],{'x':4,'y':0,'w':2,'h':2})
        mapping=P['fieldConfig']['defaults']['mappings'][0]['options']
        self.assertEqual(mapping['-2']['text'],'NO DATA')
        self.assertEqual(mapping['3']['text'],'K3S')
        self.assertEqual(mapping['3']['color'],mapping['1']['color'])
        self.assertNotIn('socrat_vpn_fallback_active',P['targets'][0]['expr'])
        self.assertIn('component=',P['targets'][0]['expr'])
        self.assertIn('/explore?',P['fieldConfig']['defaults']['links'][0]['url'])

    @unittest.skipUnless(shutil.which('promtool'),'promtool required')
    def test_actual_mode_expression_two_components_partial_total_stale_and_errors(self):
        cases=[]
        def add(name,data,value):
            cases.append({'name':name,'interval':'15s','input_series':data,'promql_expr_test':[{'expr':P['targets'][0]['expr'],'eval_time':'3m','exp_samples':[{'labels':'{}','value':value}]}]})
        add('both Kubernetes',component('relay')+component('backend'),0)
        add('relay native',component('relay',runtime=1)+component('backend'),1)
        add('backend native',component('relay')+component('backend',runtime=1),1)
        add('both native',component('relay',runtime=1)+component('backend',runtime=1),1)
        add('Kube partial failure is amber not total OFF',component('relay',check=0)+component('backend'),3)
        add('native partial failure stays OS amber',component('relay',runtime=1,check=0)+component('backend'),1)
        add('relay has no data sockets',component('relay',runtime=-1,check=0,off=1)+component('backend'),2)
        add('backend has no data sockets',component('relay')+component('backend',runtime=-1,check=0,off=1),2)
        add('one positively dead component is sufficient',component('backend',runtime=-1,check=0,off=1),2)
        add('no observation',[],-2)
        add('missing relay',component('backend'),-2)
        add('missing backend',component('relay'),-2)
        add('observer error',component('relay',success=0)+component('backend'),-2)
        add('runtime conflict not green',component('relay',runtime=-1)+component('backend'),-2)
        add('unknown backend runtime',component('relay')+component('backend',runtime=-1),-2)
        add('fresh scrape cannot hide stale file',component('relay',observed='0x20')+component('backend'),-2)
        add('stale OFF is not evidence',component('relay',off=1,observed='0x20')+component('backend'),-2)
        add('future observation is unknown',component('relay',observed='300x20')+component('backend'),-2)
        add('unrelated exporter cannot supply component',component('relay')+[{**s,'series':s['series'].replace('10.250.0.2:9100','10.250.0.99:9100')} for s in component('backend')],-2)
        add('old stale HA labels cannot override fresh healthy',component('relay',extra=',pod="new"')+component('relay',runtime=1,off=1,observed='0x20',extra=',pod="old"')+component('backend'),0)
        # Per-file check missing must not be silently treated as successful.
        add('missing check metric', [s for s in component('relay') if 'check_success' not in s['series']]+component('backend'),-2)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'test.json';p.write_text(json.dumps({'rule_files':[],'evaluation_interval':'15s','tests':cases}))
            r=subprocess.run(['promtool','test','rules',str(p)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
