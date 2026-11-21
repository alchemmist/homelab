"""Full report campaign. Trusted scheduler on socrat-0; no agent or pytest on host."""
import ast
import collections
import contextlib
import difflib
import fcntl
import gzip
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict
import dispatcher as pilot
from artifact import artifact_response

class Task(TypedDict):
 """Queued mutation task loaded from SQLite."""

 id: str
 fam: str
 num: int
 category: str
 base: str
 pr: int | None

class Repair(TypedDict):
 """In-place pull request repair handed to the author."""

 dest: str
 previous: str
 head: str
 fails: list[str]

class GitUser(TypedDict):
 """GitHub user fields read during reconciliation."""

 login: str

class GitHead(TypedDict):
 """GitHub ref fields read during reconciliation."""

 ref: str
 sha: str

class Pull(TypedDict, total=False):
 """Open pull request fields read from the public GitHub API."""

 number: int
 title: str
 state: str
 merged: bool
 draft: bool
 head: GitHead
 user: GitUser
R=pilot.ROOT; 
BASE0=pilot.BASE; 
D=R/'campaign.sqlite'; 
A=R/'campaign-artifacts';
A.mkdir(exist_ok=True); 
C=json.load(gzip.open(R/'catalog-full.json.gz')); 
BACK=json.loads((R/'backlog.json').read_text()); 
J='/scratch/monori/'; 
K=pilot.k

ISSUE=509

def query(q: str,a: Sequence[object]=()):
 with contextlib.closing(sqlite3.connect(D,timeout=15)) as db,db:
  db.row_factory=sqlite3.Row;
  return [dict(x) for x in db.execute(q,a)]
def init():
 global C,A
 query('create table if not exists tasks(id text primary key,fam text,num integer,category text,ord integer,state text,base text,note text,pr integer,updated real)');
 query('create table if not exists audit(t real,id text,state text,note text)');
 query('create table if not exists meta(k text primary key,v text)')
 wave=query("select v from meta where k='active_census'")
 if wave:
  root=R/'waves'/wave[0]['v'];
  C=json.load(gzip.open(root/'catalog.json.gz'));
  A=root/'artifacts';
  A.mkdir(exist_ok=True);
  return
 with contextlib.closing(sqlite3.connect(D)) as db,db:
  for r in BACK:
   fam,_,single=r['family'].partition('__mutmut_');
   f=C.get(fam);
   nums=[single] if single else list(f['diffs']) if f else ['0'];
   for num in nums:
    uid=fam+'__mutmut_'+num;
    priority=int(r['id']);
    if fam.endswith('common.json_values.x_optional_string'):priority=-3
    if fam.endswith('server.app.importer.x_parse_amount_kop'):priority=-2
    if fam.endswith('server.app.workbook.spec.x_kop_from_rub'):priority=-1
    db.execute('insert or ignore into tasks values(?,?,?,?,?,?,?,?,?,?)',(uid,fam,int(num),r['section'],priority,'queued' if f and num in f['diffs'] else 'catalog_drift','','',None,0))
 # Seed actual published pilot coverage, never re-publish it.
 for name in ('integer_value','_amount'):
  proof=R/(name+'-proof.json');
  if proof.exists():
   published=pilot.sql("select note from events where card=? and state='published' order by rowid desc limit 1",(name,));
   if published:
    v=json.loads(proof.read_text());
    uid=next((k for k in C if k.endswith('.x_'+name)),None)
    if uid:query("update tasks set state='published',pr=?,base=?,note=? where id=? and state='queued'",(json.loads(published[0][0])['pr'],v['base'],'pilot proof',uid.rsplit('.',1)[0]+'.'+v['mutmut']))

def mark(t: Task,state: str,note: str='',base: str | None=None,pr: int | None=None):
 q=(state,note[:1500],base or t['base'],pr or t['pr'],time.time(),t['id']);
 query('update tasks set state=?,note=?,base=?,pr=?,updated=? where id=?',q);
 query('insert into audit values(?,?,?,?)',(time.time(),t['id'],state,note[:1500]));
 print(time.strftime('%FT%T%z'),state,t['id'],note[:120].replace('\n',' '),flush=True)
