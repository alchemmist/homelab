"""Start an additive TLS seed; no production bucket settings or retention mutations."""

import json, secrets, subprocess, sys
from pathlib import Path

D = Path(__file__).parent
NS = "cattle-monitoring-system"
P = "python@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2"
NAME = "warm-raw-seed-" + secrets.token_hex(4)
SEC = {
    "allowPrivilegeEscalation": False,
    "readOnlyRootFilesystem": True,
    "capabilities": {"drop": ["ALL"]},
}
BASE = {
    "automountServiceAccountToken": False,
    "restartPolicy": "Never",
    "securityContext": {
        "runAsNonRoot": True,
        "runAsUser": 1000,
        "runAsGroup": 2000,
        "seccompProfile": {"type": "RuntimeDefault"},
    },
}
RES = {
    "requests": {"cpu": "50m", "memory": "32Mi"},
    "limits": {"cpu": "1", "memory": "128Mi"},
}


def kube(*args, data=None):
    p = subprocess.run(
        ["kubectl", "--context=Socrat", "-n", NS, *args],
        input=data,
        text=True,
        capture_output=True,
        timeout=90,
    )
    if p.returncode:
        raise RuntimeError(
            "kubectl failed: " + str(args[:2])
        )  # no capability paths in errors
    return p.stdout


def create(kind, body, name=NAME, api="v1"):
    return json.loads(
        kube(
            "create",
            "-f",
            "-",
            "-o",
            "json",
            data=json.dumps(
                {"apiVersion": api, "kind": kind, "metadata": {"name": name}, **body}
            ),
        )
    )


INVENTORY = """
import json,re
from pathlib import Path
p=Path('/host/var/lib/socrat-thanos');blocks=[]
for d in sorted(p.iterdir()):
 if not re.fullmatch(r'[0-9A-HJKMNP-TV-Z]{26}',d.name) or not (d/'meta.json').is_file() or (d/'deletion-mark.json').exists():continue
 m=json.loads((d/'meta.json').read_text());assert m['ulid']==d.name
 files=[]
 for f in sorted(d.rglob('*'),key=lambda f:(f.name=='meta.json',str(f))):
  assert not f.is_symlink()
  if f.is_file():files.append([str(f.relative_to(p)),f.stat().st_size])
 blocks.append((sum(n for _,n in files),files))
print(json.dumps([f for _,files in sorted(blocks) for f in files]))
"""


