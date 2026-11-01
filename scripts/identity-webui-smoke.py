#!/usr/bin/env python3
"""Explicit acceptance test: temporary observer, real MFA/OIDC, then fixture cleanup.
Run from the owner Mac with private DNS/WireGuard. Never tests as the real owner.
"""
import json,urllib.request,urllib.error,urllib.parse,http.cookiejar,secrets,uuid,hmac,hashlib,base64,struct,time
from pathlib import Path
root=Path.home()/'.cache/homelab-authentik';base='https://auth.socrat.alchemmist.xyz';runtime=json.loads(__import__('subprocess').check_output(['ssh','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0','cat ~/.cache/homelab-authentik/credentials.json']))
def admin(method,path,data=None):
 req=urllib.request.Request(base+'/api/v3/'+path,method=method,
   headers={'Authorization':'Bearer '+runtime['AUTHENTIK_BOOTSTRAP_TOKEN'],'Content-Type':'application/json'},
   data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(req,timeout=30) as r:
  data=r.read();return json.loads(data) if data else None
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args):return None
jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar),NoRedirect)
def browser(url,data=None):
 headers={'Content-Type':'application/json','Referer':base+'/'}
 for c in jar:
  if 'csrf' in c.name and c.domain in ['auth.socrat.alchemmist.xyz','.socrat.alchemmist.xyz']:headers['X-authentik-CSRF']=c.value
 req=urllib.request.Request(url,headers=headers,data=json.dumps(data).encode() if data is not None else None)
 try:
  with opener.open(req,timeout=30) as r:return r.status,r.headers,r.read()
 except urllib.error.HTTPError as e:
  if e.code in [301,302,303,307]:
   e.headers.replace_header('Location',urllib.parse.urljoin(url,e.headers['Location']));loc=urllib.parse.urlparse(e.headers['Location']);q=urllib.parse.parse_qs(loc.query);return e.code,e.headers,b''
  raise RuntimeError('Browser request failed with HTTP '+str(e.code)+' at '+urllib.parse.urlsplit(url).path)
