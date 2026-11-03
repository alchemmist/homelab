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
        self.creds={k:{'id':'test-id','name':'Test'}for k in ['googleCalendarOAuth2Api','httpCustomAuth']}
    def render(self,cloud=None):
        return sync.render_workflow(self.template,self.creds,{'calendar_ids':['primary','work@example.test']},cloud or {'scenario_id':'scenario-test','device_id':'device-test'})
    def test_render_and_loop(self):
        w=self.render();raw=json.dumps(w)
        self.assertNotIn('REPLACE_WITH_',raw);self.assertNotIn('yandex-voice',raw)
        self.assertEqual(w['connections']['Each Reminder']['main'][0],[])
        self.assertEqual(w['connections']['Each Reminder']['main'][1][0]['node'],'Prepare Yandex Announcement')
        self.assertEqual(w['connections']['Mark Announced']['main'][0][0]['node'],'Each Reminder')
        self.assertLess(w['settings']['executionTimeout'],60)
        self.assertIn('REPLACE_WITH_',json.dumps(self.template))
    def test_internal_deployment_forbidden(self):
        with self.assertRaisesRegex(RuntimeError,'Internal Yandex API is forbidden'):
            sync.require_public_yandex_api(self.template)
        sync.require_public_yandex_api({'nodes':[{'parameters':{'url':'https://api.iot.yandex.net/v1.0/scenarios/example/actions'}}]})

    def test_missing_auth_rejected(self):
        with self.assertRaises(RuntimeError):sync.render_workflow(self.template,{}, {}, {})
    def test_missing_or_unsafe_cloud_rejected(self):
        for x in ['',"bad'id",'../path']:
            with self.assertRaises(RuntimeError):self.render({'scenario_id':x,'device_id':'test'})
    def test_json_body_escapes_untrusted_titles(self):
        node=next(n for n in self.render()['nodes']if n['name']=='Prepare Yandex Announcement')
        expression=node['parameters']['jsonBody'][3:-3].strip()
        text='Meeting "quoted"\n<script> & \\path; ${notCode}'
        script='const f=new Function("$json",'+json.dumps('return '+expression)+');console.log(f({text:'+json.dumps(text)+'}));'
        result=json.loads(subprocess.check_output(['node','-e',script],text=True))
        caps=result['steps'][0]['parameters']['items'][0]['value']['capabilities']
        self.assertEqual(caps[1]['state']['value']['text'],text)
        self.assertEqual(caps[0]['state']['value'],{'value':5})
    def test_failed_prepare_cannot_run_or_mark(self):
        w=self.render();run=next(n for n in w['nodes']if n['name']=='Announce via Yandex Station')
        expr=run['parameters']['url'][3:-3].strip()
        script='const f=new Function("$json",'+json.dumps('return '+expr)+');try{f({status:"error"});process.exit(1)}catch(e){};console.log(f({status:"ok"}));'
        out=subprocess.check_output(['node','-e',script],text=True)
        self.assertIn('/scenario-test/actions',out)
        mark=next(n for n in w['nodes']if n['name']=='Mark Announced')
        self.assertIn('throw new Error',mark['parameters']['jsCode'])
if __name__=='__main__':unittest.main()