def main():
    delta = sys.argv[1:] == ["--run", "--delta"]
    marks = sys.argv[1:] == ["--run", "--source-compaction-marks"]
    if not delta and not marks and sys.argv[1:] != ["--run"]:
        sys.exit("use --run explicitly")
    jobs = json.loads(
        kube("get", "jobs", "-l", "thanos-warm-client=seed", "-o", "json")
    )["items"]
    assert not any(
        not any(
            c["type"] in ("Complete", "Failed") and c["status"] == "True"
            for c in j.get("status", {}).get("conditions", [])
        )
        for j in jobs
    ), "another seed in flight"
    pods = json.loads(
        kube(
            "get",
            "pods",
            "-l",
            "app=thanos-disk",
            "--field-selector=spec.nodeName=socrat-0,status.phase=Running",
            "-o",
            "json",
        )
    )["items"]
    assert len(pods) == 1
    files = json.loads(
        kube("exec", pods[0]["metadata"]["name"], "--", "python3", "-c", INVENTORY)
    )
    if marks:
        from markers import batch

        files = batch(jobs)
        if not files:
            return
    if delta:
        import re
        from delta import remote_objects

        objects = remote_objects()
        verified = set()
        for j in jobs:
            if not j.get("status", {}).get("succeeded"):
                continue
            log = kube("logs", "job/" + j["metadata"]["name"])
            if not re.search(
                r"^all files verified .*sha256\(manifest\) [a-f0-9]{64}$", log, re.M
            ):
                continue
            verified.update(
                re.findall(
                    r"^verified block ([0-9A-Z]{26}) cumulative bytes", log, re.M
                )
            )
        assert not any(k in objects and objects[k] != n for k, n in files), (
            "size mismatch; review required"
        )
        needed = {
            k.split("/")[0]
            for k, n in files
            if k not in objects or k.split("/")[0] not in verified
        }
        files = [(k, n) for k, n in files if k.split("/")[0] in needed]
        if not files:
            print("No unconfirmed active blocks at this observation")
            return
    assert files and max(n for _, n in files) < 5 * 2**30
    backend = json.loads(kube("get", "pod", "-l", "app=thanos-warm-api", "-o", "json"))[
        "items"
    ]
    assert len(backend) == 1 and backend[0]["spec"]["nodeName"] == "socrat-1"
    free = (
        int(
            kube(
                "exec",
                backend[0]["metadata"]["name"],
                "-c",
                "rustfs",
                "--",
                "sh",
                "-ec",
                "df -Pk /data | awk 'END{print $4}'",
            )
        )
        * 1024
    )
    size = sum(n for _, n in files)
    assert free - size > 50 * 2**30, "insufficient headroom"
    signer = NAME + "-sign"
    create(
        "Pod",
        {
            "spec": {
                **BASE,
                "activeDeadlineSeconds": 180,
                "nodeSelector": {"kubernetes.io/hostname": "socrat-1"},
                "containers": [
                    {
                        "name": "sign",
                        "image": P,
                        "command": ["python3", "-Bc", "import time;time.sleep(150)"],
                        "env": [
                            {
                                "name": k.upper(),
                                "valueFrom": {
                                    "secretKeyRef": {
                                        "name": "thanos-warm-root",
                                        "key": k,
                                    }
                                },
                            }
                            for k in ["access", "secret"]
                        ],
                        "securityContext": SEC,
                        "resources": RES,
                    }
                ],
            }
        },
        signer,
    )
    try:
        kube("wait", "--for=condition=Ready", "pod/" + signer, "--timeout=60s")
        caps = kube(
            "exec",
            "-i",
            signer,
            "--",
            "python3",
            "-Bc",
            (D / "sign.py").read_text(),
            data=json.dumps(files),
        )
        assert set(json.loads(caps)) == set(k for k, _ in files)
    finally:
        kube("delete", "pod", signer, "--wait=false")
    mounts = [
        {"name": "source", "mountPath": "/source", "readOnly": True},
        {"name": "caps", "mountPath": "/caps", "readOnly": True},
        {"name": "trust", "mountPath": "/trust", "readOnly": True},
    ]
    labels = {"thanos-warm-client": "seed"}
    job = create(
        "Job",
        {
            "metadata": {"name": NAME, "labels": labels},
            "spec": {
                "ttlSecondsAfterFinished": 86400,
                "backoffLimit": 0,
                "activeDeadlineSeconds": 10800,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        **BASE,
                        "nodeSelector": {"kubernetes.io/hostname": "socrat-0"},
                        "containers": [
                            {
                                "name": "copy",
                                "image": P,
                                "command": [
                                    "python3",
                                    "-Bc",
                                    (D / "worker.py").read_text(),
                                ],
                                "volumeMounts": mounts,
                                "securityContext": SEC,
                                "resources": RES,
                            }
                        ],
                        "volumes": [
                            {
                                "name": "source",
                                "hostPath": {
                                    "path": "/var/lib/socrat-thanos",
                                    "type": "Directory",
                                },
                            },
                            {
                                "name": "trust",
                                "secret": {
                                    "secretName": "thanos-warm-api-tls",
                                    "items": [{"key": "ca.crt", "path": "ca.crt"}],
                                },
                            },
                            {"name": "caps", "secret": {"secretName": NAME}},
                        ],
                    },
                },
            },
        },
        api="batch/v1",
    )
    create(
        "Secret",
        {
            "metadata": {
                "name": NAME,
                "ownerReferences": [
                    {
                        "apiVersion": "batch/v1",
                        "kind": "Job",
                        "name": NAME,
                        "uid": job["metadata"]["uid"],
                    }
                ],
            },
            "immutable": True,
            "stringData": {"keys.json": caps},
        },
    )
    print(NAME, len(files), "files", size, "bytes", flush=True)


if __name__ == "__main__":
    main()
