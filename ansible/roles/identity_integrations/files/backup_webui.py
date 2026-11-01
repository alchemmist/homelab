"""Consistent SQLite plus auth secrets snapshot; stream only into encryption."""
import json,os,subprocess,sys,tarfile,tempfile
from pathlib import Path
os.environ['K3S_CONFIG_FILE']='/dev/null'
root=Path.home()/'.cache/homelab-authentik';k=['kubectl','--kubeconfig','/etc/rancher/k3s/k3s.yaml','-n','llm']
remote='/tmp/identity-before-oidc.sqlite'
try:
 subprocess.run(k+['exec','deployment/open-webui','-c','open-webui','--','python','-c',
  'import sqlite3,os; s=sqlite3.connect("/app/backend/data/webui.db"); d=sqlite3.connect("'+remote+'"); s.backup(d); d.close(); os.chmod("'+remote+'",0o600)'],check=True,stdout=subprocess.DEVNULL)
 with tempfile.TemporaryDirectory(dir=root) as work:
  p=Path(work)
  with (p/'webui.db').open('wb') as f:subprocess.run(k+['exec','deployment/open-webui','-c','open-webui','--','cat',remote],stdout=f,check=True)
  secrets=subprocess.check_output(k+['get','secret','open-webui-auth','open-webui-litellm','-o','json'])
  (p/'secrets.json').write_bytes(secrets)
  with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as tar:
   for name in ['webui.db','secrets.json']:tar.add(p/name,arcname=name)
finally:
 subprocess.run(k+['exec','deployment/open-webui','-c','open-webui','--','rm','-f',remote],stdout=subprocess.DEVNULL,check=False)
