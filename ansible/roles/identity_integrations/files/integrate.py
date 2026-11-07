"""Explicit native OIDC rollout. Back up configuration privately; never log secrets."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

root=Path(sys.argv[1]);service=sys.argv[2]
kube=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml']
clients=json.loads((root/'oidc-clients.json').read_text())

def private_save(path,data):
    if path.exists():return
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f)

def kubectl(args,body=None):
    result=subprocess.run(kube+args,input=json.dumps(body) if body is not None else None,
        text=True,capture_output=True)
    if result.returncode:raise RuntimeError('Kubernetes operation failed; details suppressed to protect configuration')
    return result.stdout

def idp(method,path,payload=None):
    runtime=json.loads((root/'credentials.json').read_text())
    request=urllib.request.Request('https://auth.socrat.alchemmist.xyz/api/v3/'+path,method=method,
        headers={'Authorization':'Bearer '+runtime['AUTHENTIK_BOOTSTRAP_TOKEN'],'Content-Type':'application/json'},
        data=json.dumps(payload).encode() if payload is not None else None)
    with urllib.request.urlopen(request,timeout=60) as response:
        data=response.read();return json.loads(data) if data else None

def reviewed_user(username, account):
    from urllib.parse import urlencode
    users=idp('GET','core/users/?'+urlencode({'username':username}))['results']
    exact=[u for u in users if u['username']==username]
    if len(exact)!=1 or exact[0]['uuid']!=account.get('idpUserUuid'):
        raise RuntimeError('Reviewed Authentik subject mismatch; no relinking allowed')
    return exact[0]

if service=='harbor':
    # Harbor's supported CONFIG_OVERWRITE_JSON is authoritative configuration.
    # It avoids resetting a human admin password merely to migrate authentication.
    # Refuse to orphan pre-existing non-admin local identities.
    users=kubectl(['-n','harbor','exec','harbor-database-0','-c','database','--',
        'psql','-U','postgres','-d','registry','-Atc',
        "SELECT u.username FROM harbor_user u WHERE u.deleted=false AND u.username <> 'admin' AND NOT EXISTS (SELECT 1 FROM oidc_user o WHERE o.user_id=u.user_id);"])
    if users.strip():raise RuntimeError('Active non-admin Harbor identities require explicit migration review')
    previous=json.loads(kubectl(['-n','harbor','get','deployment','harbor-core','-o','json']))
    private_save(root/'harbor-core-before-oidc.json',previous)
    config={'self_registration':False,'project_creation_restriction':'adminonly',
        'auth_mode':'oidc_auth','oidc_name':'Authentik',
        'oidc_endpoint':'https://auth.socrat.alchemmist.xyz/application/o/harbor/',
        'oidc_client_id':clients['harbor']['client_id'],
        'oidc_client_secret':clients['harbor']['client_secret'],
        'oidc_scope':'openid,profile,email,groups','oidc_user_claim':'preferred_username',
        'oidc_groups_claim':'groups','oidc_admin_group':'homelab-owner',
        'oidc_verify_cert':True,'oidc_auto_onboard':True,
        'project_creation_restriction':'adminonly'}
    secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'socrat-authentik-harbor','namespace':'harbor'},
        'type':'Opaque','stringData':{'config-json':json.dumps(config)}}
    kubectl(['apply','-f','-'],secret)
    # Replace env entry rather than merging value and valueFrom for the same key.
    containers=previous['spec']['template']['spec']['containers']
    core=next(c for c in containers if c['name']=='core')
    env=[e for e in core.get('env',[]) if e['name']!='CONFIG_OVERWRITE_JSON']
    env.append({'name':'CONFIG_OVERWRITE_JSON','valueFrom':{'secretKeyRef':{
        'name':'socrat-authentik-harbor','key':'config-json'}}})
    patch=[{'op':'replace','path':'/spec/template/spec/containers/'+str(containers.index(core))+'/env','value':env}]
    kubectl(['-n','harbor','patch','deployment','harbor-core','--type=json','--patch',json.dumps(patch)])
    kubectl(['-n','harbor','rollout','status','deployment/harbor-core','--timeout=300s'])
    # Public configuration contains no OIDC client secret.
    with urllib.request.urlopen('https://harbor.socrat.alchemmist.xyz/api/v2.0/systeminfo',timeout=30) as r:
        after=json.load(r)
    if after['auth_mode']!='oidc_auth':raise RuntimeError('Harbor OIDC config did not activate')
    print('Harbor OIDC configured via supported override; local admin password unchanged')
elif service=='grafana':
    # Public key/value settings were generated from the committed YAML by Ansible,
    # avoiding a PyYAML dependency on the remote machine.
    public=json.loads((root/'grafana-public-env.json').read_text())
    secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'socrat-authentik-grafana',
        'namespace':'cattle-monitoring-system'},'type':'Opaque',
        'stringData':{'client-secret':clients['grafana']['client_secret']}}
    kubectl(['apply','-f','-'],secret)
    deployment='kube-prometheus-stack-grafana'
    previous=json.loads(kubectl(['-n','cattle-monitoring-system','get','deployment',deployment,'-o','json']))
    private_save(root/'grafana-deployment-before-oidc.json',previous)
    container=next(c for c in previous['spec']['template']['spec']['containers'] if c['name']=='grafana')
    env=[{'name':k,'value':str(v)} for k,v in public.items()]
    env.append({'name':'GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET','valueFrom':{'secretKeyRef':{
        'name':'socrat-authentik-grafana','key':'client-secret'}}})
    patch={'spec':{'template':{'spec':{'containers':[{'name':container['name'],'env':env}]}}}}
    kubectl(['-n','cattle-monitoring-system','patch','deployment',deployment,'--type=strategic','--patch',json.dumps(patch)])
    kubectl(['-n','cattle-monitoring-system','rollout','status','deployment/'+deployment,'--timeout=300s'])
    print('Grafana OIDC button configured without removing local/anonymous access; browser validation pending')
elif service=='open-webui':
    accounts=json.loads((root/'account-mappings.json').read_text())
    links=[]
    for username,account in accounts.items():
        user=reviewed_user(username,account)
        links.append({'id':account['openWebuiUserId'],'email':account['email'],'sub':user['uuid']})
    # Use the application's own model method for reviewed, exact-ID linking.
    code="""import asyncio,json,sys
