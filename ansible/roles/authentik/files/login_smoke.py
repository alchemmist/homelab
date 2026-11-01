import http.cookiejar,json,urllib.request
from pathlib import Path
root=Path.home()/'.cache/homelab-authentik'
owner=json.loads((root/'owner-login.json').read_text())
jar=http.cookiejar.CookieJar();opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
base='https://auth.socrat.alchemmist.xyz';endpoint=base+'/api/v3/flows/executor/default-authentication-flow/'
def call(data=None):
 headers={'Content-Type':'application/json','Referer':base+'/if/flow/default-authentication-flow/'}
 for cookie in jar:
  if 'csrf' in cookie.name:headers['X-CSRFToken']=cookie.value
 req=urllib.request.Request(endpoint,data=json.dumps(data).encode() if data is not None else None,headers=headers)
 return json.load(opener.open(req,timeout=30))
for i in range(6):
 response=call() if i==0 else response
 component=response.get('component','');kind=response.get('type','')
 print('Login stage:',component or kind)
 if component=='ak-stage-identification':response=call({'uid_field':owner['username']})
 elif component=='ak-stage-password':response=call({'password':owner['password']})
 elif component in ['ak-stage-authenticator-totp','ak-stage-authenticator-validate']:
  print('Owner initial password accepted; MFA enrollment/challenge required (not enrolled by automation)');break
 elif kind=='redirect':
  target=response.get('to','')
  if 'default-authenticator-totp-setup' in target:print('MFA setup redirect required');break
  print('Additional browser interaction required');break
 else:
  print('Challenge keys:',list(response));break