def key(t: Task):return hashlib.sha256(t['id'].encode()).hexdigest()[:12]
def remote_json(path: str):
 # Public GET only; no publisher/host credentials in workers.
 import urllib.request
 with urllib.request.urlopen(urllib.request.Request('https://api.github.com/repos/alchemmist/monori/'+path,headers={'User-Agent':'socrat-campaign'}),timeout=15) as r:return json.load(r)
def git(*a):return pilot.cmd(['git','--git-dir=base.git',*a]).stdout
def source(sha: str,file: str):return git('show',sha+':'+file)

def patch(t: Task,sha: str):
 f=C[t['fam']];
 file=f['file'];
 s=source(sha,file);
 old=''.join(f['old']);
 start,end,repl=f['diffs'][str(t['num'])];
 mut=''.join(f['old'][:start]+repl+f['old'][end:]);
 if not old or s.count(old)!=1:raise ValueError('Generated function body not unique/exact on current base; refresh required')
 return file,s,s.replace(old,mut,1),''.join(difflib.unified_diff(old.splitlines(True),mut.splitlines(True),n=3))

def select_suite(t: Task,sha: str):
 mod=C[t['fam']]['file'];
 leaf=Path(mod).stem;
 func=t['fam'].split('.')[-1].split('ǁ')[-1];
 func=func.removeprefix('x_');
 area='ci/tests' if mod.startswith('ci/') else 'server/tests/unit';
 files=git('ls-tree','-r','--name-only',sha,'--',area).splitlines();
 tests=[p for p in files if Path(p).name.startswith('test_') and p.endswith('.py')];
 module=mod[:-3].replace('/','.');
 p=pilot.cmd(['git','--git-dir=base.git','grep','-l','-F',module,sha,'--',area],ok=False);
 imports={line.split(':',1)[-1] for line in p.stdout.splitlines()};
 p=pilot.cmd(['git','--git-dir=base.git','grep','-l','-Fw',func,sha,'--',area],ok=False);
 refs={line.split(':',1)[-1] for line in p.stdout.splitlines()};
 top=sorted(tests,key=lambda p:(-(10*(p in imports)+6*(p in refs)+4*(leaf in Path(p).stem)),p));
 direct=[p for p in top if p in imports|refs or leaf in Path(p).stem];
 return (direct[:6] or [area]),area

def sandbox_write(path: str,text: str):pilot.write('judge',J+path,text)
def reset_source(src: str,original: str):
 sandbox_write(src,original);
 K('judge',['rm','-rf',J+str(Path(src).parent/'__pycache__')])
def tests(paths: Sequence[str],limit: int=250):
 r=K('judge',['sh','-ec','cd /scratch/monori; export PYTHONPATH=/scratch PYTHONDONTWRITEBYTECODE=1;exec timeout -k 5 "$1" .venv/bin/python -m pytest -q --tb=short --disable-warnings -m "not integration" "${@:2}"'.replace('"${@:2}"','"$@"').replace('exec timeout -k 5 "$1"','budget=$1;shift;exec timeout -k 5 "$budget"'),'sh',str(limit),*paths],timeout=limit+25,ok=False);
 return r.returncode,r.stdout[-5000:]
def green(p: tuple[int, str]):return p[0]==0 and bool(re.search(r'\b[1-9]\d* passed',p[1]))
def killed(p: tuple[int, str]):return p[0]==1 and bool(re.search(r'\b[1-9]\d* failed',p[1]))

def install_base(sha: str):
 """Stream tracked files only. No untrusted tar input on the SSH host."""
 for file in ('pyproject.toml','server/pyproject.toml','common/pyproject.toml','ci/pyproject.toml'):
  if source(sha,file)!=source(BASE0,file):raise RuntimeError('dependency drift: rebuild locked offline verifier before admitting this base')
 prep=K('judge',['sh','-ec','cd /scratch/monori; if test -f /scratch/campaign-base && test "$(cat /scratch/campaign-base)" = "$1";then echo ready;fi','sh',sha]);
 if 'ready' not in prep.stdout:
  with subprocess.Popen(['git','--git-dir=base.git','archive',sha],stdout=subprocess.PIPE) as inp:
   subprocess.run(['kubectl','-n','openhands','exec','-i','deploy/pi-monori-judge','-c','sandbox','--','sh','-ec','cd /scratch/monori; find . -mindepth 1 -maxdepth 1 ! -name .venv -exec rm -rf -- {} +;tar xf -;echo "$1" >/scratch/campaign-base','sh',sha],stdin=inp.stdout,check=True,timeout=120);
   assert inp.wait()==0
 # Author fetches public main; no host key or git credential is passed in.
 K('author',['sh','-ec','git --git-dir=/scratch/base.git cat-file -e "$1^{commit}" 2>/dev/null || git --git-dir=/scratch/base.git fetch --depth=1 https://github.com/alchemmist/monori.git main','sh',sha])

