"""Create role groups without granting access or importing human identities."""
import json
from pathlib import Path
import sys
import urllib.request

root=Path(sys.argv[1])
credentials=json.loads((root/'credentials.json').read_text())
base='https://auth.socrat.alchemmist.xyz/api/v3/'
def api(method,path,payload=None):
    req=urllib.request.Request(base+path,method=method,
        headers={'Authorization':'Bearer '+credentials['AUTHENTIK_BOOTSTRAP_TOKEN'],'Content-Type':'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(req,timeout=60) as response:
        body=response.read();return json.loads(body) if body else None


import os
import secrets

def unique(path, field, value):
    from urllib.parse import urlencode
    query={field:value}
    if path=='core/applications/':query['superuser_full_list']='true'
    rows=api('GET',path+'?'+urlencode(query))['results']
    exact=[x for x in rows if x[field]==value]
    if len(exact)>1:raise RuntimeError('Ambiguous identity/configuration: '+value)
    return exact[0] if exact else None

groups={}
for name in ['homelab-owner','homelab-platform-operator','homelab-project-maintainer','homelab-observer','homelab-machine-owner']:
    group=unique('core/groups/','name',name)
    if group is None:group=api('POST','core/groups/',{'name':name,'is_superuser':False})
    groups[name]=group['pk']

# Bootstrap a personal owner account; never auto-link or import another service's
# human accounts. The initial password is private and never silently reset.
owner_path=root/'owner-login.json'
owner=unique('core/users/','username','alchemmist')
if not owner_path.exists():
    if owner:raise RuntimeError('Owner username already exists without bootstrap journal; review identity manually')
    fd=os.open(owner_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump({'username':'alchemmist','password':secrets.token_urlsafe(32),'initialized':False},f)
owner_login=json.loads(owner_path.read_text())
if not owner_login['initialized']:
    if not owner:
        owner=api('POST','core/users/',{'username':'alchemmist','name':'alchemmist',
             'is_active':True,'groups':[groups['homelab-owner']]})
    api('POST','core/users/'+str(owner['pk'])+'/set_password/',{'password':owner_login['password']})
    owner_login['initialized']=True
    owner_path.write_text(json.dumps(owner_login));owner_path.chmod(0o600)
# Only the declared owner may inherit this group's superuser rights.
owner_group=unique('core/groups/','name','homelab-owner')
if set(owner_group.get('users',[]))-set([owner['pk']]):
    raise RuntimeError('Unexpected owner group membership; review before granting superuser')
api('PATCH','core/groups/'+groups['homelab-owner']+'/',{'is_superuser':True})

# Explicitly reviewed existing identities; no general email-based account merging.
account_path=root/'account-mappings.json'
if account_path.exists():
    accounts=json.loads(account_path.read_text())
    for username,account in accounts.items():
        if username!='alchemmist' and 'homelab-owner' in account['groups']:
            raise RuntimeError('Only the declared owner may receive owner membership')
        user=unique('core/users/','username',username)
        login_path=root/(username+'-login.json') if username!='alchemmist' else owner_path
        if not login_path.exists():
            if user:raise RuntimeError('Account exists without bootstrap journal: '+username)
            fd=os.open(login_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'w') as f:json.dump({'username':username,'password':secrets.token_urlsafe(32),'initialized':False},f)
        journal=json.loads(login_path.read_text())
        if not journal['initialized']:
            if not user:user=api('POST','core/users/',{'username':username,'name':account['name'],
                'email':account['email'],'groups':[groups[g] for g in account['groups']],'is_active':True})
            api('POST','core/users/'+str(user['pk'])+'/set_password/',{'password':journal['password']})
            journal['initialized']=True;login_path.write_text(json.dumps(journal));login_path.chmod(0o600)
        if user.get('email') not in ['',None,account['email']]:
            raise RuntimeError('Existing email differs from reviewed account mapping: '+username)
        if not user.get('email'):api('PATCH','core/users/'+str(user['pk'])+'/',{'email':account['email']})

# Enforce enrollment rather than the upstream default of silently skipping MFA.
validation=unique('stages/authenticator/validate/','name','default-authentication-mfa-validation')
totp=unique('stages/authenticator/totp/','name','default-authenticator-totp-setup')
if not validation or not totp:raise RuntimeError('Expected default MFA stages missing')
api('PATCH','stages/authenticator/validate/'+validation['pk']+'/',{
    'not_configured_action':'configure','device_classes':['totp','webauthn','static'],
    'configuration_stages':[totp['pk']]})

flows=api('GET','flows/instances/?page_size=100')['results']
flow={x['slug']:x['pk'] for x in flows}
cert=unique('crypto/certificatekeypairs/','name','authentik Self-signed Certificate')
scopes=api('GET','propertymappings/provider/scope/?page_size=100')['results']
mapping=[x['pk'] for x in scopes if x['scope_name'] in ['openid','profile','email']]
if len(mapping)!=3 or not cert:raise RuntimeError('OIDC defaults missing')
services=json.loads((root/'services.json').read_text())
clients_path=root/'oidc-clients.json'
clients=json.loads(clients_path.read_text()) if clients_path.exists() else {}
proxy_ids=[]
for slug,service in services.items():
    provider=None
    if service.get('proxy'):
        provider=unique('providers/proxy/','name','homelab-'+slug)
        settings={'name':'homelab-'+slug,'mode':'proxy',
            'authentication_flow':flow['default-authentication-flow'],
            'authorization_flow':flow['default-provider-authorization-implicit-consent'],
            'invalidation_flow':flow['default-provider-invalidation-flow'],
            'external_host':service['url'],'internal_host':service['proxy']['internalHost'],
            'internal_host_ssl_validation':True,'skip_path_regex':service['proxy']['skipPathRegex'],
            'cookie_domain':__import__('urllib.parse',fromlist=['urlparse']).urlparse(service['url']).hostname,
            'intercept_header_auth':False,'basic_auth_enabled':False}
        if provider:provider=api('PATCH','providers/proxy/'+str(provider['pk'])+'/',settings)
        else:provider=api('POST','providers/proxy/',settings)
        proxy_ids.append(provider['pk'])
    elif 'redirect' in service:
        provider=unique('providers/oauth2/','name','homelab-'+slug)
        if slug not in clients:
            if provider:raise RuntimeError('Provider exists without local client credentials; refusing rotation')
            clients[slug]={'client_id':'socrat-'+slug,'client_secret':secrets.token_urlsafe(48)}
            # Persist before provider creation, so retries cannot regenerate its secret.
            fd=os.open(clients_path,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as f:json.dump(clients,f)
        settings={'name':'homelab-'+slug,'client_type':'confidential',**clients[slug],
            'grant_types':['authorization_code','refresh_token'],
            'authentication_flow':flow['default-authentication-flow'],
            'authorization_flow':flow['default-provider-authorization-explicit-consent'],
            'invalidation_flow':flow['default-provider-invalidation-flow'],
            'property_mappings':mapping,'signing_key':cert['pk'],
            'redirect_uris':[{'matching_mode':'strict','url':url} for url in [service['redirect']]+service.get('extraRedirects',[])],
            'include_claims_in_id_token':True,'sub_mode':service.get('subMode','hashed_user_id'),
            'access_token_validity':'minutes=5','refresh_token_validity':'hours=8'}
        if provider:
            provider=api('PATCH','providers/oauth2/'+str(provider['pk'])+'/',settings)
        else:provider=api('POST','providers/oauth2/',settings)
    # Portal links for non-OIDC services are explicitly not native SSO.
    application=unique('core/applications/','slug',slug)
    settings={'name':service['name'],'slug':slug,'provider':provider['pk'] if provider else None,
        'meta_launch_url':service['url'],'meta_description':service['description'],
        'policy_engine_mode':'any','group':'Socrat','meta_icon':service.get('icon','')}
    if application:application=api('PATCH','core/applications/'+slug+'/',settings)
    else:application=api('POST','core/applications/',settings)
    # Deny by default: explicit application bindings to approved role groups.
    bindings=api('GET','policies/bindings/?target='+str(application['pk'])+'&page_size=100')['results']
    for order,name in enumerate(service.get('groups',['homelab-owner'])):
        if not any(b.get('group')==groups[name] for b in bindings):
            api('POST','policies/bindings/',{'target':application['pk'],'group':groups[name],
                'order':order,'enabled':True,'failure_result':False})
if proxy_ids:
    outposts=api('GET','outposts/instances/?page_size=100')['results']
    embedded=[o for o in outposts if o.get('managed')=='goauthentik.io/outposts/embedded']
    if len(embedded)!=1:raise RuntimeError('Expected one managed embedded outpost')
    outpost=embedded[0];config=dict(outpost['config'])
    config['authentik_host']='https://auth.socrat.alchemmist.xyz/'
    config['authentik_host_browser']='https://auth.socrat.alchemmist.xyz/'
    api('PATCH','outposts/instances/'+outpost['pk']+'/',{
        'providers':list(set(outpost['providers'])|set(proxy_ids)),'config':config})
print('Owner bootstrap, role groups, mandatory MFA and restricted providers reconciled; no existing service accounts auto-linked')
