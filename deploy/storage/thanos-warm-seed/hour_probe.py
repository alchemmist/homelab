"""Exercise resolution-filtered S3 -> socrat-3 replication in disposable storage."""

import json
import re
import sys
from pathlib import Path

from start import BASE, create, kube

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thanos-warm-drill"))
from job import PYTHON, THANOS, container

VERIFY = """
import hashlib,json,sys
from pathlib import Path
p=Path('/tmp/hour');expected=json.loads(sys.argv[1]);got={}
for f in p.rglob('*'):
 if f.is_file():
  with f.open('rb') as r:got[str(f.relative_to(p))]=hashlib.file_digest(r,'sha256').hexdigest()
assert set(expected)==set(got),(set(expected)-set(got),set(got)-set(expected))
assert got==expected,'content differs'
for f in p.glob('*/meta.json'):assert json.loads(f.read_text())['thanos']['downsample']['resolution']==3600000
print('Only 1h replicated; files matched SHA-256:',len(got),flush=True)
"""


def main():
    logs = kube("logs", "job/thanos-hour-fixture-reader-bootstrap", "-c", "provision")
    hashes = {k: h for h, k in re.findall(r"^([0-9a-f]{64})  \./([^\n]+)$", logs, re.M)}
    assert any(k.endswith("/meta.json") for k in hashes)
    cmd = [
        "tools",
        "bucket",
        "replicate",
        "--single-run",
        "--resolution=1h",
        "--compaction-max=100",
        "--ignore-marked-for-deletion",
        "--objstore.config-file=/s3/objstore.yml",
        "--objstore-to.config="
        + json.dumps({"type": "FILESYSTEM", "config": {"directory": "/tmp/hour"}}),
    ]
    trust = {"name": "trust", "mountPath": "/trust", "readOnly": True}
    s3 = {"name": "s3", "mountPath": "/s3", "readOnly": True}
    worker = container("pull", THANOS, ["/bin/thanos"], cmd)
    worker["volumeMounts"] += [trust, s3]
    j = create(
        "Job",
        {
            "metadata": {"generateName": "warm-hour-pull-"},
            "spec": {
                "activeDeadlineSeconds": 240,
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": 86400,
                "template": {
                    "metadata": {"labels": {"thanos-warm-client": "seed"}},
                    "spec": {
                        **BASE,
                        "nodeSelector": {"kubernetes.io/hostname": "socrat-3"},
                        "volumes": [
                            {"name": "scratch", "emptyDir": {"sizeLimit": "256Mi"}},
                            {
                                "name": "trust",
                                "secret": {
                                    "secretName": "thanos-warm-api-tls",
                                    "items": [{"key": "ca.crt", "path": "ca.crt"}],
                                },
                            },
                            {
                                "name": "s3",
                                "secret": {
                                    "secretName": "thanos-hour-fixture-reader",
                                    "items": [
                                        {"key": "objstore.yml", "path": "objstore.yml"}
                                    ],
                                },
                            },
                        ],
                        "initContainers": [worker],
                        "containers": [
                            container(
                                "verify",
                                PYTHON,
                                ["python3", "-Bc"],
                                [VERIFY, json.dumps(hashes)],
                            )
                        ],
                    },
                },
            },
        },
        api="batch/v1",
    )
    print(j["metadata"]["name"])


if __name__ == "__main__":
    main()
