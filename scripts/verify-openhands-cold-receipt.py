"""Verify a completed cold-archive receipt using the operator's recovery key (never sent to pod)."""
import base64, hashlib, json, os, pathlib, subprocess

os.umask(0o077);ns="openhands";job="openhands-cold-backup-20261119";home=pathlib.Path.home()/".config/homelab/openhands/backups"
def k(*args):return subprocess.check_output(["kubectl","-n",ns,*args])
state=json.loads(k("get","job",job,"-o","json"));assert any(c["type"]=="Complete" and c["status"]=="True" for c in state["status"]["conditions"]);lines=k("logs","job/"+job).splitlines();r=json.loads(next(l for l in reversed(lines) if l.startswith(b"{")));assert r["format"]=="openhands-full-claim-v2" and r["restored_sqlite_integrity"]=="ok" and r["verified_settings_and_handoff"] and min(r["history_events"].values())>0 and r["excluded"]==[]
key=subprocess.check_output(["openssl","pkeyutl","-decrypt","-inkey",str(home/"upgrade-rsa.pem"),"-pkeyopt","rsa_padding_mode:oaep","-pkeyopt","rsa_oaep_md:sha256"],input=base64.b64decode(r["wrapped_key"],validate=True));assert len(key)==32 and hashlib.sha256(key).hexdigest()==r["key_sha256"];del key
r.update(job_uid=state["metadata"]["uid"],completed_at=state["status"]["completionTime"],operator_unwrap_verified=True,claim="openhands-cold-backups",archive="canvas-cold-20261119.gcm");p=home/"canvas-cold-20261119-receipt.json"
if p.exists(): assert json.loads(p.read_bytes())==r
else:
 with p.open("x") as out:json.dump(r,out);out.flush();os.fsync(out.fileno())
print("verified",r["bytes"],"ciphertext bytes;",r["members"],"archive members; events:",r["history_events"],"; local private-key unwrap OK; sha256:",r["ciphertext_sha256"])