def candidate_guard(text: str,src: str):
 if not 40<len(text)<20000:raise ValueError('missing/oversized candidate')
 if re.search(r'#\s*(?:type:\s*ignore|noqa|nosec)',text):raise ValueError('repo forbids lint/type suppressions')
 tree=ast.parse(text)
 if any(isinstance(n,ast.arg) and n.annotation and any(isinstance(a,ast.Name) and a.id in {'object','Any'} for a in ast.walk(n.annotation)) for n in ast.walk(tree)):raise ValueError('use a concrete project type, not object/Any')
 allowed=('monori.'+src.partition('/')[0]+'.','monori.common.');
 safe={'pytest','datetime','decimal','collections','dataclasses','typing','pathlib','io','json','re','math','unittest.mock','openpyxl','sqlite3','uuid'}
 if not any(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in tree.body):raise ValueError('missing test')
 for n in ast.walk(tree):
  if isinstance(n,(ast.Import,ast.ImportFrom)):
   mods=[n.module or ''] if isinstance(n,ast.ImportFrom) else [a.name for a in n.names]
   bad=[m for m in mods if not (m.startswith(allowed) or m in {v.rstrip('.') for v in allowed} or any(m==v or m.startswith(v+'.') for v in safe))]
   if bad:raise ValueError('Outside offline unit-test scope: '+', '.join(bad)+'. Use the target module directly: monori.'+src[:-3].replace('/','.'))
   if any(a.name.startswith('__') or a.name=='*' for a in n.names):raise ValueError('dynamic import')
  if isinstance(n,(ast.Name,ast.Attribute)):
   x=n.id if isinstance(n,ast.Name) else n.attr
   if x.startswith('__') or x in {'eval','exec','compile','globals','locals','exit','quit','getattr','setattr','delattr','skip','skipif','xfail','importorskip','open','read_bytes','read_text','write_bytes','write_text','unlink','system','popen','connect_ex','socket','subprocess','os','sys','builtins','importlib','pytest_plugins'}:raise ValueError('test uses unsupported introspection, I/O or bypass')
  if isinstance(n,ast.Constant) and isinstance(n.value,str) and ('/scratch/' in n.value or '/proc/' in n.value or 'PYTEST_CURRENT_TEST' in n.value):raise ValueError('environment-dependent test')

