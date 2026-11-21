"""Two-card #509 pilot. Only validated scalar cases cross the executor/judge boundary."""
import gzip
import ast, contextlib, datetime, hashlib, hmac, json, os, re, shutil, sqlite3, subprocess, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE='61ca009312ee850c70cd87ed4c60296e2a78abcc'
CARDS={'day_number':('server/app/transfer_match.py',['server/tests/unit/test_transfer_match.py']), '_amount':('server/app/workbook/parser.py',['server/tests/unit/test_workbook_parser.py','server/tests/unit/test_workbook_parser_mutation.py'])}
MODEL='v-deepseek-uc'; DB='/state/survivor-first-v2.db'; REPO=Path('/scratch/monori'); WROOT='/home/openhands/workspace/monori-pilot-v1'; LOCK=threading.Lock()
CAT=json.loads(Path('/code/mutants.json').read_text()); RUN='mutation-pilot-v2'; ENV={'PATH':os.environ['PATH'],'HOME':'/scratch','UV_CACHE_DIR':'/scratch/uv-cache','PYTHONPATH':'/scratch','PYTHONDONTWRITEBYTECODE':'1','TZ':'UTC','LANG':'C.UTF-8'}

def http(url,body=None,key=None):
    headers={'Content-Type':'application/json','User-Agent':'monori-pilot'}
    if key:headers['X-Session-API-Key']=key
    with urlopen(Request(url,headers=headers,data=None if body is None else json.dumps(body).encode()),timeout=25) as r:return json.load(r)
