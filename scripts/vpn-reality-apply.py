#!/usr/bin/env python3
"""One explicit native API target correction with a synthetic VLESS acceptance client.
No listener retirement/firewall update/SQL mutation or human credential use.
Preview is read-only. Apply requires both fresh hashes and private node state.
"""
import argparse
import base64
import copy
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import ssl
import subprocess
import time
import uuid


def load(name, filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

session_module=load('panel_session','vpn-panel-session.py')
planner=load('reality_plan','vpn-reality-plan.py')
h=session_module.h


def configuration(database):
    with closing(sqlite3.connect(h.check_path(database).as_uri()+'?mode=ro',uri=True)) as source:
        with closing(sqlite3.connect(':memory:')) as snapshot:
            source.backup(snapshot)
            if snapshot.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('Integrity check failed')
            return h.projection(snapshot)


def semantic(config):
    def normalize(value):
        if isinstance(value,str) and value.lstrip().startswith(('{','[')):
            try:return normalize(json.loads(value))
            except ValueError:pass
        if isinstance(value,dict):return {k:normalize(v) for k,v in value.items()}
        if isinstance(value,list):return [normalize(v) for v in value]
        return value
    return {table:sorted([normalize(row) for row in rows],key=h.canonical) for table,rows in config.items()}


def corrected(config):
    after=copy.deepcopy(config)
    rows=[r for r in after['inbounds'] if r['port']==32053]
    if len(rows)!=1:raise ValueError('Unexpected target count')
    stream=json.loads(rows[0]['stream_settings']);reality=stream['realitySettings']
    if reality.get('serverNames')!=['www.yahoo.com'] or reality.get('target')!='www.intel.com:443':
        raise ValueError('Target/SNI drift')
    reality['target']='www.yahoo.com:443'
    rows[0]['stream_settings']=h.canonical(stream)
    return after


def json_field(value):
    # 3x-ui3.11 emits native objects; its decoder also accepts legacy JSON strings.
    if value is None or value == '':return None
    return json.loads(value) if isinstance(value,str) else copy.deepcopy(value)


def api_payload(inbound):
    after=copy.deepcopy(inbound)
    if (after.get('port')!=32053 or after.get('protocol')!='vless' or not after.get('enable')):
        raise ValueError('Unexpected native inbound')
    stream=json_field(after['streamSettings'])
    if stream.get('security')!='reality' or stream.get('network')!='xhttp':raise ValueError('Transport drift')
    if stream['realitySettings'].get('serverNames')!=['www.yahoo.com'] or stream['realitySettings'].get('target')!='www.intel.com:443':
        raise ValueError('API target drift')
    stream['realitySettings']['target']='www.yahoo.com:443'
    after['streamSettings']=h.canonical(stream) if isinstance(inbound['streamSettings'],str) else stream
    after.pop('clientStats',None)  # Not an editable client-statistics operation.
    return after


def vless_client(stream, client_id, port):
    reality=stream['realitySettings']
    public=(reality.get('settings') or {}).get('publicKey')
    if not public or not reality.get('shortIds'):raise ValueError('Missing native client parameters')
    xhttp=stream.get('xhttpSettings') or stream.get('splithttpSettings')
    if not xhttp or 'path' not in xhttp:raise ValueError('Missing XHTTP path')
    return {'log':{'loglevel':'warning'},
      'inbounds':[{'listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth','udp':False}}],
      'outbounds':[{'tag':'blocked','protocol':'blackhole'},
        {'tag':'probe','protocol':'vless','settings':{'vnext':[{'address':'127.0.0.1','port':32053,
          'users':[{'id':client_id,'encryption':'none','flow':''}]}]},
         'streamSettings':{'network':'xhttp','security':'reality',
          'realitySettings':{'serverName':'www.yahoo.com','fingerprint':'chrome','publicKey':public,'shortId':reality['shortIds'][0]},
          'xhttpSettings':{'path':xhttp['path'],'mode':xhttp.get('mode','auto')}}}],
      'routing':{'rules':[{'type':'field','domain':['full:speed.cloudflare.com'],'outboundTag':'probe'},
                           {'type':'field','network':'tcp,udp','outboundTag':'blocked'}]}}