def try_pi(
 t: Task,
 sha: str,
 mid: str,
 detail: str,
 oldtests: list[str],
 folder: Path,
 repair: Repair | None=None,
):
 src=C[t['fam']]['file'];
 slug=key(t);
 dest=('ci/tests/' if src.startswith('ci/') else 'server/tests/unit/')+'test_mutation_'+slug+'.py';
 wt='/scratch/campaign/'+slug+'/monori';
 folder.mkdir(exist_ok=True);
 K('author',['sh','-ec','if test -d "$1";then git --git-dir=/scratch/base.git worktree remove --force "$1";fi;git --git-dir=/scratch/base.git worktree prune;git --git-dir=/scratch/base.git worktree add --detach "$1" "$2"','sh',wt,sha]);
 feedback=''
 if repair:
  dest=repair['dest'];
  pilot.write('author',wt+'/'+dest,repair['previous']);
  feedback='Repair this existing PR test in place, retain the behavioral assertion and remove all lint suppressions. Red current-head checks: '+', '.join(repair['fails'])
 try:
  for attempt in range(1,4):
   prompt=f"""Take one atomic item from alchemmist/monori#{ISSUE}: {t['category']}, {mid}, base {sha}. Work directly in this worktree. Keep this atomic: prefer one direct assertion or a small parametrized test of the assigned symbol, not separate caller/integration tests. Import from monori.{src[:-3].replace(chr(47),chr(46))} or pytest. Write an actual English annotated regression test to {dest} and no other tracked file. Original/mutant diff:\n{detail[:7800]}\nExisting tests {oldtests} passed on both. Read source/dependencies and existing tests, use actual /scratch/monori/.venv/bin/python with PYTHONPATH set to worktree parent, check actual output before proposing. Follow existing formatting and annotation gates: no type: ignore/noqa, no object/Any parameter annotations, prefer the project type alias. No external systems, networking, credentials, exploits, PoCs, bypasses, live banking, gh, merge or dummy PR. Only ordinary offline behavior on fixtures. The independent judge runs your file on original and mutant. If not distinguishable write OUTCOME.md with concrete evidence; not a fictional test. Plans do not count: write your file with tools. Feedback: {feedback[:750]}""";
   (folder/'prompt.md').write_text(prompt);
   mark(t,'authoring',f'attempt {attempt}',sha)
   # Print-mode agents sometimes end with plans. The alternate protocol exchanges a typed
   # file, not a tool invocation; the judge and allowlist are identical on both paths.
   artifact=bool(repair) or attempt>=2 or (not repair and len(C[t['fam']]['old'])<=16)
   if artifact:
    context=''.join(C[t['fam']]['old'])[:7000]
    prompt=f"Return exactly one Markdown ```python block containing the complete new English pytest file. No plan or tool calls. Actual source module: monori.{src[:-3].replace('/', '.')}. Test only this function directly using literal ordinary fixture values. One shortest meaningful test, annotated -> None, no suppressions, skips, arbitrary I/O, or unrelated caller imports. Must pass on original and fail on exact mutant. Source:\n{context}\nOriginal-to-mutant diff:\n{detail[:6000]}\nFeedback: {feedback[:700]}"+(('\nExisting test to repair:\n'+repair['previous'][:5000]) if repair else '')
    (folder/f'artifact-prompt-{attempt}.md').write_text(prompt)
   with (folder/f'pi-{attempt}.log').open('wb') as log:
    res=subprocess.run(['kubectl','-n','openhands','exec','-i','deploy/pi-monori-author','-c','sandbox','--','sh','-ec','cd "$1";export PYTHONPATH="$(dirname "$1")";exec timeout -k 5 900 /opt/pi/node_modules/.bin/pi --provider litellm --model v-deepseek-uc --no-approve --no-extensions --no-mcp --no-skills --no-prompt-templates --no-context-files --no-session $2 -p "$(cat)"','sh',wt,'--no-tools' if artifact else '--tools read,bash,edit,write'],input=prompt.encode(),stdout=log,stderr=log,timeout=950)
   if res.returncode and re.search(rb'unable to upgrade connection|502 Bad Gateway|error dialing backend|i/o timeout', (folder/f'pi-{attempt}.log').read_bytes()[-2000:], re.I):
    mark(t,'transport_wait','kubectl transport unavailable; no model verdict or attempt charged',sha);
    return
   if res.returncode:
    feedback='executor ended without a verified result, exit '+str(res.returncode);
    time.sleep(60);
    continue
   if artifact:
    try:
     proposed=artifact_response((folder/f'pi-{attempt}.log').read_text(errors='replace'));
     candidate_guard(proposed,src)
    except (SyntaxError,ValueError) as err:
     feedback=str(err);
     mark(t,'rejected',feedback,sha);
     continue
    pilot.write('author',wt+'/'+dest,proposed)
   get="import pathlib,sys;p=pathlib.Path(sys.argv[1]);assert p.is_file() and not p.is_symlink() and p.stat().st_size<20000;sys.stdout.write(p.read_text())";
   r=K('author',['python','-c',get,wt+'/'+dest],ok=False)
   if r.returncode:
    outcome=K('author',['python','-c',get,wt+'/OUTCOME.md'],ok=False)
    if not outcome.returncode:
     (folder/'outcome.md').write_text(outcome.stdout);
     mark(t,'needs_triage','Agent supplied explanation; not certified equivalent',sha);
     return
    feedback='No test file exists. Use write tool on exact path now; do not finish with a plan.';
    continue
   # Apply only the repo-pinned formatter to the one proposed file, inside the disposable author sandbox.
   fmt=K('author',['sh','-ec','cd "$1"; f="$2"; r=/scratch/tools/ruff/bin/ruff; test "$("$r" --version)" = "ruff 0.17.5"; "$r" check --fix --no-cache "$f"; "$r" format --no-cache "$f"; "$r" check --no-cache "$f"','sh',wt,dest],ok=False)
   if fmt.returncode:
    feedback='Project Ruff gate failed: '+fmt.stdout[-550:];
    mark(t,'rejected',feedback,sha);
    continue
   text=K('author',['python','-c',get,wt+'/'+dest]).stdout
   try:
    candidate_guard(text,src)
    if repair and text==repair['previous']:raise ValueError('CI repair did not change the failed file')
    changed=K('author',['git','-C',wt,'diff','--name-only',sha]).stdout.strip();
    assert changed in ('',dest),'unrelated edits present';
    receipt=prove(t,sha,dest,text,oldtests)
   except (ValueError,AssertionError,SyntaxError) as ex:
    feedback=str(ex)[-750:];
    mark(t,'rejected',feedback,sha);
    continue
   (folder/'test.py.txt').write_text(text);
   (folder/'proof.json').write_text(json.dumps(receipt,indent=2))
   if repair:
    payload={'action':'update','pr':t['pr'],'head':repair['head'],'title':'test: address current-head CI for #'+str(t['pr']),'files':{dest:text}};
    mark(t,'update_uncertain','Update in flight; inspect current head if acknowledgement lost',sha)
    r=pilot.cmd(['kubectl','-n','openhands','exec','-i','openhands-0','-c','mutation-pilot','--','python','-c',pilot.PUBLISH],json.dumps(payload),timeout=95);
    obj=json.loads(r.stdout);
    assert obj['pr']==t['pr'];
    mark(t,'published',obj['head'],sha,obj['pr'])
   else:mark(t,'verified','Independent proof archived; awaiting publisher slot',sha)
   return
  mark(t,'needs_triage','No proof after 3 attempts. '+feedback,sha)
 finally:
  if repair:
   event=query('select state from tasks where id=?',(t['id'],))[0]['state']
   if event not in ('published','update_uncertain','rejected','needs_triage'):mark(t,'published','CI repair attempt did not meet proof; PR remains open',sha,t['pr'])
  K('author',['git','--git-dir=/scratch/base.git','worktree','remove','--force',wt],ok=False)

