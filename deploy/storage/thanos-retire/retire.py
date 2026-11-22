"""Approved single retirement. Refuse if live writer, coverage or cold restore is unverified."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

D = Path(__file__).resolve().parent
NS = "cattle-monitoring-system"
SPOOL = "/home/alchemmist/.local/state/socrat-backups/retired-thanos-raw-20261121"
RAW = "/var/lib/socrat-thanos"
UID = "4cab5a96-09e6-4699-8119-e3f0c9094d22"
PV = "pvc-97a31a0a-b498-42a6-be10-1cab44673c41"
WATCH = "warm-natural-shipper-ngvx2"
SSH = [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=yes",
    "-o",
    "HostName=10.250.0.1",
    "-o",
    "ProxyJump=none",
    "socrat-0",
]
K = ["kubectl", "--context=Socrat", "-n", NS]


class Compaction(TypedDict):
    sources: list[str]


class BlockMeta(TypedDict):
    thanos: dict[str, object]
    minTime: int
    maxTime: int
    compaction: Compaction


def output(args: list[str], stdin: str | None = None) -> str:
    return subprocess.check_output(args, input=stdin, text=True)


def main() -> None:
    if sys.flags.optimize:
        msg = "safety checks need standard Python"
        raise RuntimeError(msg)
    apply = sys.argv[1:] == ["--release-verified-files"]
    assert apply or sys.argv[1:] in (["--check"], ["--audit-cluster"])
    j = json.loads(output([*K, "get", "job", WATCH, "-o", "json"]))
    assert j["status"].get("succeeded") == 1, "first real shipper upload not verified"
    log = output([*K, "logs", "job/" + WATCH])
    mat = re.search(
        r"new sidecar block verified ([0-9A-Z]{26}) files (\d+) index/chunk bytes (\d+)",
        log,
    )
    assert mat
    assert int(mat[2]) >= 2
    assert int(mat[3]) > 0
    print("new shipper evidence", mat.group(0), flush=True)
    pods = json.loads(output([*K, "get", "pod", "-o", "json"]))["items"]
    p = next(
        p for p in pods if p["metadata"]["name"] == "prometheus-kube-prometheus-stack-prometheus-0"
    )
    assert p["metadata"]["uid"] == UID
    assert any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"]["conditions"])
    side = next(c for c in p["spec"]["containers"] if c["name"] == "thanos-sidecar")
    assert any(
        e.get("valueFrom", {}).get("secretKeyRef", {}).get("name") == "thanos-warm-shipper"
        for e in side["env"]
    )
    assert not any(
        v.get("hostPath", {}).get("path", "").rstrip("/") == RAW for v in p["spec"]["volumes"]
    )
    pvc = next(
        v["persistentVolumeClaim"]["claimName"]
        for v in p["spec"]["volumes"]
        if "persistentVolumeClaim" in v
    )
    assert json.loads(output([*K, "get", "pvc", pvc, "-o", "json"]))["spec"]["volumeName"] == PV
    for p in pods:
        if p.get("status", {}).get("phase") in ("Succeeded", "Failed"):
            continue
        for v in p["spec"].get("volumes", []):
            path = v.get("hostPath", {}).get("path", "").rstrip("/")
            assert path != RAW and not path.startswith(RAW + "/"), p["metadata"]["name"]
    for name, cred in [
        ("thanos-compactor", "thanos-warm-compactor"),
        ("thanos-store", "thanos-warm-store-reader"),
    ]:
        dep = json.loads(output([*K, "get", "deploy", name, "-o", "json"]))
        assert dep["status"].get("readyReplicas") == 1
        assert any(
            v.get("secret", {}).get("secretName") == cred
            for v in dep["spec"]["template"]["spec"]["volumes"]
        )
    spec = json.loads(output([*K, "get", "cj", "thanos-cascade", "-o", "json"]))["spec"][
        "jobTemplate"
    ]["spec"]["template"]["spec"]
    assert spec["nodeSelector"]["kubernetes.io/hostname"] == "socrat-3"
    assert "hour_copy.py" in str(spec["containers"][0]["command"])
    data = output(
        [
            *K,
            "exec",
            "deploy/thanos-store",
            "--",
            "/bin/thanos",
            "tools",
            "bucket",
            "ls",
            "-o",
            "json",
            "--exclude-delete",
            "--objstore.config-file=/etc/thanos/objstore.yml",
            "--timeout=2m",
            "--log.level=error",
        ]
    ).strip()
    remote: list[BlockMeta] = []
    dec = json.JSONDecoder()
    while data:
        m, i = dec.raw_decode(data)
        remote.append(m)
        data = data[i:].lstrip()
    assert remote
    old: list[BlockMeta] = json.loads(
        output(
            [*SSH, "python3 -"],
            """import json
