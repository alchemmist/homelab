"""Closed set of GitHub actions. Never execute candidate code or accept URLs/refs."""
import hmac
import base64, json, re, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TypedDict, cast
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

REPO='alchemmist/monori'; PREFIX='openhands/issue-509/'
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args)->None:return None

class PullHead(TypedDict):
    """Head branch metadata of a GitHub pull request."""

    ref: str
    sha: str
    repo: dict[str, object]

class PullRequest(TypedDict):
    """Fields of a GitHub pull request used by the publisher policy."""

    state: str
    number: int
    html_url: str
    base: dict[str, object]
    head: PullHead
    user: dict[str, object]
    labels: list[dict[str, object]]
    node_id: str

class PrRef(TypedDict):
    """Minimal open-PR listing entry used for branch-prefix accounting."""

    head: PullHead

def api(path, data=None,method=None) -> dict[str, object]:
    url='https://api.github.com/'+('graphql' if path=='graphql' else 'repos/'+REPO+'/'+path)
    token=Path('/credential/token').read_text().strip()
    req=Request(url,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','User-Agent':'openhands-scoped-publisher'})
    with build_opener(NoRedirect).open(req,timeout=20) as resp:
        raw=resp.read();document: dict[str, object]=json.loads(raw) if raw else {};return document

def check(condition)->None:
    if not condition:raise ValueError('Invalid or disallowed operation')

QA='openhands/qa-issue-'
MUT='openhands/issue-'
def mutation_target(issue)->int:
    check(type(issue) is int and 0<issue<2**31);i=api('issues/'+str(issue));check('pull_request' not in i and i['state']=='open' and cast("dict[str, object]",i['user'])['id']==104511335 and any(l['name']=='mutation-report' for l in cast("list[dict[str, object]]",i['labels'])));return cast("int", issue)

def clean_text(t,lo,hi)->str:
    check(isinstance(t,str) and lo<=len(t)<=hi and all(c.isprintable() or c=='\n' for c in t))
    check(not re.search(r'@|https?://|[<>]|github_pat_|gh[pousr]_|Bearer\s|sk-[A-Za-z0-9]{16}|-----BEGIN',t,re.I));return cast("str", t)

def qa_issue(x)->dict[str, object]:
    import io,hashlib
    from PIL import Image
    check(set(x)-{'frames'}=={'action','key','title','kind','head','steps','expected','actual','pngs','reviewed_synthetic'} and x['reviewed_synthetic'] is True)
    key=x['key'];check(isinstance(key,str) and re.fullmatch('[a-z0-9][a-z0-9-]{4,64}',key));marker=f'<!-- socrat-qa:{key} -->';title=clean_text(x['title'],8,110);check('\n' not in title and x['kind'] in ('bug','improvement'));sha=x['head'];check(isinstance(sha,str) and re.fullmatch('[a-f0-9]{40}',sha));fields=[clean_text(x[k],6,3500) for k in ('steps','expected','actual')];check(isinstance(x['pngs'],list) and 1<=len(x['pngs'])<=4)
    images=[]
    for encoded in x['pngs']:
        check(isinstance(encoded,str) and len(encoded)<=1100000);raw=base64.b64decode(encoded,validate=True)
        with Image.open(io.BytesIO(raw),formats=['PNG']) as im:
            check(im.width*im.height<=3000000 and im.n_frames==1);rgb=im.convert('RGB');rgb.info.clear();out=io.BytesIO();rgb.save(out,'PNG');images.append(out.getvalue())
    video=None
    if 'frames' in x:
        import sys
        if '/code' not in sys.path:sys.path.insert(0,'/code')
        from qa_video import encode
        video=encode(x['frames'])
    # Stable marker; check open AND closed issues before writing. Fail closed on pagination ceiling.
    for page in range(1,21):
        items=cast("list[dict[str, object]]",api(
            f'issues?state=all&sort=created&direction=desc&per_page=100&page={page}'))
        for item in items:
            if 'pull_request' not in item and cast("str",cast("dict[str, object]",item['user'])['login'])=='alchemmist' and marker in cast("str", item['body'] or ''):return {'issue':item['number'],'url':item['html_url'],'existing':True}
        if len(items)<100:break
    else: raise ValueError('Incomplete duplicate scan')
    check(api('git/commits/'+sha)['sha']==sha);digest=hashlib.sha256(b''.join(images)+(video or b'')).hexdigest()[:24];branch='openhands/qa-evidence/'+key+'-'+digest
    try:oid=cast("dict[str, object]",api('git/ref/heads/'+branch)['object'])['sha']
    except HTTPError as exc:
        if exc.code!=404:raise
        entries=[]
        for i,image in enumerate(images,1):
            blob=api('git/blobs',{'content':base64.b64encode(image).decode(),'encoding':'base64'});entries.append({'path':f'{i}.png','mode':'100644','type':'blob','sha':blob['sha']})
        if video:
            blob=api('git/blobs',{'content':base64.b64encode(video).decode(),'encoding':'base64'});entries.append({'path':'repro.mp4','mode':'100644','type':'blob','sha':blob['sha']})
        tree=api('git/trees',{'tree':entries});oid=api('git/commits',{'message':'QA synthetic screenshot evidence','tree':tree['sha'],'parents':[]})['sha'];api('git/refs',{'ref':'refs/heads/'+branch,'sha':oid})
    links=[f'https://raw.githubusercontent.com/{REPO}/{oid}/{i}.png' for i in range(1,len(images)+1)];body=f'{marker}\nTested revision: `{sha}` (local synthetic data).\n\n## Steps\n{fields[0]}\n\n## Expected\n{fields[1]}\n\n## Actual\n{fields[2]}\n\n## Evidence\n'+'\n'.join(f'![Reproduction step {i}]({u})' for i,u in enumerate(links,1))
    if video:body+=f'\n\n[Play the browser recording (MP4)](https://github.com/{REPO}/blob/{oid}/repro.mp4) · [Download MP4](https://raw.githubusercontent.com/{REPO}/{oid}/repro.mp4)'
    issue=api('issues',{'title':'[QA '+x['kind']+'] '+title,'body':body});return {'issue':issue['number'],'url':issue['html_url'],'evidence':links}

def changes(files,qa=False,pi_ci=False)->list[dict[str, object]]:
    check(isinstance(files,dict) and 1<=len(files)<=12); result: list[dict[str, object]]=[]
    for p,value in files.items():
        check((re.fullmatch(r'server/(?:tests|app)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py',p) or (pi_ci and re.fullmatch(r'ci/tests/test_mutation_[0-9a-f]{12}\.py',p)) or (qa and re.fullmatch(r'web/(?:src|e2e|tests)/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+(?:\.(?:spec|test))?\.(?:tsx?|jsx?|css)',p))) and isinstance(value,str) and '\x00' not in value)
        result.append({'path':p,'contents':base64.b64encode(value.encode()).decode()})
    return result

def owned_pr(n,sha)->PullRequest:
    check(type(n) is int and n>0 and isinstance(sha,str) and re.fullmatch('[a-f0-9]{40}',sha))
    p: PullRequest=cast("PullRequest",api('pulls/'+str(n)));check(p['state']=='open' and cast("str",p['base']['ref'])=='main' and cast("str",p['head']['repo']['full_name'])==REPO and cast("str",p['user']['login'])=='alchemmist' and re.fullmatch('(?:'+MUT+'[1-9][0-9]*/|'+QA+'[0-9]+/)[a-f0-9]{32}',p['head']['ref']) and p['head']['sha']==sha)
    return p

def review(x)->dict[str, object]:
    p=owned_pr(x['pr'],x['head']);a=x['action'];sha=x['head']
    if a=='threads':
        check(set(x)=={'action','pr','head'});q='query($n:Int!,$c:String){repository(owner:"alchemmist",name:"monori"){pullRequest(number:$n){reviewThreads(first:50,after:$c){pageInfo{hasNextPage endCursor} nodes{id isResolved path line comments(first:1){nodes{body author{login} url}}}}}}}'
        rows=[];cursor=None
        for _ in range(10):
            data=api('graphql',{'query':q,'variables':{'n':x['pr'],'c':cursor}});check(not data.get('errors'));page=cast("dict[str, object]",cast("dict[str, object]",cast("dict[str, object]",cast("dict[str, object]",data['data'])['repository'])['pullRequest'])['reviewThreads']);rows.extend(cast("list[dict[str, object]]",page['nodes']))
            if not cast("bool",cast("dict[str, object]",page['pageInfo'])['hasNextPage']):
                return {'threads':rows,'head':sha}
            cursor=cast("str",cast("dict[str, object]",page['pageInfo'])['endCursor']);check(cursor)
        raise ValueError('Incomplete pagination')
    if a=='report':
        check(set(x)=={'action','pr','head'});ref=p['head']['ref'];target=int(ref.split('/')[1].rsplit('-',1)[1]);res=api(f'issues/{target}/comments',{'body':f"OpenHands: mutation coverage PR #{p['number']}, head `{sha}`. Review/CI status is tracked on the PR."});return {'url':res['html_url']}
    check(set(x)=={'action','pr','head','thread','reason','decision'});t=x['thread'];reason=x['reason'];check(isinstance(t,str) and re.fullmatch('PRRT_[A-Za-z0-9_-]{4,150}',t));check(x['decision'] in ('fixed','declined') and isinstance(reason,str) and 30<=len(reason)<=2000 and all(c.isprintable() for c in reason) and '@' not in reason and not any(c in reason for c in '<>'))
    def gql(q,v):
        r=api('graphql',{'query':q,'variables':v});check(not r.get('errors') and r.get('data'));return r['data']
    thread=cast("dict[str, object]",cast("dict[str, object]",gql('query($t:ID!){node(id:$t){... on PullRequestReviewThread{isResolved pullRequest{id}}}}',{'t':t}))['node']);owned=cast("dict[str, object]",thread['pullRequest'])
    check(thread and not thread['isResolved'] and owned['id']==p['node_id'])
    body=f"{x['decision']} at {sha}: {reason}"
    reply=cast("dict[str,object]",gql('mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t,body:$b}){comment{id}}}',{'t':t,'b':body}))
    wrapped=cast("dict[str, object]",reply['addPullRequestReviewThreadReply'])
    check(cast("str",cast("dict[str, object]",wrapped['comment'])['id']))
    owned_pr(x['pr'],sha)
    resolved=cast("dict[str, object]",gql('mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}',{'t':t}));check(cast("dict[str, object]",cast("dict[str, object]",resolved['resolveReviewThread'])['thread'])['isResolved']);return {'resolved':True,'head':sha}

def dispatch(x)->dict[str, object]:
    check(isinstance(x,dict));action=x.get('action')
    signed_create=action=='create' and Path('/proof').is_dir()
    signed_update=action=='update' and 'proof' in x and Path('/proof').is_dir()
    life=action in ('life_snapshot','life_dispose','life_ready','life_head','life_ci','life_request');check(not life or Path('/proof').is_dir())
    if signed_create or signed_update or life:
        signature=x.pop('proof','');check(isinstance(signature,str) and hmac.compare_digest(signature,hmac.new(Path('/proof/key').read_bytes(),json.dumps(x,sort_keys=True).encode(),'sha256').hexdigest()))
    if life:
        import runpy
        if action=='life_head':
            n=x['pr'];check(type(n) is int and n>0);p=cast("PullRequest",api('pulls/'+str(n)));return {'head':p['head']['sha'],'enrolled':p['state']=='open' and cast("str",p['head']['repo']['full_name'])==REPO and cast("str",p['user']['login'])=='alchemmist' and cast("str",p['base']['ref'])=='main' and re.fullmatch(MUT+r'[1-9][0-9]*/[a-f0-9]{32}',p['head']['ref']) is not None and any(l['name']=='mutation-pr' for l in p['labels'])}
        if action=='life_ci':
            p=owned_pr(x['pr'],x['head']);check(p['head']['ref'].startswith(MUT) and any(l['name']=='mutation-pr' for l in p['labels']));return cast("dict[str, object]",runpy.run_path(str(Path(__file__).with_name('ci_excerpt.py')))['extract'](x['pr'],x['head'],api,NoRedirect,check))
        return cast("dict[str, object]",runpy.run_path(str(Path(__file__).with_name('pr_lifecycle.py')))['lifecycle'](x,api,owned_pr,check))
    if action=='qa_issue':return qa_issue(x)
    if action=='qa_capabilities':return {'actions':['qa_issue','qa_create','update','threads','reply_then_resolve','report'],'evidence':'reviewed synthetic PNG and optional 6fps H.264 MP4 from frames','merge':False}
    if action=='capabilities':return {'repository':REPO,'issue':509,'actions':['create','update','report','threads','reply_then_resolve'],'merge':False,'main_write':False}
    if action in ('report','threads','reply_then_resolve'):return review(x)
    check(action in ('create','qa_create','update')); required={'action','head','files','title'}|({'pr'} if action=='update' else {'issue'} if action=='qa_create' or signed_create and 'issue' in x else set());check(set(x)==required)
    sha=x['head'];check(isinstance(sha,str) and re.fullmatch('[a-f0-9]{40}',sha)); title=x['title'];check(isinstance(title,str) and 4<=len(title)<=110 and all(c.isprintable() for c in title) and '@' not in title)
    target=509;prefix=PREFIX
    if signed_create and 'issue' in x:
        target=mutation_target(x['issue']);prefix=MUT+str(target)+'/'
    if action=='qa_create':
        target=x['issue'];check(type(target) is int and target>0);issue=api('issues/'+str(target));check('pull_request' not in issue and issue['state']=='open' and cast("str",cast("dict[str, object]",issue['user'])['login'])=='alchemmist' and re.match(r'<!-- socrat-qa:[a-z0-9-]+ -->',cast("str", issue.get('body') or '')));prefix=QA+str(target)+'/'
    if action!='update':
        files=changes(x['files'],action=='qa_create',signed_create)
        check(cast("dict[str, object]",api('git/ref/heads/main')['object'])['sha']==sha)
        # cap outstanding work; use a bounded list fail-closed if incomplete.
        prs=cast("list[PrRef]",api('pulls?state=open&per_page=100'));check(len(prs)<100 and sum(p['head']['ref'].startswith(MUT) for p in prs)<5)
        check(action!='qa_create' or not any(p['head']['ref'].startswith(prefix) for p in prs));check(sum(p['head']['ref'].startswith(QA) for p in prs)<5);branch=prefix+uuid.uuid4().hex;api('git/refs',{'ref':'refs/heads/'+branch,'sha':sha})
    else:
        p=owned_pr(x['pr'],sha);branch=p['head']['ref'];check(not branch.startswith(MUT) or branch.startswith(PREFIX) or signed_update);files=changes(x['files'],branch.startswith(QA),signed_update and branch.startswith(MUT))
    mutation='mutation($i:CreateCommitOnBranchInput!){createCommitOnBranch(input:$i){commit{oid}}}'
    res=api('graphql',{'query':mutation,'variables':{'i':{'branch':{'repositoryNameWithOwner':REPO,'branchName':branch},'expectedHeadOid':sha,'message':{'headline':title},'fileChanges':{'additions':files}}}})
    create=cast("dict[str,object]",cast("dict[str,object]",res['data'])['createCommitOnBranch'])
    oid=cast("dict[str,object]",create['commit'])['oid']
    if action!='update':p=cast("PullRequest",api('pulls',{'head':branch,'base':'main','draft':False,'title':title,'body':f'Follow-up for #{target}. Published via the scoped OpenHands publisher. Human review and merge required.'}))
    if signed_create:api('issues/'+str(p['number'])+'/labels',{'labels':['mutation-pr']})
    return {'pr':p['number'],'head':oid,'url':p['html_url']}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args)->None:pass
    def send(self,status,obj)->None:
        raw=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self)->None:
        try:
            self.connection.settimeout(10);check(self.path=='/v1' and not self.headers.get('Transfer-Encoding'));n=int(self.headers['Content-Length']);check(0<n<=20000000);x=json.loads(self.rfile.read(n));check(x.get('action')=='qa_issue' or n<=250000);self.send(200,dispatch(x))
        except HTTPError as e:self.send(502,{'github_status':e.code,'retry':'Inspect existing branch/PR before retrying'})
        except (ValueError,TypeError):self.send(400,{'error':'Invalid request, stale head or operation outside policy'})
        except Exception:self.send(503,{'error':'Publisher unavailable; inspect GitHub before retrying'})
if __name__=='__main__':HTTPServer(('0.0.0.0',8081),Handler).serve_forever()
