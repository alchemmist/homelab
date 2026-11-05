#!/usr/bin/env python3
"""Explicit LiteLLM native OIDC acceptance with a temporary read-only observer.
No real owner password/MFA is read or reset. No QR/secret/session traces are saved.
Requires Playwright + Chromium. Run from the owner Mac with --run.
"""
import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', action='store_true', help='Explicitly authorize temporary acceptance fixtures')
parser.add_argument('--public-edge', choices=['109.173.40.247','109.120.141.97'], default='109.173.40.247')
args = parser.parse_args()
if not args.run:
    parser.error('--run is required for a live fixture test')
import json,urllib.request,urllib.error,subprocess,os
from pathlib import Path
BASE='https://auth.socrat.alchemmist.xyz'
# Process-local public-edge resolution; keep verified TLS/SNI, no system DNS changes.
import socket
_original_getaddrinfo=socket.getaddrinfo
def public_auth(host,*params,**kwargs):
 return _original_getaddrinfo(args.public_edge if host in ['auth.socrat.alchemmist.xyz','llm.alchemmist.xyz'] else host,*params,**kwargs)
socket.getaddrinfo=public_auth
SSH=['ssh','-o','ConnectTimeout=10','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0']
credential=json.loads(subprocess.check_output(SSH+['cat ~/.cache/homelab-authentik/credentials.json']))
def api(method,path,data=None):
 req=urllib.request.Request(BASE+'/api/v3/'+path,method=method,headers={'Authorization':'Bearer '+credential['AUTHENTIK_BOOTSTRAP_TOKEN'],'Content-Type':'application/json'},data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(req,timeout=45) as r:
  b=r.read();return json.loads(b) if b else None

from playwright.sync_api import sync_playwright
import secrets,time,urllib.parse,base64,hmac,hashlib,struct,uuid
username='litellm-smoke-'+uuid.uuid4().hex[:10];password=secrets.token_urlsafe(32)
group=next(x for x in api('GET','core/groups/?name=homelab-observer')['results'] if x['name']=='homelab-observer')
user=api('POST','core/users/',{'username':username,'name':'Temporary LiteLLM acceptance probe','email':username+'@example.invalid','groups':[group['pk']],'is_active':True})
binding=None
fixture_id='authentik:'+user['uuid']
try:
 app=next(a for a in api('GET','core/applications/?superuser_full_list=true&page_size=100')['results'] if a['slug']=='litellm')
 binding=api('POST','policies/bindings/',{'target':app['pk'],'user':user['pk'],'order':90,'enabled':True,'failure_result':False})
 api('POST','core/users/'+str(user['pk'])+'/set_password/',{'password':password})
 with sync_playwright() as p:
  browser=p.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz '+args.public_edge+', MAP llm.alchemmist.xyz '+args.public_edge])
  page=browser.new_page(viewport={'width':1440,'height':960});last={};totp_challenge={};components=[];errors=[]
  def observe(response):
   if urllib.parse.urlparse(response.url).hostname=='llm.alchemmist.xyz' and '/sso/callback' in response.url:
    print('LiteLLM callback HTTP status:',response.status)
    if response.status>=400:
     try:
      import re
      err=json.dumps(response.json())
      print('Callback error classifications:',[word for word in ['client','pkce','state','scope','userinfo','issuer','csrf','missing','secret','insecure','token','redirect','SyntaxError','AttributeError','NameError','TypeError','invalid'] if word.lower() in err.lower()])
      print('Callback exception types:',re.findall(r'\b[A-Z][A-Za-z]+(?:Error|Exception)\b',err))
     except Exception:pass
   if '/api/v3/flows/executor/' in response.url and response.status in [200,400]:
    try:
     data=response.json();last.clear();last.update(data);print('Executor result:',response.status,data.get('type'),data.get('component'),'errors:',bool(data.get('response_errors')))
     if data.get('component'):components.append(data['component'])
     if data.get('component')=='ak-stage-authenticator-totp':totp_challenge.clear();totp_challenge.update(data)
    except Exception:pass
  page.on('response',observe);page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('https://llm.alchemmist.xyz/sso/key/generate');page.locator('input[name="uidField"]').wait_for()
  page.locator('input[name="uidField"]').fill(username);page.locator('input[type=password]').filter(visible=True).fill(password)
  page.locator('button[type=submit]').click();page.wait_for_timeout(2000)
  for step in range(60):
   if page.locator('ak-stage-authenticator-totp').is_visible():
    print('Native TOTP enrollment presented')
    source=totp_challenge.get('secret') or totp_challenge.get('secret_key') or urllib.parse.parse_qs(urllib.parse.urlparse(totp_challenge.get('config_url','')).query).get('secret',[None])[0]
    if not source:raise RuntimeError('TOTP setup data unavailable')
    key=base64.b32decode(source.upper()+'='*((-len(source))%8));sig=hmac.new(key,struct.pack('>Q',int(time.time())//30),hashlib.sha1).digest();offset=sig[-1]&15
    code=str((struct.unpack('>I',sig[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)
    stage=page.locator('ak-stage-authenticator-totp')
    stage.locator('input[name=code]').fill(code);stage.locator('button[type=submit]').click()
    stage.wait_for(state='hidden',timeout=30000)
   elif page.locator('ak-stage-consent').is_visible():
    print('Native consent presented')
    slug=urllib.parse.urlparse(page.url).path.strip('/').split('/')[-1]
    inspection=page.request.get(BASE+'/api/v3/flows/inspector/'+slug+'/')
    assert inspection.status in [403,404], 'Observer must not inspect flows'
    assert not page.get_by_role('button',name='Open flow inspector').is_visible()
    print('Observer native inspector access denied:',inspection.status)
    stage=page.locator('ak-stage-consent');stage.locator('button[name=continue]').click();stage.wait_for(state='hidden',timeout=30000)
   elif urllib.parse.urlparse(page.url).hostname=='llm.alchemmist.xyz' and '/ui' in urllib.parse.urlparse(page.url).path:
    cookies=page.context.cookies('https://llm.alchemmist.xyz')
    session=next((c for c in cookies if c['name']=='token'),None)
    token=session['value'] if session else None
    if not token:
     page.wait_for_timeout(500);continue
    assert session['secure'], 'SSO session cookie must be HTTPS-only'
    part=token.split('.')[1];payload=json.loads(base64.urlsafe_b64decode(part+'='*((-len(part))%4)))
    assert payload['user_id']==fixture_id and payload['user_role']=='internal_user_viewer'
    request=urllib.request.Request('https://llm.alchemmist.xyz/user/info?'+urllib.parse.urlencode({'user_id':fixture_id}),headers={'Authorization':'Bearer '+payload['key']})
    with urllib.request.urlopen(request,timeout=30) as response:profile=json.load(response)
    assert profile['user_info']['user_role']=='internal_user_viewer'
    assert 'ak-stage-authenticator-totp' in components and 'ak-stage-consent' in components
    print('PASS: LiteLLM native password + TOTP + consent + PKCE/OIDC callback and server-verified read-only identity')
    break
   page.wait_for_timeout(500)
  else:
   print('Final browser location:',urllib.parse.urlparse(page.url).hostname,urllib.parse.urlparse(page.url).path)
   raise RuntimeError('Browser roundtrip did not complete')
  print('Browser JS errors:',len(errors));assert not errors
  browser.close()
finally:
 try:
  if binding:api('DELETE','policies/bindings/'+binding['pk']+'/')
  api('DELETE','core/users/'+str(user['pk'])+'/')
 finally:
  cleanup=Path(__file__).with_name('identity-litellm-cleanup.py').read_text()
  subprocess.run(SSH+['python3','-'],input=('target='+repr(fixture_id)+'\n'+cleanup).encode(),check=True,timeout=90)
