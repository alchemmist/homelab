#!/usr/bin/env python3
"""Live MFA gateway acceptance, NOT a 3x-ui login or native SSO test.
Explicit temporary observer/admission writes; never reads/resets owner factors or
native panel passwords. No screenshots, traces, HTML, cookies or OTPs are saved.
"""
import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run',action='store_true')
parser.add_argument('--wait-refresh',action='store_true',help='Also wait beyond actual five-minute provider token lifetime')
parser.add_argument('--public-edge',choices=['176.98.185.59','109.173.40.247'],default='176.98.185.59')
args=parser.parse_args()
if not args.run:parser.error('--run required for temporary live fixtures')
import base64,hashlib,hmac,json,secrets,socket,struct,subprocess,time,urllib.parse,urllib.request,uuid
from playwright.sync_api import sync_playwright
BASE='https://auth.socrat.alchemmist.xyz'
original=socket.getaddrinfo
socket.getaddrinfo=lambda h,*a,**kw:original('109.173.40.247' if h=='auth.socrat.alchemmist.xyz' else args.public_edge if h=='vpn.alchemmist.xyz' else h,*a,**kw)
SSH=['ssh','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0']
credential=json.loads(subprocess.check_output(SSH+['cat ~/.cache/homelab-authentik/credentials.json']))
def api(method,path,data=None):
 req=urllib.request.Request(BASE+'/api/v3/'+path,method=method,headers={'Authorization':'Bearer '+credential['AUTHENTIK_BOOTSTRAP_TOKEN'],'Content-Type':'application/json'},data=json.dumps(data).encode() if data is not None else None)
 with urllib.request.urlopen(req,timeout=45) as r:
  body=r.read();return json.loads(body) if body else None
