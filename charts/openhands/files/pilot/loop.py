"""Two-card #509 pilot. Only validated scalar cases cross the executor/judge boundary."""
import ast, contextlib, datetime, hashlib, hmac, json, os, re, shutil, sqlite3, subprocess, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE='61ca009312ee850c70cd87ed4c60296e2a78abcc'
CARDS={'day_number':('server/app/transfer_match.py',['server/tests/unit/test_transfer_match.py']), '_amount':('server/app/workbook/parser.py',['server/tests/unit/test_workbook_parser.py','server/tests/unit/test_workbook_parser_mutation.py'])}
MODEL='v-deepseek-uc'; DB='/state/loop.db'; REPO=Path('/scratch/monori'); WROOT='/home/openhands/workspace/monori-pilot-v1'; LOCK=threading.Lock()
CAT=json.loads(Path('/code/mutants.json').read_text()); RUN='mutation-pilot-v1'; ENV={'PATH':os.environ['PATH'],'HOME':'/scratch','UV_CACHE_DIR':'/scratch/uv-cache','PYTHONPATH':'/scratch','PYTHONDONTWRITEBYTECODE':'1','TZ':'UTC','LANG':'C.UTF-8'}

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
    with sqlite3.connect(DB) as d:
        d.execute('create table if not exists cards(name text primary key,state text,cid text,attempt int,due real,detail text,pr integer)');d.execute('create table if not exists transitions(t real,name text,state text,note text)')
        for name in CARDS:d.execute('insert or ignore into cards values(?,?,?,0,0,?,null)',(name,'queued','',''))
def state():
    with sqlite3.connect(DB) as d:
        d.row_factory=sqlite3.Row;return [dict(r) for r in d.execute('select * from cards order by rowid')]
def save(c,phase,note='',**kw):
    fields={'state':phase,'detail':note[:1000],**kw}; assert fields.keys()<={'state','detail','pr','due','cid','attempt'}
    with sqlite3.connect(DB) as d:
        d.execute('update cards set '+','.join(k+'=?' for k in fields)+' where name=?',(*fields.values(),c['name']));d.execute('insert into transitions values(?,?,?,?)',(time.time(),c['name'],phase,note[:1000]))
    print(c['name'],phase,flush=True)

def fixture():
    if not (REPO/'.git').exists():
        shutil.rmtree(REPO,ignore_errors=True);run(['git','clone','--depth=1','https://github.com/alchemmist/monori.git',str(REPO)])
    if run(['git','rev-parse','HEAD']).stdout.strip()!=BASE:raise ValueError('base changed; review new fixture')
    run(['git','reset','--hard',BASE]);run(['git','clean','-fd','--','server/tests/unit']);run(['uv','sync','--locked','--group','test'],timeout=360)

def render(name,data):
    if not isinstance(data,dict) or set(data)!={'input','expected','why'} or not isinstance(data['why'],str) or not 8<=len(data['why'])<=500:raise ValueError('provide input, expected, why')
    x=data['input'];y=data['expected'];assert y is None or type(y) is int and abs(y)<10**12
    if name=='day_number':
        assert type(x) is str and len(x)==10;datetime.date.fromisoformat(x);assert type(y) is int
        imp='from monori.server.app.transfer_match import day_number';call=f'day_number({json.dumps(x)})';setup=''
    else:
        assert x is None or type(x) is int and abs(x)<10**8 or type(x) is str and 0<len(x)<=32 and x.isprintable() and not x.startswith('=')
        imp='from openpyxl import Workbook\n\nfrom monori.server.app.workbook.parser import _amount';call='_amount(cell)';setup=f'    cell = Workbook().active.cell(1, 1, value={json.dumps(x,ensure_ascii=False) if isinstance(x,str) else repr(x)})\n'
    return f'# Copyright (c) 2026\n"""Regression coverage for {name.strip("_")}."""\n\n{imp}\n\n\ndef test_{name.strip("_")}_regression() -> None:\n{setup}    assert {call}'+(' is None' if y is None else f' == {y}')+'\n'

def verify(c,data):
    name=c['name'];text=render(name,data);fixture();src,suite=CARDS[name];file=REPO/src;orig=file.read_text();node=next(n for n in ast.parse(orig).body if isinstance(n,ast.FunctionDef) and n.name==name);lines=orig.splitlines(keepends=True);fn=''.join(lines[node.lineno-1:node.end_lineno]);dest='server/tests/unit/test_'+name.strip('_')+'_pilot_regression.py';path=REPO/dest;assert not path.exists();path.write_text(text);pytest=['.venv/bin/python','-m','pytest','-q','--tb=short','--disable-warnings'];testname='test_'+name.strip('_')+'_regression';
    def test(args):return run(pytest+args,False,timeout=120)
    try:
        if test([dest]).returncode:raise ValueError('new test fails on unmodified main')
        for mid,(a,b) in CAT[name].items():
            if fn.splitlines().count(a)!=1:continue
            mutated=fn.replace(a+'\n',b+'\n',1);file.write_text(''.join(lines[:node.lineno-1])+mutated+''.join(lines[node.end_lineno:]));shutil.rmtree(file.parent/'__pycache__',ignore_errors=True)
            p=test([dest]);
            if p.returncode!=1 or not re.search(r'AssertionError|^E\s+assert ',p.stdout,re.M) or f'FAILED {dest}::{testname}' not in p.stdout:continue
            p=test(suite);oldpass=re.search(r'(\d+) passed',p.stdout)
            if p.returncode or not oldpass:continue
            file.write_text(orig);shutil.rmtree(file.parent/'__pycache__',ignore_errors=True);p=test(suite+[dest]);green=re.search(r'(\d+) passed',p.stdout)
            if p.returncode or not green:raise ValueError('original focused suite not green')
            return dest,text,f'{mid}: old focused tests {oldpass[1]} passed on mutant; new assertion failed; original {green[1]} passed'
        raise ValueError('no surviving catalog mutant killed by this case in focused baseline suite')
    finally:file.write_text(orig);path.unlink(missing_ok=True)

