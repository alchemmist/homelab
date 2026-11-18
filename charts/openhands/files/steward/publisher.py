"""Closed set of GitHub actions. Never execute candidate code or accept URLs/refs."""
import base64, json, re, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

REPO='alchemmist/monori'; PREFIX='openhands/issue-509/'
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):return None

def api(path, data=None):
    url='https://api.github.com/'+('graphql' if path=='graphql' else 'repos/'+REPO+'/'+path)
    token=Path('/credential/token').read_text().strip()
    req=Request(url,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','User-Agent':'openhands-scoped-publisher'})
    with build_opener(NoRedirect).open(req,timeout=20) as resp:return json.load(resp)

def check(condition):
    if not condition:raise ValueError('Invalid or disallowed operation')

def changes(files):
    check(isinstance(files,dict) and 1<=len(files)<=12); result=[]
    for p,value in files.items():
        check(re.fullmatch(r'server/(?:tests|app)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py',p) and isinstance(value,str) and '\x00' not in value)
        result.append({'path':p,'contents':base64.b64encode(value.encode()).decode()})
    return result

def owned_pr(n,sha):
    check(type(n) is int and n>0 and isinstance(sha,str) and re.fullmatch('[a-f0-9]{40}',sha))
    p=api('pulls/'+str(n));check(p['state']=='open' and p['base']['ref']=='main' and p['head']['repo']['full_name']==REPO and p['user']['login']=='alchemmist' and re.fullmatch(PREFIX+'[a-f0-9]{32}',p['head']['ref']) and p['head']['sha']==sha)
    return p

def review(x):
    p=owned_pr(x['pr'],x['head']);a=x['action'];sha=x['head']
    if a=='report':
        check(set(x)=={'action','pr','head'});res=api('issues/509/comments',{'body':f"OpenHands: mutation coverage PR #{p['number']}, head `{sha}`. Review/CI status is tracked on the PR."});return {'url':res['html_url']}
    check(set(x)=={'action','pr','head','thread','reason','decision'});t=x['thread'];reason=x['reason'];check(isinstance(t,str) and re.fullmatch('PRRT_[A-Za-z0-9_-]{4,150}',t));check(x['decision'] in ('fixed','declined') and isinstance(reason,str) and 30<=len(reason)<=2000 and all(c.isprintable() for c in reason) and '@' not in reason and not any(c in reason for c in '<>'))
    def gql(q,v):
        r=api('graphql',{'query':q,'variables':v});check(not r.get('errors') and r.get('data'));return r['data']
    thread=gql('query($t:ID!){node(id:$t){... on PullRequestReviewThread{isResolved pullRequest{id}}}}',{'t':t})['node'];check(thread and not thread['isResolved'] and thread['pullRequest']['id']==p['node_id'])
    body=f"{x['decision']} at {sha}: {reason}"
    reply=gql('mutation($t:ID!,$b:String!){addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$t,body:$b}){comment{id}}}',{'t':t,'b':body});check(reply['addPullRequestReviewThreadReply']['comment']['id'])
    owned_pr(x['pr'],sha)
    resolved=gql('mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}',{'t':t});check(resolved['resolveReviewThread']['thread']['isResolved']);return {'resolved':True,'head':sha}

def dispatch(x):
    check(isinstance(x,dict));action=x.get('action')
    if action=='capabilities':return {'repository':REPO,'issue':509,'actions':['create','update','report','reply_then_resolve'],'merge':False,'main_write':False}
    if action in ('report','reply_then_resolve'):return review(x)
    check(action in ('create','update')); required={'action','head','files','title'}|({'pr'} if action=='update' else set());check(set(x)==required)
    sha=x['head'];check(isinstance(sha,str) and re.fullmatch('[a-f0-9]{40}',sha)); title=x['title'];check(isinstance(title,str) and 4<=len(title)<=110 and all(c.isprintable() for c in title) and '@' not in title)
    files=changes(x['files'])
    if action=='create':
        check(api('git/ref/heads/main')['object']['sha']==sha)
        # cap outstanding work; use a bounded list fail-closed if incomplete.
        prs=api('pulls?state=open&per_page=100');check(len(prs)<100 and sum(p['head']['ref'].startswith(PREFIX) for p in prs)<5)
        branch=PREFIX+uuid.uuid4().hex;api('git/refs',{'ref':'refs/heads/'+branch,'sha':sha})
    else:
        p=owned_pr(x['pr'],sha);branch=p['head']['ref']
    mutation='mutation($i:CreateCommitOnBranchInput!){createCommitOnBranch(input:$i){commit{oid}}}'
    res=api('graphql',{'query':mutation,'variables':{'i':{'branch':{'repositoryNameWithOwner':REPO,'branchName':branch},'expectedHeadOid':sha,'message':{'headline':title},'fileChanges':{'additions':files}}}});oid=res['data']['createCommitOnBranch']['commit']['oid']
    if action=='create':p=api('pulls',{'head':branch,'base':'main','draft':False,'title':title,'body':'Mutation coverage follow-up for #509. Published via the scoped OpenHands publisher. Human review and merge required.'})
    return {'pr':p['number'],'head':oid,'url':p['html_url']}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,status,obj):
        raw=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        try:
            self.connection.settimeout(10);check(self.path=='/v1' and not self.headers.get('Transfer-Encoding'));n=int(self.headers['Content-Length']);check(0<n<=250000);self.send(200,dispatch(json.loads(self.rfile.read(n))))
        except HTTPError as e:self.send(502,{'github_status':e.code,'retry':'Inspect existing branch/PR before retrying'})
        except (ValueError,TypeError):self.send(400,{'error':'Invalid request, stale head or operation outside policy'})
        except Exception:self.send(503,{'error':'Publisher unavailable; inspect GitHub before retrying'})
if __name__=='__main__':HTTPServer(('0.0.0.0',8081),Handler).serve_forever()
