#!/usr/bin/env python3
"""Explicit Argo CD native OIDC refresh acceptance with a temporary read-only observer.
Requires a reviewed refresh + end-to-end TLS deployment; fails closed before
creating fixtures when offline_access is absent. Expects renewed cookies to retain
Secure; Argo CD 3.5.6 server.insecure=true fails this check.
No real owner password/MFA is read or reset. No QR/secret/session traces are saved.
Requires Playwright + Chromium. Run from the owner Mac with --run.
"""
import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', action='store_true', help='Explicitly authorize temporary acceptance fixtures')
parser.add_argument('--public-edge', choices=['109.173.40.247','176.98.185.59'], default='109.173.40.247')
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
 return _original_getaddrinfo(args.public_edge if host in ['auth.socrat.alchemmist.xyz','argocd.socrat.alchemmist.xyz'] else host,*params,**kwargs)
socket.getaddrinfo=public_auth
SSH=['ssh','-o','ConnectTimeout=10','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0']
credential=json.loads(subprocess.check_output(SSH+['cat ~/.cache/homelab-authentik/credentials.json']))
def api(method,path,data=None):
 req=urllib.request.Request(BASE+'/api/v3/'+path,method=method,headers={'Authorization':'Bearer '+credential['AUTHENTIK_BOOTSTRAP_TOKEN'],'Content-Type':'application/json'},data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(req,timeout=45) as r:
  b=r.read();return json.loads(b) if b else None

from playwright.sync_api import sync_playwright
import secrets,time,urllib.parse,base64,hmac,hashlib,struct,uuid
provider=next(x for x in api('GET','providers/oauth2/?page_size=100')['results'] if x['name']=='homelab-argocd')
offline=[x for x in api('GET','propertymappings/provider/scope/?page_size=100')['results'] if x['scope_name']=='offline_access']
if len(offline)!=1 or offline[0]['pk'] not in provider['property_mappings']:
 raise SystemExit('Refresh deployment not activated; no fixtures created')
username='argocd-refresh-smoke-'+uuid.uuid4().hex[:10];password=secrets.token_urlsafe(32)
group=next(x for x in api('GET','core/groups/?name=homelab-observer')['results'] if x['name']=='homelab-observer')
user=api('POST','core/users/',{'username':username,'name':'Temporary Argo CD acceptance probe','email':username+'@example.invalid','groups':[group['pk']],'is_active':True})
binding=None
fixture_id=user['uuid']
try:
 app=next(a for a in api('GET','core/applications/?superuser_full_list=true&page_size=100')['results'] if a['slug']=='argocd')
 binding=api('POST','policies/bindings/',{'target':app['pk'],'user':user['pk'],'order':90+secrets.randbelow(100000),'enabled':True,'failure_result':False})
 api('POST','core/users/'+str(user['pk'])+'/set_password/',{'password':password})
 with sync_playwright() as p:
  browser=p.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz '+args.public_edge+', MAP argocd.socrat.alchemmist.xyz '+args.public_edge])
  page=browser.new_page(viewport={'width':1440,'height':960});last={};totp_challenge={};components=[];errors=[]
  def observe(response):
   if urllib.parse.urlparse(response.url).hostname=='argocd.socrat.alchemmist.xyz' and urllib.parse.urlparse(response.url).path=='/auth/login' and response.status in [302,303,307]:
    authorization=urllib.parse.parse_qs(urllib.parse.urlparse(response.headers.get('location','')).query)
    assert 'offline_access' in authorization.get('scope',[''])[0].split(), 'Live authorization must request offline_access'
   if urllib.parse.urlparse(response.url).hostname=='argocd.socrat.alchemmist.xyz' and '/auth/callback' in response.url:
    print('Argo CD callback HTTP status:',response.status)
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
  page.goto('https://argocd.socrat.alchemmist.xyz/auth/login?return_url=https%3A%2F%2Fargocd.socrat.alchemmist.xyz%2Fapplications');page.locator('input[name="uidField"]').wait_for()
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
   elif urllib.parse.urlparse(page.url).hostname=='argocd.socrat.alchemmist.xyz' and '/applications' in urllib.parse.urlparse(page.url).path:
    context=page.context
    def claims():
     c=next(c for c in context.cookies('https://argocd.socrat.alchemmist.xyz') if c['name']=='argocd.token')
     assert c['secure']
     raw=c['value'].split('.')[1]
     return json.loads(base64.urlsafe_b64decode(raw+'='*((-len(raw))%4)))
    old=claims();assert 'homelab-observer' in old['groups'] and not set(old['groups']) & {'homelab-owner','homelab-platform-operator'}
    def api_page(path):
     response=page.goto('https://argocd.socrat.alchemmist.xyz'+path)
     assert response.status==200
     return response.json()
    info=api_page('/api/v1/session/userinfo');assert info.get('loggedIn') is True, 'Initial native session must be authenticated'
    assert api_page('/api/v1/account/can-i/applications/create/*')['value']=='no'
    old=claims();assert 0<old['exp']-time.time()<=305
    page.goto('about:blank')
    # No application polls/heartbeats during the idle period. Wait beyond the REAL
    # five-minute expiry; do not forge a JWT or shorten a production token lifetime.
    delay=max(0,old['exp']-time.time()+8)
    print('Native MFA and read-only login passed; waiting past actual token expiry:',round(delay),'seconds',flush=True)
    page.wait_for_timeout(delay*1000)
    auth_navigations=[]
    page.on('request',lambda req:auth_navigations.append(True) if req.is_navigation_request() and urllib.parse.urlparse(req.url).hostname=='auth.socrat.alchemmist.xyz' else None)
    assert api_page('/api/v1/session/userinfo').get('loggedIn') is True, 'Native session lost authentication'
    new=claims();assert new['exp']>old['exp'] and new['sub']==old['sub']
    assert not auth_navigations, 'Browser must not navigate to IdP for refresh'
    assert api_page('/api/v1/account/can-i/applications/create/*')['value']=='no'
    print('PASS: expired five-minute token renewed after idle; Secure preserved, same subject, no IdP navigation or admin grant',flush=True)
    # Then prove preemptive refresh as well, without forging tokens or changing TTL.
    active=new
    deadline=active['exp']+15
    while time.time()<deadline:
     page.wait_for_timeout(15000)
     before_request=time.time()
     assert api_page('/api/v1/session/userinfo').get('loggedIn') is True, 'Native session lost authentication'
     candidate=claims()
     if candidate['exp']>active['exp']:
      assert before_request<active['exp'], 'Active refresh must occur BEFORE expiry'
      assert candidate['sub']==old['sub'] and not auth_navigations
      print('PASS: active preemptive refresh before expiry; Secure preserved; no browser IdP redirect',flush=True)
      break
    else:raise AssertionError('Preemptive renewal was not observed')
    assert api_page('/api/v1/account/can-i/applications/create/*')['value']=='no'
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
 finally:
  api('DELETE','core/users/'+str(user['pk'])+'/')
 print('Temporary Argo CD admission binding and Authentik identity removed',flush=True)