def prove(t: Task,sha: str,dest: str,text: str,oldtests: list[str]):
 src,orig,mut,_=patch(t,sha);
 reset_source(src,orig)
 try:
  sandbox_write(dest,text);
  a=tests([dest]);
  assert green(a),'original did not pass: '+a[1][-450:];
  reset_source(src,mut);
  b=tests(['--ignore='+dest,*oldtests]);
  assert green(b),'old suite did not survive independently: '+b[1][-260:];
  red=tests([dest]);
  assert killed(red) and 'FAILED '+dest+'::test_' in red[1] and re.search(r'AssertionError|^E\s+assert |DID NOT RAISE|Regex pattern did not match',red[1],re.M),'no assertion kill: '+red[1][-450:];
  reset_source(src,orig);
  g=tests(oldtests if any(dest.startswith(p.rstrip('/')+'/') for p in oldtests) else oldtests+[dest]);
  assert green(g),'combined original failed: '+g[1][-450:];
  return {'base':sha,'mutant':t['id'],'dest':dest,'sha256':hashlib.sha256(text.encode()).hexdigest(),'old_suite':oldtests,'old_on_mutant':b[1].splitlines()[-1],'new_on_mutant':red[1][-2400:],'original':g[1].splitlines()[-1]}
 finally:
  reset_source(src,orig);
  K('judge',['rm','-f',J+dest])

