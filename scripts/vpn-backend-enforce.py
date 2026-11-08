#!/usr/bin/env python3
"""Explicit public-backend enforcement with own Trojan TLS443 before/after proof.
Never retires32063 or uses human credentials. Private backup and three approvals.
"""
import argparse
from contextlib import closing
import copy
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import time
import uuid


def load(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

native=load('native','vpn-panel-session.py')
target=load('target','vpn-reality-apply.py')
publication=load('publication','vpn-subscription-migrate.py')
guard=load('guard','vpn-backend-guard.py')
h=native.h


def client(stream,password,port):
    path=stream.get('wsSettings',{}).get('path')
    if stream.get('network')!='ws' or stream.get('security') not in ('none','',None) or not path or not path.startswith('/'):
        raise ValueError('Trojan backend transport drift')
    return {'log':{'loglevel':'warning'},
      'inbounds':[{'listen':'127.0.0.1','port':port,'protocol':'socks','settings':{'auth':'noauth','udp':False}}],
      'outbounds':[{'tag':'blocked','protocol':'blackhole'},
       {'tag':'probe','protocol':'trojan','settings':{'servers':[{'address':'vpn.alchemmist.xyz','port':443,'password':password}]},
        'streamSettings':{'network':'ws','security':'tls','tlsSettings':{'serverName':'vpn.alchemmist.xyz','allowInsecure':False,'alpn':['http/1.1']},
                          'wsSettings':{'path':path,'headers':{'Host':'vpn.alchemmist.xyz'}}}}],
      'routing':{'rules':[{'type':'field','domain':['full:speed.cloudflare.com'],'outboundTag':'probe'},
                          {'type':'field','network':'tcp,udp','outboundTag':'blocked'}]}}


def apply(state,session_hash,config_hash,guard_hash):
    s=native.NativeSession(state);original=target.configuration(s.database)
    if h.digest(original)!=config_hash or h.digest(guard.plan())!=guard_hash:raise ValueError('Fresh approvals required')
    trojan=[r for r in original['inbounds'] if r['port']==32087 and r['protocol']=='trojan' and r['enable']]
    if len(trojan)!=1:raise ValueError('Trojan target drift')
    row=trojan[0];email=s.state.name+'-probe';identifier=str(uuid.uuid4());sub_id=secrets.token_hex(12);password=secrets.token_urlsafe(32)
    s.open(session_hash);fixture=False;process=None;log=None
    try:
        if target.semantic(target.configuration(s.database))!=target.semantic(original):raise ValueError('Config changed opening session')
        h.save(s.state/'proxy-before-private.json',original)
        executable=s.state/'owned-xray-probe';shutil.copyfile(target.server_executable(),executable);executable.chmod(0o700)
        with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as c:
            if c.execute('SELECT COUNT(*) FROM clients WHERE email=? OR uuid=? OR sub_id=?',(email,identifier,sub_id)).fetchone()[0]:raise ValueError('Fixture collision')
        h.save(s.state/'fixture-private.json',{'email':email,'uuid':identifier,'sub_id':sub_id,'inbound_id':row['id']})
        fixture=True
        s.call('POST','/clients/add',{'client':{'id':identifier,'email':email,'subId':sub_id,'password':password,'security':'auto','flow':'',
          'enable':True,'limitIp':1,'totalGB':10*1024*1024,'expiryTime':int(time.time()*1000)+20*60000,
          'comment':'owned83-public-Trojan-guard-acceptance'},'inboundIds':[row['id']]})
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        h.save(s.state/'trojan-client-private.json',client(json.loads(row['stream_settings']),password,port))
        fd=os.open(s.state/'trojan-client-private.log',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);log=os.fdopen(fd,'w')
        process=subprocess.Popen([str(executable),'run','-c',str(s.state/'trojan-client-private.json')],stdout=log,stderr=subprocess.STDOUT)
        for attempt in range(40):
            if process.poll() is not None:raise RuntimeError('Own Trojan client exited')
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.3):break
            except OSError:
                if attempt==39:raise
                time.sleep(.25)
        time.sleep(1);before_tunnel=target.transfer(port,s.state,'trojan-before')
        with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as c:
            own_id=c.execute('SELECT id FROM clients WHERE email=?',(email,)).fetchone()[0]
        # Actor-marked GETs may update last_sub_fetch, never count as device refresh.
        before=publication.snapshot(s.database,s.state,'backend-before-uri',exclude_client_ids=(own_id,))
        json_before=publication.snapshot(s.database,s.state,'backend-before-json',True,exclude_client_ids=(own_id,))
        pre=target.configuration(s.database)
        guard.apply(s.state,guard_hash)
        after=publication.snapshot(s.database,s.state,'backend-after-uri',exclude_client_ids=(own_id,))
        json_after=publication.snapshot(s.database,s.state,'backend-after-json',True,exclude_client_ids=(own_id,))
        if before!=after or json_before!=json_after:raise ValueError('Publication changed through guard')
        after_tunnel=target.transfer(port,s.state,'trojan-after')
        if target.semantic(target.configuration(s.database))!=target.semantic(pre):raise ValueError('Proxy config changed during guard')
        guard.persist(s.state)
        h.save(s.state/'functional-acceptance.json',{'own_trojan_tls443_before':before_tunnel,'own_trojan_tls443_after':after_tunnel,
          'uri_json_public_backend_preserved':True,'original_identities':len(original['clients']),
          'synthetic_fixture_excluded_from_original_subscription_comparison':True,'external_raw_denial_not_yet_verified':True})
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if log:log.close()
        try:
            if fixture:
                with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as c:
                    rows=c.execute('SELECT uuid,sub_id FROM clients WHERE email=?',(email,)).fetchall()
                if rows:
                    if rows!=[(identifier,sub_id)]:raise ValueError('Fixture ownership mismatch')
                    s.call('POST','/clients/del/'+email,{})
                with closing(sqlite3.connect(s.database.as_uri()+'?mode=ro',uri=True)) as c:
                    if c.execute('SELECT COUNT(*) FROM clients WHERE email=?',(email,)).fetchone()[0]:raise ValueError('Fixture cleanup incomplete')
        finally:s.cleanup()
    current=target.configuration(s.database);h.save(s.state/'proxy-after-private.json',current)
    if target.semantic(current)!=target.semantic(original):raise ValueError('Final proxy preservation failed')
    result={'guard_installed':True,'persistent_unit_active_enabled':True,'reboot_tested':False,
      'own_trojan_tls443_64k_before_after':True,'all_original_uri_json_subscriptions_preserved':True,
      'fixture_and_temporary_tokens_removed':True,'proxy_config_unchanged':True,'plaintext_listener_retired':False,
      'russian_mobile_acceptance':False,'external_raw_denial_requires_separate_vantage':True}
    h.save(s.state/'receipt.json',result);return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,required=True);p.add_argument('--apply',action='store_true')
    p.add_argument('--approve-session-hash');p.add_argument('--approve-configuration-hash');p.add_argument('--approve-guard-hash');a=p.parse_args()
    if a.apply:
        if not all([a.approve_session_hash,a.approve_configuration_hash,a.approve_guard_hash]):p.error('Three approvals required')
        print(h.canonical(apply(a.state,a.approve_session_hash,a.approve_configuration_hash,a.approve_guard_hash)))
    else:
        s=native.NativeSession(a.state);plan=s.preview()
        print(h.canonical({'session_sha256':h.digest(plan),'configuration_sha256':plan['configuration_sha256'],'guard_sha256':h.digest(guard.plan()),'writes':0}))


if __name__=='__main__':
    try:main()
    except Exception:
        import sys,traceback
        try:
            if '--state' in sys.argv:
                state=Path(sys.argv[sys.argv.index('--state')+1])
                if state.exists():h.save(h.private_directory(state)/'failure-private.json',{'traceback':traceback.format_exc()})
        except (OSError,ValueError):pass
        raise SystemExit('Backend enforcement stopped; inspect private receipts, never replay writes.') from None
