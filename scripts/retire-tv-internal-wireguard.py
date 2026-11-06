#!/usr/bin/env python3
"""Retire only the explicitly owned xiaomi-tv peer, without restarting WireGuard."""
import argparse,fcntl,hashlib,json,os,re,socket,subprocess
from pathlib import Path
KEY='2iba8vq4KkAZmoLR+5u9t/WUlvtrHOtS+ys/k8oN4wQ='; IP='10.250.0.8/32'
ROOT=Path('/var/lib/homelab-tv-wireguard-retirement');CONF=Path('/etc/wireguard/wg-socrat.conf')
def need(ok,msg):
    if not ok:raise RuntimeError(msg)
def digest(b):return hashlib.sha256(b).hexdigest()
def peers():
    out=subprocess.check_output(['wg','show','wg-socrat','allowed-ips'],text=True)
    return dict(line.split('\t',1) for line in out.splitlines())
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    need(socket.gethostname().split('.')[0] in ['socrat-0','socrat-1','socrat-2','socrat-3'],'Unexpected node')
    need(not ROOT.is_symlink(),'Unsafe state');ROOT.mkdir(mode=0o700,exist_ok=True);need(ROOT.stat().st_uid==0 and not ROOT.stat().st_mode&0o077,'Unsafe state owner/mode')
    with (ROOT/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);need(not (ROOT/'uncertain.json').exists(),'Uncertain previous retirement; stop')
        need(not CONF.is_symlink() and CONF.stat().st_uid==0 and not CONF.stat().st_mode&0o077,'Unsafe WireGuard config')
        before=CONF.read_bytes();kept=[];count=0
        for block in re.split(r'(?m)(?=^\[Peer\])',before.decode()):
            k=re.search(r'(?m)^PublicKey\s*=\s*(\S+)\s*$',block);ips=re.search(r'(?m)^AllowedIPs\s*=\s*([^\n]+)',block)
            if k and (k[1]==KEY or (ips and ips[1].strip()==IP)):
                need(k[1]==KEY and ips and ips[1].strip()==IP and '# xiaomi-tv' in block,'Peer ownership mismatch');count+=1
            else:kept.append(block)
        need(count<=1,'Duplicate owned peer');after=''.join(kept).encode();runtime=peers()
        need(all(k==KEY or v.strip()!=IP for k,v in runtime.items()),'Address belongs to another identity')
        need(KEY not in runtime or runtime[KEY].strip()==IP,'Unexpected owned peer routes')
        context={'before_sha':digest(before),'after_sha':digest(after),'runtime':runtime,'tool_sha':digest(Path(__file__).read_bytes())}
        h=digest(json.dumps(context,sort_keys=True).encode());changed=bool(count or KEY in runtime)
        if a.apply and changed:
            need(a.approve_plan_hash==h,'Fresh exact approval required');need(not (ROOT/'before.conf').exists(),'Existing retirement backup; inspect before retry')
            (ROOT/'before.conf').write_bytes(before);(ROOT/'before.json').write_text(json.dumps(context));(ROOT/'uncertain.json').write_text(json.dumps({'plan_hash':h}))
            need(CONF.read_bytes()==before and peers()==runtime,'Concurrent drift; stop')
            if count:
                temp=CONF.with_name('wg-socrat.conf.tv-retirement');need(not temp.exists(),'Unexpected temporary config');temp.write_bytes(after);temp.chmod(0o600);temp.replace(CONF)
            if KEY in runtime:subprocess.run(['wg','set','wg-socrat','peer',KEY,'remove'],check=True,capture_output=True)
            need(peers()=={k:v for k,v in runtime.items() if k!=KEY},'Other peer routes changed')
            need(CONF.read_bytes()==after,'Persistent readback failed')
            (ROOT/'after.json').write_text(json.dumps({'plan_hash':h,'other_peers_unchanged':True,'interface_restarted':False}));(ROOT/'uncertain.json').unlink()
        print(json.dumps({'operations':int(changed),'plan_hash':h,'applied':bool(a.apply and changed)}))
if __name__=='__main__':main()
