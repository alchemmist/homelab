"""Trusted systemd consumer. Only enrolled repo adapters; never execute issue text here."""
import fcntl, json, os, re, subprocess, sys, time
import campaign as c
import restore_worker
# Remote RPC via the existing operator transport. No pod gets kube credentials.
RPC='''import json,sqlite3,sys
m=json.load(sys.stdin); db=sqlite3.connect('/state/reports.db',timeout=10);db.row_factory=sqlite3.Row
with db:
 if m['op']=='list':print(json.dumps([x[0] for x in db.execute("select issue from reports where repo=? and state not in ('unsupported_report','closed','adapter_required') order by issue",(m['repo'],))]));sys.exit()
 key=(m['repo'],m['issue']); r=db.execute('select digest,state from reports where repo=? and issue=?',key).fetchone()
 if not r: print('null');sys.exit()
 if m['op']=='get':print(json.dumps({'digest':r['digest'],'cards':[dict(x) for x in db.execute('select section,target,reported from cards where repo=? and issue=?',key)]}));sys.exit()
 assert m['digest']==r['digest'];db.execute('create table if not exists outputs(repo integer,issue integer,mutant text,state text,pr integer,base text,primary key(repo,issue,mutant))');db.executemany('insert or replace into outputs values(?,?,?,?,?,?)',[(*key,*row) for row in m['outputs']]);db.executemany('update cards set state=? where repo=? and issue=? and section=? and target=?',[(s,*key,section,t) for section,t,s in m['rows']]);db.execute('update reports set state=? where repo=? and issue=?',(m['state'],*key));print('true')'''

ADAPTER=json.loads((c.R/'worker_adapter.json').read_text())
# Publisher is intentionally not a generic GitHub token. Never silently route another repo to it.
if ADAPTER['adapter']!='monori-mutmut-v1' or ADAPTER['repository']!='alchemmist/monori':raise ValueError('Unenrolled publisher')

def rpc(op,**kw):
 p=c.pilot.cmd(['kubectl','-n','openhands','exec','-i','deploy/mutation-report-intake','--','python','-c',RPC],json.dumps(dict(op=op,repo=ADAPTER['repository_id'],issue=c.ISSUE,**kw)),timeout=20);return json.loads(p.stdout)

def main():
 lock=(c.R/'run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 while not (reports:=rpc('list')):time.sleep(45)
 last=c.query("select v from meta where k='last_admission'") if c.D.exists() else []
 prior=int(last[0]['v']) if last else 0;c.ISSUE=next((i for i in reports if i>prior),reports[0]);r=rpc('get')
 revision=(c.R/'report_dispatch.py').stat().st_mtime_ns
 rows=r['cards']; c.BACK=[dict(id=str(i+1),family=x['target'],section=x['section']) for i,x in enumerate(rows)];c.init(); allowed=set()
 for x in rows:
  f,_,num=x['target'].partition('__mutmut_');allowed.update(f+'__mutmut_'+n for n in ([num] if num else c.C.get(f,{}).get('diffs',{})))
 if not allowed:
  rpc('sync',rows=[[x['section'],x['target'],'catalog_required'] for x in rows],outputs=[],digest=r['digest'],state='adapter_required');return
 c.query("insert or replace into meta values('last_admission',?)",(str(c.ISSUE),));discovery=time.time()+300
 if not c.query("select v from meta where k='artifact_protocol_v1'"):
  c.query("update tasks set state='queued' where pr is null and state='needs_triage' and note like '%outside offline unit-test scope%'");c.query("insert into meta values('artifact_protocol_v1','1')")
 # Recover only historical infra failures with concrete evidence; no model retries for real red tests.
 for t in c.query("select * from tasks where state='needs_triage' and note like '%executor ended%'"):
  log=c.A/c.key(t)/'pi-3.log'
  if log.exists() and b'502 Bad Gateway' in log.read_bytes()[-2000:]:c.mark(t,'queued','Recovered prior transport failure, no model verdict')
 c.query("update tasks set state='queued' where pr is null and state in ('screening','survived','authoring','rejected')");c.query("update tasks set state='published' where pr is not null and state in ('authoring','rejected')");c.query("update tasks set state='publication_uncertain' where state='publishing'");cache=0;nextrepair=time.time()+600
 def sync(active=''):
  tasks={x['id']:x for x in c.query('select id,state,pr from tasks')};changes=[]
  for row in rows:
   f,_,n=row['target'].partition('__mutmut_');ids=[f+'__mutmut_'+i for i in ([n] if n else c.C.get(f,{}).get('diffs',{}))];states={tasks[i]['state'] for i in ids if i in tasks};state='processing' if active in ids else 'partial' if 'queued' in states and len(states)>1 else 'queued' if states=={'queued'} else 'attention' if states-{'published','merged','already_killed','covered_pending_merge'} or not states else 'assessed';changes.append([row['section'],row['target'],state])
  outputs=[[x['id'],x['state'],x['pr'],x['base']] for x in c.query('select id,state,pr,base from tasks where pr is not null') if x['id'] in allowed];rpc('sync',rows=changes,outputs=outputs,digest=r['digest'],state='processing' if active else 'tracking')
 while True:
  try:
   if (c.R/'report_dispatch.py').stat().st_mtime_ns!=revision:os.execv(sys.executable,[sys.executable,'-Bu',__file__])
   if time.time()>discovery:
    discovery=time.time()+300
    if any(i!=c.ISSUE for i in rpc('list')):os.execv(sys.executable,[sys.executable,'-Bu',__file__])
   if time.time()>cache:
    live=c.remote_json('issues/'+str(c.ISSUE))
    if live['state']!='open' or ADAPTER['label'] not in [x['name'] for x in live['labels']]:
     rpc('sync',rows=[],outputs=[],digest=r['digest'],state='closed');return
    restore_worker.ensure(c)
    c.git('fetch','--depth=1','origin','main');sha=c.git('rev-parse','FETCH_HEAD').strip();c.install_base(sha);prs=c.remote_json('pulls?state=open&per_page=100');c.reconcile(prs,sha);slots=max(0,ADAPTER['publication_limit']-sum(p['head']['ref'].startswith('openhands/issue-') for p in prs)) if len(prs)<100 else 0;cache=time.time()+240
   if slots:
    ready=next((x for x in c.query("select * from tasks where state='verified' order by updated") if x['id'] in allowed),None)
    if ready:c.publish(ready,sha);slots-=1;sync();continue
   if time.time()>nextrepair:
    nextrepair=time.time()+1200;c.repair_one(prs,sha)
   c.query("update tasks set state='queued' where state='transport_wait' and updated<?",(time.time()-180,));t=next((x for x in c.query("select * from tasks where state='queued' order by case when ord<0 then -1 else 0 end,num,case when category='Timeouts' then 1 else 0 end,ord,id") if x['id'] in allowed),None)
   if not t:sync();time.sleep(60);continue
   if re.search(r'connector|credential|access_denied|auth(?:entication|orization)?_|subprocess|webhook|password|token|crypto',t['fam'],re.I):c.mark(t,'needs_triage','Requires human scope review; no agent assigned',sha);continue
   sync(t['id']);c.mark(t,'screening','Leased from signed issue admission',sha)
   try:c.screen(t,sha)
   except (RuntimeError,subprocess.TimeoutExpired) as ex:
    cache=0;c.K('judge',['rm','-f','/scratch/campaign-base'],ok=False);c.mark(t,'transport_wait',str(ex)[:360],sha)
   sync()
  except Exception as ex:print('adapter backoff:',type(ex).__name__,str(ex)[:360],flush=True);time.sleep(45)
if __name__=='__main__':main()
