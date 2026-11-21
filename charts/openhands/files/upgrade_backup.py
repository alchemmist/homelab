"""Trusted operator backup, never a coding-agent tool. No network or SA token."""
import base64
import hashlib
import io
import json
import os
import pathlib
import sqlite3
import tarfile
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

os.umask(0o077)
root=pathlib.Path("/backup");
receipt=root/"pre142.json";
encrypted=root/"pre142.aesgcm"
assert not receipt.exists() and not encrypted.exists(), "Never overwrite a previous backup"
source=sqlite3.connect("file:/source/openhands/automation/automations.db?mode=ro",uri=True)
snapshot=sqlite3.connect("/tmp/snapshot.db");
deadline=time.monotonic()+90

def progress(status,left,total):
    if time.monotonic()>deadline:raise RuntimeError("SQLite snapshot deadline")

source.backup(snapshot,pages=64,progress=progress)
assert snapshot.execute("pragma integrity_check").fetchone()[0]=="ok"
snapshot.close();
source.close()

def filt(info):
    if info.name.startswith(".openhands/automation/automations.db"):return None
    if info.name.startswith(".openhands/workspaces/automation-runs/") and ".venv" in pathlib.Path(info.name).parts:return None
    return info

buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode="w:gz") as tar:
    tar.add("/source/openhands",arcname=".openhands",filter=filt)
    tar.add("/source/workspace",arcname="workspace")
    tar.add("/tmp/snapshot.db",arcname=".openhands/automation/automations.db")
raw=buf.getvalue();
key=AESGCM.generate_key(bit_length=256);
nonce=os.urandom(12)
cipher=nonce+AESGCM(key).encrypt(nonce,raw,b"openhands-pre142-v1")
with encrypted.open("xb") as f:f.write(cipher)
check=encrypted.read_bytes();
restored=AESGCM(key).decrypt(check[:12],check[12:],b"openhands-pre142-v1")
assert hashlib.sha256(restored).digest()==hashlib.sha256(raw).digest()
with tarfile.open(fileobj=io.BytesIO(restored),mode="r:gz") as tar:
    db=sqlite3.connect(":memory:");
    db.deserialize(tar.extractfile(".openhands/automation/automations.db").read())
    assert db.execute("pragma integrity_check").fetchone()[0]=="ok"
    assert tar.getmember("workspace/the-loop-demo/HANDOFF.md").size>0
public=serialization.load_pem_public_key(pathlib.Path("/config/recipient.pem").read_bytes())
wrapped=public.encrypt(key,padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
report={"format":"openhands-pre142-v1","encrypted_sha256":hashlib.sha256(check).hexdigest(),"bytes":len(check),"decrypt_verified":True,"sqlite_integrity":"ok","handoff_present":True,"wrapped_key":base64.b64encode(wrapped).decode(),"key_sha256":hashlib.sha256(key).hexdigest(),"excluded":"regenerable automation .venv only"}
with receipt.open("x") as f:json.dump(report,f)
print(json.dumps(report))
