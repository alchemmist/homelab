"""Stream a pre-OIDC Harbor snapshot to the encryption process, never to logs."""
import os,subprocess,sys,tarfile,tempfile
from pathlib import Path
os.environ['K3S_CONFIG_FILE']='/dev/null'
root=Path.home()/'.cache/homelab-harbor';k=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml','-n','harbor']
with tempfile.TemporaryDirectory(dir=root) as work:
 p=Path(work)
 with (p/'database.dump').open('wb') as f:subprocess.run(k+['exec','harbor-database-0','-c','database','--','pg_dump','-U','postgres','-d','registry','-Fc'],stdout=f,check=True)
 with (p/'registry.tar').open('wb') as f:subprocess.run(k+['exec','deployment/harbor-registry','-c','registry','--','tar','-C','/storage','-cf','-','.'],stdout=f,check=True)
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tar:
  for name in ['private-values.json','ci-push.json','cluster-pull.json','values.yaml']:tar.add(root/name,arcname=name)
  for name in ['database.dump','registry.tar']:tar.add(p/name,arcname=name)
