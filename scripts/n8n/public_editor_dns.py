#!/usr/bin/env python3
"""Exact macOS n8n public DNS exception; plan by default, native root consent to apply."""
import argparse,hashlib,json,os,subprocess,sys,tempfile,time
from pathlib import Path
HOST='n8n.socrat.alchemmist.xyz'
BODY=b'# Public n8n HTTPS must not depend on private VPN DNS. Authentik remains required.\nnameserver 1.1.1.1\nnameserver 9.9.9.9\ntimeout 2\noptions attempts:2\n'
def apply():
    if sys.platform!='darwin' or os.geteuid()!=0:raise RuntimeError('Native macOS administrator authorization required')
    folder=Path('/etc/resolver');assert folder.is_dir() and not folder.is_symlink()
    assert folder.stat().st_uid==0 and not folder.stat().st_mode&0o022
    p=folder/HOST;assert not p.is_symlink()
    old=p.read_bytes() if p.exists() else None
    if old==BODY:print('Exact public n8n resolver already installed');return
    if old is not None:assert p.is_file() and len(old)<4096
    backup=Path('/var/root/.local/state/n8n-public-dns')/str(time.time_ns());backup.mkdir(parents=True,mode=0o700)
    if old is not None:(backup/'resolver.before').write_bytes(old);(backup/'resolver.before').chmod(0o600)
    (backup/'metadata.json').write_text(json.dumps({'path':str(p),'preexisting':old is not None,'before_sha256':hashlib.sha256(old).hexdigest() if old is not None else None,'after_sha256':hashlib.sha256(BODY).hexdigest()}));(backup/'metadata.json').chmod(0o600)
    fd,tmp=tempfile.mkstemp(prefix='.n8n-public-',dir=folder)
    try:
        os.fchmod(fd,0o644)
        with os.fdopen(fd,'wb') as f:f.write(BODY);f.flush();os.fsync(f.fileno())
        assert not p.is_symlink() and (p.read_bytes() if p.exists() else None)==old,'Concurrent change: stop'
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    subprocess.run(['/usr/bin/dscacheutil','-flushcache'],check=True)
    subprocess.run(['/usr/bin/killall','-HUP','mDNSResponder'],check=True)
    print('Only n8n resolver changed; root-only backup: '+str(backup))
if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--apply',action='store_true');args=a.parse_args()
    if args.apply:apply()
    else:print(json.dumps({'apply':False,'exact_domain':HOST,'resolver':BODY.decode(),'other_domains_unchanged':True},indent=2))
