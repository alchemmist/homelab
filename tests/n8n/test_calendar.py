import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
BASE=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('sync',BASE/'scripts/n8n/sync.py');sync=importlib.util.module_from_spec(spec);spec.loader.exec_module(sync)
class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.template=json.loads((BASE/'docs/n8n/calendar-voice-reminder.json').read_text())
        self.creds={k:{'id':'test-id','name':'Test'}for k in ['googleCalendarOAuth2Api','httpHeaderAuth']}
    def render(self,cloud=None):
        return sync.render_workflow(self.template,self.creds,{'calendar_ids':['primary','work@example.test']},cloud or {'scenario_id':'scenario-test'})
    def test_render_public_only(self):
        w=self.render();raw=json.dumps(w)
        self.assertNotIn('REPLACE_WITH_',raw);self.assertNotIn('yandex-voice',raw)
        self.assertNotIn('httpCustomAuth',raw);self.assertNotIn('quasar.yandex',raw)
        self.assertEqual(len(w['nodes']),6)
        calls=[n for n in w['nodes']if n['type']=='n8n-nodes-base.httpRequest']
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['parameters']['url'],'https://api.iot.yandex.net/v1.0/scenarios/scenario-test/actions')
        self.assertNotIn('jsonBody',calls[0]['parameters'])
        self.assertIn('REPLACE_WITH_',json.dumps(self.template))
    def test_nonpublic_deployment_forbidden(self):
        for url in ['https://iot.quasar.yandex.ru/m/user/scenarios/x/actions','http://api.iot.yandex.net/v1.0/scenarios/x/actions','https://api.iot.yandex.net.evil.test/v1.0/scenarios/x/actions','https://api.iot.yandex.net/v1.0/scenarios/x/actions?token=bad']:
            w=self.render();next(n for n in w['nodes']if n['type']=='n8n-nodes-base.httpRequest')['parameters']['url']=url
            with self.assertRaises(RuntimeError):sync.require_public_yandex_api(w)
    def test_missing_auth_rejected(self):
        with self.assertRaises(RuntimeError):sync.render_workflow(self.template,{}, {}, {})
    def test_missing_or_unsafe_scenario_rejected(self):
        for x in ['',"bad'id",'../path']:
            with self.assertRaises(RuntimeError):self.render({'scenario_id':x})
    def test_failed_call_does_not_mark(self):
        code=next(n for n in self.render()['nodes']if n['name']=='Mark Announced')['parameters']['jsCode']
        script='const s={};const f=new Function("items","$getWorkflowStaticData","$",'+json.dumps(code)+');try{f([{json:{status:"error"}}],()=>s,()=>({itemMatching:()=>({json:{dedupKey:"a"}})}));process.exit(1)}catch(e){};if(s.voiced.a)process.exit(2);f([{json:{status:"ok"}}],()=>s,()=>({itemMatching:()=>({json:{dedupKey:"a"}})}));if(!s.voiced.a)process.exit(3);'
        subprocess.check_call(['node','-e',script])
    def test_due_matching_and_dedup(self):
        code=next(n for n in self.render()['nodes']if n['name']=='Match Due Reminders')['parameters']['jsCode']
        event={'id':'event-test','summary':'Meeting','start':{'dateTime':'2026-11-03T14:00:00+03:00'},'reminders':{'useDefault':False,'overrides':[{'method':'popup','minutes':10}]}}
        script='Date.now=()=>Date.parse("2026-11-03T13:50:00+03:00");const s={};const f=new Function("items","$getWorkflowStaticData",'+json.dumps(code)+');const a=f([{json:'+json.dumps(event)+'}],()=>s);if(a.length!==1)process.exit(1);s.voiced[a[0].json.dedupKey]=Date.now();if(f([{json:'+json.dumps(event)+'}],()=>s).length)process.exit(2);'
        subprocess.check_call(['node','-e',script])
if __name__=='__main__':unittest.main()