def server_executable():
    found=[]
    for path in Path('/proc').glob('[0-9]*/exe'):
        try:
            if Path(os.readlink(path)).name!='xray-linux-amd64':continue
            args=(path.parent/'cmdline').read_bytes().split(b'\0')
            if any(x.endswith(b'bin/config.json') for x in args):found.append(str(path))
        except (FileNotFoundError,PermissionError,ProcessLookupError):pass
    if len(found)!=1:raise ValueError('Expected one known running server executable')
    return found[0]


def transfer(port,state,phase):
    output=state/(phase+'-body.bin')
    env=dict(os.environ,NO_PROXY='',no_proxy='')
    args=['curl','--silent','--show-error','--max-time','25','--max-filesize','131072',
          '--proxy','socks5h://127.0.0.1:'+str(port),'--output',str(output),
          '--write-out','%{http_code} %{size_download}','https://speed.cloudflare.com/__down?bytes=65536']
    result=subprocess.run(args,capture_output=True,text=True,env=env,timeout=30)
    h.save(state/(phase+'-curl-private.json'),{'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
    if result.returncode or result.stdout.strip()!='200 65536' or not output.is_file() or output.stat().st_size!=65536:
        raise RuntimeError('Authenticated transfer failed; inspect private evidence')
    proof={'http_status':200,'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
           'native_authenticated_tunnel':True,'vantage':'same-node-synthetic-not-Russian-ISP'}
    output.unlink();h.save(state/(phase+'-proof.json'),proof)
    return proof


def apply(state,policy,session_hash,target_hash):
    if policy['realityCorrection'].get('apiApplyEnabled') is not True:
        raise ValueError('API apply is disabled by source policy')
    s=session_module.NativeSession(state)
    original=configuration(s.database)
    plan=planner.build(original,policy)
    if plan['plan_sha256']!=target_hash or len(plan['operations'])!=1:raise ValueError('Target approval drift')
    # Candidate must be validated before credentials or client state are written.
    context=ssl.create_default_context();context.set_alpn_protocols(['h2'])
    with socket.create_connection(('www.yahoo.com',443),timeout=10) as raw:
        with context.wrap_socket(raw,server_hostname='www.yahoo.com') as tls:
            if tls.version()!='TLSv1.3' or tls.selected_alpn_protocol()!='h2':raise ValueError('Candidate failed TLS/H2')
    executable=server_executable()
    email=s.state.name+'-probe';fixture_id=str(uuid.uuid4());sub_id=secrets.token_hex(12)
    fixture=False;proc=None;log=None;applied=False
    s.open(session_hash)
    try:
        if semantic(configuration(s.database))!=semantic(original):raise ValueError('Proxy changed while opening session')
        h.save(s.state/'target-plan.json',plan)
        h.save(s.state/'proxy-before-private.json',original)
        with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as con:
            if con.execute('SELECT COUNT(*) FROM clients WHERE email=? OR uuid=? OR sub_id=?',(email,fixture_id,sub_id)).fetchone()[0]:
                raise ValueError('Fixture collision')
        target=next(r for r in original['inbounds'] if r['port']==32053)
        marker={'email':email,'uuid':fixture_id,'sub_id':sub_id,'inbound_id':target['id']}
        h.save(s.state/'fixture-private.json',marker)
        # Mark intent before an API response can be lost; cleanup ownership-checks DB.
        fixture=True
        s.call('POST','/clients/add',{'client':{'id':fixture_id,'email':email,'subId':sub_id,
          'password':secrets.token_urlsafe(24),'security':'auto','flow':'','enable':True,
          'limitIp':1,'totalGB':10*1024*1024,'expiryTime':int(time.time()*1000)+20*60000,
          'comment':'owned-vpn83-temporary-acceptance'},'inboundIds':[target['id']]})
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        cfg=vless_client(json.loads(target['stream_settings']),fixture_id,port)
        h.save(s.state/'probe-client-private.json',cfg)
        log=(s.state/'probe-client-private.log').open('x');os.chmod(log.name,0o600)
        proc=subprocess.Popen([executable,'run','-c',str(s.state/'probe-client-private.json')],stdout=log,stderr=subprocess.STDOUT)
        for _ in range(40):
            if proc.poll() is not None:raise RuntimeError('Private acceptance client exited')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.3):break
            except OSError:time.sleep(.25)
        time.sleep(1)
        before=transfer(port,s.state,'before')
        # Fresh native DTO plus complete config preimage after our own fixture.
        before_api=configuration(s.database)
        rows=s.call('GET','/inbounds/list');matches=[r for r in rows if r['id']==target['id']]
        if len(matches)!=1:raise ValueError('Native API target missing')
        payload=api_payload(matches[0]);prewrite=configuration(s.database)
        if semantic(before_api)!=semantic(prewrite):raise ValueError('Concurrent config change during API read')
        db_target=next(r for r in prewrite['inbounds'] if r['id']==target['id'])
        for api_key,db_key in (('settings','settings'),('streamSettings','stream_settings'),('sniffing','sniffing')):
            if json_field(matches[0][api_key])!=json_field(db_target[db_key]):raise ValueError('API/DB projection mismatch')
        h.save(s.state/'proxy-prewrite-private.json',prewrite)
        h.save(s.state/'target-write-uncertain.json',{'target_plan_sha256':target_hash})
        # Only one native write. An ambiguous response is not automatically retried.
        s.call('POST','/inbounds/update/'+str(target['id']),payload);applied=True
        expected=corrected(prewrite)
        if semantic(configuration(s.database))!=semantic(expected):raise RuntimeError('Unexpected API normalization/drift; inspect private data')
        # Wait only on real local fallback readiness, not repeated external transfers.
        for attempt in range(40):
            try:
                ctx=ssl.create_default_context();ctx.set_alpn_protocols(['h2'])
                with socket.create_connection(('127.0.0.1',32053),timeout=2) as raw:
                    with ctx.wrap_socket(raw,server_hostname='www.yahoo.com') as tls:
                        if tls.version()!='TLSv1.3' or tls.selected_alpn_protocol()!='h2':raise ValueError('Fallback TLS/H2 failed')
                break
            except (OSError,ssl.SSLError):
                if attempt==39:raise RuntimeError('Fallback never converged')
                time.sleep(.5)
        after=transfer(port,s.state,'after')
        h.save(s.state/'target-acceptance.json',{'target_corrected':True,'fallback_verified':True,
            'before':before,'after':after,'only_expected_config_change':True})
        (s.state/'target-write-uncertain.json').unlink()
    finally:
        if proc is not None:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
        if log:log.close()
        try:
            if fixture:
                with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as con:
                    rows=con.execute('SELECT uuid,sub_id FROM clients WHERE email=?',(email,)).fetchall()
                if rows:
                    if rows!=[(fixture_id,sub_id)]:raise ValueError('Fixture ownership mismatch')
                    s.call('POST','/clients/del/'+email,{})
                with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as con:
                    if con.execute('SELECT COUNT(*) FROM clients WHERE email=?',(email,)).fetchone()[0]:raise ValueError('Fixture cleanup incomplete')
        finally:s.cleanup()
    final=configuration(s.database)
    expected=corrected(original) if applied else original
    h.save(s.state/'proxy-after-private.json',final)
    if semantic(final)!=semantic(expected):raise RuntimeError('Final proxy preservation check failed')
    receipt={'target_corrected':applied,'fixture_removed':True,'temporary_credentials_removed':True,
             'existing_credentials_preserved':True,'only_target_changed':True,'human_credentials_used':False,
             'russian_isp_acceptance':False,'plaintext_retired':False,'raw_backends_enforced':False}
    h.save(s.state/'receipt.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--policy',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--approve-session-hash');parser.add_argument('--approve-target-plan-hash')
    args=parser.parse_args();policy=json.loads(args.policy.read_text())
    if args.apply:
        if not args.approve_session_hash or not args.approve_target_plan_hash:parser.error('Both fresh hashes required')
        print(h.canonical(apply(args.state,policy,args.approve_session_hash,args.approve_target_plan_hash)))
    else:
        s=session_module.NativeSession(args.state);plan=s.preview();target=planner.build(configuration(s.database),policy)
        print(h.canonical({'session_sha256':h.digest(plan),'target_plan_sha256':target['plan_sha256'],
                           'target_operations':target['operations'],'writes':0}))


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('Target operation stopped; inspect private receipts before retrying. No automatic replay.') from None
