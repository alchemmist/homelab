"""Trusted tmux dispatcher. Never run agent code on the SSH host or in publisher."""
import ast,contextlib,fcntl,hashlib,json,os,pathlib,re,sqlite3,subprocess,sys,time
ROOT=pathlib.Path(__file__).resolve().parent;os.chdir(ROOT);os.umask(0o077)
BASE='61ca009312ee850c70cd87ed4c60296e2a78abcc';CAT=json.loads((ROOT/'catalog.json').read_text());
CARDS={'integer_value':('common/json_values.py',['server/tests/unit/test_db_records.py']), '_amount':('server/app/workbook/parser.py',['server/tests/unit/test_workbook_parser.py','server/tests/unit/test_workbook_parser_mutation.py'])}

def cmd(args,data=None,timeout=120,ok=True):
    p=subprocess.run(args,input=data,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout); 
    if ok and p.returncode:raise RuntimeError(f'{args[0]} exit {p.returncode}: '+p.stderr[-500:]+p.stdout[-300:]);
    return p

def k(role,args,data=None,timeout=120,ok=True):return cmd(['kubectl','-n','openhands','exec','-i','deploy/pi-monori-'+role,'-c','sandbox','--',*args],data,timeout,ok)
def sql(q,args=()):
    with contextlib.closing(sqlite3.connect(ROOT/'queue.sqlite')) as d,d:return d.execute(q,args).fetchall()
def phase(name,st,note):
    sql('insert into events values(?,?,?,?)',(time.time(),name,st,note[:2300]));print(time.strftime('%FT%T%z'),name,st,note[:180],flush=True)
def write(role,path,value):k(role,['sh','-ec','cat > "$1"','sh',path],value)
def gitfile(path):return cmd(['git','--git-dir=base.git','show',BASE+':'+path]).stdout
def suite(paths,timeout=220):
    p=k('judge',['sh','-ec','cd /scratch/monori; PYTHONPATH=/scratch exec .venv/bin/python -m pytest -q --tb=short --disable-warnings "$@"','sh',*paths],timeout=timeout,ok=False);return p.returncode,p.stdout[-2800:]

def mutfile(name,src,mid):
    s=gitfile(src);fn=next(n for n in ast.parse(s).body if isinstance(n,ast.FunctionDef) and n.name==name);lines=s.splitlines(keepends=True);a,b=CAT[name][mid];part=lines[fn.lineno-1:fn.end_lineno];idx=[i for i,line in enumerate(part) if line.rstrip('\n')==a];assert len(idx)==1;part[idx[0]]=b+'\n';return ''.join(lines[:fn.lineno-1]+part+lines[fn.end_lineno:])

def inspect_test(text,name):
    if not 30<len(text)<15000:raise ValueError('missing or oversized new regression test')
    tree=ast.parse(text); calls={'integer_value','_amount','Workbook','pytest.raises','str','isinstance','len','type','bool','int','float','dict','list','tuple','set','Cell','Decimal','range','date','pytest.mark.parametrize'};modules={'pytest','datetime','decimal','openpyxl','openpyxl.cell.cell','monori.common.json_values','monori.server.app.workbook.parser'}
    tests=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
    if not tests or any(not isinstance(n,(ast.FunctionDef,ast.Import,ast.ImportFrom,ast.Expr)) for n in tree.body):raise ValueError('new file must be a small isolated regression')
    for n in ast.walk(tree):
        if isinstance(n,(ast.Import,ast.ImportFrom)):
            ms=[n.module] if isinstance(n,ast.ImportFrom) else [a.name for a in n.names]
            if any(m not in modules for m in ms) or any(a.asname or a.name.startswith('__') or a.name=='*' for a in n.names):raise ValueError('unexpected import in test')
        if isinstance(n,(ast.Name,ast.Attribute)) and (getattr(n,'id','').startswith('__') or getattr(n,'attr','').startswith('__')):raise ValueError('dunder forbidden')
        if isinstance(n,(ast.While,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda,ast.Global,ast.Nonlocal,ast.Delete,ast.Try)):raise ValueError('unsupported test construct')
        if isinstance(n,ast.Call):
            called=ast.unparse(n.func)
            if called not in calls and not (isinstance(n.func,ast.Attribute) and n.func.attr in {'cell','search','group'}):raise ValueError('unsupported test call: '+called[:60])
    if not any(isinstance(n,ast.Call) and ast.unparse(n.func)==name for n in ast.walk(tree)):raise ValueError('test must call the assigned function directly')

