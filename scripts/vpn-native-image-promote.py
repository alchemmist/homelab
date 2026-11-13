#!/usr/bin/env python3
"""Explicit one-shot atomic exchange of verified dormant native image on NL.

Never stops/starts any service. The watchdog lock protects the standby path while
Kubernetes continues serving the SAME live DB. Old image retained in candidate.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

ROOT=Path('/opt/homelab-vpn-failover')
STATE=Path('/var/lib/homelab-vpn-failover')
RECEIPT=Path('/var/lib/homelab-recovery/20261113-vpn-native-image/promotion.json')

def active(unit):
    p=subprocess.run(['systemctl','is-active','--quiet',unit],capture_output=True,timeout=5)
    assert p.returncode in (0,3)
    return p.returncode==0

def running_core():
    found=[]
    for path in Path('/proc').glob('[0-9]*/exe'):
        try:
            if Path(os.readlink(path)).name!='xray-linux-amd64':continue
            if any(x.endswith(b'bin/config.json') for x in (path.parent/'cmdline').read_bytes().split(b'\0')):found.append(path)
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
    assert len(found)==1
    return hashlib.sha256(found[0].read_bytes()).hexdigest()

def promote(candidate,old_image,new_image):
    assert os.geteuid()==0 and socket.gethostname()=='socrat-2'
    assert candidate.parent==ROOT and candidate.name.startswith('staged-') and not candidate.is_symlink()
    assert not RECEIPT.exists(), 'Existing attempt/receipt; inspect, never replay'
    proof=json.loads((candidate/'.isolated-smoke-accepted.json').read_text())
    assert proof['healthy'] and proof['cleanup_verified'] and not proof['production_runtime_changed']
    assert 0<=time.time()-proof['accepted_at']<=900, 'Fresh isolated smoke required'
    assert proof['image']==new_image
    new=candidate/'primary';current=ROOT/'primary'
    assert not new.is_symlink() and not current.is_symlink()
    assert new.stat().st_dev==current.stat().st_dev
    assert (new/'.homelab-image').read_text().strip()==new_image
    assert hashlib.sha256((new/'app/x-ui').read_bytes()).hexdigest()==proof['ui_sha256']
    core=hashlib.sha256((new/'app/bin/xray-linux-amd64').read_bytes()).hexdigest()
    assert core==running_core(), 'Candidate core differs from live; stop for explicit review'
    with (STATE/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert not (STATE/'active').exists() and not (STATE/'inhibit').exists()
        assert active('k3s.service')
        assert not active('homelab-vpn-primary.service') and not active('homelab-vpn-caddy.service')
        status=subprocess.run(['/usr/local/sbin/homelab-vpn-failover','status'],capture_output=True,text=True,timeout=30)
        assert status.returncode==0 and json.loads(status.stdout)['healthy']
        assert (current/'.homelab-image').read_text().strip()==old_image
        # Durable intent before atomic syscall; any uncertainty prohibits replay.
        fd=os.open(RECEIPT,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump({'state':'intent','old_image':old_image,'new_image':new_image},stream)
            stream.flush();os.fsync(stream.fileno())
        fd=os.open(RECEIPT.parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
        libc=ctypes.CDLL(None,use_errno=True)
        fn=libc.renameat2
        fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        if fn(-100,os.fsencode(current),-100,os.fsencode(new),2)!=0:
            raise OSError(ctypes.get_errno(),'Atomic image exchange failed; inspect intent')
        for path in (ROOT,candidate):
            fd=os.open(path,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
        assert (current/'.homelab-image').read_text().strip()==new_image
        assert (new/'.homelab-image').read_text().strip()==old_image
        receipt={'state':'accepted','old_image_preserved':True,'new_image':new_image,
                 'core_matches_running':True,'no_runtime_restart':True,'at':time.time()}
        temporary=RECEIPT.with_suffix('.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(receipt,stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,RECEIPT)
        fd=os.open(RECEIPT.parent,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
        print(json.dumps(receipt))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--old-image',required=True);p.add_argument('--new-image',required=True);a=p.parse_args()
    try:promote(a.candidate,a.old_image,a.new_image)
    except Exception:raise SystemExit('Native image promotion stopped; inspect private intent/receipts, never replay.') from None
