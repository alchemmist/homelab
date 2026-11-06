#!/usr/bin/env python3
"""Retire only the owned tv alias to the existing authoritative renderer; zone refresh, no restart."""
import argparse,fcntl,hashlib,importlib.util,json,os,subprocess
from pathlib import Path
CURRENT=Path('/usr/local/libexec/public_dns_zone.py');ROOT=Path('/var/lib/homelab-grafana-tv-dns-retirement')
def require(ok,message):
    if not ok:raise RuntimeError(message)
def load(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def delta(old,new):
    for home,vps in [(True,True),(True,False),(False,True),(False,False)]:
        before=old.render(123,home,vps).splitlines();after=new.render(123,home,vps).splitlines()
        require([x for x in after if not x.startswith('tv IN A ')]==[x for x in before if not x.startswith('tv IN A ')],'Unrelated DNS record change; stop')
        require(not [x for x in after if x.startswith('tv IN A ')],'Retired alias must have no A records')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--approve-plan-hash');a=p.parse_args();os.umask(0o077)
    proposed=ROOT/'proposed.py'
    for path in [CURRENT,proposed]:require(path.is_file() and not path.is_symlink() and path.stat().st_uid==0 and not path.stat().st_mode&0o022,'Unsafe renderer')
    require(ROOT.stat().st_uid==0 and not ROOT.stat().st_mode&0o077,'Unsafe state directory')
    with (ROOT/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX);require(not (ROOT/'uncertain.json').exists(),'Uncertain prior write; stop')
        old=CURRENT.read_bytes();new=proposed.read_bytes();oldmod=load(CURRENT,'old');newmod=load(proposed,'new');delta(oldmod,newmod)
        changed=old!=new;context={'tool':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'before':hashlib.sha256(old).hexdigest(),'after':hashlib.sha256(new).hexdigest(),'name':'tv'}
        digest=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
        if a.apply and changed:
            require(a.approve_plan_hash==digest,'Fresh hash approval required')
            (ROOT/'before.py').write_bytes(old);(ROOT/'uncertain.json').write_text(json.dumps(context))
            temp=CURRENT.with_name('public_dns_zone.py.public-web.tmp');require(not temp.exists(),'Unexpected temporary renderer')
            temp.write_bytes(new);temp.chmod(0o755);temp.replace(CURRENT)
            subprocess.run(['systemctl','start','public-dns-refresh.service'],check=True,capture_output=True)
            result=subprocess.check_output(['knotc','zone-read','alchemmist.xyz'],text=True)
            require(not any('tv.alchemmist.xyz.' in line.split() and 'A' in line.split() for line in result.splitlines()),'Alias retirement not confirmed')
            (ROOT/'after.json').write_text(json.dumps({'renderer_sha256':context['after'],'zone_read_confirmed':True}));(ROOT/'uncertain.json').unlink()
        print(json.dumps({'operations':int(changed),'plan_hash':digest,'applied':bool(a.apply and changed)}))
if __name__=='__main__':main()
