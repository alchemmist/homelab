"""Create role groups without granting access or importing human identities."""
import json
from pathlib import Path
import sys
import urllib.request
from app_iam import LEGACY_GROUPS, GROUP_MARKER, app_groups, admission_groups, rows, validate_group, validate_bindings

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

services=json.loads((root/'services.json').read_text())
# Never admit new Harbor observers while its native project-creation defaults
# are still broad. The one-time native bootstrap writes this private receipt.
observer_ready_path=root/'observer-ready.json'
observer_ready=False
if observer_ready_path.exists():
    import os
    st=observer_ready_path.stat()
    if observer_ready_path.is_symlink() or st.st_mode & 0o077 or st.st_uid!=os.geteuid():
        raise RuntimeError('Unsafe observer readiness receipt')
    ready=json.loads(observer_ready_path.read_text())
    import hashlib
    observer_profile=root/'observer-profile.json'
    observer_ready=(ready.get('version')==1 and ready.get('nativeObserverReady') is True
                    and observer_profile.is_file()
                    and ready.get('policy_sha256')==hashlib.sha256(observer_profile.read_bytes()).hexdigest())
account_path=root/'account-mappings.json'
accounts=json.loads(account_path.read_text()) if account_path.exists() else {}
# Check pinned identities BEFORE any write, including email/link reconciliation.
for username,account in accounts.items():
    existing=unique('core/users/','username',username)
    if not existing:
        raise RuntimeError('Reviewed identity missing; restore/review instead of recreating: '+username)
    if existing.get('uuid')!=account.get('idpUserUuid'):
        raise RuntimeError('Reviewed Authentik UUID mismatch: '+username)

managed_app_groups=app_groups(services)
groups={}
for name in LEGACY_GROUPS+list(managed_app_groups):
    group=unique('core/groups/','name',name)
    if group is None:
        settings={'name':name,'is_superuser':False}
        if name in managed_app_groups:settings['attributes']=GROUP_MARKER
        group=api('POST','core/groups/',settings)
    if name in managed_app_groups:validate_group(group)
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
if account_path.exists():
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
groups_scope=unique('propertymappings/provider/scope/','name','homelab-groups')
groups_settings={'name':'homelab-groups','scope_name':'groups',
    'expression':'return {"groups": [group.name for group in request.user.ak_groups.all()]}'}
if not groups_scope:
    groups_scope=api('POST','propertymappings/provider/scope/',groups_settings)
elif groups_scope.get('expression')!=groups_settings['expression']:
    groups_scope=api('PATCH','propertymappings/provider/scope/'+str(groups_scope['pk'])+'/',groups_settings)
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
        service_mapping=list(mapping)
        for mapping_name in service.get('extraScopeMappings', []):
            custom_mapping=unique('propertymappings/provider/scope/','name',mapping_name)
            if not custom_mapping:
                if slug!='litellm':raise RuntimeError('Reviewed custom scope missing: '+slug)
                print('LiteLLM awaits explicit reviewed native integration; no placeholder application created')
                service_mapping=None
                break
            service_mapping.append(custom_mapping['pk'])
        if service_mapping is None:continue
        if service.get('groupsScope'):
            service_mapping.append(groups_scope['pk'])
        if slug=='grafana':
            offline=next((x for x in scopes if x.get('scope_name')=='offline_access'), None)
            if not offline:raise RuntimeError('offline_access scope missing')
            service_mapping.append(offline['pk'])
        settings={'name':'homelab-'+slug,'client_type':'confidential',**clients[slug],
            'grant_types':['authorization_code','refresh_token'],
            'authentication_flow':flow['default-authentication-flow'],
            'authorization_flow':flow['default-provider-authorization-explicit-consent'],
            'invalidation_flow':flow['default-provider-invalidation-flow'],
            'property_mappings':service_mapping,'signing_key':cert['pk'],
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
    allowed=admission_groups(slug,service)
    bindings=[]
    if application:
        if application.get('policy_engine_mode')!='any':
            raise RuntimeError('Application policy mode drift: '+slug)
        bindings=rows(api,'policies/bindings/?target='+str(application['pk']))
        validate_bindings(bindings,{groups[name] for name in allowed})
        application=api('PATCH','core/applications/'+slug+'/',settings)
    else:application=api('POST','core/applications/',settings)
    # Additive bindings only. Unknown/disabled/negated UI policy is a blocker.
    for order,name in enumerate(allowed):
        if name=='homelab-observer' and service.get('observerAdmissionRequiresBootstrap') and not observer_ready:
            continue
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
