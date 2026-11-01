#!/usr/bin/env python3
"""Explicit live branding acceptance: temporary observer, real MFA/OIDC, cleanup.
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
 return _original_getaddrinfo(args.public_edge if host=='auth.socrat.alchemmist.xyz' else host,*params,**kwargs)
socket.getaddrinfo=public_auth
SSH=['ssh','-o','ConnectTimeout=10','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0']
credential=json.loads(subprocess.check_output(SSH+['cat ~/.cache/homelab-authentik/credentials.json']))
def api(method,path,data=None):
 req=urllib.request.Request(BASE+'/api/v3/'+path,method=method,headers={'Authorization':'Bearer '+credential['AUTHENTIK_BOOTSTRAP_TOKEN'],'Content-Type':'application/json'},data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(req,timeout=45) as r:
  b=r.read();return json.loads(b) if b else None

from playwright.sync_api import sync_playwright
import secrets,time,urllib.parse,base64,hmac,hashlib,struct,uuid
username='theme-smoke-'+uuid.uuid4().hex[:10];password=secrets.token_urlsafe(32)
group=next(x for x in api('GET','core/groups/?name=homelab-observer')['results'] if x['name']=='homelab-observer')
user=api('POST','core/users/',{'username':username,'name':'Temporary theme acceptance probe','email':username+'@example.invalid','groups':[group['pk']],'is_active':True})
try:
 api('POST','core/users/'+str(user['pk'])+'/set_password/',{'password':password})
 with sync_playwright() as p:
  browser=p.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz '+args.public_edge])
  page=browser.new_page(viewport={'width':1440,'height':960});last={};totp_challenge={};components=[];errors=[]
  def observe(response):
   if '/api/v3/flows/executor/' in response.url and response.status in [200,400]:
    try:
     data=response.json();last.clear();last.update(data);print('Executor result:',response.status,data.get('type'),data.get('component'),'errors:',bool(data.get('response_errors')))
     if data.get('component'):components.append(data['component'])
     if data.get('component')=='ak-stage-authenticator-totp':totp_challenge.clear();totp_challenge.update(data)
    except Exception:pass
  page.on('response',observe);page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto('https://grafana.socrat.alchemmist.xyz/login/generic_oauth');page.locator('input[name="uidField"]').wait_for()
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
   elif urllib.parse.urlparse(page.url).hostname=='grafana.socrat.alchemmist.xyz':
    resp=page.request.get('https://grafana.socrat.alchemmist.xyz/api/user')
    if resp.status!=200:
     page.wait_for_timeout(500);continue
    profile=resp.json();assert profile['login']==username and not profile.get('isGrafanaAdmin')
    assert 'ak-stage-authenticator-totp' in components and 'ak-stage-consent' in components
    print('PASS: native browser password + TOTP + consent + Grafana OIDC; observer is not server admin')
    break
   page.wait_for_timeout(500)
  else:raise RuntimeError('Browser roundtrip did not complete')
  print('Browser JS errors:',len(errors));assert not errors
  browser.close()
finally:
 try:
  api('DELETE','core/users/'+str(user['pk'])+'/');print('Temporary Authentik theme identity removed')
 finally:
  source=Path(__file__).with_name('identity-grafana-smoke.py').read_text();cleanup=source.split('cleanup="""',1)[1].split('"""',1)[0]
  cleanup=cleanup.replace("user.get('name')=='Temporary SSO acceptance probe'", "user.get('name') in ['Temporary theme acceptance probe','Temporary SSO acceptance probe']")
  subprocess.run(SSH+['python3','-'],input=('target='+repr(username)+'\n'+cleanup).encode(),check=True,timeout=60)