def screen(t: Task,sha: str):
 try:src,orig,mut,detail=patch(t,sha)
 except (ValueError,KeyError):
  mark(t,'catalog_drift','Cannot apply exact mutation to current main',sha);
  return
 oldtests,area=select_suite(t,sha);
 reset_source(src,orig);
 cache='baseline:'+sha+':'+hashlib.sha256(json.dumps(oldtests).encode()).hexdigest()
 if not query('select v from meta where k=?',(cache,)):
  g=tests(oldtests)
  if not green(g):
   mark(t,'baseline_blocked','Original focused suite not green: '+g[1][-240:],sha);
   return
  query('insert or replace into meta values(?,?)',(cache,g[1].splitlines()[-1]))
 try:
  reset_source(src,mut);
  p=tests(oldtests,50 if t['category']=='Timeouts' else 220)
 finally:reset_source(src,orig)
 if killed(p):
  mark(t,'already_killed',p[1].splitlines()[-1],sha);
  return
 if not green(p):
  mark(t,'timeout_triage' if p[0] in (124,137) else 'needs_triage','Focused suite exit '+str(p[0])+'; not counted as fixed',sha);
  return
 # Prior proven test on a sibling mutation may already cover this one. Do not open a duplicate PR.
 for prior in query("select * from tasks where fam=? and state in ('verified','published','merged')",(t['fam'],)):
  folder=A/key(prior);
  pf=folder/'proof.json';
  tf=folder/'test.py.txt'
  if not pf.exists() or not tf.exists():continue
  receipt=json.loads(pf.read_text())
  if receipt['base']!=sha:continue
  try:prove(t,sha,receipt['dest'],tf.read_text(),oldtests)
  except (AssertionError,ValueError):continue
  mark(t,'covered_pending_merge','Covered by '+prior['id'],sha,prior['pr']);
  return
 mark(t,'survived',p[1].splitlines()[-1],sha);
 try_pi(t,sha,t['id'],detail,oldtests,A/key(t))

def publish(t: Task,sha: str):
 folder=A/key(t);
 receipt=json.loads((folder/'proof.json').read_text());
 text=(folder/'test.py.txt').read_text();
 assert hashlib.sha256(text.encode()).hexdigest()==receipt['sha256'];
 dest=receipt['dest']
 if receipt['base']!=sha:
  oldtests,_=select_suite(t,sha)
  try:receipt=prove(t,sha,dest,text,oldtests)
  except (AssertionError,ValueError):
   mark(t,'rebase_triage','Proof no longer holds on new main',sha);
   return
  (folder/'proof.json').write_text(json.dumps(receipt,indent=2))
 title='test: cover '+t['fam'].split('.')[-1].replace('ǁ','.')[:60]+f' [{ISSUE}:'+key(t)+']';
 payload={'action':'create','issue':ISSUE,'head':sha,'title':title,'files':{dest:text}};
 mark(t,'publishing','Reconcile this unique title on any ambiguous acknowledgement: '+title,sha)
 try:
  r=pilot.cmd(['kubectl','-n','openhands','exec','-i','openhands-0','-c','mutation-pilot','--','python','-c',pilot.PUBLISH],json.dumps(payload),timeout=95);
  obj=json.loads(r.stdout);
  assert obj['pr'] and obj['head']
 except (OSError,ValueError,KeyError,subprocess.SubprocessError,AssertionError):
  mark(t,'publication_uncertain',title,sha);
  return
 (folder/'publication.json').write_text(json.dumps(obj));
 mark(t,'published',obj['head'],sha,obj['pr'])

def reconcile(prs: Sequence[Pull],sha: str):
 open_by={p['number']:p for p in prs}
 # Repair lost acknowledgements by unique title, never replay a blind create.
 for t in query("select * from tasks where state='publication_uncertain'"):
  matches=[p for p in prs if p['title'].endswith(f'[{ISSUE}:'+key(t)+']') and p['head']['ref'].startswith(f'openhands/issue-{ISSUE}/') and p['user']['login']=='alchemmist']
  if len(matches)==1:mark(t,'published',matches[0]['head']['sha'],t['base'],matches[0]['number'])
 if len(prs)>=100:return
 for t in query("select * from tasks where state in ('published','needs_triage') and pr is not null"):
  if t['pr'] in open_by:continue
  p=remote_json('pulls/'+str(t['pr']))
  if p['state']=='closed':mark(t,'merged' if p['merged'] else 'closed_unmerged','GitHub reconciliation; full rerun still required',sha,t['pr'])

