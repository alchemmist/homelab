#!/usr/bin/env python3
"""Off-node AES-GCM encrypted Authentik snapshot. Local key is never sent to cluster."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT=Path(__file__).resolve().parents[1]
SSH=['ssh','-o','BatchMode=yes','-o','Hostname=109.173.40.247','-o','HostKeyAlias=[socrat.alchemmist.xyz]:2222','socrat-0']
HEADER=b'SOCRAT-IDENTITY-BACKUP-v1\n'

def save(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as f:f.write(data)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--service',choices=['authentik','harbor','open-webui'],default='authentik')
    p.add_argument('--key',type=Path,default=Path.home()/'.config/homelab/identity-backup.key')
    args=p.parse_args()
    if args.output.exists():raise SystemExit('Refusing overwrite')
    args.key.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not args.key.exists():save(args.key,AESGCM.generate_key(bit_length=256))
    if args.key.stat().st_mode & 0o077:raise SystemExit('Backup key must be private (0600)')
    helper=ROOT / {'authentik':'ansible/roles/authentik/files/backup.py','harbor':'ansible/roles/identity_integrations/files/backup_harbor.py','open-webui':'ansible/roles/identity_integrations/files/backup_webui.py'}[args.service]
    archive=subprocess.check_output(SSH+['python3','-'],input=helper.read_bytes(),timeout=180)
    nonce=os.urandom(12)
    cipher=AESGCM(args.key.read_bytes()).encrypt(nonce,archive,HEADER)
    save(args.output,HEADER+nonce+cipher)
    digest=hashlib.sha256(args.output.read_bytes()).hexdigest()
    save(Path(str(args.output)+'.sha256'),(digest+'  '+args.output.name+'\n').encode())
    print(json.dumps({'encryptedBackup':str(args.output),'sha256':digest,'restoreTested':False,
                      'observedAt':datetime.now(timezone.utc).isoformat()}))

if __name__=='__main__':main()