username='identity-smoke-'+uuid.uuid4().hex[:10];password=secrets.token_urlsafe(32)
group=next(g for g in admin('GET','core/groups/?name=homelab-observer')['results'] if g['name']=='homelab-observer')
user=admin('POST','core/users/',{'username':username,'name':'Temporary SSO acceptance probe','email':username+'@example.invalid','groups':[group['pk']],'is_active':True})
try:
 admin('POST','core/users/'+str(user['pk'])+'/set_password/',{'password':password})
 import subprocess
 fixture={'email':username+'@example.invalid','password':password,'subject':user['uuid']}
 code="""import asyncio,json,sys,inspect
from sqlalchemy import update
from open_webui.models.auths import Auths,Auth
from open_webui.internal.db import get_async_db_context
from open_webui.utils.auth import get_password_hash
async def main():
 p=json.load(sys.stdin);hashed=get_password_hash(p['password'])
 if inspect.isawaitable(hashed):hashed=await hashed
 u=await Auths.insert_new_auth(p['email'],hashed,'Temporary SSO acceptance probe',role='user',oauth={'oidc':{'sub':p['subject']}})
 assert u and u.id not in ['81ac54e7-89b1-4728-88e6-08802271e316','01e16076-81f3-40b6-ab9b-2d7a3795799d']
 async with get_async_db_context() as db:
  await db.execute(update(Auth).where(Auth.id==u.id).values(active=True));await db.commit()
 print('Temporary WebUI fixture prepared with active native credential')
asyncio.run(main())"""
 import shlex
 subprocess.run(['ssh','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0',
   'env K3S_CONFIG_FILE=/dev/null kubectl -n llm exec -i deployment/open-webui -c open-webui -- python -c '+shlex.quote(code)],input=json.dumps(fixture).encode(),check=True,timeout=60)
 status,headers,body=browser('https://chat.alchemmist.xyz/oauth/oidc/login')
 target=headers['Location']
 for step in range(30):
  if '/if/flow/' in target or '/api/v3/flows/executor/' in target:
   if '/if/flow/' in target:browser(urllib.parse.urljoin(base,target))
   p=urllib.parse.urlparse(target);slug=p.path.strip('/').split('/')[-1]
   executor=(urllib.parse.urljoin(base,target) if '/api/v3/flows/executor/' in target else base+'/api/v3/flows/executor/'+slug+'/?'+urllib.parse.urlencode({'query':p.query}))
   status,headers,body=browser(executor)
   if status in [301,302,303,307]:target=headers['Location'];continue
   challenge=json.loads(body)
   for inner in range(12):
    component=challenge.get('component');kind=challenge.get('type')
    # Challenge data, TOTP secrets and OAuth parameters stay in memory.
    if kind=='redirect' or component=='xak-flow-redirect':target=urllib.parse.urljoin(base,challenge.get('to',''));break
    if component=='ak-stage-identification':data={'uid_field':username}
    elif component=='ak-stage-password':data={'password':password}
    elif component=='ak-stage-authenticator-totp':
     key=challenge.get('secret') or challenge.get('secret_key') or urllib.parse.parse_qs(urllib.parse.urlparse(challenge.get('config_url','')).query).get('secret',[None])[0]
     if not key:
      print('TOTP challenge fields:',sorted(challenge.keys()));raise RuntimeError('TOTP setup format needs driver update')
     key=base64.b32decode(key.upper()+'='*((-len(key))%8));h=hmac.new(key,struct.pack('>Q',int(time.time())//30),hashlib.sha1).digest();o=h[-1]&15
     data={'code':str((struct.unpack('>I',h[o:o+4])[0]&0x7fffffff)%1000000).zfill(6)}
    elif component=='ak-stage-consent':
     data={'consent':True,'token':challenge.get('token')}
    else:raise RuntimeError('Unhandled browser challenge: '+str(component))
    status,headers,body=browser(executor,data)
    challenge=({'type':'redirect','to':headers['Location']} if status in [301,302,303,307] else json.loads(body))
   else:raise RuntimeError('Too many flow challenges')
  else:
   status,headers,body=browser(urllib.parse.urljoin(base,target))
   if status in [301,302,303,307]:target=headers['Location']
   elif 'chat.alchemmist.xyz' in urllib.parse.urljoin(base,target):
    _,_,body=browser('https://chat.alchemmist.xyz/api/v1/auths/')
    profile=json.loads(body)
    if profile.get('email')!=username+'@example.invalid' or profile.get('role')!='user':raise RuntimeError('Unexpected WebUI identity or role')
    if profile.get('token'):
     claims=json.loads(base64.urlsafe_b64decode(profile['token'].split('.')[1]+'==='))
     print('WebUI session method:',claims.get('auth_method'),'type:',claims.get('typ','session'))
    print('WebUI password + TOTP + consent + OIDC/PKCE passed with native credential active; role=user')
    break
   else:raise RuntimeError('Unexpected final non-Wiki page')
 else:raise RuntimeError('Too many redirects')
finally:
 admin('DELETE','core/users/'+str(user['pk'])+'/')
 print('Temporary Authentik acceptance identity removed')
 import subprocess
 cleanup="""import asyncio
from open_webui.models.auths import Auths
from open_webui.models.users import Users
async def main():
 u=await Users.get_user_by_email(target+'@example.invalid')
 if u:
  assert u.name=='Temporary SSO acceptance probe' and u.id not in ['81ac54e7-89b1-4728-88e6-08802271e316','01e16076-81f3-40b6-ab9b-2d7a3795799d']
  assert await Auths.delete_auth_by_id(u.id)
 print('Temporary WebUI fixture removed')
asyncio.run(main())
"""
 subprocess.run(['ssh','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0',
  'env K3S_CONFIG_FILE=/dev/null kubectl -n llm exec -i deployment/open-webui -c open-webui -- python -'],input=('target='+repr(username)+'\n'+cleanup).encode(),check=True,timeout=60)
