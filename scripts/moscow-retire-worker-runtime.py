#!/usr/bin/env python3
"""One-time owned-runtime retirement, not k3s-killall/uninstall or a table flush.
Default is preview. Requires an accepted native-primary and the reviewed pod plan.
Never removes keys, runtime state, interfaces, routes, or cluster objects.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import socket
import time


def allowed(plan):
    pods=plan['items']
    assert len(pods)==2
    result={};ids=set()
    for p in pods:
        m=p['metadata'];ns=m['namespace'];name=m['name']
        assert p['spec']['nodeName']=='socrat-4'
        assert (ns=='vpn-transit' and name.startswith('vpn-transit-')) or (ns=='cattle-monitoring-system' and name.startswith('kube-prometheus-stack-prometheus-node-exporter-'))
        assert not any('persistentVolumeClaim' in v for v in p['spec'].get('volumes',[]))
        result[m['uid'].replace('-','_')]=ns
        for c in p.get('status',{}).get('containerStatuses',[]):
            cid=c.get('containerID','')
            if cid:
                assert cid.startswith('containerd://')
                ids.add(cid.split('://',1)[1])
    assert set(result.values())=={'vpn-transit','cattle-monitoring-system'}
    return result,ids


def identity(pid):
    p=Path('/proc')/str(pid)
    try:
        st=(p/'stat').read_text();fields=st[st.rfind(')')+2:].split()
        if fields[0]=='Z':return None
        return {'pid':int(pid),'start':fields[19], 'name':(p/'comm').read_text().strip(),
                'cgroup':(p/'cgroup').read_text(), 'argv':(p/'cmdline').read_bytes().split(b'\0')[:-1]}
    except (FileNotFoundError,ProcessLookupError):return None


def inventory(uids,ids):
    owned=[];shims=[]
    for p in Path('/proc').glob('[0-9]*'):
        i=identity(p.name)
        if i is None:continue
        cg=i['cgroup'];name=i['name']
        if 'kubepods' in cg:
            assert any('pod'+uid+'.slice' in cg for uid in uids), 'Unknown pod process: STOP'
            assert name in ('pause','node_exporter','xray'), 'Unknown task in owned pod: STOP'
            cid=re.search(r'cri-containerd-([a-f0-9]{64})\.scope',cg)
            assert cid is not None
            ids.add(cid.group(1));owned.append(i)
        elif name=='containerd-shim' and '/system.slice/k3s-agent.service' in cg:
            shims.append(i)
        elif name in ('k3s-agent','containerd'):
            raise RuntimeError('Agent or containerd still running: inspect before retirement')
    for i in shims:
        args=i['argv'];assert b'-namespace' in args and args[args.index(b'-namespace')+1]==b'k8s.io'
        assert b'-id' in args and args[args.index(b'-id')+1].decode() in ids, 'Unknown shim owner: STOP'
    return owned,shims


def terminate(i):
    now=identity(i['pid'])
    if now is None:return
    assert now==i, 'Process identity drift: STOP'
    os.kill(i['pid'],signal.SIGTERM)
    for _ in range(80):
        if identity(i['pid']) is None:return
        time.sleep(.1)
    assert identity(i['pid'])==i
    os.kill(i['pid'],signal.SIGKILL)
    for _ in range(30):
        if identity(i['pid']) is None:return
        time.sleep(.1)
    raise RuntimeError('Owned process did not exit')


def main():
    a=argparse.ArgumentParser();a.add_argument('pod_plan',type=Path);a.add_argument('--apply',action='store_true');args=a.parse_args()
    assert socket.gethostname()=='socrat-4' and os.geteuid()==0
    s=importlib.util.spec_from_file_location('relay','/usr/local/libexec/vpn-transit-failover.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    # Use the same lock as the watchdog and promotion/failback operations.
    with (m.ROOT/'lock').open('a') as lock:
        m.fcntl.flock(lock,m.fcntl.LOCK_EX)
        c=m.Controller();status=c.status()
        assert status['mode']=='native-primary' and status['native_active'] and status['fallback_marker'] and status['data_path_healthy'] and not status['agent_active']
        uids,ids=allowed(json.loads(args.pod_plan.read_text()));owned,shims=inventory(uids,ids)
        if args.apply:
            for i in owned+shims:terminate(i)
            assert inventory(uids,ids)==([],[])
            assert c.healthy() and m.active(m.NATIVE) and not m.active(m.AGENT)
            c.receipt('worker-runtime-retired',owned_tasks=len(owned),owned_shims=len(shims))
        print(json.dumps({'applied':args.apply,'owned_tasks':len(owned),'owned_shims':len(shims),'native_healthy':True}))

if __name__=='__main__':main()
