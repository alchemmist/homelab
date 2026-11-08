#!/usr/bin/env python3
"""Explicit temporary native 3x-ui machine access. Never edits SQLite or human auth.
CLI bootstrap uses a collision-checked NEW name; normal operations use node-sync.
A TTL admin token exists only to issue/revoke our tokens. All secrets stay private.
The CLI bootstrap cannot have a native TTL: an interrupted issuance must be treated
as uncertain and recovered from its private stdout, never blindly replayed.
"""
from contextlib import closing
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import time
import urllib.request

spec = importlib.util.spec_from_file_location('inventory', Path(__file__).with_name('vpn-hardening-inventory.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
IMAGE = 'ghcr.io/mhsanaei/3x-ui@sha256:1628adbd9bed680d25d6f714bef4a20f132105f4612ea294952f6665dad32e5b'
DB = Path('/srv/x-ui-lab/db/x-ui.db')
KUBE = ['/usr/local/bin/kubectl', '--kubeconfig', '/etc/rancher/k3s/k3s.yaml']


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('API redirect refused')


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=25, **kwargs)
    if result.returncode:
        raise RuntimeError('Native read failed')
    return result.stdout


def token_rows(database=DB):
    with closing(sqlite3.connect(h.check_path(database).as_uri() + '?mode=ro', uri=True)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute('SELECT * FROM api_tokens ORDER BY id')]


def api_path(database=DB):
    with closing(sqlite3.connect(h.check_path(database).as_uri() + '?mode=ro', uri=True)) as con:
        settings = dict(con.execute('SELECT key,value FROM settings'))
    path = settings['webBasePath']
    if not re.fullmatch(r'/[A-Za-z0-9_/-]*/?', path) or '..' in path or '//' in path:
        raise ValueError('Unexpected API base path')
    if int(settings['webPort']) != 18082:
        raise ValueError('Unexpected panel port')
    return 'http://127.0.0.1:18082/' + path.strip('/') + '/panel/api'


def request(base, token, method, path, body=None):
    if not re.fullmatch(r'/(?:setting/apiTokens(?:/create|/delete/[0-9]+)?|inbounds/(?:list|update/[0-9]+)|clients/(?:add|del/[A-Za-z0-9_.@-]+))', path):
        raise ValueError('Unreviewed native API operation')
    if not re.fullmatch(r'[A-Za-z0-9]{48}', token):
        raise ValueError('Invalid machine credential')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(base + path, method=method,
        data=None if body is None else h.canonical(body).encode(),
        headers={'Authorization':'Bearer '+token,'Content-Type':'application/json',
                 'Accept':'application/json','X-Requested-With':'XMLHttpRequest','Host':'vpn.alchemmist.xyz'})
    try:
        with opener.open(req, timeout=20) as response:
            data = response.read(8*1024*1024 + 1)
            if len(data)>8*1024*1024 or response.status != 200:
                raise ValueError('Unexpected native API response')
        obj = json.loads(data)
        if obj.get('success') is not True:
            raise ValueError('Native API rejected operation')
        return obj.get('obj')
    except Exception:
        raise RuntimeError('Native API operation failed; inspect private receipts, never retry writes blindly') from None


def pod_identity():
    items = json.loads(command(KUBE+['-n','x-ui','get','pods','-l','app.kubernetes.io/name=x-ui','-o','json']))['items']
    if len(items)!=1:
        raise ValueError('Expected one primary pod')
    p=items[0]
    if (p['spec']['nodeName']!='socrat-2' or p['status']['phase']!='Running'
            or p['spec']['containers'][0]['image']!=IMAGE
            or not all(c['ready'] for c in p['status']['containerStatuses'])):
        raise ValueError('Unexpected primary workload')
    ex=KUBE+['-n','x-ui','exec',p['metadata']['name'],'-c','primary','--']
    if command(ex+['/app/x-ui','-v']).strip()!='3.11.0':
        raise ValueError('Panel version drift')
    if not command(ex+['/app/bin/xray-linux-amd64','version']).splitlines()[0].startswith('Xray 26.10.21 '):
        raise ValueError('Core version drift')
    return {'name':p['metadata']['name'],'uid':p['metadata']['uid'],'image':IMAGE}


class NativeSession:
    def __init__(self, state, database=DB):
        self.state=Path(state).absolute();self.database=Path(database)
        label=self.state.name
        if not re.fullmatch(r'vpn83-[a-z0-9-]{8,32}',label):
            raise ValueError('Use a fresh explicit vpn83-* session name')
        self.names={kind:label+'-'+kind for kind in ('bootstrap','cleanup','worker')}
        self.base=None;self.credentials={};self.original=[];self.lock=None

    def preview(self):
        original=token_rows(self.database)
        if any(r['name'] in self.names.values() for r in original):
            raise ValueError('Temporary token name collision; never rotate')
        return {'pod':pod_identity(),'configuration_sha256':h.inspect(self.database)['configuration_sha256'],
                'existing_tokens_sha256':h.digest(original),'names':self.names,'scope':'node-sync',
                'worker_ttl_minutes':20,'cleanup_ttl_minutes':30}

    def _save_credential(self,kind,value):
        h.save(self.state/(kind+'.json'),value);self.credentials[kind]=value

    def _owned(self,kind):
        expected=self.credentials[kind]
        rows=[r for r in token_rows(self.database) if r['id']==expected['id']]
        if not rows:return None
        row=rows[0]
        if (row['name']!=self.names[kind] or row['scope']!=expected['scope']
                or row['token']!=hashlib.sha256(expected['token'].encode()).hexdigest()):
            raise ValueError('Credential ownership changed; refusing deletion')
        return row

    def _delete(self,kind,actor):
        row=self._owned(kind)
        if row is not None:
            request(self.base,self.credentials[actor]['token'],'POST','/setting/apiTokens/delete/'+str(row['id']),{'expectedScope':row['scope']})
        if self._owned(kind) is not None:
            raise RuntimeError('Credential deletion did not converge')

    def _create(self,kind,scope,minutes,actor):
        expires=int(time.time()*1000)+minutes*60000
        # Write intent BEFORE remote creation. An ambiguous result stays uncertain.
        h.save(self.state/(kind+'-intent.json'),{'name':self.names[kind],'scope':scope,'expiresAt':expires})
        obj=request(self.base,self.credentials[actor]['token'],'POST','/setting/apiTokens/create',
                    {'name':self.names[kind],'scope':scope,'expiresAt':expires})
        if obj.get('name')!=self.names[kind] or obj.get('scope')!=scope or obj.get('expiresAt')!=expires:
            raise RuntimeError('Unexpected created credential')
        self._save_credential(kind,obj)
        if self._owned(kind) is None:
            raise RuntimeError('Missing created credential')

    def open(self,approval):
        if socket.gethostname()!='socrat-2' or os.geteuid()!=0:
            raise ValueError('Explicit session creation requires root on socrat-2')
        self.state=h.private_directory(self.state)
        fd=os.open(self.state/'lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        self.lock=os.fdopen(fd,'w');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if any(p.name!='lock' for p in self.state.iterdir()):
            raise ValueError('Existing session state; inspect instead of replaying')
        plan=self.preview()
        if approval!=h.digest(plan):raise ValueError('Fresh approval hash required')
        self.original=token_rows(self.database);self.base=api_path(self.database)
        h.inspect(self.database,self.state/'backup')
        if self.preview()!=plan:raise ValueError('State drift before credential creation')
        h.save(self.state/'before-tokens.json',self.original)
        h.save(self.state/'uncertain.json',{'approval':approval,'names':self.names})
        p=plan['pod']
        # Native CLI stdout contains a credential. Direct it to a private file,
        # not a terminal, environment, shell argument or exception message.
        fd=os.open(self.state/'bootstrap.stdout',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
        args=KUBE+['-n','x-ui','exec',p['name'],'-c','primary','--','/app/x-ui','setting','-getApiToken','-tokenName',self.names['bootstrap'],'-tokenScope','admin']
        try:
            with os.fdopen(fd,'w') as output:
                result=subprocess.run(args,stdout=output,stderr=subprocess.DEVNULL,text=True,timeout=30)
            text=(self.state/'bootstrap.stdout').read_text()
            found=re.findall(r'^apiToken:\s*([A-Za-z0-9]{48})\s*$',text,re.M)
            if result.returncode or len(found)!=1:raise RuntimeError('Bootstrap issuance uncertain')
            rows=[r for r in token_rows(self.database) if r['name']==self.names['bootstrap']]
            if len(rows)!=1:raise RuntimeError('Bootstrap row uncertain')
            self._save_credential('bootstrap',{'id':rows[0]['id'],'name':self.names['bootstrap'],'scope':'admin','token':found[0]})
            if self._owned('bootstrap') is None:raise RuntimeError('Bootstrap ownership missing')
            self._create('cleanup','admin',30,'bootstrap')
            self._delete('bootstrap','cleanup')
            self._create('worker','node-sync',20,'cleanup')
            return self
        except Exception:
            self.cleanup()
            raise

    def call(self,method,path,body=None):
        if path.startswith('/setting/'):
            raise ValueError('Worker cannot use administrative token endpoints')
        if self._owned('worker') is None:raise RuntimeError('Worker credential unavailable')
        return request(self.base,self.credentials['worker']['token'],method,path,body)

    def cleanup(self):
        errors=[]
        actor='cleanup' if 'cleanup' in self.credentials else 'bootstrap'
        if actor in self.credentials:
            for kind in ('worker','bootstrap','cleanup'):
                if kind not in self.credentials:continue
                try:self._delete(kind,actor)
                except Exception:errors.append(kind)
        rows=token_rows(self.database)
        if any(r['name'] in self.names.values() for r in rows):errors.append('temporary-row-remains')
        # Untouched tokens must remain byte-identical, not just still enabled.
        original_ids={r['id'] for r in self.original}
        if self.original and [r for r in rows if r['id'] in original_ids]!=self.original:
            errors.append('original-token-drift')
        if errors:
            raise RuntimeError('Temporary credential cleanup uncertain; inspect private state')
        if (self.state/'uncertain.json').exists():
            h.save(self.state/'credential-cleanup.json',{'temporary_rows_removed':True,'existing_tokens_unchanged':True})
            (self.state/'uncertain.json').unlink()
        for name in ('bootstrap.stdout','bootstrap.json','cleanup.json','worker.json'):
            path=self.state/name
            if path.exists():path.unlink()
        if self.lock:self.lock.close();self.lock=None

    def __enter__(self):return self
    def __exit__(self,*args):self.cleanup()
