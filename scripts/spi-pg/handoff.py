"""Temporary SPI admission handoff. No dispatch, model, GitHub, bot or evidence clients."""
import os,sys,time,json,http.client,hmac
from contextlib import nullcontext,contextmanager
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from types import SimpleNamespace
import psycopg
from core import Store,normalize,Failure
from pg_store import Conn,factory
from service import read_request_body
from card_correlation import record_receipt
from telegram_links import Links

URL=os.environ['SPI_POSTGRES_URL']; TOKEN=os.environ['WORKER_TOKEN'];LOCK=1397770577
ADMIT=('/enqueue','/enqueue-group','/telegram-receipt')
@contextmanager
def txn():
    with psycopg.connect(URL,connect_timeout=5,row_factory=factory) as d:
        d.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,));yield d

def admit(path,data):
    with txn() as d:
        if not d.execute('SELECT live FROM handoff.mode').fetchone()['live']:d.execute('SET LOCAL search_path=handoff')
        c=Conn(d);st=SimpleNamespace(db=lambda:nullcontext(c));now=time.time()
        if path=='/enqueue':return Store._enqueue(None,c,normalize(data),now)
        if path=='/enqueue-group':
            alerts=data.get('alerts');
            if not isinstance(alerts,list) or not 0<len(alerts)<=200:raise Failure('INVALID_ALERT_GROUP')
            events=[normalize({'source':data.get('externalURL','socrat-alerts'),'alert':a}) for a in alerts]
            for e in events:Store._enqueue(None,c,e,now)
            return {'accepted':len(events),'events':[{'event_key':e['event_key'],'episode':e['episode']} for e in events]}
        r=record_receipt(st,data);v=data.get('receipt');
        if isinstance(v,dict) and not v.get('error') and v.get('episode')==r['episode'] and v.get('immutable_key') is True and str(v.get('key','')).endswith('/spi/'+r['episode']):Links.record_card_receipt(None,r['episode'],v,connection=c)
        return r

def activate():
    with txn() as d:
        assert d.execute('SELECT live FROM handoff.mode').fetchone()['live'] is False
        assert d.execute('SELECT EXISTS(SELECT FROM public.jobs) ready').fetchone()['ready']
        d.execute('''INSERT INTO public.jobs SELECT * FROM handoff.jobs ON CONFLICT(id) DO UPDATE SET deliveries=public.jobs.deliveries+excluded.deliveries,updated=greatest(public.jobs.updated,excluded.updated)''')
        d.execute('''INSERT INTO public.telegram_receipt_events SELECT * FROM handoff.telegram_receipt_events ON CONFLICT(event_key) DO UPDATE SET observed=greatest(public.telegram_receipt_events.observed,excluded.observed),unknown=greatest(public.telegram_receipt_events.unknown,excluded.unknown)''')
        d.execute('INSERT INTO public.telegram_receipts SELECT * FROM handoff.telegram_receipts ON CONFLICT DO NOTHING')
        for r in d.execute('SELECT episode,receipt FROM handoff.spi_card_receipts'):
            Links.record_card_receipt(None,r['episode'],json.loads(r['receipt']),connection=Conn(d))
        print('merged admissions:',d.execute('SELECT count(*) n FROM handoff.jobs').fetchone()['n'],'receipt events:',d.execute('SELECT count(*) n FROM handoff.telegram_receipt_events').fetchone()['n'])
        d.execute('UPDATE handoff.mode SET live=true')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def output(self,status,body,typ='application/json'):
        if not isinstance(body,bytes):body=json.dumps(body).encode()
        self.send_response(status);self.send_header('Content-Type',typ);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if self.path=='/healthz':return self.output(200,{'status':'ok'})
        if self.path=='/metrics':return self.forward(None)
        self.output(404,{})
    def forward(self,data):
        conn=http.client.HTTPConnection('spi-cutover-backend.automation.svc.cluster.local',80,timeout=1950)
        try:
            headers={k:self.headers[k] for k in ('X-Worker-Token','X-SPI-Workflow-Contract','X-Queue-Token') if k in self.headers};headers['Content-Type']='application/json';conn.request(self.command,self.path,body=json.dumps(data) if data is not None else None,headers=headers);r=conn.getresponse();self.output(r.status,r.read(),r.getheader('Content-Type','application/json'))
        except OSError:self.output(503,{'code':'WORKER_MAINTENANCE'})
        finally:conn.close()
    def do_POST(self):
        if self.path not in (*ADMIT,'/claim','/match','/collect','/analyze','/publish','/operator/queue/list','/operator/queue/cancel','/operator/queue/cancel-batch'):return self.output(404,{})
        if not self.path.startswith('/operator/') and not hmac.compare_digest(self.headers.get('X-Worker-Token','').encode(),TOKEN.encode()):return self.output(403,{})
        try:
            data=read_request_body(self)
            if self.path not in ADMIT:return self.forward(data)
            if self.headers.get('X-SPI-Workflow-Contract') not in (None,'1'):raise Failure('INVALID_WORKFLOW_CONTRACT')
            self.output(200,admit(self.path,data))
        except Failure as e:self.output(422,{'code':e.code})
        except Exception:self.output(500,{'code':'HANDOFF_FAILED'})

if __name__=='__main__':
    if sys.argv[-1]=='activate':activate()
    else:ThreadingHTTPServer(('0.0.0.0',8080),Handler).serve_forever()
