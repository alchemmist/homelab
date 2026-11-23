"""Render a read-only Store/Query historical acceptance Job for a verified seed."""

import json
import sys
from uuid import UUID

from job import PYTHON, THANOS, container


def render(uid: str) -> dict[str, object]:
    seed = "seed-five-" + str(UUID(uid)) + "/tree"
    dst = {
        "name": "candidate",
        "mountPath": "/candidate",
        "readOnly": True,
        "subPath": seed,
    }
    store = container(
        "store",
        THANOS,
        ["/bin/thanos"],
        [
            "store",
            "--objstore.config="
            + json.dumps({"type": "FILESYSTEM", "config": {"directory": "/candidate"}}),
            "--data-dir=/tmp/store",
            "--http-address=127.0.0.1:10902",
            "--grpc-address=127.0.0.1:10901",
        ],
        dst,
        True,
    )
    query = container(
        "query",
        THANOS,
        ["/bin/thanos"],
        [
            "query",
            "--endpoint=127.0.0.1:10901",
            "--http-address=127.0.0.1:12902",
            "--grpc-address=127.0.0.1:12901",
        ],
        sidecar=True,
    )
    verify = """
import json, time, urllib.parse, urllib.request

def read(res):
    q=urllib.parse.urlencode({'query':'sum(count_over_time(up[1h]))','time':'1792785600','max_source_resolution':res,'partial_response':'false'})
    with urllib.request.urlopen('http://127.0.0.1:12902/api/v1/query?'+q,timeout=5) as f: data=json.load(f)
    assert data['status']=='success' and not data.get('warnings'), data
    return [float(d['value'][1]) for d in data['data']['result']]
for _ in range(90):
    try:
        if read('5m')==[900]: break
    except (OSError, AssertionError): pass
    time.sleep(2)
else: raise SystemExit('historical 5m answer not verified')
assert read('0s')==[], 'unexpected raw data'
print('isolated production seed read: 5m=900 raw-only=empty at 1792785600')
"""
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "namespace": "cattle-monitoring-system",
            "generateName": "thanos-five-seed-read-",
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 360,
            "ttlSecondsAfterFinished": 86400,
            "template": {
                "spec": {
                    "automountServiceAccountToken": False,
                    "nodeSelector": {"kubernetes.io/hostname": "socrat-1"},
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 2000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "restartPolicy": "Never",
                    "initContainers": [store, query],
                    "containers": [container("verify", PYTHON, ["python3", "-Bc"], [verify])],
                    "volumes": [
                        {"name": "scratch", "emptyDir": {"sizeLimit": "512Mi"}},
                        {
                            "name": "candidate",
                            "persistentVolumeClaim": {
                                "claimName": "thanos-warm-s1-candidate",
                                "readOnly": True,
                            },
                        },
                    ],
                }
            },
        },
    }


if __name__ == "__main__":
    print(json.dumps(render(sys.argv[1])))
