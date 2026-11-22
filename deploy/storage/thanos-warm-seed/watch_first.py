"""One-shot check: an unforced new production shipper block is readable from warm S3."""

import json
import re
import sys
from pathlib import Path

from start import BASE, RES, SEC, P, create, kube

VERIFY = """
class Compare:
    def __init__(self,f): self.f=f
    def write(self,data):
        if self.f.read(len(data))!=data: raise IOError('source/object bytes differ')

baseline=set(json.loads(os.environ['BASELINE']));root=Path('/tsdb'); b=Bucket(json.loads(Path('/s3/objstore.yml').read_text())['config'])
for _ in range(350):
    ids=set(json.loads((root/'thanos.shipper.json').read_bytes())['uploaded'])-baseline
    for u in sorted(ids):
        if not ULID.fullmatch(u):raise ValueError('invalid journal ULID')
        local=root/u
        if not (local/'meta.json').is_file():continue
        m=json.loads(b.read(u+'/meta.json')); lm=json.loads((local/'meta.json').read_bytes()); assert m['thanos']['source']=='sidecar'
        assert all(m[k]==lm[k] for k in ['ulid','minTime','maxTime','stats']); assert m['ulid']==u
        paths=[local/'index',*sorted((local/'chunks').iterdir())]; assert len(paths)>=2
        n=0
        for p in paths:
            with p.open('rb') as f:
                size,_=b.read(u+'/'+str(p.relative_to(local)),sink=Compare(f)); assert not f.read(1);n+=size
        print('new sidecar block verified',u,'files',len(paths),'index/chunk bytes',n,'interval',m['minTime'],m['maxTime'],flush=True);exit(0)
    time.sleep(30)
raise TimeoutError('no new journaled block verified during observation')
"""


def main() -> None:
    baseline = json.loads(Path(sys.argv[1]).read_bytes())["uploaded"]
    assert baseline and all(re.fullmatch("[0-9A-HJKMNP-TV-Z]{26}", u) for u in baseline)
    pod = json.loads(
        kube(
            "get", "pod", "prometheus-kube-prometheus-stack-prometheus-0", "-o", "json"
        )
    )
    claim = next(
        v["persistentVolumeClaim"]["claimName"]
        for v in pod["spec"]["volumes"]
        if "persistentVolumeClaim" in v
    )
    assert claim.startswith("prometheus-kube-prometheus-stack-prometheus-db-")
    # Bind only the production TSDB PVC, read-only; no host root, no API token.
    path = Path(__file__).resolve().parents[3] / "charts/thanos/files/hour_copy.py"
    src = path.read_text().split('if __name__ == "__main__":')[0] + VERIFY
    vol = [
        {
            "name": "src",
            "persistentVolumeClaim": {"claimName": claim, "readOnly": True},
        },
        {
            "name": "s3",
            "secret": {
                "secretName": "thanos-warm-store-reader",
                "items": [{"key": "objstore.yml", "path": "objstore.yml"}],
            },
        },
        {
            "name": "trust",
            "secret": {
                "secretName": "thanos-warm-api-tls",
                "items": [{"key": "ca.crt", "path": "ca.crt"}],
            },
        },
    ]
    c = {
        "name": "verify",
        "image": P,
        "command": ["python3", "-Bc", src],
        "env": [{"name": "BASELINE", "value": json.dumps(baseline)}],
        "securityContext": SEC,
        "resources": RES,
        "volumeMounts": [
            {
                "name": "src",
                "mountPath": "/tsdb",
                "subPath": "prometheus-db",
                "readOnly": True,
            },
            *(
                {"name": k, "mountPath": "/" + k, "readOnly": True}
                for k in ["s3", "trust"]
            ),
        ],
    }
    # Match the Prometheus disk reader uid/gid without changing PVC ownership.
    base = {
        **BASE,
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 1000,
            "runAsGroup": 2000,
            "supplementalGroups": [2000, 65534],
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    }
    j = create(
        "Job",
        {
            "metadata": {"generateName": "warm-natural-shipper-"},
            "spec": {
                "activeDeadlineSeconds": 10800,
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": 86400,
                "template": {
                    "metadata": {"labels": {"thanos-warm-client": "seed"}},
                    "spec": {
                        **base,
                        "nodeSelector": {"kubernetes.io/hostname": "socrat-0"},
                        "volumes": vol,
                        "containers": [c],
                    },
                },
            },
        },
        api="batch/v1",
    )
    print(j["metadata"]["name"])


if __name__ == "__main__":
    main()