PUBLISH='''import sys,json,hmac,pathlib,urllib.request as u
x=json.load(sys.stdin);x['proof']=hmac.new(pathlib.Path('/proof/key').read_bytes(),json.dumps(x,sort_keys=True).encode(),'sha256').hexdigest();r=u.urlopen(u.Request('http://monori-publisher:8081/v1',data=json.dumps(x).encode(),headers={'Content-Type':'application/json'}),timeout=75);print(r.read().decode())'''

def packet(name,mid,feedback):
    src,suitefiles=CARDS[name];dest='server/tests/unit/test_pi509_'+name.strip('_')+'.py';a,b=CAT[name][mid];return f'''Implement ONE new focused mutation regression, not a progress report. Monori #509, main {BASE}, target {src}::{name}, ID {mid}. Existing focused suite passed with this mutation. Original line: {a!r}. Replacement: {b!r}. Your workstation is a disposable isolated git worktree, not OpenHands. Inspect the source (including callees), and run experiments with /scratch/monori/.venv/bin/python and PYTHONPATH set to the parent of this worktree. Write an actual pytest regression to the new file {dest}, no other changes. Run it on original and mutant if useful, restore any production edit before exit. Prefer a simple positive or negative behavior assertion. Allowed test style: direct imports of {name}, pytest.raises, pytest.mark.parametrize, integer_value, Workbook/cell etc; no mocks, process/FS/network, broad fixtures or skip. All tests in English, annotated -> None. No gh, publisher, credentials or merge. A separate trusted controller runs old tests on mutant, new test on mutant and suite on original then publishes your test as PR. If genuinely equivalent or duplicate, explain concrete evidence in OUTCOME.md instead of a dummy test. Do not waste time installing packages. Use tools and actually write the test before you finish. Reviewer feedback: {feedback[:800]}'''

