#!/usr/bin/env python3
"""Owned, per-process home fixed-path VPN acceptance. No OS proxy/routes/DNS writes.
Takes private prepared configs and a checksum-pinned copy of the running Xray core.
Only temporary loopback SOCKS proxies and a single64KiB request per protocol.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


def exclusive(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())


def network(endpoint="91.189.82.238"):
    r=subprocess.run(['ip','-j','route','get',endpoint],capture_output=True,text=True,timeout=10)
    if r.returncode:raise ValueError('Route read failed')
    rows=json.loads(r.stdout)
    if len(rows)!=1 or rows[0].get('dev')!='eno1' or rows[0].get('gateway')!='192.168.0.1':raise ValueError('Not approved home WAN route')
    main=subprocess.run(['ip','-j','route','show','table','main'],capture_output=True,timeout=10)
    if main.returncode:raise ValueError('Route snapshot failed')
    return {'route_device':'eno1','gateway':'192.168.0.1','main_route_sha256':hashlib.sha256(main.stdout).hexdigest(),
            'resolv_conf_sha256':hashlib.sha256(Path('/etc/resolv.conf').read_bytes()).hexdigest()}


def run(state,approved_binary,endpoint="91.189.82.238"):
    import ipaddress
    if not ipaddress.ip_address(endpoint).is_global:raise ValueError("Public probe endpoint required")
    if socket.gethostname()!='socrat-0' or os.geteuid()!=0:raise ValueError('Requires socrat-0 root')
    if state.is_symlink() or any(p.is_symlink() for p in state.parents) or state.stat().st_mode&0o077 or state.stat().st_uid!=0:raise ValueError('Private state required')
    binary=state/'xray-probe';configs=state/'home-configs-private.json'
    if binary.is_symlink() or configs.is_symlink():raise ValueError('Symlink refused')
    if hashlib.sha256(binary.read_bytes()).hexdigest()!=approved_binary:raise ValueError('Binary checksum mismatch')
    prepared=json.loads(configs.read_text());before=network(endpoint);proofs={}
    if prepared['reality']['outbounds'][1]['settings']['vnext'][0]['address']!=endpoint or prepared['trojan']['outbounds'][1]['settings']['servers'][0]['address']!=endpoint:
        raise ValueError('Both protocols must use literal approved VPS IP')
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('https://api.ipify.org',timeout=10) as r:
            public=r.read(64).decode().strip()
        exclusive(state/'source-address-private.json',{'actual_public_ip':public})
        expected_home_source=public=='109.173.40.247'
        for label in prepared:
            config=prepared[label]
            for rule in config.get('routing',{}).get('rules',[]):
                if 'full:speed.cloudflare.com' in rule.get('domain',[]):rule['domain'].append('full:api4.ipify.org')
            with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
            config['inbounds'][0]['port']=port
            path=state/(label+'-config-private.json');exclusive(path,config)
            logpath=state/(label+'-log-private.txt');fd=os.open(logpath,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as log:
                process=subprocess.Popen([str(binary),'run','-c',str(path)],stdout=log,stderr=subprocess.STDOUT)
                try:
                    for attempt in range(40):
                        if process.poll() is not None:raise RuntimeError('Own home client exited')
                        try:
                            with socket.create_connection(('127.0.0.1',port),timeout=.3):break
                        except OSError:
                            if attempt==39:raise
                            time.sleep(.25)
                    egress=subprocess.run(['curl','--silent','--show-error','--max-time','20','--max-filesize','64','--proxy','socks5h://127.0.0.1:'+str(port),'https://api4.ipify.org'],capture_output=True,text=True,timeout=25,env=dict(os.environ,NO_PROXY='',no_proxy=''))
                    if egress.returncode or egress.stdout.strip()!='109.120.141.60':raise RuntimeError('Expected Netherlands IPv4 egress not proven')
                    body=state/(label+'-body.bin')
                    args=['curl','--silent','--show-error','--max-time','30','--max-filesize','131072',
                      '--proxy','socks5h://127.0.0.1:'+str(port),'--output',str(body),'--write-out','%{http_code} %{size_download}',
                      'https://speed.cloudflare.com/__down?bytes=65536']
                    r=subprocess.run(args,capture_output=True,text=True,timeout=35,env=dict(os.environ,NO_PROXY='',no_proxy=''))
                    exclusive(state/(label+'-curl-private.json'),{'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
                    if r.returncode or r.stdout.strip()!='200 65536' or body.stat().st_size!=65536:raise RuntimeError('Home tunnel transfer failed')
                    proofs[label]={'http_status':200,'bytes':65536,'sha256':hashlib.sha256(body.read_bytes()).hexdigest(),'egress_ipv4':'109.120.141.60'}
                    body.unlink()
                finally:
                    process.terminate()
                    try:process.wait(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                    path.unlink(missing_ok=True)
        after=network(endpoint)
        if before!=after:raise ValueError('Network state changed during home probe')
        result={'vantage':'home-fixed-WAN-not-mobile','expected_home_public_source':expected_home_source,
          'uses_overlay_to_vps':False,'literal_endpoint':endpoint,'network_state_preserved':True,'own_ephemeral_identity_only':True,
          'protocols':proofs,'reality':proofs['reality'],'trojan':proofs['trojan'],'mobile_acceptance':False}
        exclusive(state/'receipt.json',result);return result
    finally:
        configs.unlink(missing_ok=True);binary.unlink(missing_ok=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state',type=Path,required=True);p.add_argument('--approved-binary-sha256',required=True);p.add_argument('--endpoint',default='91.189.82.238');a=p.parse_args()
    try:print(json.dumps(run(a.state,a.approved_binary_sha256,endpoint=a.endpoint)))
    except Exception:raise SystemExit('Home probe stopped; inspect private evidence; no global network changes requested.') from None
