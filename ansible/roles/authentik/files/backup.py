import json,os,subprocess,sys,tarfile,tempfile
from pathlib import Path
os.environ['K3S_CONFIG_FILE']='/dev/null'
root=Path.home()/'.cache/homelab-authentik'
k=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml','-n','identity']
with tempfile.TemporaryDirectory(dir=root) as work:
 p=Path(work)
 with (p/'database.dump').open('wb') as f:
  subprocess.run(k+['exec','authentik-postgres-0','--','pg_dump','-U','authentik','-d','authentik','-Fc'],stdout=f,check=True)
 pod=json.loads(subprocess.check_output(k+['get','pods','-l','app.kubernetes.io/component=server','-o','json']))['items'][0]['metadata']['name']
 with (p/'data.tar').open('wb') as f:
  subprocess.run(k+['exec',pod,'-c','server','--','tar','-C','/data','-cf','-','.'],stdout=f,check=True)
 with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tar:
  for name in ['credentials.json','oidc-clients.json','values.yaml','foundation.yaml','services.json','owner-login.json','antropophag-login.json','account-mappings.json']:
   tar.add(root/name,arcname=name)
  # Include machine-identity journal and guarded rollback credentials when present.
  for extra in [root/'automation-api.json',*root.glob('credentials-before-automation-*.json')]:
   if extra.exists():tar.add(extra,arcname=extra.name)
  for name in ['database.dump','data.tar']:tar.add(p/name,arcname=name)
