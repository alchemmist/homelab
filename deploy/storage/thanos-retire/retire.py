"""Approved single retirement. Refuse if live writer, coverage or cold restore is unverified."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast

D = Path(__file__).resolve().parent
NS = "cattle-monitoring-system"
SPOOL = "/home/alchemmist/.local/state/socrat-backups/retired-thanos-raw-20261121"
RAW = "/var/lib/socrat-thanos"
UID = "4cab5a96-09e6-4699-8119-e3f0c9094d22"
PV = "pvc-97a31a0a-b498-42a6-be10-1cab44673c41"
WATCH = "warm-natural-shipper-ngvx2"
PROM_POD = "prometheus-kube-prometheus-stack-prometheus-0"
MIN_VERIFIED_FILES = 2
MIN_COLD_BLOCKS = 10
MAT_LOG_PATTERN = r"new sidecar block verified ([0-9A-Z]{26}) files (\d+) index/chunk bytes (\d+)"
READY_NODE = "socrat-3"
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
    """Per-block compaction source list."""

    sources: list[str]


class BlockMeta(TypedDict):
    """One Thanos block meta.json shape."""

    thanos: dict[str, object]
    minTime: int
    maxTime: int
    compaction: Compaction


def output(args: list[str], stdin: str | None = None) -> str:
    """Run one reviewed command and return its complete stdout."""
    return subprocess.check_output(args, input=stdin, text=True)


def _map(node: object) -> dict[str, object]:
    """Cast one reviewed JSON node to a plain object map."""
    return cast("dict[str, object]", node)


def _host_path(volume: dict[str, object]) -> str:
    """Return a volume hostPath with its trailing slash stripped."""
    return cast("str", _map(volume.get("hostPath", {})).get("path", "")).rstrip("/")


def _verify_shipper() -> None:
    """Confirm the first real warm-shipper upload finished and was verified."""
    j = json.loads(output([*K, "get", "job", WATCH, "-o", "json"]))
    if j["status"].get("succeeded") != 1:
        msg = "first real shipper upload not verified"
        raise RuntimeError(msg)
    log = output([*K, "logs", "job/" + WATCH])
    mat = re.search(MAT_LOG_PATTERN, log)
    if mat is None:
        msg = "shipper log lacks the verified-upload evidence line"
        raise RuntimeError(msg)
    if int(mat[2]) < MIN_VERIFIED_FILES:
        msg = "verified upload must keep at least the reviewed file count"
        raise RuntimeError(msg)
    if int(mat[3]) <= 0:
        msg = "verified upload must carry index/chunk bytes"
        raise RuntimeError(msg)
    print("new shipper evidence", mat.group(0), flush=True)


def _verify_prometheus_writer(pods: list[dict[str, object]]) -> None:
    """Confirm the live writer is exactly the reviewed UID on the reviewed PV."""
    p = next(pod for pod in pods if cast("dict[str, object]", pod["metadata"])["name"] == PROM_POD)
    writer_meta = cast("dict[str, object]", p["metadata"])
    if writer_meta["uid"] != UID:
        msg = "live writer UID changed"
        raise RuntimeError(msg)
    writer_status = cast("dict[str, object]", p["status"])
    conditions = cast("list[dict[str, object]]", writer_status["conditions"])
    if not any(c["type"] == "Ready" and c["status"] == "True" for c in conditions):
        msg = "live writer must be Ready"
        raise RuntimeError(msg)
    writer_spec = cast("dict[str, object]", p["spec"])
    containers = cast("list[dict[str, object]]", writer_spec["containers"])
    side = next(c for c in containers if c["name"] == "thanos-sidecar")
    side_env = cast("list[dict[str, object]]", side["env"])
    if not any(
        _map(_map(e.get("valueFrom", {})).get("secretKeyRef", {})).get("name")
        == "thanos-warm-shipper"
        for e in side_env
    ):
        msg = "sidecar must keep the reviewed warm-shipper secret"
        raise RuntimeError(msg)
    volumes = cast("list[dict[str, object]]", writer_spec["volumes"])
    if any(_host_path(v) == RAW for v in volumes):
        msg = "live writer must not mount the reviewed raw path"
        raise RuntimeError(msg)
    pvc = next(
        cast("str", _map(v["persistentVolumeClaim"])["claimName"])
        for v in volumes
        if "persistentVolumeClaim" in v
    )
    live_pv = cast("dict[str, object]", json.loads(output([*K, "get", "pvc", pvc, "-o", "json"])))
    if cast("str", _map(live_pv["spec"])["volumeName"]) != PV:
        msg = "live writer PV changed"
        raise RuntimeError(msg)
    for pod in pods:
        pod_status = _map(pod.get("status", {}))
        if pod_status.get("phase") in ("Succeeded", "Failed"):
            continue
        pod_spec = _map(pod["spec"])
        for v in cast("list[dict[str, object]]", pod_spec.get("volumes", [])):
            path = _host_path(v)
            if path == RAW or path.startswith(RAW + "/"):
                pod_name = cast("str", _map(pod["metadata"])["name"])
                msg = "running pod mounts the reviewed raw path: " + pod_name
                raise RuntimeError(msg)


def _verify_warm_deployments() -> None:
    """Confirm both warm consumers stay single-replica on reviewed creds."""
    expected = [
        ("thanos-compactor", "thanos-warm-compactor"),
        ("thanos-store", "thanos-warm-store-reader"),
    ]
    for name, cred in expected:
        dep = json.loads(output([*K, "get", "deploy", name, "-o", "json"]))
        if dep["status"].get("readyReplicas") != 1:
            msg = "warm consumer must stay single replica: " + name
            raise RuntimeError(msg)
        if not any(
            v.get("secret", {}).get("secretName") == cred
            for v in dep["spec"]["template"]["spec"]["volumes"]
        ):
            msg = "warm consumer must keep the reviewed credential volume: " + name
            raise RuntimeError(msg)


def _verify_cascade_cron() -> None:
    """Confirm the cascade cronjob still runs the reviewed hour copy."""
    spec = json.loads(output([*K, "get", "cj", "thanos-cascade", "-o", "json"]))["spec"][
        "jobTemplate"
    ]["spec"]["template"]["spec"]
    if spec["nodeSelector"]["kubernetes.io/hostname"] != READY_NODE:
        msg = "cascade must stay pinned to the reviewed node"
        raise RuntimeError(msg)
    if "hour_copy.py" not in str(spec["containers"][0]["command"]):
        msg = "cascade must keep the reviewed hour copy command"
        raise RuntimeError(msg)


def _read_bucket_blocks() -> list[BlockMeta]:
    """Stream the live bucket listing (several concatenated JSON documents)."""
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
    if not remote:
        msg = "bucket listing is empty"
        raise RuntimeError(msg)
    return remote


def _covers(a: BlockMeta, b: BlockMeta) -> bool:
    """Return whether live block a fully covers cold block b."""
    return (
        a["thanos"].get("labels") == b["thanos"].get("labels")
        and a["thanos"].get("downsample") == b["thanos"].get("downsample")
        and a["minTime"] <= b["minTime"]
        and a["maxTime"] >= b["maxTime"]
        and bool(b["compaction"]["sources"])
        and set(b["compaction"]["sources"]) <= set(a["compaction"]["sources"])
    )


def _verify_cold_coverage(remote: list[BlockMeta]) -> None:
    """Confirm every cold block on socrat-0 has a live same-resolution successor."""
    old: list[BlockMeta] = json.loads(
        output(
            [*SSH, "python3 - "],
            """import json