def api(route,body=None):return http('http://localhost:8000/api/'+route,body,Path('/session-key').read_text().strip())
def run(cmd,success=True,timeout=150):
    p=subprocess.run(cmd,cwd=REPO if REPO.exists() else '/scratch',env=ENV,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
    if success and p.returncode:raise RuntimeError(str(cmd[0])+' failed: '+p.stdout[-450:])
    return p

def init():
    with contextlib.closing(sqlite3.connect(DB)) as d, d:
        d.execute('create table if not exists cards(name text primary key,state text,cid text,attempt int,due real,detail text,pr integer)');d.execute('create table if not exists transitions(t real,name text,state text,note text)')
        d.execute('create table if not exists scans(name text, mid text, verdict text, primary key(name,mid))');d.execute('create table if not exists evidence(name text primary key, value text)')
        d.execute('create table if not exists rejections(name text, mid text, pair text, reason text, primary key(name,mid,pair))')
        for name in reversed(CARDS):d.execute('insert or ignore into cards values(?,?,?,0,0,?,null)',(name,'screen','',''))
def state():
    with contextlib.closing(sqlite3.connect(DB)) as d, d:
        d.row_factory=sqlite3.Row;return [dict(r) for r in d.execute('select * from cards order by rowid')]
def save(c,phase,note='',**kw):
    fields={'state':phase,'detail':note[:1000],**kw}; assert fields.keys()<={'state','detail','pr','due','cid','attempt'}
    with contextlib.closing(sqlite3.connect(DB)) as d, d:
        d.execute('update cards set '+','.join(k+'=?' for k in fields)+' where name=?',(*fields.values(),c['name']));d.execute('insert into transitions values(?,?,?,?)',(time.time(),c['name'],phase,note[:1000]))
    print(c['name'],phase,flush=True)

def fixture():
    if not (REPO/'.git').exists():
        shutil.rmtree(REPO,ignore_errors=True);run(['git','clone','--depth=1','https://github.com/alchemmist/monori.git',str(REPO)])
    if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE:raise ValueError('base changed; review new fixture')
    lock=gzip.decompress(Path('/code/uv.lock.gz').read_bytes())
    if hashlib.sha256(lock).hexdigest()!='58013ce07ee72defe4e946f74c84c5f9e6cb50ebc7f7fe352cc625522624bf3a':raise RuntimeError('independent dependency lock drift')
    (REPO/'uv.lock').write_bytes(lock)
    run(['git','reset','--hard',BASE]);run(['git','clean','-fd','--','server/tests/unit']);run(['uv','sync','--locked','--group','test'],timeout=360)

def render(name,data):
    if not isinstance(data,dict) or set(data)!={'input','expected','why'} or not isinstance(data['why'],str) or not 8<=len(data['why'])<=500:raise ValueError('provide input, expected, why')
    x=data['input'];y=data['expected'];assert y is None or type(y) is int and abs(y)<10**12
    if name=='day_number':
        assert type(x) is str and len(x)==10;assert re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',x);datetime.date.fromisoformat(('2000'+x[4:]) if x.startswith('0000-') else x);assert type(y) is int
        imp='from monori.server.app.transfer_match import day_number';call=f'day_number({json.dumps(x)})';setup=''
    else:
        assert x is None or type(x) is int and abs(x)<10**8 or type(x) is str and 0<len(x)<=32 and x.isprintable() and not x.startswith('=')
        imp='from openpyxl import Workbook\n\nfrom monori.server.app.workbook.parser import _amount';call='_amount(cell)';setup=f'    cell = Workbook().active.cell(1, 1, value={json.dumps(x,ensure_ascii=False) if isinstance(x,str) else repr(x)})\n'
    return f'# Copyright (c) 2026\n"""Regression coverage for {name.strip("_")}."""\n\n{imp}\n\n\ndef test_{name.strip("_")}_regression() -> None:\n{setup}    assert {call}'+(' is None' if y is None else f' == {y}')+'\n'

def pair(data):return json.dumps([data['input'],data['expected']],ensure_ascii=False,separators=(',',':'))

def rejected(name,mid,data):
    return sql('select reason from rejections where name=? and mid=? and pair=?',(name,mid,pair(data)))

def measured(name,data):
    # Fixed trusted program; case data is passed as JSON argv, never as code.
    runner="""import json,sys
from monori.server.app.transfer_match import day_number
from monori.server.app.workbook.parser import _amount
from openpyxl import Workbook
name,x=json.loads(sys.argv[1]);result=day_number(x) if name=='day_number' else _amount(Workbook().active.cell(1,1,value=x));print(json.dumps(result))"""
    val=json.loads(run(['.venv/bin/python','-c',runner,json.dumps([name,data['input']])]).stdout);assert val is None or type(val) is int;return json.dumps(val)

def verify(c,data,chosen):
    name=c['name'];text=render(name,data);fixture();src,suite=CARDS[name];file=REPO/src;orig=file.read_text();node=next(n for n in ast.parse(orig).body if isinstance(n,ast.FunctionDef) and n.name==name);lines=orig.splitlines(keepends=True);fn=''.join(lines[node.lineno-1:node.end_lineno]);dest='server/tests/unit/test_'+name.strip('_')+'_pilot_regression.py';path=REPO/dest;assert not path.exists();path.write_text(text);pytest=['.venv/bin/python','-m','pytest','-q','--tb=short','--disable-warnings'];testname='test_'+name.strip('_')+'_regression';
    def test(args):return run(pytest+args,False,timeout=120)
    try:
        if test([dest]).returncode:raise ValueError('unmodified main returned '+measured(name,data)+'; expected '+json.dumps(data['expected']))
        for mid,(a,b) in CAT[name].items():
            if mid!=chosen or fn.splitlines().count(a)!=1:continue
            mutated=fn.replace(a+'\n',b+'\n',1);file.write_text(''.join(lines[:node.lineno-1])+mutated+''.join(lines[node.end_lineno:]));shutil.rmtree(file.parent/'__pycache__',ignore_errors=True)
            p=test([dest]);
            if p.returncode!=1 or not re.search(r'AssertionError|^E\s+assert ',p.stdout,re.M) or f'FAILED {dest}::{testname}' not in p.stdout:continue
            p=test(suite);oldpass=re.search(r'(\d+) passed',p.stdout)
            if p.returncode or not oldpass:continue
            file.write_text(orig);shutil.rmtree(file.parent/'__pycache__',ignore_errors=True);p=test(suite+[dest]);green=re.search(r'(\d+) passed',p.stdout)
            if p.returncode or not green:raise ValueError('original focused suite not green')
            return dest,text,f'{mid}: old focused tests {oldpass[1]} passed on mutant; new assertion failed; original {green[1]} passed'
        raise ValueError('case passed on main but did not establish an assertion kill of '+chosen)
    finally:file.write_text(orig);path.unlink(missing_ok=True)

def sql(q,args=()):
    with contextlib.closing(sqlite3.connect(DB)) as d,d:return d.execute(q,args).fetchall()

def target(c):
    rows=sql("select mid from scans where name=? and verdict='survived' order by rowid limit 1",(c['name'],));return rows[0][0] if rows else None

def screen(c):
    name=c['name'];src,suite=CARDS[name];fixture();file=REPO/src;orig=file.read_text();lines=orig.splitlines(keepends=True);n=next(n for n in ast.parse(orig).body if isinstance(n,ast.FunctionDef) and n.name==name);fn=''.join(lines[n.lineno-1:n.end_lineno]);seen=dict(sql('select mid,verdict from scans where name=?',(name,)))
    def test():return run(['.venv/bin/python','-m','pytest','-q','--tb=no',*suite],False,120)
    baseline=test()
    if baseline.returncode or not re.search(r'\d+ passed',baseline.stdout):raise RuntimeError('baseline suite not green')
    if target(c):save(c,'queued','Restored survivor '+target(c));return
    try:
        for mid,(a,b) in CAT[name].items():
            if mid in seen:continue
            if fn.splitlines().count(a)!=1:raise ValueError('catalog no longer matches pinned code')
            file.write_text(''.join(lines[:n.lineno-1])+fn.replace(a+'\n',b+'\n',1)+''.join(lines[n.end_lineno:]));shutil.rmtree(file.parent/'__pycache__',ignore_errors=True)
            try:r=test()
            except subprocess.TimeoutExpired:verdict='timeout'
            else:
                if r.returncode==0 and re.search(r'\d+ passed',r.stdout):verdict='survived'
                elif r.returncode==1 and re.search(r'\d+ failed',r.stdout):verdict='killed'
                else:raise RuntimeError('invalid pytest completion')
            sql('insert into scans values(?,?,?)',(name,mid,verdict));
            if verdict=='survived':save(c,'queued',mid+' survived existing focused tests');return
        save(c,'exhausted','No remaining actionable survivors in this pinned catalog; inspect per-mutant results')
    finally:file.write_text(orig);shutil.rmtree(file.parent/'__pycache__',ignore_errors=True)

def current():return next((c for c in state() if c['state'] not in ('published','blocked','exhausted')),None)
ROUTES={'screen':'screen','queued':'assign','authoring':'collect','proposed':'verify','verified':'publish'}
def decision():
    c=current()
    return ROUTES.get(c['state'],'hold') if c and c['due']<=time.time() and not LOCK.locked() else 'hold'

def step(action):
    c=current()
    if not c or ROUTES.get(c['state'])!=action or c['due']>time.time():return
    name=c['name'];cid=c['cid'];conv='conversations/'+cid
    if action=='screen':screen(c);return
    mid=target(c)
    if not mid:raise ValueError('missing independently reproduced survivor')
    if action=='assign':
        if c['attempt']>=4:
            sql("update scans set verdict='inconclusive' where name=? and mid=? and verdict='survived'",(name,mid));save(c,'screen','Budget exhausted for '+mid+'; not classified as equivalent.',attempt=0,cid='',due=0);return
        cid=str(uuid.uuid5(uuid.NAMESPACE_URL,RUN+'-feedback-'+name+mid+str(c['attempt'])));conv='conversations/'+cid
        prof=api('agent-profiles/socrat-pilot-proposer')['profile'];assert prof['llm_profile_ref']==MODEL
        try:j=api(conv)
        except HTTPError as e:
            if e.code!=404:raise
            api('conversations',{'conversation_id':cid,'workspace':{'kind':'LocalWorkspace','working_dir':WROOT+'/'+name+'/monori'},'agent_profile_id':prof['id'],'autotitle':False,'max_iterations':20});j=api(conv)
        assert j['agent']['llm']['model']=='openai/'+MODEL
        facts=json.loads(Path('/code/facts.json').read_text())[name]
        prompt=(f'You are the test-case author for {name} in #509. No tools, no commands, no prose. '
                f'Code and regression tests from immutable {BASE}:\n{facts}\n'
                f'Existing focused tests PASSED on exact mutant {mid}. Original line / mutated line: {json.dumps(CAT[name][mid])}. Target this specific behavioral difference. Choose one non-duplicate case with a real observable contract. Input is '+
                ('a YYYY-MM-DD date' if name=='day_number' else 'the scalar value of an openpyxl cell')+
                '. The judge independently runs pytest. Use only one JSON object, exactly these keys: '
                '{"input": ..., "expected": integer or null, "why":"short reason"}. Previous rejection: '+c['detail'][:450])
        prompt+='\nRejected [input,expected] pairs on this exact mutant and measured feedback; do not repeat: '+json.dumps(sql('select pair,reason from rejections where name=? and mid=? order by rowid desc limit 6',(name,mid)),ensure_ascii=False)[:2400]
        ev=api(conv+'/events/search?limit=4&sort_order=TIMESTAMP_DESC')['items'];
        if not any(e.get('source') in ('user','agent') for e in ev) and j['execution_status'] not in ('running','finished'):api(conv+'/events',{'role':'user','content':[{'type':'text','text':prompt}],'run':True})
        save(c,'authoring','Awaiting independent case',cid=cid,attempt=c['attempt']+1,due=time.time()+20);return
    if action=='collect':
        j=api(conv);st=j['execution_status'];es=api(conv+'/events/search?limit=20&sort_order=TIMESTAMP_DESC')['items'];
        if st=='paused':return
        if st=='error':
            e=next((e for e in es if e['kind']!='ConversationStateUpdateEvent'),{});detail=e.get('detail','');
            if e.get('code')=='LLMRateLimitError' and ('max_parallel_requests' in detail):
                if c['detail'].startswith('Capacity wait'):api(conv+'/run',{});save(c,'authoring','Resumed after capacity wait',due=time.time()+120)
                else:save(c,'authoring','Capacity wait',due=time.time()+180)
            elif e.get('code')=='MaxIterationsReached':save(c,'queued','Attempt ended without a proposal; provide JSON only.',due=time.time()+30)
            else:save(c,'blocked','Executor stopped: '+str(e.get('code') or e['kind']))
            return
        if st!='finished':return
        e=next((e for e in es if e['kind']=='MessageEvent' and e['source']=='agent'),{});s=' '.join(x.get('text','') for x in e.get('llm_message',{}).get('content',[]) if isinstance(x,dict)).strip();s=re.sub(r'^```(?:json)?\s*|\s*```$','',s)
        try:data=json.loads(s);render(name,data)
        except (AssertionError,ValueError,TypeError) as err:save(c,'queued','Invalid scalar proposal: '+str(err)[:180],due=time.time()+30);return
        previous=rejected(name,mid,data)
        if previous:save(c,'queued','Duplicate rejected before pytest: '+pair(data)+'; '+previous[0][0],due=time.time()+30);return
        sql('insert or replace into evidence values(?,?)',(name,json.dumps({'proposal':data})));save(c,'proposed','Proposal received for '+mid);return
    record=json.loads(sql('select value from evidence where name=?',(name,))[0][0]);
    if action=='verify':
        try:dest,text,receipt=verify(c,record['proposal'],mid)
        except (AssertionError,ValueError) as err:
            sql('insert or replace into rejections values(?,?,?,?)',(name,mid,pair(record['proposal']),str(err)[:350]));save(c,'queued',str(err)+'; rejected: '+pair(record['proposal']),due=time.time()+30);return
        sql('update evidence set value=? where name=?',(json.dumps({**record,'result':[dest,text,receipt]}),name));save(c,'verified',receipt);return
    dest,text,receipt=record['result']
    payload={'action':'create','head':BASE,'title':'test: cover '+name.strip('_')+' regression (#509)','files':{dest:text}};payload['proof']=hmac.new(Path('/proof/key').read_bytes(),json.dumps(payload,sort_keys=True).encode(),'sha256').hexdigest();save(c,'publishing',receipt)
    pr=http('http://monori-publisher:8081/v1',payload);save(c,'published',receipt,pr=pr['pr'])

def background(action):
    try:step(action)
    except Exception as ex:
        c=current()
        if c and c['state']!='publishing':save(c,'blocked','Stage '+action+' failed: '+type(ex).__name__+' '+str(ex)[:250])
        print('stage failure',action,type(ex).__name__,flush=True)
    finally:LOCK.release()
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        action=self.path.lstrip('/')
        if action not in {*ROUTES.values(),'status','tick'} or self.headers.get('Transfer-Encoding') or int(self.headers.get('Content-Length',0))!=0:self.send_error(400);return
        if action==decision() and LOCK.acquire(False):threading.Thread(target=background,args=(action,),daemon=True).start()
        raw=json.dumps({'next':decision(),'cards':state(),'screened':sql('select name,verdict,count(*) from scans group by name,verdict')}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def log_message(self,*a: object) -> None:pass
if __name__=='__main__':init();ThreadingHTTPServer(('0.0.0.0',8083),Handler).serve_forever()