app=api('GET','core/applications/xui-panel/')
owner=next(g for g in api('GET','core/groups/?name=homelab-owner')['results'] if g['name']=='homelab-owner')
bindings=[b for b in api('GET','policies/bindings/?page_size=1000')['results'] if b['target']==app['pk']]
assert len(bindings)==1 and bindings[0]['group']==owner['pk'] and not bindings[0].get('user')
launch=app['meta_launch_url'];assert urllib.parse.urlparse(launch).hostname=='vpn.alchemmist.xyz'
username='xui-gateway-smoke-'+uuid.uuid4().hex[:10];password=secrets.token_urlsafe(32)
observer=next(g for g in api('GET','core/groups/?name=homelab-observer')['results'] if g['name']=='homelab-observer')
user=api('POST','core/users/',{'username':username,'name':'Temporary VPN gateway acceptance','email':username+'@example.invalid','groups':[observer['pk']],'is_active':True})
binding=None
try:
 api('POST','core/users/'+str(user['pk'])+'/set_password/',{'password':password})
 with sync_playwright() as p:
  browser=p.chromium.launch(args=['--host-resolver-rules=MAP auth.socrat.alchemmist.xyz 109.173.40.247, MAP vpn.alchemmist.xyz '+args.public_edge])
  context=browser.new_context(viewport={'width':1440,'height':960})
  page=context.new_page();challenge={};components=[];errors=[];denials=[];authorization_scopes=[]
  def observe(response):
   parsed=urllib.parse.urlparse(response.url)
   if parsed.hostname=='auth.socrat.alchemmist.xyz' and parsed.path=='/application/o/authorize/':
    authorization_scopes.extend(urllib.parse.parse_qs(parsed.query).get('scope',[''])[0].split())
   if response.status==403 and parsed.hostname in ['auth.socrat.alchemmist.xyz','vpn.alchemmist.xyz']:
    denials.append(True);print('Native policy HTTP denial:',response.status,flush=True)
   if '/api/v3/flows/executor/' not in response.url or response.status not in [200,400]:return
   try:
    data=response.json();component=data.get('component')
    if component:components.append(component);print('Native stage:',component,flush=True)
    if component=='ak-stage-authenticator-totp':challenge.clear();challenge.update(data)
   except Exception:pass
  page.on('response',observe)
  page.on('pageerror',lambda e:errors.append(True) if urllib.parse.urlparse(page.url).hostname=='auth.socrat.alchemmist.xyz' else None)
  page.goto(launch);page.locator('input[name=uidField]').wait_for(timeout=30000)
  page.locator('input[name=uidField]').fill(username);page.locator('input[type=password]').filter(visible=True).fill(password)
  page.locator('button[type=submit]').click()
  denied=False
  for step in range(100):
   if page.locator('ak-stage-authenticator-totp').is_visible():
    source=challenge.get('secret') or challenge.get('secret_key') or urllib.parse.parse_qs(urllib.parse.urlparse(challenge.get('config_url','')).query).get('secret',[None])[0]
    if not source:raise RuntimeError('Fixture-only TOTP setup challenge unavailable')
    key=base64.b32decode(source.upper()+'='*((-len(source))%8));sig=hmac.new(key,struct.pack('>Q',int(time.time())//30),hashlib.sha1).digest();offset=sig[-1]&15
    otp=str((struct.unpack('>I',sig[offset:offset+4])[0]&0x7fffffff)%1000000).zfill(6)
    stage=page.locator('ak-stage-authenticator-totp');stage.locator('input[name=code]').fill(otp);stage.locator('button[type=submit]').click();stage.wait_for(state='hidden',timeout=30000)
   native_denied=urllib.parse.urlparse(page.url).hostname=='auth.socrat.alchemmist.xyz' and 'permission denied' in page.locator('body').inner_text().lower()
   if 'ak-stage-access-denied' in components or denials or native_denied:
    denied=True;break
   if urllib.parse.urlparse(page.url).hostname=='vpn.alchemmist.xyz' and page.locator('input[type=password]').count():raise AssertionError('Non-owner reached native panel login without admission')
   page.wait_for_timeout(500)
  if not denied:
   text=page.locator('body').inner_text().lower()
   print('Denied-state classification:',urllib.parse.urlparse(page.url).hostname,[x for x in ['permission','denied','forbidden','unauthorized','error','redirect','bad request','invalid','access'] if x in text], 'body characters:',len(text),flush=True)
  assert denied and 'ak-stage-authenticator-totp' in components,'Expected native MFA and non-owner policy denial'
  print('PASS: real native MFA completed; ordinary observer denied by owner-only application policy',flush=True)
  inspection=context.request.get(BASE+'/api/v3/flows/inspector/default-provider-authorization-implicit-consent/')
  assert inspection.status in [403,404]
  print('PASS: fixture inspector access denied',inspection.status)
  binding=api('POST','policies/bindings/',{'target':app['pk'],'user':user['pk'],'order':90000+secrets.randbelow(10000),'enabled':True,'failure_result':False})
  # Native policy/outpost caches may briefly retain the preceding denial.
  for attempt in range(8):
   page.goto(launch);page.wait_for_timeout(1800)
   if urllib.parse.urlparse(page.url).hostname=='vpn.alchemmist.xyz' and page.locator('input[type=password]').count():break
   if page.locator('ak-stage-consent').is_visible():page.locator('ak-stage-consent button[name=continue]').click()
   page.wait_for_timeout(1000)
  else:raise AssertionError('Explicit fixture admission did not reach native login')
  cookies=context.cookies('https://vpn.alchemmist.xyz')
  proxy=[c for c in cookies if c['name'].startswith('authentik_proxy')]
  assert proxy and all(c['secure'] and c['httpOnly'] for c in proxy),'Proxy cookies must be Secure and HttpOnly'
  assert page.locator('input[type=password]').count(),'Test must remain at native login screen'
  print('PASS: admitted fixture reached separate native 3x-ui password screen; proxy cookies Secure/HttpOnly',flush=True)
  # Exercise native CSRF + POST parsing without a real native username/password.
  transport=page.evaluate("""async base=>{
   const c=await fetch(base+'csrf-token',{credentials:'same-origin'});const token=(await c.json()).obj;
   const r=await fetch(base+'login',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded','X-CSRF-Token':token,'X-Requested-With':'XMLHttpRequest'},body:'username=&password='});
   return {csrf:c.status,status:r.status,redirected:r.redirected,json:(r.headers.get('content-type')||'').includes('json')};
  }""",launch)
  assert transport=={'csrf':200,'status':200,'redirected':False,'json':True}
  print('PASS: native CSRF + safe empty-login POST returns native JSON, no redirect',flush=True)
  # Missing proxy cookie models the exact expired-session branch, no forged JWT.
  context.clear_cookies(name=__import__('re').compile('^authentik_proxy'))
  missing=page.evaluate("""async base=>{
   const r=await fetch(base+'login',{method:'POST',credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest','Content-Type':'application/x-www-form-urlencoded'},body:'username=&password='});
   return {status:r.status,redirected:r.redirected,origin:new URL(r.url).origin};
  }""",launch)
  assert missing=={'status':401,'redirected':False,'origin':'https://vpn.alchemmist.xyz'}
  print('PASS: missing/expired gateway session returns same-origin 401, not Failed to fetch',flush=True)
  # The real native login UI handles that 401 itself with top-level navigation.
  page.locator('input[autocomplete=username]').fill('gateway-recovery-nonexistent-fixture')
  page.locator('input[type=password]').fill(secrets.token_urlsafe(24))
  if page.locator('input[autocomplete=one-time-code]').count():page.locator('input[autocomplete=one-time-code]').fill('000000')
  rejected=[]
  page.on('response',lambda r:rejected.append(r.status) if r.request.method=='POST' and urllib.parse.urlparse(r.url).path==urllib.parse.urlparse(launch).path+'login' else None)
  page.locator('button[type=submit]').click()
  for attempt in range(100):
   page.wait_for_timeout(200)
   proxy=[c for c in context.cookies('https://vpn.alchemmist.xyz') if c['name'].startswith('authentik_proxy')]
   if 401 in rejected and proxy and page.url==launch and page.locator('input[type=password]').count():break
  else:raise AssertionError('Native UI did not recover missing gateway session')
  assert 200 not in rejected,'Synthetic native credentials must never reach the backend'
  print('PASS: actual native login submit handles 401 and returns via top-level SSO; no native password attempted',flush=True)

  response=context.request.get(launch+'panel/api/server/status',headers={'Authorization':'Bearer deliberately-invalid-probe'},max_redirects=0)
  assert response.status==401
  print('PASS: invalid machine Bearer returns native 401 even with authenticated gateway browser cookies')
  if args.wait_refresh:
   assert 'offline_access' in authorization_scopes,'Live proxy authorization must request offline_access'
   navigations=[]
   page.on('request',lambda r:navigations.append(True) if r.is_navigation_request() and urllib.parse.urlparse(r.url).hostname=='auth.socrat.alchemmist.xyz' else None)
   page.goto('about:blank');print('Waiting past real five-minute proxy access-token lifetime',flush=True)
   page.wait_for_timeout(315000);page.goto(launch);page.locator('input[type=password]').wait_for(timeout=30000)
   print('Native proxy browser IdP roundtrip after expiry:',bool(navigations),flush=True)
   assert all(c['secure'] and c['httpOnly'] for c in context.cookies('https://vpn.alchemmist.xyz') if c['name'].startswith('authentik_proxy'))
   print('PASS: gateway authorization returns after real five-minute expiry; Secure preserved (not a silent-refresh claim)',flush=True)
  anonymous=browser.new_context()
  r=anonymous.request.get(launch,headers={'X-authentik-username':'alchemmist','X-authentik-groups':'homelab-owner'},max_redirects=0)
  assert r.status==302
  print('PASS: forged identity headers do not bypass gateway authentication')
  assert not errors,'Authentik JS error observed'
  browser.close()
except Exception as error:
 print('Acceptance failed (sanitized):',type(error).__name__,flush=True)
 raise SystemExit(1)
finally:
 try:
  if binding:api('DELETE','policies/bindings/'+binding['pk']+'/')
 finally:api('DELETE','core/users/'+str(user['pk'])+'/')
 print('Temporary observer identity and exact admission binding removed',flush=True)
