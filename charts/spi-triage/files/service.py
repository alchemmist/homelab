"""Authenticated private stage API. Durable state is independent of n8n executions."""
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dispatcher import Dispatcher
from core import Failure, Store, digest, normalize, render
from integrations import Evidence, GitHub, HTTP, Model, REQUEST_DEADLINE
from evidence_bundle import index_markdown, publish_parts
from grafana_links import repair_markdown_links

class Engine:
    def __init__(self,store,github,model,evidence,write=False):
        self.store=store;self.github=github;self.model=model;self.evidence=evidence;self.write=write
        self.lock=threading.Lock()
    def claim(self):
        # A socket call may outlive the durable lease. Never reclaim while this
        # process still owns a stage, including its final save/failure handling.
        if not self.lock.acquire(blocking=False):return {'job_id':''}
        try:return self.store.claim()
        finally:self.lock.release()
    def run(self,name,key):
        with self.lock:
            REQUEST_DEADLINE.at=time.monotonic()+780
            try:return self._run(name,key)
            except Failure as e:
                self.store.fail(key,e.code)
                print(json.dumps({'component':'spi-triage','event':'stage_failed','stage':name,'code':e.code}),flush=True)
                raise
            except Exception:
                self.store.fail(key,'INTERNAL_ERROR')
                raise Failure('INTERNAL_ERROR') from None
            finally:
                del REQUEST_DEADLINE.at
    def _run(self,name,key):
        stages={'match':1,'collect':2,'analyze':3,'publish':4}
        if name not in stages:raise Failure('INVALID_STAGE')
        job=self.store.get(key);wanted=stages[name]
        if job['stage']>=wanted:return {'job_id':key,'status':job['state'],'stage':job['stage']}
        if job['stage']!=wanted-1 or job['state']!='processing':raise Failure('INVALID_STAGE_ORDER')
        r=job['result'];event=job['event'];resolved=event['status']=='resolved'
        if name=='match':
            if resolved:
                r['resolved_issue']=self.store.episode_issue(event['episode'])
            else:
                issues=self.github.snapshot();r['open_signature']=digest([(x['number'],x['updated_at']) for x in issues])
                r['match']=self.model.match(event,issues)
        elif name=='collect':
            if not resolved or r.get('resolved_issue'):r['evidence']=self.evidence.collect(event)
        elif name=='analyze':
            if not resolved:
                r['report']=self.model.analyze(event,r['match'],r['evidence']);render(r['report'],event)
        elif name=='publish':
            if not self.write:
                self.store.save(key,4,r,state='dry_run');return {'job_id':key,'status':'dry_run','issue_number':0}
            marker='<!-- socrat-spi:'+key+' -->'
            # Reconcile BEFORE checking open candidates: the previous write may itself
            # have changed that snapshot, or a human may have closed the created issue.
            if job['intent']:
                intent=json.loads(job['intent'])
                number=intent['number'] if intent.get('primary_done') else self.github.reconcile(marker,intent['number'])
                if not number:raise Failure('WRITE_NEEDS_REVIEW')
                self.finish_evidence(key,r,number)
                return {'job_id':key,'status':'reconciled','issue_number':number}
            if resolved:
                number=r['resolved_issue']
                if not number or self.github.request('GET','/issues/'+str(number)).get('state')!='open':
                    self.store.save(key,4,r,state='complete');return {'job_id':key,'status':'resolved_without_open_spi'}
                title='';body='## Incident resolved\n\nObserved recovery at '+(event['endsAt'] or 'an unspecified time')+'.\n\nResolution does not establish root-cause remediation; this issue remains open.\n\n'+marker
            else:
                issues=self.github.snapshot()
                if digest([(x['number'],x['updated_at']) for x in issues])!=r['open_signature']:
                    self.store.save(key,0,{},state='processing');raise Failure('OPEN_SPI_CHANGED')
                title,body=render(r['report'],event);number=r['report']['issue_number']
                if number not in {0,*[x['number']for x in r['match']['candidates']]}:raise Failure('INVALID_MATCH_TARGET')
            body=repair_markdown_links(body+index_markdown(r.get('evidence',{}).get('bundle')))
            self.store.save(key,3,r,intent=json.dumps({'number':number}))
            try:
                if number:
                    self.github.request('POST','/issues/'+str(number)+'/comments',{'body':body})
                else:
                    number=self.github.request('POST','/issues',{'title':title,'body':body})['number']
            except Failure as e:
                # 4xx are definitive rejections. Network errors/5xx can hide a
                # successful write: keep intent and never blindly repeat the POST.
                if e.code.startswith('HTTP_4') and e.code!='HTTP_408':
                    self.store.save(key,3,r,intent=None)
                raise
            self.finish_evidence(key,r,number)
            print(json.dumps({'component':'spi-triage','event':'publication_ok','issue_number':number}),flush=True)
            return {'job_id':key,'status':'published','issue_number':number}
        self.store.save(key,wanted,r)
        return {'job_id':key,'status':'processing','stage':wanted}


    def finish_evidence(self,key,result,number):
        intent=json.dumps({'number':number,'primary_done':True})
        progress=result.setdefault('artifact_publication',{})
        def save():self.store.save(key,3,result,intent=intent)
        save()
        publish_parts(self.github,number,result.get('evidence',{}).get('bundle'),progress,save)
        self.store.save(key,4,result,state='complete',issue=number,intent=None)


