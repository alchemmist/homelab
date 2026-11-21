"""Render an isolated seed-copy Job, NOT a writer switch or a cold backup."""

import json
from job import PYTHON, container

COPY = """
from pathlib import Path
import hashlib,json,os,stat,time
src=Path('/source'); dest=Path('/candidate')/('seed-five-'+os.environ['POD_UID']); dest.mkdir()
if not any(src.glob('*/meta.json')): raise SystemExit('empty source')

def scan():
    out={}
    for p in sorted(src.rglob('*')):
        st=p.lstat(); rel=p.relative_to(src).as_posix()
        if stat.S_ISDIR(st.st_mode): kind='dir'
        elif stat.S_ISREG(st.st_mode): kind='file'
        else: raise RuntimeError('unsupported entry: '+rel)
        out[rel]=(kind,st.st_size,st.st_mtime_ns,st.st_ino)
    return out
before=scan(); size=sum(x[1] for x in before.values() if x[0]=='file');fs=os.statvfs(dest)
assert fs.f_bavail*fs.f_frsize-size>=80*2**30, 'insufficient destination headroom'
manifest={}; root=dest/'tree';root.mkdir(); start=time.monotonic(); written=0
for rel,(kind,n,*_) in before.items():
    p=root/rel
    if kind=='dir': p.mkdir();continue
    h=hashlib.sha256()
    with (src/rel).open('rb') as f,p.open('xb') as out:
        while buf:=f.read(1024**2):
            h.update(buf);out.write(buf);written+=len(buf)
            time.sleep(max(0,written/(32*1024**2)-(time.monotonic()-start)))
        out.flush();os.fsync(out.fileno())
    assert p.stat().st_size==n
    with p.open('rb') as r: assert hashlib.file_digest(r,'sha256').hexdigest()==h.hexdigest()
    manifest[rel]={'bytes':n,'sha256':h.hexdigest()}
assert before==scan(), 'source changed; do not accept this seed'
encoded=json.dumps(manifest,sort_keys=True).encode(); (dest/'files.json').write_bytes(encoded)
print('seed',dest.name,'verified files',len(manifest),'bytes',written,'manifest sha256',hashlib.sha256(encoded).hexdigest(),flush=True)
"""


def render():
    c = container("seed", PYTHON, ["python3", "-Bc"], [COPY])
    c["volumeMounts"] = [
        {
            "name": "source",
            "mountPath": "/source",
            "subPath": "active",
            "readOnly": True,
        },
        {"name": "candidate", "mountPath": "/candidate"},
    ]
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "namespace": "cattle-monitoring-system",
            "generateName": "thanos-five-seed-",
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 1200,
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "spec": {
                    "nodeSelector": {"kubernetes.io/hostname": "socrat-1"},
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 2000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [c],
                    "volumes": [
                        {
                            "name": "source",
                            "persistentVolumeClaim": {
                                "claimName": "thanos-5m-s1-candidate",
                                "readOnly": True,
                            },
                        },
                        {
                            "name": "candidate",
                            "persistentVolumeClaim": {
                                "claimName": "thanos-warm-s1-candidate"
                            },
                        },
                    ],
                }
            },
        },
    }


if __name__ == "__main__":
    print(json.dumps(render()))
