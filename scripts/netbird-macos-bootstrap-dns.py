#!/usr/bin/env python3
"""Plan by default; --apply needs native macOS root consent. Exact control DNS only."""
import os,json,hashlib,tempfile,subprocess,sys,argparse
from pathlib import Path
HOSTS = ('netbird.socrat.alchemmist.xyz', 'netbird-relay-vps.socrat.alchemmist.xyz',
         'auth.socrat.alchemmist.xyz')
PUBLIC_DNS = ('1.1.1.1', '9.9.9.9')


def render():
    return ('# NetBird/Auth bootstrap must not depend on the private VPN DNS path.\n'
            + ''.join('nameserver '+ip+'\n' for ip in PUBLIC_DNS)
            + 'timeout 2\noptions attempts:2\n').encode()


def apply():
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise RuntimeError('Explicit macOS root authorization required')
    folder=Path('/etc/resolver')
    assert folder.is_dir() and not folder.is_symlink()
    assert folder.stat().st_uid==0 and not folder.stat().st_mode & 0o022
    backup=Path('/var/root/.local/state/netbird-bootstrap-dns')
    backup.mkdir(parents=True,exist_ok=True,mode=0o700)
    assert not (backup/'complete.json').exists(),'existing completed change: stop, inspect'
    hosts=HOSTS;body=render()
    result={}
    for host in hosts:
     p=folder/host;assert not p.is_symlink()
     if p.exists():
      assert p.is_file();old=p.read_bytes();assert len(old)<4096
      fd=os.open(backup/(host+'.before'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
      with os.fdopen(fd,'wb') as f:f.write(old)
      result[host]={'preexisting':True,'before_sha256':hashlib.sha256(old).hexdigest()}
     else:result[host]={'preexisting':False}
     fd,tmp=tempfile.mkstemp(prefix='.netbird-bootstrap-',dir=folder)
     try:
      os.fchmod(fd,0o644)
      with os.fdopen(fd,'wb') as f:f.write(body);f.flush();os.fsync(f.fileno())
      os.replace(tmp,p)
     finally:
      if os.path.exists(tmp):os.unlink(tmp)
     result[host]['after_sha256']=hashlib.sha256(body).hexdigest()
    fd=os.open(backup/'complete.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f)
    subprocess.run(['/usr/bin/dscacheutil','-flushcache'],check=True)
    subprocess.run(['/usr/bin/killall','-HUP','mDNSResponder'],check=True)
    print('Three exact control-plane DNS exceptions installed; private app resolvers unchanged; root-only backups saved.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.apply:
        apply()
    else:
        print(json.dumps({'apply':False,'exact_control_domains':HOSTS,
                          'public_dns':PUBLIC_DNS,'private_app_dns_unchanged':True},indent=2))