from open_webui.models.users import Users
async def main():
 for link in json.load(sys.stdin):
  user=await Users.get_user_by_id(link['id'])
  if not user or user.email!=link['email']:raise RuntimeError('Reviewed WebUI identity mismatch')
  old=(user.oauth or {}).get('oidc',{})
  if old.get('sub') not in [None,link['sub']]:raise RuntimeError('Existing OAuth subject differs')
  await Users.update_user_oauth_by_id(user.id,'oidc',link['sub'])
asyncio.run(main())"""
    kubectl(['-n','llm','exec','-i','deployment/open-webui','-c','open-webui','--','python','-c',code],links)
    secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'socrat-authentik-webui','namespace':'llm'},
        'type':'Opaque','stringData':{'client-secret':clients['open-webui']['client_secret']}}
    kubectl(['apply','-f','-'],secret)
    previous=json.loads(kubectl(['-n','llm','get','deployment','open-webui','-o','json']))
    private_save(root/'webui-deployment-before-oidc.json',previous)
    public=json.loads((root/'open-webui-env.json').read_text())
    env=[{'name':k,'value':str(v)} for k,v in public.items()]
    env.append({'name':'OAUTH_CLIENT_SECRET','valueFrom':{'secretKeyRef':{
        'name':'socrat-authentik-webui','key':'client-secret'}}})
    patch={'spec':{'template':{'spec':{'containers':[{'name':'open-webui','env':env}]}}}}
    kubectl(['-n','llm','patch','deployment','open-webui','--type=strategic','--patch',json.dumps(patch)])
    kubectl(['-n','llm','rollout','status','deployment/open-webui','--timeout=600s'])
    print('Open WebUI native OIDC configured; exact UUID links preserve users/chats; no email-based merging')
elif service=='rancher':
    accounts=json.loads((root/'account-mappings.json').read_text())
    original=json.loads(kubectl(['get','authconfigs.management.cattle.io','genericoidc','-o','json']))
    private_save(root/'rancher-authconfig-before-oidc.json',original)
    all_users=json.loads(kubectl(['get','users.management.cattle.io','-o','json']))['items']
    allowed=[]
    for username,account in accounts.items():
        user=reviewed_user(username,account)
        principal='genericoidc_user://'+user['uuid']
        user_id=account['rancherUserId']
        # Rancher's webhook correctly makes existing principalIds immutable.
        # Do not bypass it: create a separate external identity and mirror ONLY
        # the reviewed local user's Rancher-managed grants. Keep local break-glass.
        import hashlib
        external_id=account.get('rancherOidcUserId','u-authentik-'+username)
        collision=[u for u in all_users if principal in u.get('principalIds',[])]
        if any(u['metadata']['name'] not in [user_id,external_id] for u in collision):
            raise RuntimeError('OIDC principal belongs to an unexpected Rancher user')
        existing=next(u for u in all_users if u['metadata']['name']==user_id)
        private_save(root/('rancher-user-'+user_id+'-before-oidc.json'),existing)
        if collision:external_id=collision[0]['metadata']['name']
        elif not any(u['metadata']['name']==external_id for u in all_users):
            external={'apiVersion':'management.cattle.io/v3','kind':'User',
                'metadata':{'name':external_id,'labels':{'app.kubernetes.io/managed-by':'homelab-identity'}},
                'username':username,'displayName':account['name']+' (Authentik)',
                'enabled':True,'principalIds':[principal]}
            kubectl(['create','-f','-'],external)
        else:raise RuntimeError('External Rancher username exists with another principal')
        for kind in ['globalrolebindings','clusterroletemplatebindings','projectroletemplatebindings']:
            resource=kind+'.management.cattle.io'
            bindings=json.loads(kubectl(['get',resource,'-A','-o','json']))['items']
            desired=set()
            for binding in bindings:
                if binding.get('userName')!=user_id:continue
                old_name=binding['metadata']['name']
                new_name=account.get('rancherBindingPrefix','identity-'+username+'-')+hashlib.sha256(old_name.encode()).hexdigest()[:16]
                namespace=binding['metadata'].get('namespace')
                desired.add((namespace,new_name))
                manifest={'apiVersion':binding['apiVersion'],'kind':binding['kind'],
                    'metadata':{'name':new_name,'labels':{'app.kubernetes.io/managed-by':'homelab-identity',
                        'homelab.alchemmist.xyz/identity-user':username}},'userName':external_id}
                if namespace:manifest['metadata']['namespace']=namespace
                for field in ['globalRoleName','roleTemplateName','clusterName','projectName']:
                    if field in binding:manifest[field]=binding[field]
                kubectl(['apply','-f','-'],manifest)
            for binding in bindings:
                labels=binding['metadata'].get('labels',{})
                key=(binding['metadata'].get('namespace'),binding['metadata']['name'])
                if labels.get('app.kubernetes.io/managed-by')=='homelab-identity' and labels.get('homelab.alchemmist.xyz/identity-user')==username and key not in desired:
                    args=['delete',resource,key[1]]
                    if key[0]:args+=['-n',key[0]]
                    kubectl(args)
        allowed.append(principal)
    # Observer admission is group-driven only after native safe defaults exist.
    observer_principal='genericoidc_group://homelab-observer'
    raw_default=json.loads(kubectl(['get','globalroles.management.cattle.io','-o','json']))['items']
    safe_default=next((r for r in raw_default if r['metadata']['name']=='homelab-observer-login'),None)
    ttl=json.loads(kubectl(['get','settings.management.cattle.io','auth-user-session-ttl-minutes','-o','json']))
    ready=bool(safe_default and safe_default.get('newUserDefault') is True
               and safe_default['metadata'].get('labels',{}).get('homelab.alchemmist.xyz/identity-profile')=='observer-v1'
               and all(not r.get('newUserDefault') or r['metadata']['name']=='homelab-observer-login' for r in raw_default)
               and (ttl.get('value') or ttl.get('default'))=='60')
    # Only the reviewed bootstrap may OPEN group admission: readiness here
    # does not prove legacy chat migration or the other service prerequisites.
    if observer_principal in original.get('allowedPrincipalIds',[]):
        if not ready:
            raise RuntimeError('Observer defaults drifted; do not silently rewrite active group admission')
        allowed.append(observer_principal)
    secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'genericoidcconfig-clientsecret','namespace':'cattle-global-data'},
        'type':'Opaque','stringData':{'clientsecret':clients['rancher']['client_secret']}}
    kubectl(['apply','-f','-'],secret)
    settings={'enabled':True,'type':'genericOIDCConfig','accessMode':'restricted',
        'allowedPrincipalIds':allowed,'clientId':clients['rancher']['client_id'],
        'clientSecret':'cattle-global-data:genericoidcconfig-clientsecret',
        'issuer':'https://auth.socrat.alchemmist.xyz/application/o/rancher/',
        'rancherUrl':'https://rancher.socrat.alchemmist.xyz/verify-auth',
        'rancherApiHost':'https://rancher.socrat.alchemmist.xyz',
        'scope':'openid profile email','groupsClaim':'groups','nameClaim':'preferred_username',
        'emailClaim':'email','groupSearchEnabled':False,'clientAuthenticatedSearch':False,'pkceMethod':'S256'}
    kubectl(['patch','authconfigs.management.cattle.io','genericoidc','--type=merge','--patch',json.dumps(settings)])
    print('Rancher native OIDC enabled; UUID-bound external identities mirror reviewed grants; local emergency identities preserved')
elif service=='wiki':
    import secrets
    accounts=json.loads((root/'account-mappings.json').read_text())
    links={};roles={}
    for name,account in accounts.items():
        if 'wikiUserId' not in account:continue
        user=reviewed_user(name,account)
        subject=user['uuid'];links[subject]=account['wikiUserId'];roles[subject]=account['wikiRole']
    previous=kubectl(['-n','wiki','get','secret','socrat-authentik-wiki','--ignore-not-found','-o','json'])
    existing=json.loads(previous) if previous.strip() else None
    if existing:
        state_key=base64.b64decode(existing['data']['WIKI_OIDC_SESSION_SECRET']).decode()
    else:state_key=secrets.token_urlsafe(48)
    data={'UVICORN_ACCESS_LOG':'false','WIKI_OIDC_ISSUER':'https://auth.socrat.alchemmist.xyz/application/o/wiki/',
        'WIKI_OIDC_CLIENT_ID':clients['wiki']['client_id'],'WIKI_OIDC_CLIENT_SECRET':clients['wiki']['client_secret'],
        'WIKI_OIDC_SESSION_SECRET':state_key,'WIKI_OIDC_LOCAL_OWNER_IDS':json.dumps([accounts['alchemmist']['wikiUserId']]),
        'WIKI_OIDC_GROUP_ROLES':json.dumps({'homelab-owner':'admin','homelab-project-maintainer':'editor','homelab-observer':'reader','app-wiki-reader':'reader','app-wiki-editor':'editor'}),
        'WIKI_OIDC_LINKS':json.dumps(links),'WIKI_OIDC_SUBJECT_ROLES':json.dumps(roles)}
    kubectl(['apply','-f','-'],{'apiVersion':'v1','kind':'Secret','metadata':{'name':'socrat-authentik-wiki','namespace':'wiki'},'type':'Opaque','stringData':data})
    old_data={k:base64.b64decode(v).decode() for k,v in existing.get('data',{}).items()} if existing else {}
    if existing and old_data!=data:
        deployment=json.loads(kubectl(['-n','wiki','get','deployment','wiki-runtime-wiki','-o','json']))
        if any(e.get('secretRef',{}).get('name')=='socrat-authentik-wiki' for c in deployment['spec']['template']['spec']['containers'] for e in c.get('envFrom',[])):
            kubectl(['-n','wiki','rollout','restart','deployment/wiki-runtime-wiki'])
            kubectl(['-n','wiki','rollout','status','deployment/wiki-runtime-wiki','--timeout=600s'])
    print('Wiki OIDC Secret reconciled; exact reviewed subjects, owner-only local fallback; no password reset')
elif service=='lms':
    kubectl(['apply','-f','-'],{'apiVersion':'v1','kind':'Secret','metadata':{'name':'socrat-authentik-lms','namespace':'lms'},
        'type':'Opaque','stringData':{'client-id':clients['lms']['client_id'],'client-secret':clients['lms']['client_secret']}})
    print('LMS OIDC secret reconciled; Authentik remains the only identity provider')
else:raise SystemExit('Unsupported integration')
