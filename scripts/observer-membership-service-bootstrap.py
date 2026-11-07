"""One-time machine membership-reader setup, not human provisioning.

Default is a credential-free desired-policy preview. Applying requires the exact
preview hash and an operator-owned 0700 state directory containing credentials.json.
Existing role/group/user names STOP instead of being adopted or overwritten.
After any partial failure inspect the private progress receipt before retrying.
"""
import urllib.request,urllib.error,pathlib,json,os,argparse,hashlib
policy={'role':'homelab-observer-membership-read','permissions':['authentik_core.view_user','authentik_core.view_group'],'serviceAccount':'svc-observer-membership','token':'homelab-observer-membership','namespaces':['cattle-system','wiki'],'humanMembershipWrites':False}
policy_hash=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--state',type=pathlib.Path)
parser.add_argument('--apply',action='store_true')
parser.add_argument('--approve-policy-sha256')
args=parser.parse_args()
if not args.apply:
 print(json.dumps({'desiredPolicy':policy,'approvalPolicySha256':policy_hash,'writes':False}));raise SystemExit(0)
if args.approve_policy_sha256!=policy_hash or args.state is None:
 raise SystemExit('Exact approval hash and private --state required')
root=args.state
assert not root.is_symlink() and root.is_dir() and root.stat().st_uid==os.geteuid() and root.stat().st_mode & 0o777==0o700,'State must be operator-owned mode 0700'
cred=json.loads((root/'credentials.json').read_text());os.umask(0o077)
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):return None
http=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
def api(method,path,body=None):
 req=urllib.request.Request('https://auth.socrat.alchemmist.xyz/api/v3/'+path,method=method,headers={'Authorization':'Bearer '+cred['authentikToken'],'Content-Type':'application/json'},data=None if body is None else json.dumps(body).encode())
 try:
  with http.open(req,timeout=30) as r:
   data=r.read();return json.loads(data) if data else None
 except urllib.error.HTTPError as e:
  data=e.read();p=root/'idp-service-last-error.json';p.write_bytes(data);p.chmod(0o600);raise RuntimeError('IdP service provisioning stopped HTTP '+str(e.code)+'; private error retained') from None
def rows(path):
 out=[]
 for page in range(1,101):
  d=api('GET',path+('&' if '?' in path else '?')+'page_size=100&page='+str(page));out+=d['results']
  if not d.get('pagination',{}).get('next'):return out
 raise RuntimeError('Incomplete pagination')
name='homelab-observer-membership-read'
assert not [r for r in rows('rbac/roles/') if r['name']==name],'Role collision; inspect before retry'
assert not [r for r in rows('core/groups/') if r['name']==name],'Group collision; inspect before retry'
assert not [u for u in rows('core/users/?username=svc-observer-membership') if u['username']=='svc-observer-membership'],'Service identity collision'
p=root/'idp-service-progress.json';state={'state':'applying'};p.write_text(json.dumps(state));p.chmod(0o600)
role=api('POST','rbac/roles/',{'name':name});state['role']=role['pk'];p.write_text(json.dumps(state))
api('POST','rbac/permissions/assigned_by_roles/'+role['pk']+'/assign/',{'permissions':['authentik_core.view_user','authentik_core.view_group']})
g=api('POST','core/groups/',{'name':name,'is_superuser':False,'roles':[role['pk']],'parents':[],'attributes':{'homelab_observer_membership_reader':1}});state['group']=g['pk'];p.write_text(json.dumps(state))
u=api('POST','core/users/',{'username':'svc-observer-membership','name':'Observer membership reader (machine)','type':'service_account','path':'services/observer','is_active':True,'groups':[g['pk']],'attributes':{'homelab_observer_membership_reader':1}});state['user']=u['pk'];p.write_text(json.dumps(state))
t=api('POST','core/tokens/',{'identifier':'homelab-observer-membership','intent':'api','user':u['pk'],'expiring':False,'description':'Read users/groups only for native observer membership freshness'})
key=api('GET','core/tokens/homelab-observer-membership/view_key/')['key']
p2=root/'membership-reader-token';p2.write_text(key);p2.chmod(0o600)
for path in ['core/users/?username=observer-acceptance-20261107','core/groups/?name=homelab-observer']:
 req=urllib.request.Request('https://auth.socrat.alchemmist.xyz/api/v3/'+path,headers={'Authorization':'Bearer '+key})
 with http.open(req,timeout=30) as r:d=json.load(r);assert d['results'],'Scoped service read returned no data'
state['state']='configured';p.write_text(json.dumps(state));print('READ_ONLY_MEMBERSHIP_SERVICE_CONFIGURED',{'role':role['pk'],'service_user':u['pk'],'permissions':['authentik_core.view_user','authentik_core.view_group'],'human_roles_changed':False,'can_write_idp':False})

# Store no credentials in Git. Existing Secrets are never overwritten/adopted.
import subprocess,base64
k=['/usr/local/bin/kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml']
for namespace in policy['namespaces']:
 result=subprocess.run(k+['-n',namespace,'get','secret','observer-membership-reader','--ignore-not-found','-o','name'],capture_output=True,text=True)
 assert result.returncode==0 and not result.stdout.strip(),'Secret collision; inspect private receipts'
 secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'observer-membership-reader','namespace':namespace,'labels':{'app.kubernetes.io/managed-by':'homelab-identity','homelab.alchemmist.xyz/purpose':'observer-membership-read'}},'type':'Opaque','data':{'token':base64.b64encode(key.encode()).decode()}}
 result=subprocess.run(k+['create','-f','-'],input=json.dumps(secret),capture_output=True,text=True)
 assert result.returncode==0,'Scoped Secret creation failed; inspect private receipts'
print('READ_ONLY_MEMBERSHIP_SECRETS_INSTALLED',policy['namespaces'])