def repair_one(prs: Sequence[Pull],sha: str):
 bynum={p['number']:p for p in prs};
 now=time.time()
 for t in query("select * from tasks where state in ('published','needs_triage') and pr is not null order by updated"):
  p=bynum.get(t['pr'])
  if not p or p.get('draft') or not p['head']['ref'].startswith(f'openhands/issue-{ISSUE}/'):continue
  head=p['head']['sha'];
  cache='checks:'+head;
  cached=query('select v from meta where k=?',(cache,))
  if cached and now-float(cached[0]['v'])<900:continue
  query('insert or replace into meta values(?,?)',(cache,str(now)));
  checks=remote_json('commits/'+head+'/check-runs?per_page=100');
  fails=[r['name'] for r in checks['check_runs'] if r['conclusion']=='failure']
  if not fails:continue
  keyfix='fix:'+str(p['number']);
  attempts=query('select v from meta where k=?',(keyfix,))
  if attempts and int(attempts[0]['v'])>=3:continue
  files=remote_json('pulls/'+str(p['number'])+'/files?per_page=30')
  if len(files)!=1 or files[0]['status']!='added' or not re.fullmatch(r'(?:ci/tests|server/tests/unit)/test_(?:mutation_[0-9a-f]{12}|pi509_[a-z_]+)\.py',files[0]['filename']):continue
  dest=files[0]['filename'];
  git('fetch','--depth=1','origin','refs/pull/'+str(p['number'])+'/head');
  previous=source(head,dest);
  src,_,_,diff=patch(t,sha);
  olds,_=select_suite(t,sha)
  query('insert or replace into meta values(?,?)',(keyfix,str(1+(int(attempts[0]['v']) if attempts else 0))));
  folder=A/key(t)/('repair-'+head[:10]);
  folder.mkdir(parents=True,exist_ok=True)
  try_pi(t,sha,t['id'],diff,olds,folder,{'dest':dest,'previous':previous,'head':head,'fails':fails});
  return

def census(sha: str,prs: Sequence[Pull]):
 # No blanket merge; only after queued work drained and GitHub writes reconciled.
 if sha==BASE0 or any(p['head']['ref'].startswith(f'openhands/issue-{ISSUE}/') for p in prs):return False
 if query("select id from tasks where state in ('published','verified','publishing','publication_uncertain','update_uncertain') limit 1"):return False
 token='census:'+sha
 if query('select v from meta where k=?',(token,)):return False
 pre=K('judge',['/scratch/census-venv/bin/python','-m','mutmut','run','--help'],ok=False)
 if pre.returncode:raise RuntimeError('full mutation environment not seeded')
 root=R/'waves'/sha;
 root.mkdir(parents=True,exist_ok=True);
 query('insert into meta values(?,?)',(token,'running'));
 print('full mutation census',sha,flush=True)
 with (root/'mutation.log').open('wb') as log:
  rr=subprocess.run(['kubectl','-n','openhands','exec','deploy/pi-monori-judge','-c','sandbox','--','sh','-ec','cd /scratch/monori; rm -rf mutants; export PATH=/scratch/census-venv/bin:$PATH PYTHONPATH=/scratch;exec timeout -k 30 86400 /scratch/census-venv/bin/python -m mutmut run --max-children 1'],stdout=log,stderr=log,timeout=86500)
 if rr.returncode:
  query('update meta set v=? where k=?',('failed '+str(rr.returncode),token));
  return False
 catalog_source=(R/'index_catalog.py').read_text();
 main_guard=re.search(r"(?m)^if\s+__name__\s*==\s*(['\"])__main__\1\s*:",catalog_source);
 assert main_guard,'index catalog CLI guard missing';
 extractor=catalog_source[:main_guard.start()]+"\nroot=pathlib.Path('/scratch/monori/mutants'); c=extract(root); statuses={k:v for f in root.rglob('*.py.meta') for k,v in json.loads(f.read_text())['exit_code_by_key'].items()};sys.stdout.buffer.write(gzip.compress(json.dumps([c,statuses]).encode()))"
 with (root/'raw.json.gz').open('wb') as out:subprocess.run(['kubectl','-n','openhands','exec','-i','deploy/pi-monori-judge','-c','sandbox','--','python','-'],input=extractor.encode(),stdout=out,check=True,timeout=180)
 catalog,status=json.load(gzip.open(root/'raw.json.gz'));
 expect=sum(len(f['diffs']) for f in catalog.values());
 assert expect and len(status)>=expect and all(type(v) is int for v in status.values()),'incomplete census; never mark as clear';
 rows=[];
 classes={0:'Survivors by area',33:'No coverage by area',-24:'Timeouts'}
 for uid,rc in status.items():
  if rc not in classes:continue
  u=uid if uid.startswith('monori.') else 'monori.'+uid;
  fam,_,num=u.rpartition('__mutmut_');
  rows.append((u,fam,int(num),classes[rc],100,'queued' if num in catalog.get(fam,{}).get('diffs',{}) else 'catalog_drift',sha,'fresh full census',None,0))
 (root/'catalog.json.gz').write_bytes(gzip.compress(json.dumps(catalog).encode()));
 (root/'summary.json').write_text(json.dumps({'base':sha,'total':len(status),'exit_codes':dict(collections.Counter(status.values())),'remaining':len(rows)}));
 with contextlib.closing(sqlite3.connect(D)) as db, contextlib.closing(sqlite3.connect(root/'previous.sqlite')) as backup:
  db.backup(backup)
  with db:
   db.execute('delete from tasks');
   db.executemany('insert into tasks values(?,?,?,?,?,?,?,?,?,?)',rows);
   db.execute('insert or replace into meta values(?,?)',('active_census',sha));
   db.execute('update meta set v=? where k=?',('complete',token))
 init();
 print('census complete; residual tasks',len(rows),flush=True);
 return True

