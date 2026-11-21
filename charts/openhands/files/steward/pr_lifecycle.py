"""Only callable via the trusted signer. Validate mutable GitHub state before each write."""
import hashlib,json,re,runpy
from pathlib import Path
G=runpy.run_path(str(Path(__file__).with_name('ready_gate.py')));REVIEWERS={'socrat-steward','coderabbitai'};HANDLERS={'alchemmist'}

def lifecycle(x,api,owned,check):
 n=x['pr'];head=x['head'];p=owned(n,head);check(p['head']['ref'].startswith('openhands/issue-') and 'mutation-pr' in {l['name'] for l in p['labels']});mode=x['action'];issue=f'issues/{n}'
 def snap():
  q=api('graphql',{'query':G['QUERY'].replace('reviewThreads(first:100){nodes{id isResolved comments(first:100){nodes{id author','reviewThreads(first:100){nodes{id isResolved comments(first:100){nodes{id originalCommit{oid} author'),'variables':{'owner':'alchemmist','repo':'monori','number':n}});check(not q.get('errors'));v=q['data']['repository']['pullRequest'];check(v['headRefOid']==head);v['statusCheckRollup']=(v['tip']['nodes'][-1]['commit']['statusCheckRollup'] or {});a=G['assess'](v,REVIEWERS,HANDLERS);ctx=v['statusCheckRollup'].get('contexts',{}).get('nodes',[])
  if not any(y.get('name')=='Quality Graph' and y.get('conclusion')=='SUCCESS' for y in ctx):a['blockers'].append('Missing successful Quality Graph aggregate')
  # Required gate above is in addition to all visible checks, not a replacement.
  rows=[];replies=v['comments']['nodes']+[c for t in v['reviewThreads']['nodes'] for c in t['comments']['nodes']];seen={}
  for c in replies:
   if (c.get('author') or {}).get('login') not in HANDLERS:continue
   for data in re.findall(r'<!-- rtr:(\{[^\n]+?\}) -->',c.get('body','')):
    try:j=json.loads(data);seen[(j['comment'],j.get('digest'),j.get('head'))]=True
    except (ValueError,KeyError):pass
  def add(c,thread=None,resolved=False):
   auth=c.get('author') or {};body=c.get('body') or ''
   if not body or auth.get('__typename')!='Bot' and auth.get('login') not in REVIEWERS:return
   digest=hashlib.sha256(body.encode()).hexdigest();replied=(c['id'],digest,head) in seen
   if not replied or thread and not resolved:
    rows.append({'id':c['id'],'thread':thread,'resolved':resolved,'replied':replied,'author':auth['login'],'original':(c.get('originalCommit') or {}).get('oid'),'body':body[:24000],'truncated':len(body)>24000,'digest':digest,'url':c.get('url')});a['blockers'].append('Current disposition pending: '+c['id'])
  for c in v['comments']['nodes']+v['reviews']['nodes']:add(c)
  for t in v['reviewThreads']['nodes']:
   mixed=any((c.get('author') or {}).get('__typename')!='Bot' and not ((c.get('author') or {}).get('login') in HANDLERS and '<!-- rtr:' in c['body']) for c in t['comments']['nodes'])
   for c in t['comments']['nodes']:
    add(c,t['id'],t['isResolved'])
   if mixed and not t['isResolved']:
    for row in rows:
     if row['thread']==t['id']:row['human_discussion']=True
  a['ready_to_review']=not a['blockers'];return a,rows,ctx
 a,rows,ctx=snap();incomplete=any('pagination' in b for b in a['blockers']);url=f'https://github.com/alchemmist/monori';ready='mutation-ready'
 if ready in {l['name'] for l in p['labels']} and not a['ready_to_review']:api(issue+'/labels/'+ready,method='DELETE')
 if mode=='life_snapshot':return dict(a,files=[{k:f.get(k,'') for k in ('filename','status','patch')} for f in api(f'pulls/{n}/files?per_page=20')],remarks=rows,checks=[{'name':c.get('name',c.get('context')),'status':c.get('status',c.get('state')),'conclusion':c.get('conclusion'),'url':c.get('detailsUrl',c.get('targetUrl'))} for c in ctx])
 check(not incomplete)
 if mode=='life_request':
  bot=x['reviewer'];check(bot in REVIEWERS and 'Bot review incomplete on current head: '+bot in a['blockers']);marker=f'<!-- mutation-review-request:{bot}:{head} -->';comments=api(issue+'/comments?per_page=100');check(len(comments)<100);previous=[c for c in comments if c['user']['login']=='alchemmist' and marker in c['body']];
  if previous:return {'requested':False}
  owned(n,head);api(issue+'/comments',{'body':('@coderabbitai review' if bot=='coderabbitai' else '/review')+'\n\n'+marker});return {'requested':True}
 if mode=='life_ready':
  check(a['ready_to_review'] and snap()[0]==a);owned(n,head);api(issue+'/labels',{'labels':[ready]});return {'ready':True,'head':head}
 check(mode=='life_dispose');r=next((r for r in rows if r['id']==x['remark'] and r['digest']==x['digest']),None);check(r is not None and not r.get('human_discussion'));decision=x['decision'];reason=x['reason'];check(decision in ('fixed','irrelevant') and isinstance(reason,str) and 40<=len(reason)<=1100 and not re.search(r'[@<>\x00-\x1f]|https?://|github_pat_|Bearer',reason,re.I));j={'comment':r['id'],'digest':r['digest'],'head':head,'decision':decision};body=reason
 if decision=='fixed':check(x['commit']==head);j['commit']=head;body+=' Fixed in '+url+'/commit/'+head
 else:j['reason']=reason
 body+='\n\n<!-- rtr:'+json.dumps(j,separators=(',',':'))+' -->';owned(n,head)
 if not r['replied']:
  if r['thread']:
   res=api('graphql',{'query':'mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t,body:$b}){comment{id}}}','variables':{'t':r['thread'],'b':body}});check(res.get('data',{}).get('addPullRequestReviewThreadReply',{}).get('comment',{}).get('id'))
  else:check(api(issue+'/comments',{'body':f"Regarding {r['url']}: " +body})['id'])
 if r['thread'] and not r['resolved']:
  # Re-read after reply. Never resolve a thread that has other unanswered remarks.
  after=snap()[1];remaining=[row for row in after if row['thread']==r['thread']];
  if any(not row['replied'] or row.get('human_discussion') for row in remaining):return {'handled':r['id'],'thread':'awaiting other dispositions','head':head}
  owned(n,head);res=api('graphql',{'query':'mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}','variables':{'t':r['thread']}});check(res.get('data',{}).get('resolveReviewThread',{}).get('thread',{}).get('isResolved'))
 return {'handled':r['id'],'head':head}