from pathlib import Path
p=Path('/var/lib/socrat-thanos');print(json.dumps([json.loads(f.read_bytes()) for f in p.glob('*/meta.json')]))""",
        )
    )

    def covers(a: BlockMeta, b: BlockMeta) -> bool:
        return (
            a["thanos"].get("labels") == b["thanos"].get("labels")
            and a["thanos"].get("downsample") == b["thanos"].get("downsample")
            and a["minTime"] <= b["minTime"]
            and a["maxTime"] >= b["maxTime"]
            and bool(b["compaction"]["sources"])
            and set(b["compaction"]["sources"]) <= set(a["compaction"]["sources"])
        )

    assert len(old) >= 10 and all(any(covers(t, s) for t in remote) for s in old), (
        "cold block lacks a live same-resolution successor"
    )
    print("active S3 coverage for", len(old), "original blocks", flush=True)
    if sys.argv[1:] == ["--audit-cluster"]:
        return  # Read-only preflight: no release or filesystem changes.
    # Final comparison and unlink happen in the same remote process. Only names from
    # the fully restored archive can be removed; the directory itself is preserved.
    prog = (
        (D / "tree.py").read_text()
        + """\nimport socket,shutil,os
from pathlib import Path
root=Path('/var/lib/socrat-thanos');spool=Path('/home/alchemmist/.local/state/socrat-backups/retired-thanos-raw-20261121');assert socket.gethostname().split('.')[0]=='socrat-0' and root.resolve()==root and (root.stat().st_dev,root.stat().st_ino)==(66306,5507292)
assert spool.resolve()==spool and spool.is_dir() and spool.stat().st_mode&0o077==0
for line in Path('/proc/self/mountinfo').read_text().splitlines():
 mount=line.split()[4];assert mount!=str(root) and not mount.startswith(str(root)+'/')
m=json.loads((spool/'manifest.json').read_bytes());assert digest(m)==(spool/'verified.sha256').read_text().strip(); sha,name=(spool/'archive.sha256').read_text().split();assert name=='raw.tar.zst' and checksum(spool/name)==sha
assert manifest(root)==m,'source differs from fully restored archive';print('final source SHA-256 manifest',digest(m),'archive SHA-256',sha,flush=True)
"""
    )
    if apply:
        prog += """
assert not (spool/'released.json').exists();before=shutil.disk_usage(root).free
for f in m['files']:(root/f).unlink()
for d in sorted(m['dirs'],key=lambda x:x.count('/'),reverse=True):(root/d).rmdir()
fd=os.open(root,os.O_DIRECTORY);os.fsync(fd);os.close(fd);assert not any(root.iterdir());rec={'files':len(m['files']),'logical_bytes':sum(v[0] for v in m['files'].values()),'source_empty':True,'free_before':before,'free_after':shutil.disk_usage(root).free,'manifest':digest(m),'archive':sha};(spool/'released.json').write_text(json.dumps(rec));print(json.dumps(rec),flush=True)
"""
    print(output([*SSH, "nice -n 12 ionice -c2 -n7 python3 -I -"], prog), flush=True)


if __name__ == "__main__":
    main()