from pathlib import Path
p=Path('/var/lib/socrat-thanos');print(json.dumps([json.loads(f.read_bytes()) for f in p.glob('*/meta.json')]))""",
        )
    )
    if len(old) < MIN_COLD_BLOCKS:
        msg = "cold source lost blocks before the retirement"
        raise RuntimeError(msg)
    if not all(any(_covers(t, s) for t in remote) for s in old):
        msg = "cold block lacks a live same-resolution successor"
        raise RuntimeError(msg)
    print("active S3 coverage for", len(old), "original blocks", flush=True)


def main() -> None:
    """Run the single approved retirement entry point."""
    if sys.flags.optimize:
        msg = "safety checks need standard Python"
        raise RuntimeError(msg)
    argv = sys.argv[1:]
    apply = argv == ["--release-verified-files"]
    if not apply and argv not in (["--check"], ["--audit-cluster"]):
        msg = "pass exactly one reviewed mode: --check, --audit-cluster or --release-verified-files"
        raise RuntimeError(msg)
    _verify_shipper()
    pods = json.loads(output([*K, "get", "pod", "-o", "json"]))["items"]
    _verify_prometheus_writer(pods)
    _verify_warm_deployments()
    _verify_cascade_cron()
    remote = _read_bucket_blocks()
    _verify_cold_coverage(remote)
    if argv == ["--audit-cluster"]:
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