def tick():
    c=next((c for c in state() if c['state'] not in ('published','blocked')),None)
    if not c or c['state']=='publishing' or c['due']>time.time():return
    name=c['name'];phase=c['state'];cid=c['cid'];conv='conversations/'+cid
    if phase=='queued':
        if c['attempt']>=4:save(c,'blocked','Four unsuccessful proposals. Inspect action receipts.');return
        cid=str(uuid.uuid5(uuid.NAMESPACE_URL,RUN+name+str(c['attempt'])));conv='conversations/'+cid
        prof=api('agent-profiles/socrat-compact-code')['profile'];assert prof['llm_profile_ref']==MODEL
        try:j=api(conv)
        except HTTPError as e:
            if e.code!=404:raise
            api('conversations',{'conversation_id':cid,'workspace':{'kind':'LocalWorkspace','working_dir':WROOT+'/'+name+'/monori'},'agent_profile_id':prof['id'],'autotitle':False,'max_iterations':20});j=api(conv)
        assert j['agent']['llm']['model']=='openai/'+MODEL
        prompt=f'''#509 mutation pilot, {RUN}/{name}. Work only in {WROOT}/{name}/monori on pinned {BASE}. Read {CARDS[name][0]} and the existing tests {CARDS[name][1]}. No edits, no GitHub calls, no publication. You are the author, another process actually runs the tests. Find one meaningful new input and its correct expected output for {name}. For _amount input is an openpyxl cell value (integer, short string or null); for day_number a valid YYYY-MM-DD. The independent judge tries real mutmut diffs, rejects duplicates already killed, and publishes a generated regression ONLY after red/green. Avoid pytest installations or running a full mutation scan. Conclude with exactly one JSON object only: {{"input":...,"expected":...,"why":"..."}}. Prior attempt: {c['detail'][:450]}'''
        ev=api(conv+'/events/search?limit=4&sort_order=TIMESTAMP_DESC')['items'];
        if not any(e.get('source') in ('user','agent') for e in ev) and j['execution_status'] not in ('running','finished'):api(conv+'/events',{'role':'user','content':[{'type':'text','text':prompt}],'run':True})
        save(c,'authoring','Awaiting independent case',cid=cid,attempt=c['attempt']+1,due=time.time()+20);return
    j=api(conv);st=j['execution_status'];es=api(conv+'/events/search?limit=20&sort_order=TIMESTAMP_DESC')['items'];
    if st=='paused':return
    if st=='error':
        e=next((e for e in es if e['kind']!='ConversationStateUpdateEvent'),{});detail=e.get('detail','');
        if e.get('code')=='LLMRateLimitError' and ('max_parallel_requests' in detail):
            if c['detail'].startswith('Capacity wait'):api(conv+'/run',{});save(c,'authoring','Resumed after capacity wait',due=time.time()+120)
            else:save(c,'authoring','Capacity wait',due=time.time()+180)
        else:save(c,'blocked','Executor stopped: '+str(e.get('code') or e['kind']))
        return
    if st!='finished':return
    e=next((e for e in es if e['kind']=='MessageEvent' and e['source']=='agent'),{});s=' '.join(x.get('text','') for x in e.get('llm_message',{}).get('content',[]) if isinstance(x,dict)).strip();s=re.sub(r'^```(?:json)?\s*|\s*```$','',s)
    try:data=json.loads(s);dest,text,receipt=verify(c,data)
    except (ValueError,AssertionError) as err:save(c,'queued',str(err)+'; prior case '+s[:230],due=time.time()+30);return
    payload={'action':'create','head':BASE,'title':'test: cover '+name.strip('_')+' regression (#509)','files':{dest:text}};payload['proof']=hmac.new(Path('/proof/key').read_bytes(),json.dumps(payload,sort_keys=True).encode(),'sha256').hexdigest();save(c,'publishing',receipt)
    pr=http('http://monori-publisher:8081/v1',payload);save(c,'published',receipt,pr=pr['pr'])

def background():
    try:tick()
    except Exception as ex:
        # No automated retry after an ambiguous publication; phase remains publishing.
        print('pilot step failed',type(ex).__name__,str(ex)[:350],flush=True)
    finally:LOCK.release()
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path!='/tick' or self.headers.get('Transfer-Encoding') or int(self.headers.get('Content-Length',0))!=0:self.send_error(400);return
        if LOCK.acquire(False):threading.Thread(target=background,daemon=True).start()
        raw=json.dumps({'cards':state()}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def log_message(self,*a):pass
if __name__=='__main__':init();ThreadingHTTPServer(('0.0.0.0',8083),Handler).serve_forever()
