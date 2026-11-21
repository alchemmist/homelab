"""Compare independent single-Store Queries: live raw Store vs read-only warm S3."""

import json, sys
from pathlib import Path
from start import BASE, create, kube
from delta import source_pod

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "thanos-warm-drill"))
from job import container, THANOS, PYTHON

TIMES = """
import json,time
from pathlib import Path
rows=[]
for f in sorted(Path('/host/var/lib/socrat-thanos').glob('*/meta.json')):
 if (f.parent/'deletion-mark.json').exists():continue
 m=json.loads(f.read_text());a=m['minTime']//1000;z=min(m['maxTime']//1000,int(time.time()-7*3600));r=m.get('thanos',{}).get('downsample',{}).get('resolution',0)
 if z-a<7200:continue
 rows.append((f.parent.name,(a+z)//2,r))
print(json.dumps(rows))
"""
VERIFY = """
import hashlib,json,time,urllib.parse,urllib.request,sys
from concurrent.futures import ThreadPoolExecutor
rows=json.loads(sys.argv[1]);assert {x[2] for x in rows}>={0,300000}
def read(port,expr,t,res):
 q=urllib.parse.urlencode(dict(query=expr,time=t,partial_response='false',max_source_resolution=res,dedup='false'))
 with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/query?'+q,timeout=20) as f:d=json.load(f)
 assert d['status']=='success' and not d.get('warnings')
 return sorted(json.dumps(x,sort_keys=True) for x in d['data']['result'])
for _ in range(90):
 try:
  if all(read(p,'sum(count_over_time(up[1h]))',rows[0][1],'5m') for p in (12002,13002)): break
 except (OSError,AssertionError):pass
 time.sleep(2)
else:raise SystemExit('failed readiness: Store did not serve known history')
for block,t,r in rows:
 expr='up[5m]' if r==0 else 'sum by (job) (count_over_time(up[1h]))';res='0s' if r==0 else '5m'
 with ThreadPoolExecutor(2) as pool:a,b=pool.map(lambda port:read(port,expr,t,res),(12002,13002))
 if not a or a!=b:raise SystemExit(f'parity failed {block} {t} {res} old={len(a)} warm={len(b)}')
 print('match',block,t,res,len(a),'series',hashlib.sha256(json.dumps(a).encode()).hexdigest()[:16],flush=True)
print('matched time windows',len(rows),flush=True)
"""


def main():
    rows = json.loads(kube("exec", source_pod(), "--", "python3", "-c", TIMES))
    assert rows
    st = container(
        "warm-store",
        THANOS,
        ["/bin/thanos"],
        [
            "store",
            "--objstore.config-file=/s3/objstore.yml",
            "--data-dir=/tmp/store",
            "--max-time=-6h",
            "--ignore-deletion-marks-delay=1h",
            "--grpc-address=127.0.0.1:11901",
            "--http-address=127.0.0.1:11902",
        ],
        sidecar=True,
    )
    st["volumeMounts"] += [
        {"name": n, "mountPath": p, "readOnly": True}
        for n, p in [("trust", "/trust"), ("s3", "/s3")]
    ]
    init = [st]
    for name, port, endpoint in [
        ("reference", 12000, "thanos-store:10901"),
        ("warm", 13000, "127.0.0.1:11901"),
    ]:
        init.append(
            container(
                name,
                THANOS,
                ["/bin/thanos"],
                [
                    "query",
                    "--endpoint=" + endpoint,
                    f"--grpc-address=127.0.0.1:{port + 1}",
                    f"--http-address=127.0.0.1:{port + 2}",
                ],
                sidecar=True,
            )
        )
    vols = [
        {"name": "scratch", "emptyDir": {"sizeLimit": "1500Mi"}},
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
    j = create(
        "Job",
        {
            "metadata": {"generateName": "warm-workshop-parity-"},
            "spec": {
                "activeDeadlineSeconds": 600,
                "backoffLimit": 0,
                "ttlSecondsAfterFinished": 86400,
                "template": {
                    "metadata": {"labels": {"thanos-warm-client": "seed"}},
                    "spec": {
                        **BASE,
                        "nodeSelector": {"kubernetes.io/hostname": "socrat-1"},
                        "volumes": vols,
                        "initContainers": init,
                        "containers": [
                            container(
                                "compare",
                                PYTHON,
                                ["python3", "-Bc"],
                                [VERIFY, json.dumps(rows)],
                            )
                        ],
                    },
                },
            },
        },
        api="batch/v1",
    )
    print(j["metadata"]["name"], len(rows), "windows")


if __name__ == "__main__":
    main()
