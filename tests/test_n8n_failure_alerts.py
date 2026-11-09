import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/n8n'))
import sync_failure_alerts as sync
TEMPLATE=json.loads((ROOT/'docs/n8n/workflow-failure-alerts.json').read_text())

class FailureAlertsTests(unittest.TestCase):
    def notification(self,payload,handler='4321'):
        code=TEMPLATE['nodes'][1]['parameters']['jsCode']
        js='const vm=require("node:vm");const x=JSON.parse(process.argv[1]);const fn=vm.runInNewContext("(function(){"+x.code+"})",{items:[{json:x.payload}],$execution:{id:x.handler}});console.log(JSON.stringify(fn()));'
        return json.loads(subprocess.check_output(['node','-e',js,json.dumps({'code':code,'payload':payload,'handler':handler})]))[0]['json']
    def test_metadata_only_and_trusted_url(self):
        p={'workflow':{'id':'abc123','name':'Calendar'},'execution':{'id':'123','url':'https://evil.invalid/?token=secret','lastNodeExecuted':'Announce','error':{'message':'secret','stack':'private'},'executionContext':{'token':'private'}}}
        result=self.notification(p);text=json.dumps(result)
        self.assertNotIn('secret',text);self.assertNotIn('private',text);self.assertNotIn('evil.invalid',text)
        self.assertEqual(result['alert']['generatorURL'],'https://n8n.socrat.alchemmist.xyz/workflow/abc123/executions/123')
        self.assertEqual(result['alert']['fingerprint'],self.notification(p,'9999')['alert']['fingerprint'])
        p['execution']['id']='124';self.assertNotEqual(result['alert']['fingerprint'],self.notification(p)['alert']['fingerprint'])
    def test_trigger_failure_without_execution_id(self):
        p={'workflow':{'id':'abc','name':'Calendar'},'trigger':{'error':{'message':'password'}}}
        result=self.notification(p);self.assertIn('Trigger failure',result['alert']['annotations']['description'])
        self.assertNotIn('password',json.dumps(result))
        self.assertNotEqual(result['alert']['fingerprint'],self.notification(p,'9999')['alert']['fingerprint'])
    def test_no_message_storage_retries_recursion_or_spi_ingress(self):
        self.assertNotIn('errorWorkflow',TEMPLATE['settings'])
        self.assertEqual(TEMPLATE['settings']['saveDataErrorExecution'],'none')
        self.assertEqual(TEMPLATE['settings']['saveDataSuccessExecution'],'none')
        self.assertEqual(TEMPLATE['nodes'][0]['type'],'n8n-nodes-base.errorTrigger')
        last=TEMPLATE['nodes'][-1];self.assertFalse(last.get('retryOnFail',False))
        self.assertNotIn('onError',last)
        self.assertEqual(last['parameters']['url'],'http://socrat-bot.socrat-bot.svc:8080/v1/messages')
    def wf(self,active=True):
        return {'id':'abc','name':'Calendar','nodes':[{'id':'n','credentials':{'native':{'id':'credential-ref'}}}],'connections':{},'settings':{'executionTimeout':1800},'active':active,'versionId':'v1','activeVersionId':'v1'if active else None,'activeVersion':{'nodes':[{'id':'n','credentials':{'native':{'id':'credential-ref'}}}],'connections':{}}if active else None}
    def test_guard_rejects_unpublished_changes_and_other_handler(self):
        w=self.wf();w['activeVersion']['nodes']=[]
        with self.assertRaises(RuntimeError):sync.guard(w,'handler')
        w=self.wf();w['settings']['errorWorkflow']='other'
        with self.assertRaises(RuntimeError):sync.guard(w,'handler')
    def test_only_settings_change_and_active_state_preserved(self):
        for active in (True,False):
            original=self.wf(active);current=copy.deepcopy(original);calls=[]
            def api(method,path,body=None):
                calls.append((method,path,body))
                if method=='PUT':
                    self.assertEqual(body['nodes'],original['nodes']);self.assertEqual(body['connections'],original['connections'])
                    current['settings']=body['settings'];current['versionId']='v2'
                if method=='POST':
                    self.assertTrue(path.endswith('/activate'));current['activeVersionId']='v2'
                return copy.deepcopy(current)
            result=sync.bind(api,original,'handler')
            self.assertEqual(result['active'],active)
            self.assertEqual(result['settings'],{'executionTimeout':1800,'errorWorkflow':'handler'})
            self.assertEqual(sum(m=='POST'for m,_,_ in calls),int(active))
            self.assertFalse(any('execute'in path or'deactivate'in path for _,path,_ in calls))
    def test_idempotent_and_concurrent_drift_stops(self):
        w=self.wf();w['settings']['errorWorkflow']='handler';calls=[]
        def api(*args):calls.append(args);return copy.deepcopy(w)
        sync.bind(api,w,'handler');self.assertEqual(len(calls),1)
        before=self.wf();w['name']='Changed'
        with self.assertRaises(RuntimeError):sync.bind(api,before,'handler')
    def test_only_native_github_registration_may_change(self):
        before=self.wf();before['nodes']=[{'id':'n','name':'Push','type':'n8n-nodes-base.githubTrigger'}]
        before['staticData']={'node:Push':{'webhookId':1,'webhookSecret':'old','webhookEvents':['push']},'global':{'checkpoint':'preserved'}}
        after=copy.deepcopy(before);after['settings']['errorWorkflow']='handler'
        after['staticData']['node:Push'].update(webhookId=2,webhookSecret='new')
        sync.check(before,after,'handler')
        after['staticData']['global']['checkpoint']='changed'
        with self.assertRaises(RuntimeError):sync.check(before,after,'handler')
        after=copy.deepcopy(before);after['settings']['errorWorkflow']='handler'
        after['staticData']['node:Push']['webhookEvents']=['issues']
        with self.assertRaises(RuntimeError):sync.check(before,after,'handler')

    def test_transient_put_state_requires_authoritative_readback(self):
        before=self.wf();before['staticData']={'checkpoint':'must-remain'}
        transient=copy.deepcopy(before);transient['settings']['errorWorkflow']='handler';transient['staticData']=None
        sync.check(before,transient,'handler',verify_static=False)
        with self.assertRaises(RuntimeError):sync.check(before,transient,'handler')
        stable=copy.deepcopy(before);stable['settings']['errorWorkflow']='handler'
        sync.check(before,stable,'handler')

    def test_unexpected_settings_drift_stops(self):
        before=self.wf();after=copy.deepcopy(before);after['settings']={'errorWorkflow':'handler'}
        with self.assertRaises(RuntimeError):sync.check(before,after,'handler')

if __name__=='__main__':unittest.main()
