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
  raise RuntimeError('Browser request failed with HTTP '+str(e.code))
username='identity-smoke-'+uuid.uuid4().hex[:10];password=secrets.token_urlsafe(32)
group=next(g for g in admin('GET','core/groups/?name=homelab-observer')['results'] if g['name']=='homelab-observer')
user=admin('POST','core/users/',{'username':username,'name':'Temporary SSO acceptance probe','email':username+'@example.invalid','groups':[group['pk']],'is_active':True})
try:
 admin('POST','core/users/'+str(user['pk'])+'/set_password/',{'password':password})
 status,headers,body=browser('https://wiki.socrat.alchemmist.xyz/api/auth/oidc/login')
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
   elif 'wiki.socrat.alchemmist.xyz' in urllib.parse.urljoin(base,target):
    _,_,body=browser('https://wiki.socrat.alchemmist.xyz/api/auth/me')
    profile=json.loads(body)
    if profile.get('user',{}).get('username')!=username:raise RuntimeError('Unexpected Wiki identity')
    if profile['user']['role']!='reader' or profile['writable']:raise RuntimeError('Observer unexpectedly received edit rights')
    request=urllib.request.Request('https://wiki.socrat.alchemmist.xyz/api/editor/batch',data=b'{}',headers={
      'Content-Type':'application/json','Origin':'https://wiki.socrat.alchemmist.xyz','X-CSRF-Token':profile['csrf_token']})
    try:opener.open(request,timeout=30);raise RuntimeError('Reader could write')
    except urllib.error.HTTPError as error:
     if error.code!=403:raise RuntimeError('Unexpected write rejection status')
    print('Wiki password + TOTP + consent + OIDC/PKCE passed; observer is reader; writes denied 403')
    break
   else:raise RuntimeError('Unexpected final non-Wiki page')
 else:raise RuntimeError('Too many redirects')
finally:
 admin('DELETE','core/users/'+str(user['pk'])+'/')
 print('Temporary Authentik acceptance identity removed')
 import subprocess
 cleanup="""import json,sqlite3,sys
c=sqlite3.connect('/data/accounts.sqlite3');c.execute('PRAGMA foreign_keys=ON')
row=c.execute('SELECT id FROM users WHERE username=?',(target,)).fetchone()
if row:
 user_id=row[0]
 assert target.startswith('identity-smoke-') and user_id not in ['ea7db81cbccae261e353dccf7f8d0dba','95244cc04462f8495845eadb65656f53']
 with c:
  for table,column in [('sessions','user_id'),('api_tokens','user_id'),('user_preferences','user_id'),('oidc_accounts','user_id')]:c.execute('DELETE FROM '+table+' WHERE '+column+'=?',(user_id,))
  c.execute('DELETE FROM users WHERE id=?',(user_id,))
print('Temporary Wiki acceptance profile removed')
"""
 subprocess.run(['ssh','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0',
  'env K3S_CONFIG_FILE=/dev/null kubectl -n wiki exec -i deployment/wiki-runtime-wiki -- python -'],input=('target='+repr(username)+'\n'+cleanup).encode(),check=True,timeout=60)