def loop():
 lock=(R/'run.lock').open('a');
 fcntl.flock(lock,fcntl.LOCK_EX);
 init();
 if not query("select v from meta where k='old_dir_exclusion'"):
  query("update tasks set state='queued',note='Replay: old suite previously included new file' where state='needs_triage' and note like '%old suite no longer survives%'");
  query("insert into meta values('old_dir_exclusion','1')")
 query("update tasks set state='published' where pr is not null and state in ('authoring','survived','rejected')");
 query("update tasks set state='queued' where pr is null and state in ('authoring','survived','rejected','screening')");
 query("update tasks set state='publication_uncertain' where state='publishing'");
 lastfetch=0;
 sha=None;
 slots=0
 while not (R/'PAUSE-CAMPAIGN').exists():
  try:
   if time.time()-lastfetch>180 or not sha:
    git('fetch','--depth=1','origin','main');
    head=git('rev-parse','FETCH_HEAD').strip();
    install_base(head);
    sha=head;
    prs=remote_json('pulls?state=open&per_page=100');
    slots=0 if len(prs)>=100 else max(0,5-sum(p['head']['ref'].startswith(f'openhands/issue-{ISSUE}/') for p in prs));
    reconcile(prs,sha);
    lastfetch=time.time()
    try:repair_one(prs,sha)
    except (OSError,ValueError,RuntimeError,sqlite3.Error,subprocess.SubprocessError) as ex:
     print('CI repair deferred',type(ex).__name__,str(ex)[:180],flush=True)
   if query("select id from tasks where state='transport_wait' and updated<? limit 1",(time.time()-180,)):
    if K('author',['true'],ok=False).returncode==0:
     query("update tasks set state='queued' where state='transport_wait' and pr is null and updated<?",(time.time()-180,))
   ready=query("select * from tasks where state='verified' order by updated limit 1")
   if slots and ready:
    publish(ready[0],sha);
    slots-=1;
    continue
   ts=query("select * from tasks where state='queued' order by case when ord<0 then ord else 0 end, num, ord, id limit 1")
   if not ts:
    if not census(sha,prs):time.sleep(90)
    continue
   c=ts[0]
   try:
    mark(c,'screening','Independent old-suite check on current main',sha);
    screen(c,sha)
   except (subprocess.TimeoutExpired,RuntimeError,ValueError) as ex:mark(c,'infra_triage',str(ex)[:400],sha)
  except (OSError,ValueError,RuntimeError,sqlite3.Error,subprocess.SubprocessError) as ex:
   print('controller backoff',type(ex).__name__,str(ex)[:250],flush=True);
   time.sleep(60)
if __name__=='__main__':loop()
