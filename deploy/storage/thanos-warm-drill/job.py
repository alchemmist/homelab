"""Print an isolated, one-shot Kubernetes Job; no cluster credentials required to render."""

import json

PYTHON = (
    "python@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2"
)
PROM = "quay.io/prometheus/prometheus@sha256:b2a413d5a03ea6a76782a508d1c7947440bba3b973931a25676e278431891b01"
THANOS = "quay.io/thanos/thanos@sha256:b567818fe608067eb0f1d7c2c4fe361e7ad83c8a256234c97685f1d0bf670cc8"
SCRATCH = {"name": "scratch", "mountPath": "/tmp"}
ROOT = {"name": "candidate", "mountPath": "/candidate"}
BUCKET = {**ROOT, "subPathExpr": "drill-$(POD_UID)"}


def container(name, image, command, args, mount=None, sidecar=False):
    result = dict(
        name=name,
        image=image,
        command=command,
        args=args,
        env=[
            {
                "name": "POD_UID",
                "valueFrom": {"fieldRef": {"fieldPath": "metadata.uid"}},
            }
        ],
        resources={
            "requests": {"cpu": "50m", "memory": "64Mi"},
            "limits": {"cpu": "1", "memory": "768Mi"},
        },
        securityContext={
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        },
        volumeMounts=[SCRATCH] + ([mount] if mount else []),
    )
    if sidecar:
        result["restartPolicy"] = "Always"
    return result


prepare = """
from pathlib import Path
import os
p = Path('/candidate') / ('drill-' + os.environ['POD_UID'])
p.mkdir()  # Never reuse an existing bucket.
(p / 'blocks').mkdir()
start = 1702512000  # fixed historical fixture; no live data
with open('/tmp/samples.om','w') as f:
    f.write('# TYPE warm_drill gauge\\n')
    for t in range(start,start+28*86400,60): f.write(f'warm_drill 7 {t}\\n')
    f.write('# EOF\\n')
"""
project = """
import json,os
from pathlib import Path
root=Path('/candidate'); blocks=root/'blocks'; selected={}
for path in blocks.glob('*/meta.json'):
    meta=json.loads(path.read_text()); res=meta['thanos']['downsample']['resolution']
    if res not in (300000,3600000) or (path.parent/'deletion-mark.json').exists(): continue
    selected.setdefault(res,[]).append(meta)
for res in (300000,3600000):
    metas=selected[res]; folder=root/str(res); folder.mkdir()
    for meta in metas:
        # Read-only synthetic projection. No raw block can satisfy this Store.
        import shutil
        shutil.copytree(blocks/meta['ulid'],folder/meta['ulid'],copy_function=os.link)
    mid=max(metas,key=lambda m:m['maxTime']-m['minTime'])
    Path('/tmp/t'+str(res)).write_text(str((mid['minTime']+mid['maxTime'])//2000))
    print('resolution',res,'active blocks',len(metas))
"""
verify = """
import json,time,urllib.request,urllib.parse
from pathlib import Path
for res,port,maximum in ((300000,12002,'5m'),(3600000,13002,'1h')):
    def read(limit):
        q=urllib.parse.urlencode(dict(query='avg_over_time(warm_drill{fixture="s1-canary"}[4h])',time=Path('/tmp/t'+str(res)).read_text(),max_source_resolution=limit,partial_response='false'))
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/query?'+q,timeout=5) as r: data=json.load(r)
        assert data['status']=='success' and not data.get('warnings'),data
        return [float(x['value'][1]) for x in data['data']['result']]
    for _ in range(45):
        try:
            if read(maximum)==[7.0]: break
        except (OSError,AssertionError): pass
        time.sleep(2)
    else: raise SystemExit(f'{maximum} read failed')
    assert read('0s')==[], 'raw-only query unexpectedly succeeded'
    print(maximum,'value 7 verified, raw-only empty',flush=True)
"""


def obj(path):
    return "--objstore.config=" + json.dumps(
        {"type": "FILESYSTEM", "config": {"directory": "/candidate/" + path}}
    )


init = [
    container("prepare", PYTHON, ["python3", "-Bc"], [prepare], ROOT),
    container(
        "tsdb",
        PROM,
        ["/bin/promtool"],
        ["tsdb", "create-blocks-from", "openmetrics", "/tmp/samples.om", "/tmp/tsdb"],
    ),
    container(
        "upload",
        THANOS,
        ["/bin/thanos"],
        [
            "tools",
            "bucket",
            "upload-blocks",
            obj("blocks"),
            "--path=/tmp/tsdb",
            '--label=fixture="s1-canary"',
            "--shipper.upload-compacted",
        ],
        BUCKET,
    ),
    container(
        "compact",
        THANOS,
        ["/bin/thanos"],
        [
            "compact",
            obj("blocks"),
            "--data-dir=/tmp/work",
            "--consistency-delay=0s",
            "--delete-delay=1h",
        ],
        BUCKET,
    ),
    container("project", PYTHON, ["python3", "-Bc"], [project], BUCKET),
]
for resolution, port in [(300000, 12000), (3600000, 13000)]:
    init.append(
        container(
            "store-" + str(resolution),
            THANOS,
            ["/bin/thanos"],
            [
                "store",
                obj(str(resolution)),
                f"--data-dir=/tmp/store{port}",
                f"--grpc-address=127.0.0.1:{port}",
                f"--http-address=127.0.0.1:{port + 1}",
            ],
            {**BUCKET, "readOnly": True},
            True,
        )
    )
    init.append(
        container(
            "query-" + str(resolution),
            THANOS,
            ["/bin/thanos"],
            [
                "query",
                f"--endpoint=127.0.0.1:{port}",
                f"--http-address=127.0.0.1:{port + 2}",
                f"--grpc-address=127.0.0.1:{port + 3}",
            ],
            sidecar=True,
        )
    )
job = {
    "apiVersion": "batch/v1",
    "kind": "Job",
    "metadata": {
        "generateName": "thanos-warm-block-drill-",
        "namespace": "cattle-monitoring-system",
    },
    "spec": {
        "backoffLimit": 0,
        "activeDeadlineSeconds": 900,
        "ttlSecondsAfterFinished": 86400,
        "template": {
            "spec": {
                "automountServiceAccountToken": False,
                "restartPolicy": "Never",
                "nodeSelector": {"kubernetes.io/hostname": "socrat-1"},
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "runAsGroup": 2000,
                    "fsGroup": 2000,
                    "seccompProfile": {"type": "RuntimeDefault"},
                },
                "volumes": [
                    {"name": "scratch", "emptyDir": {"sizeLimit": "1Gi"}},
                    {
                        "name": "candidate",
                        "persistentVolumeClaim": {
                            "claimName": "thanos-warm-s1-candidate"
                        },
                    },
                ],
                "initContainers": init,
                "containers": [
                    container("verify", PYTHON, ["python3", "-Bc"], [verify])
                ],
            }
        },
    },
}
if __name__ == "__main__":
    print(json.dumps(job))