def process(name):
    src,olds=CARDS[name];dest='server/tests/unit/test_pi509_'+name.strip('_')+'.py';casepath='/scratch/trees/'+name+'/monori';basepath='/scratch/monori/'+src;testpath='/scratch/monori/'+dest
    def restore() -> None:
        write('judge',basepath,gitfile(src));k('judge',['rm','-f',testpath])
        k('judge',['rm','-rf','/scratch/monori/'+str(pathlib.Path(src).parent/'__pycache__')])
    restore();rc,out=suite(olds);assert not rc and re.search(r'\d+ passed',out),'baseline not green'
    for mid in CAT[name]:
        scanned=dict(sql('select mid,status from scans where card=?',(name,)))
        if mid in scanned and scanned[mid]!='survived':continue
        try:write('judge',basepath,mutfile(name,src,mid));rc,out=suite(olds)
        finally:restore()
        if rc==1 and re.search(r'\d+ failed',out):sql('insert or replace into scans values(?,?,?)',(name,mid,'killed'));continue
        if rc or not re.search(r'\d+ passed',out):raise RuntimeError('unexpected old-suite verdict')
        old_receipt=out.splitlines()[-1];sql('insert or replace into scans values(?,?,?)',(name,mid,'survived'));break
    else:phase(name,'exhausted','No reproduced survivor in bounded catalog.');return
    phase(name,'survivor',mid+' '+old_receipt);k('author',['sh','-ec','test -d "$1" || git --git-dir=/scratch/base.git worktree add --detach "$1" "$2";test "$(git -C "$1" rev-parse HEAD)" = "$2"','sh',casepath,BASE]);feedback='';
    for attempt in range(1,4):
        prior=sql("select note from events where card=? and state=? order by rowid desc limit 1",(name,'reject-'+str(attempt)))
        if prior:feedback=prior[0][0];continue
        task=packet(name,mid,feedback);(ROOT/(name+'.prompt.md')).write_text(task);phase(name,'pi-'+str(attempt),'litellm/v-deepseek-uc '+mid)
        start=time.time();logfile=ROOT/(name+f'-{attempt}.log');argv=['kubectl','-n','openhands','exec','-i','deploy/pi-monori-author','-c','sandbox','--','sh','-ec','cd "$1";export PYTHONPATH="$(dirname "$1")"; exec timeout 950 /opt/pi/node_modules/.bin/pi --provider litellm --model v-deepseek-uc --no-extensions --no-mcp --no-skills --no-prompt-templates --no-context-files --no-session --tools read,bash,edit,write -p "$(cat)"','sh',casepath]
        with logfile.open('wb') as f:
            p=subprocess.run(argv,input=task.encode(),stdout=f,stderr=f,timeout=1000)
        if p.returncode:feedback='Pi exited before handing off a result (exit '+str(p.returncode)+')';phase(name,'reject-'+str(attempt),feedback);time.sleep(65);continue
        try:
            changed=k('author',['git','-C',casepath,'diff','--name-only',BASE]).stdout.strip();assert changed in ('',dest),'unrelated tracked files changed';text=k('author',['python','-c','import sys,pathlib;p=pathlib.Path(sys.argv[1]);assert p.is_file() and not p.is_symlink() and p.stat().st_size<15000;sys.stdout.buffer.write(p.read_bytes())',casepath+'/'+dest]).stdout;inspect_test(text,name)
            (ROOT/(name+f'-{attempt}.py.txt')).write_text(text);write('judge',testpath,text);rc,green=suite([dest]);assert rc==0 and ' passed' in green,'original failed: '+green[-550:]
            write('judge',basepath,mutfile(name,src,mid));rc,red=suite([dest]);assert rc==1 and 'FAILED '+dest+'::test_' in red and re.search(r'AssertionError|^E\s+assert |DID NOT RAISE|Regex pattern did not match',red,re.M),'mutant did not fail at a meaningful assertion: '+red[-480:]
            write('judge',basepath,gitfile(src));rc,green=suite(olds+[dest]);assert rc==0 and ' passed' in green,'combined suite failed: '+green[-480:]
        except (AssertionError,ValueError,SyntaxError,RuntimeError) as err:
            feedback=str(err)[:900];phase(name,'reject-'+str(attempt),feedback);continue
        finally:restore()
        receipt={'base':BASE,'card':name,'mutmut':mid,'old_suite':olds,'old_mutant':old_receipt,'new_mutant':red,'original':green,'file':dest,'sha256':hashlib.sha256(text.encode()).hexdigest()};(ROOT/(name+'-proof.json')).write_text(json.dumps(receipt,indent=2));phase(name,'publishing',mid+' signed proof; on lost ack reconcile manually');payload={'action':'create','head':BASE,'title':'test: pin '+name.strip('_')+' behavior (#509)','files':{dest:text}};r=cmd(['kubectl','-n','openhands','exec','-i','openhands-0','-c','mutation-pilot','--','python','-c',PUBLISH],json.dumps(payload),timeout=95);pr=json.loads(r.stdout);assert pr['pr'] and pr['head'];phase(name,'published',json.dumps(pr));return
    phase(name,'blocked','Three unsuccessful tries; no publication')

def main():
    f=(ROOT/'run.lock').open('a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);assert (ROOT/'seed.ok').exists() and cmd(['git','--git-dir=base.git','rev-parse','HEAD']).stdout.strip()==BASE
    sql('create table if not exists events(t real,card text,state text,note text)');sql('create table if not exists scans(card text,mid text,status text,primary key(card,mid))');
    for name in CARDS:
        last=sql('select state from events where card=? order by rowid desc limit 1',(name,));
        if last and last[0][0] in ('blocked','published','exhausted'):continue
        if last and last[0][0]=='publishing':raise RuntimeError('Ambiguous prior write: reconcile GitHub before resuming')
        process(name)
    print('Two-card pilot finished; no automatic admission of unverified families',flush=True)
if __name__=='__main__':main()
