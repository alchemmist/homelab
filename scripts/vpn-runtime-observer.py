#!/usr/bin/env python3
"""Read-only local VPN runtime/transport observer; NEVER calls tick or failback.

Metrics contain no accounts, credentials, WS paths or command/error output.
A TLS/WS check is not authenticated VPN acceptance. OFF requires absence of ALL
local TCP+UDP data listeners, not one failed protocol or a stale metric.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import tempfile
import time

OUTPUT=Path('/var/lib/node_exporter/textfile_collector/vpn-runtime.prom')
PROFILES={
 'socrat-4': {'component':'relay','command':['python3','/usr/local/libexec/vpn-transit-failover.py','status'],
              'agent':'k3s-agent.service','native':['homelab-vpn-transit-native.service'],
              'timer':'homelab-vpn-transit-watchdog.timer',
              'marker':'/var/lib/homelab-vpn-transit/relay-failover/fallback.active',
              'tcp':{443,32053,32083,32084},'udp':{443,32085,32086}},
 'socrat-2': {'component':'backend','command':['/usr/local/sbin/homelab-vpn-failover','status'],
              'agent':'k3s.service','native':['homelab-vpn-primary.service','homelab-vpn-caddy.service'],
              'timer':'homelab-vpn-watchdog.timer','marker':'/var/lib/homelab-vpn-failover/active',
              'tcp':{32053,32083,32084,32087},'udp':{32085,32086}}
}

def command(args,timeout=30):
    return subprocess.run(args,capture_output=True,text=True,timeout=timeout,check=False)

def active(unit):
    p=command(['systemctl','is-active',unit],5)
    if p.returncode not in (0,3):raise ValueError('Unobservable unit')
    return p.returncode==0

def listening(proc,protocol):
    ports=set()
    for suffix in ('','6'):
        lines=(proc/('net/'+protocol+suffix)).read_text().splitlines()
        for line in lines[1:]:
            fields=line.split()
            if len(fields)<4:raise ValueError('Malformed socket table')
            # TCP LISTEN or established sessions; any UDP socket prevents a false OFF.
            if protocol=='udp' or fields[3] in ('0A','01'):
                ports.add(int(fields[1].rsplit(':',1)[1],16))
    return ports

def classify(profile,status,agent,native,marker):
    """Latch alone is insufficient: actual unit ownership must agree."""
    if profile['component']=='relay':
        if status.get('agent_active') is not agent or status.get('native_active') is not all(native):return -1
        if status.get('fallback_marker') is not marker:return -1
        native_mode=status.get('mode') in ('native','native-primary')
    else:
        native_mode=status.get('mode')=='fallback'
    if native_mode and marker and not agent and all(native):return 1
    if status.get('mode')=='kubernetes' and not marker and agent and not any(native):return 0
    return -1

def observe(profile,proc=Path('/proc')):
    before=Path(profile['marker']).exists()
    result=command(profile['command'])
    if result.returncode not in (0,1):raise ValueError('Status command failed')
    status=json.loads(result.stdout)
    key='data_path_healthy' if profile['component']=='relay' else 'healthy'
    if type(status.get(key)) is not bool:raise ValueError('Missing health observation')
    agent=active(profile['agent']);native=[active(u) for u in profile['native']]
    marker=Path(profile['marker']).exists()
    if marker!=before:raise ValueError('Concurrent runtime transition')
    runtime=classify(profile,status,agent,native,marker)
    tcp=listening(proc,'tcp');udp=listening(proc,'udp')
    off=not (tcp & profile['tcp'] or udp & profile['udp'])
    return {'runtime':runtime,'check_success':int(status[key]),'off':int(off),
            'observation_success':1,'observed_timestamp_seconds':time.time()}

def write_metrics(path,component,values):
    lines=[]
    for key,value in values.items():
        name='socrat_vpn_component_'+key
        lines.extend(['# TYPE '+name+' gauge',name+'{component="'+component+'"} '+str(value)])
    fd,name=tempfile.mkstemp(prefix='.vpn-runtime-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write('\n'.join(lines)+'\n');stream.flush();os.fsync(stream.fileno())
        os.chmod(name,0o644);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def audit(host,profile,expected_image=None):
    observation=observe(profile)
    native_units=[command(['systemctl','cat',unit],5).stdout for unit in profile['native']]
    agent=command(['systemctl','cat',profile['agent']],5).stdout
    if host=='socrat-4':
        boot_fence='ExecCondition=/usr/bin/test ! -e '+profile['marker'] in agent
        native_fences=all('ExecCondition=+/usr/bin/test -e '+profile['marker'] in t for t in native_units)
        validation=command(['/usr/local/libexec/xray-transit','run','-test','-config','/etc/homelab-vpn-transit/user.json']).returncode==0
        route=command(['ip','-4','route','get','10.250.0.2'],5).stdout
        extra={'relay_config_valid':validation,'mesh_route_expected':'dev wg-socrat' in route and 'src 10.250.0.40' in route,
               'relay_binary_sha256':hashlib.sha256(Path('/usr/local/libexec/xray-transit').read_bytes()).hexdigest()}
    else:
        config=json.loads(Path('/etc/homelab-vpn-failover/config.json').read_text())
        klass=runpy.run_path('/usr/local/sbin/homelab-vpn-failover')['Watchdog']
        klass(config).preflight() # read-only files + SQLite quick_check, no activation
        boot_fence='ConditionPathExists=!'+profile['marker'] in agent
        obsolete=command(['systemctl','cat','k3s-agent.service'],5).stdout
        native_fences=all('ConditionPathExists='+profile['marker'] in t and 'homelab-vpn-failover guard' in t for t in native_units)
        validation=command(['/opt/homelab-vpn-failover/caddy','validate','--config','/etc/homelab-vpn-failover/Caddyfile','--adapter','caddyfile']).returncode==0
        actual=Path('/opt/homelab-vpn-failover/primary/.homelab-image').read_text().strip()
        extra={'native_files_and_live_db_valid':True,'native_caddy_config_valid':validation,
               'native_image_matches_expected': bool(expected_image) and actual==expected_image,
               'configured_agent_is_server':config.get('agent_unit')=='k3s.service',
               'both_k3s_units_fenced':set(config.get('fenced_units',[]))=={'k3s.service','k3s-agent.service'},
               'obsolete_agent_boot_fenced':'ConditionPathExists=!'+profile['marker'] in obsolete,
               'watchdog_inhibited':Path('/var/lib/homelab-vpn-failover/inhibit').exists()}
    nameservers=[]
    for line in Path('/etc/resolv.conf').read_text().splitlines():
        if line.split()[:1]==['nameserver']:nameservers.append(line.split()[1])
    return {'host':host,'observation':observation,'watchdog_active':active(profile['timer']),
            'watchdog_enabled':command(['systemctl','is-enabled',profile['timer']],5).returncode==0,
            'agent_boot_fenced':boot_fence,'native_boot_fenced':native_fences,
            'host_resolver_uses_cluster_dns':'10.43.0.10' in nameservers,**extra}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--audit',action='store_true');parser.add_argument('--expected-image');args=parser.parse_args()
    host=socket.gethostname()
    if os.geteuid()!=0 or host not in PROFILES:raise SystemExit('Requires intended local root host')
    profile=PROFILES[host]
    try:
        if args.audit:print(json.dumps(audit(host,profile,args.expected_image),sort_keys=True))
        else:write_metrics(OUTPUT,profile['component'],observe(profile))
    except Exception:
        if not args.audit:
            write_metrics(OUTPUT,profile['component'],{'runtime':-1,'check_success':0,'off':0,'observation_success':0,'observed_timestamp_seconds':0})
        raise SystemExit('VPN observer failed; telemetry unknown, no runtime actions taken.') from None
