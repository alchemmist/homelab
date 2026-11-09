#!/usr/bin/env python3
"""Bounded two-phase native session for an owned cross-node home probe.
Prepare leaves TTL-limited credentials PRIVATE on VPS; controller must always clean.
No human credentials/SQL writes; no listener changes. Default read-only preview.
"""
import argparse
from contextlib import closing
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import time
import uuid
import hashlib
import copy
import subprocess


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

native=load('native','vpn-panel-session.py');target=load('target','vpn-reality-apply.py')
backend=load('backend','vpn-backend-enforce.py');h=native.h


def restore(state):
    if os.geteuid()!=0 or socket.gethostname()!='socrat-2':raise ValueError('Requires VPS root')
    s=native.NativeSession(state);h.private_directory(s.state)
    fd=os.open(s.state/'lock',os.O_RDWR|os.O_NOFOLLOW);s.lock=os.fdopen(fd,'w');fcntl.flock(s.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    s.original=json.loads(h.check_path(s.state/'before-tokens.json').read_text());s.base=native.api_path(s.database)
    for kind in ('bootstrap','cleanup','worker'):
        p=h.check_path(s.state/(kind+'.json'))
        if p.exists():s.credentials[kind]=json.loads(p.read_text());s._owned(kind)
    return s


def finish(s):
    marker=s.state/'home-fixture-private.json'
    try:
        if marker.exists():
            owned=json.loads(marker.read_text())
            with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as c:
                rows=c.execute('SELECT uuid,sub_id,password FROM clients WHERE email=?',(owned['email'],)).fetchall()
            if rows:
                if len(rows)!=1 or rows[0][:2]!=(owned['uuid'],owned['sub_id']) or hashlib.sha256(rows[0][2].encode()).hexdigest()!=owned['password_sha256']:
                    raise ValueError('Home fixture ownership mismatch')
                s.call('POST','/clients/del/'+owned['email'],{})
            with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as c:
                if c.execute('SELECT COUNT(*) FROM clients WHERE email=?',(owned['email'],)).fetchone()[0]:raise ValueError('Fixture still exists')
    finally:s.cleanup()
    original=json.loads((s.state/'home-proxy-before-private.json').read_text())
    if target.semantic(target.configuration(s.database))!=target.semantic(original):raise ValueError('Proxy preservation failed')
    for name in ['home-configs-private.json','xray-probe']:(s.state/name).unlink(missing_ok=True)
    proof={'fixture_removed':True,'temporary_tokens_removed':True,'original_tokens_preserved':True,'proxy_config_preserved':True}
    h.save(s.state/'home-session-cleanup-receipt.json',proof);return proof


def prepare(state,approval,endpoint="91.189.82.238",include_udp=False,include_all_vless=False):
    import ipaddress
    if not ipaddress.ip_address(endpoint).is_global:raise ValueError("Public probe endpoint required")
    s=native.NativeSession(state);s.open(approval)
    try:
        original=target.configuration(s.database);h.save(s.state/'home-proxy-before-private.json',original)
        rows={r['port']:r for r in original['inbounds']}
        if not all(rows[p]['enable'] for p in (32053,32087)):raise ValueError('Probe inbounds unavailable')
        identifier=str(uuid.uuid4());password=secrets.token_urlsafe(32);sub_id=secrets.token_hex(12);email=s.state.name+'-probe'
        with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as c:
            if c.execute('SELECT COUNT(*) FROM clients WHERE email=? OR uuid=? OR sub_id=?',(email,identifier,sub_id)).fetchone()[0]:raise ValueError('Fixture collision')
        h.save(s.state/'home-fixture-private.json',{'email':email,'uuid':identifier,'sub_id':sub_id,'password_sha256':hashlib.sha256(password.encode()).hexdigest()})
        client={'id':identifier,'email':email,'subId':sub_id,'password':password,'security':'auto','flow':'',
          'enable':True,'limitIp':1,'totalGB':10*1024*1024,'expiryTime':int(time.time()*1000)+20*60000,'comment':'owned83-home-fixed-path-probe'}
        inbound_ids=[rows[32053]['id'],rows[32087]['id']]; udp_settings={}
        if include_all_vless:
            for port in (32083,32084):
                if not rows[port]['enable']:raise ValueError('Additional VLESS transport unavailable')
                inbound_ids.append(rows[port]['id'])
        if include_udp:
            private=subprocess.check_output(['wg','genkey'],text=True).strip()
            public=subprocess.check_output(['wg','pubkey'],input=private+'\n',text=True).strip()
            client.update(privateKey=private,publicKey=public,allowedIPsByInbound={})
            for port,label in [(32085,'wireguard')]:
                if not rows[port]['enable']:raise ValueError('UDP probe inbound unavailable')
                server=json.loads(rows[port]['settings']);candidate='10.254.83.231/32'
                if candidate in h.canonical(original):raise ValueError('Fixture address collision; stop')
                client['allowedIPsByInbound'][str(rows[port]['id'])]=[candidate];inbound_ids.append(rows[port]['id'])
                server_public=subprocess.check_output(['wg','pubkey'],input=server['secretKey']+'\n',text=True).strip()
                settings=dict(secretKey=private,address=[candidate],peers=[{'publicKey':server_public,'endpoint':endpoint+':'+str(port),'allowedIPs':['0.0.0.0/0']}],noKernelTun=True,mtu=1420)
                udp_settings[label]=settings
        s.call('POST','/clients/add',{'client':client,'inboundIds':inbound_ids})
        reality=target.vless_client(json.loads(rows[32053]['stream_settings']),identifier,1080)
        reality['outbounds'][1]['settings']['vnext'][0]['address']=endpoint
        trojan=backend.client(json.loads(rows[32087]['stream_settings']),password,1080)
        trojan['outbounds'][1]['settings']['servers'][0]['address']=endpoint
        configs={'reality':reality,'trojan':trojan}
        if include_all_vless:
            for port in (32083,32084):
                stream=json.loads(rows[port]['stream_settings']);config=copy.deepcopy(reality);out=config['outbounds'][1]
                out['settings']['vnext'][0]['port']=port
                r=stream['realitySettings'];out['streamSettings']={'network':stream['network'],'security':'reality','realitySettings':{'serverName':r['serverNames'][0],'fingerprint':'chrome','publicKey':r['settings']['publicKey'],'shortId':r['shortIds'][0]}}
                field='grpcSettings' if stream['network']=='grpc' else 'xhttpSettings'
                out['streamSettings'][field]=copy.deepcopy(stream.get(field) or stream.get('splithttpSettings') or {})
                configs['vless-'+str(port)]=config
        for label,settings in udp_settings.items():
            config=copy.deepcopy(reality);config['outbounds'][1]={'tag':reality['outbounds'][1]['tag'],'protocol':label,'settings':settings};configs[label]=config
        h.save(s.state/'home-configs-private.json',configs)
        executable=s.state/'xray-probe';shutil.copyfile(target.server_executable(),executable);executable.chmod(0o700)
        proof={'prepared':True,'expires_within_minutes':20,'binary_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
               'controller_must_cleanup':True,'no_human_identity_used':True}
        h.save(s.state/'home-prepare-receipt.json',proof);return proof
    except Exception:
        finish(s);raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,required=True)
    group=p.add_mutually_exclusive_group();group.add_argument('--prepare',action='store_true');group.add_argument('--cleanup',action='store_true')
    p.add_argument('--approve-session-hash');p.add_argument('--endpoint',default='91.189.82.238');p.add_argument('--include-udp',action='store_true',help='Add an owned userspace WireGuard probe binding');p.add_argument('--include-all-vless',action='store_true');a=p.parse_args()
    try:
        if a.prepare:
            if not a.approve_session_hash:p.error('Fresh approval required')
            print(h.canonical(prepare(a.state,a.approve_session_hash,endpoint=a.endpoint,include_udp=a.include_udp,include_all_vless=a.include_all_vless)))
        elif a.cleanup:print(h.canonical(finish(restore(a.state))))
        else:
            s=native.NativeSession(a.state);print(h.canonical({'session_sha256':h.digest(s.preview()),'writes':0}))
    except Exception:raise SystemExit('Home native session stopped; inspect private receipts, no blind replay.') from None
