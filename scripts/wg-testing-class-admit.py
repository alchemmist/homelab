#!/usr/bin/env python3
"""One-time CAS admission after source-scoped guard. Never blindly replay.
Existing private config/runtime snapshot stays root-only; stdout is sanitized.
"""
import hashlib,json,os,pathlib,subprocess,time
KEY='kq9Kb6ZF9j/cuBooG3onvLfnBBjI0cTdQK26nKR4R0E='
IP='10.250.0.41/32'
EXPECTED='ea9e5dc22fabfe13af8e65fae5944846f8ac11d1d69eb62dc6b301cfbde3d503'
def run(*args):return subprocess.check_output(args,text=True).strip()
def peers():return dict(x.split('\t',1) for x in run('wg','show','wg-socrat','allowed-ips').splitlines())
def main():
 os.umask(0o077)
 assert run('hostname')=='socrat-4'
 assert run('wg','show','wg-socrat','public-key')=='rOXEc8nrYHuYG0D5t+LwY9jxv05zsjxt0P2scF+Sf0k='
 assert run('systemctl','is-active','testing-class-wg-guard.service')=='active'
 subprocess.run(['/usr/local/libexec/testing-class-wg-guard'],check=True)
 f=pathlib.Path('/etc/wireguard/wg-socrat.conf');before=f.read_bytes()
 assert hashlib.sha256(before).hexdigest()==EXPECTED,'STOP persistent CAS mismatch; inspect receipt, do not replay'
 assert KEY.encode() not in before and b'SaveConfig' not in before
 original=peers();assert KEY not in original and not any('10.250.0.41' in x for x in original.values())
 root=pathlib.Path('/var/lib/homelab-recovery/20261110-socrat5-bootstrap')
 root.mkdir(mode=0o700,exist_ok=False)
 (root/'wg-socrat.before.conf').write_bytes(before)
 (root/'wg-runtime.before.conf').write_text(run('wg','showconf','wg-socrat')+'\n')
 candidate=before.rstrip()+('\n\n[Peer]\n# bootstrap-only: socrat-5; isolation owned by dedicated guard service\nPublicKey = '+KEY+'\nAllowedIPs = '+IP+'\nPersistentKeepalive = 25\n').encode()
 tmp=f.with_name('wg-s5-new.conf');assert not tmp.exists()
 old_candidate=f.with_name('wg-socrat.testing-class-candidate.conf')
 if old_candidate.exists():
  assert old_candidate.read_bytes()==candidate,'STOP unknown old candidate'
  archived=pathlib.Path('/var/lib/homelab-recovery/20261110-testing-class-bootstrap/rejected-long-name.conf')
  assert not archived.exists();os.replace(old_candidate,archived)
 with tmp.open('xb') as o:o.write(candidate);o.flush();os.fsync(o.fileno())
 subprocess.run(['wg-quick','strip',str(tmp)],check=True,stdout=subprocess.DEVNULL)
 assert f.read_bytes()==before and peers()==original,'STOP pre-write state changed'
 (root/'receipt.json').write_text(json.dumps({'phase':'prepared','before_sha256':EXPECTED,'candidate_sha256':hashlib.sha256(candidate).hexdigest()}))
 os.replace(tmp,f)
 fd=os.open(str(f.parent),os.O_RDONLY);os.fsync(fd);os.close(fd)
 # Surgical one-peer addition: never sync/replace the other peers or restart WG.
 subprocess.run(['wg','set','wg-socrat','peer',KEY,'allowed-ips',IP,'persistent-keepalive','25'],check=True)
 current=peers();assert current.pop(KEY)==IP and current==original
 assert f.read_bytes()==candidate
 result={'phase':'peer-admitted-awaiting-client','address':IP,'other_peer_allowed_ips_preserved':True,'wg_service':run('systemctl','is-active','wg-quick@wg-socrat'),'persistent_sha256':hashlib.sha256(candidate).hexdigest(),'at':time.time()}
 (root/'receipt.json').write_text(json.dumps(result));print(json.dumps(result))
if __name__=='__main__':main()