def read_request_body(handler, timeout=10):
    """Bound partial/trickling bodies by a total elapsed-time deadline."""
    try:length=int(handler.headers.get('Content-Length','0'))
    except (ValueError,TypeError):raise Failure('INVALID_BODY_SIZE') from None
    if not 0<length<=512_000:raise Failure('INVALID_BODY_SIZE')
    deadline=time.monotonic()+timeout
    previous=handler.connection.gettimeout()
    chunks=[]
    try:
        while length:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError()
            handler.connection.settimeout(remaining)
            chunk=handler.rfile.read1(length)
            if not chunk:raise Failure('INCOMPLETE_BODY')
            chunks.append(chunk);length-=len(chunk)
        data=json.loads(b''.join(chunks))
        if not isinstance(data,dict):raise Failure('INVALID_REQUEST')
        return data
    except TimeoutError:raise Failure('REQUEST_BODY_TIMEOUT') from None
    finally:handler.connection.settimeout(previous)


def serve():
    os.umask(0o077)
    http=HTTP();store=Store(os.environ.get('SPI_DATABASE','/data/spi.sqlite'))
    recovered=store.recover_on_start()
    print(json.dumps({'component':'spi-triage','event':'worker_started','recovered_jobs':recovered}),flush=True)
    engine=Engine(store,GitHub(http,os.environ.get('GITHUB_TOKEN_FILE','/github/token')),
                  Model(http,os.environ['LITELLM_KEY']),Evidence(http,os.environ['GRAFANA_TOKEN'],os.environ['GRAFANA_URL'],github=GitHub(http,os.environ.get('GITHUB_TOKEN_FILE','/github/token'))),
                  write=os.environ.get('WRITE_ENABLED')=='true')
    dispatcher=Dispatcher(store,os.environ['WORKER_TOKEN'],enabled=os.environ.get('SPI_DISPATCH_ENABLED','false')=='true',busy=engine.lock.locked)
    dispatcher.start()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,body,content_type='application/json'):
            raw=body.encode() if isinstance(body,str) else json.dumps(body).encode()
            self.send_response(status);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(raw)));self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            if self.path=='/healthz':return self.send(200,{'status':'ok'})
            if self.path=='/metrics':
                h=store.health();lines=['# TYPE socrat_spi_jobs gauge']
                for state in ['queued','retry','processing','complete','dry_run','dead']:
                    lines.append('socrat_spi_jobs{state="'+state+'"} '+str(h['counts'].get(state,0)))
                lines+=['# TYPE socrat_spi_oldest_pending_seconds gauge','socrat_spi_oldest_pending_seconds '+str(h['oldest_pending_seconds'])]
                d=store.dispatch_status()
                lines+=['socrat_spi_dispatch_enabled '+str(int(dispatcher.enabled)), 'socrat_spi_dispatch_attempts '+str(d['attempts'])]
                return self.send(200,'\n'.join(lines)+'\n','text/plain; version=0.0.4')
            return self.send(404,{'code':'NOT_FOUND'})
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('X-Worker-Token',''),os.environ['WORKER_TOKEN']):return self.send(403,{'code':'FORBIDDEN'})
            try:
                data=read_request_body(self)
                if self.path=='/enqueue':result=store.enqueue(normalize(data))
                elif self.path=='/enqueue-group':
                    alerts=data.get('alerts')
                    if not isinstance(alerts,list) or not 0<len(alerts)<=200:raise Failure('INVALID_ALERT_GROUP')
                    events=[normalize({'source':data.get('externalURL','socrat-alerts'),'alert':a})for a in alerts]
                    result={'accepted':len(store.enqueue_many(events))}
                elif self.path=='/claim':
                    result=engine.claim();h=store.health()
                    print(json.dumps({'component':'spi-triage','event':'queue_health','oldest_pending_seconds':h['oldest_pending_seconds'],'dead_jobs':h['counts'].get('dead',0)}),flush=True)
                elif self.path in ['/match','/collect','/analyze','/publish']:
                    key=data.get('job_id','')
                    if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef'for c in key):raise Failure('INVALID_JOB_ID')
                    result=engine.run(self.path[1:],key)
                else:return self.send(404,{'code':'NOT_FOUND'})
                return self.send(200,result)
            except Failure as e:
                self.close_connection=True
                return self.send(422,{'code':e.code})
            except (ValueError,TypeError,AttributeError):return self.send(400,{'code':'INVALID_REQUEST'})
            except Exception:return self.send(500,{'code':'INTERNAL_ERROR'})
            finally:dispatcher.signal()
    ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()

if __name__=='__main__':serve()
