#!/usr/bin/env python3
"""Narrow owned nft input guard: public eth0 TCP12096/32087 only.
No forwarding/NAT/443/overlay changes. Existing connections survive; new public
connections are reset. ensure is idempotent ONLY for the exact owned rules.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess

spec=importlib.util.spec_from_file_location('inventory',Path(__file__).with_name('vpn-hardening-inventory.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
TABLE='homelab_xui_backend_guard'
OWNER='homelab issue83 public backend guard v1'


def run(args,**kwargs):
    r=subprocess.run(args,capture_output=True,text=True,timeout=20,**kwargs)
    if r.returncode:raise RuntimeError('Backend guard operation failed; inspect private receipts')
    return r.stdout


def rules():
    return '''table inet homelab_xui_backend_guard {
 comment "homelab issue83 public backend guard v1"
 chain input {
  type filter hook input priority -6; policy accept;
  iifname "eth0" tcp dport { 12096, 32087 } ct state established counter return comment "owned83:established"
  iifname "eth0" tcp dport { 12096, 32087 } counter reject with tcp reset comment "owned83:public-deny"
 }
}
'''


def stable(value):
    if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in ('packets','bytes','handle','metainfo')}
    if isinstance(value,list):return [stable(x) for x in value if not (isinstance(x,dict) and 'metainfo' in x)]
    return value


def expected():
    prefix=[{'match':{'op':'==','left':{'meta':{'key':'iifname'}},'right':'eth0'}},
            {'match':{'op':'==','left':{'payload':{'protocol':'tcp','field':'dport'}},'right':{'set':[12096,32087]}}}]
    return [{'table':{'family':'inet','name':TABLE}},
      {'chain':{'family':'inet','table':TABLE,'name':'input','type':'filter','hook':'input','prio':-6,'policy':'accept'}},
      {'rule':{'family':'inet','table':TABLE,'chain':'input','comment':'owned83:established',
       'expr':prefix+[{'match':{'op':'in','left':{'ct':{'key':'state'}},'right':'established'}},{'counter':{}},{'return':None}]}},
      {'rule':{'family':'inet','table':TABLE,'chain':'input','comment':'owned83:public-deny',
       'expr':prefix+[{'counter':{}},{'reject':{'type':'tcp reset'}}]}}]


def validate(objects):
    data=stable(objects)
    for obj in data:
        if 'table' in obj:
            comment=obj['table'].pop('comment',None)
            if comment not in (None,OWNER):raise ValueError('Foreign table owner')
    if data!=expected():raise ValueError('Not the exact owned backend guard')


def read_table():
    data=json.loads(run(['nft','-j','list','ruleset']))['nftables']
    own=[x for x in data if any(isinstance(v,dict) and v.get('family')=='inet' and
         (v.get('table')==TABLE or k=='table' and v.get('name')==TABLE) for k,v in x.items())]
    if own:validate(own)
    return own or None


def require_host():
    if os.geteuid()!=0 or socket.gethostname()!='socrat-2':raise ValueError('Requires root on socrat-2')
    links=json.loads(run(['ip','-j','link','show','eth0']))
    if len(links)!=1 or links[0]['ifname']!='eth0':raise ValueError('Public interface missing')


def plan():
    require_host();current=read_table()
    return {'table':TABLE,'interface':'eth0','ports':[12096,32087],
       'rules_sha256':h.digest(rules()),'before_sha256':h.digest(stable(current)),
       'preserve_established':True,'forwarding_or_nat_changes':False,'packet_logging':False}


def apply(state,approval):
    require_host();wanted=plan()
    if h.digest(wanted)!=approval or read_table() is not None:raise ValueError('Fresh empty-table approval required')
    run(['nft','--check','-f','-'],input=rules())
    h.save(state/'backend-guard-before.json',None)
    h.save(state/'backend-guard-uncertain.json',{'approval':approval,'plan':wanted})
    if plan()!=wanted:raise ValueError('Preimage drift')
    run(['nft','-f','-'],input=rules())
    after=read_table()
    if after is None:raise RuntimeError('Guard not present')
    h.save(state/'backend-guard-after.json',after)
    h.save(state/'backend-guard-receipt.json',wanted)
    (state/'backend-guard-uncertain.json').unlink()
    return wanted


def finalize_readback(state,approval):
    require_host()
    marker=json.loads((state/'backend-guard-uncertain.json').read_text())
    if marker['approval']!=approval or h.digest(marker['plan'])!=approval:
        raise ValueError('Interrupted approval mismatch')
    if marker['plan']['rules_sha256']!=h.digest(rules()) or marker['plan']['before_sha256']!=h.digest(None):
        raise ValueError('Interrupted rules/preimage mismatch')
    if json.loads((state/'backend-guard-before.json').read_text()) is not None:raise ValueError('Nonempty original table')
    current=read_table()
    if current is None:raise ValueError('No installed guard; do not replay')
    h.save(state/'backend-guard-after.json',current)
    h.save(state/'backend-guard-receipt.json',dict(marker['plan'],readback_finalized=True,repeated_rule_writes=0))
    (state/'backend-guard-uncertain.json').unlink()
    return {'readback_finalized':True,'repeated_rule_writes':0}


def ensure():
    require_host()
    if read_table() is None:
        run(['nft','--check','-f','-'],input=rules())
        run(['nft','-f','-'],input=rules())
        if read_table() is None:raise RuntimeError('Boot guard missing')
    return {'owned_guard_present':True}


UNIT='''[Unit]
Description=Homelab private VPN backend public-input guard
Wants=network-online.target
After=network-online.target nftables.service
Before=k3s.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/python3 /usr/local/libexec/homelab-vpn-backend-guard/vpn-backend-guard.py --ensure

[Install]
WantedBy=multi-user.target
'''


def persist(state):
    require_host()
    if read_table() is None:raise ValueError('Verified live guard required before persistence')
    dest=h.private_directory('/usr/local/libexec/homelab-vpn-backend-guard')
    files={dest/'vpn-backend-guard.py':Path(__file__).read_bytes(),
           dest/'vpn-hardening-inventory.py':Path(__file__).with_name('vpn-hardening-inventory.py').read_bytes(),
           Path('/etc/systemd/system/homelab-xui-backend-guard.service'):UNIT.encode()}
    for path,content in files.items():
        h.check_path(path)
        if path.exists():raise ValueError('Persistence path already exists; inspect instead of overwriting')
    h.save(state/'guard-persistence-uncertain.json',{'paths':[str(p) for p in files]})
    for path,content in files.items():
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600 if path.parent==dest else 0o644)
        with os.fdopen(fd,'wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
    run(['systemd-analyze','verify','/etc/systemd/system/homelab-xui-backend-guard.service'])
    run(['systemctl','daemon-reload'])
    run(['systemctl','enable','--now','homelab-xui-backend-guard.service'])
    run(['systemctl','is-enabled','homelab-xui-backend-guard.service'])
    run(['systemctl','is-active','homelab-xui-backend-guard.service'])
    read_table();h.save(state/'guard-persistence-receipt.json',{'enabled':True,'active':True,'reboot_tested':False})
    (state/'guard-persistence-uncertain.json').unlink()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ensure',action='store_true');a=p.parse_args()
    if a.ensure:print(h.canonical(ensure()))
    else:print(h.canonical(plan()))
