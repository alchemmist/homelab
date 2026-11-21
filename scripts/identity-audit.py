#!/usr/bin/env python3
"""Read-only identity inventory. Never reads shadow, private keys, tokens or Secrets."""

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from typing import cast

HOSTS = {
    "socrat-0": [
        "-o",
        "Hostname=109.173.40.247",
        "-o",
        "HostKeyAlias=[socrat.alchemmist.xyz]:2222",
        "socrat-0",
    ],
    "socrat-1": ["socrat-1"],
    "socrat-2": ["socrat-2"],
    "socrat-3": ["socrat-3"],
}
PROBE = r"""
import grp,json,os,pwd,subprocess
users=[]
for p in pwd.getpwall():
 if p.pw_uid == 0 or (1000 <= p.pw_uid < 65534):
  path=p.pw_dir+'/.ssh/authorized_keys'
  keys={'readable':os.access(path,os.R_OK),'exists':os.path.exists(path)}
  if keys['readable']:
   x=subprocess.run(['ssh-keygen','-lf',path],text=True,capture_output=True)
   keys['fingerprints']=[line.split()[1] for line in x.stdout.splitlines() if len(line.split())>1]
  users.append({'name':p.pw_name,'uid':p.pw_uid,'shell':p.pw_shell,'home':p.pw_dir,
   'groups':[g.gr_name for g in grp.getgrall() if p.pw_name in g.gr_mem or g.gr_gid==p.pw_gid],
   'authorizedKeys':keys})
m=dict(x.split(':',1) for x in open('/proc/meminfo'))
storage='/var/lib/rancher/k3s/storage'
if not os.path.isdir(storage):storage='/'
d=os.statvfs(storage)
sudo=subprocess.run(['sudo','-n','true'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
print(json.dumps({'users':users,'passwordlessPrivilege':sudo,
 'availableMemoryMiB':int(m['MemAvailable'].split()[0])//1024,
 'storagePath':storage,'freeStorageGiB':round(d.f_bavail*d.f_frsize/1024**3,1),
 'uninspected':['password hashes','sudoers effective policy','active WireGuard peer state','other unreadable authorized_keys']}))
"""


def remote(host: str, command: str) -> str:
    return subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", *HOSTS[host], command],
        text=True,
        timeout=90,
    )


def collect() -> dict[str, object]:
    import shlex

    nodes: dict[str, dict[str, object]] = {}
    result: dict[str, object] = {
        "observedAt": datetime.now(UTC).isoformat(),
        "nodes": nodes,
    }
    for host in HOSTS:
        try:
            nodes[host] = json.loads(remote(host, "python3 -c " + shlex.quote(PROBE)))
        except (subprocess.SubprocessError, ValueError, OSError):
            nodes[host] = {"inspectionFailed": True}
    prefix = "env K3S_CONFIG_FILE=/dev/null kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml "
    # Never inspect Secret objects or emit raw Pod environment variables.
    bindings: dict[str, list[dict[str, object]]] = {}
    for kind in ["clusterrolebindings", "rolebindings"]:
        data = json.loads(remote("socrat-0", prefix + "get " + kind + " -A -o json"))
        bindings[kind] = [
            {
                "name": x["metadata"]["name"],
                "namespace": x["metadata"].get("namespace"),
                "roleRef": x["roleRef"],
                "subjects": x.get("subjects", []),
            }
            for x in data["items"]
        ]
    result["kubernetesBindings"] = bindings
    data = json.loads(remote("socrat-0", prefix + "get deployments -A -o json"))
    result["applications"] = [
        {
            "namespace": d["metadata"]["namespace"],
            "name": d["metadata"]["name"],
            "images": [c["image"] for c in d["spec"]["template"]["spec"]["containers"]],
        }
        for d in data["items"]
    ]
    k8s_nodes = json.loads(remote("socrat-0", prefix + "get nodes -o json"))
    result["nodeConditions"] = {
        n["metadata"]["name"]: n["status"]["conditions"] for n in k8s_nodes["items"]
    }
    return result


def main() -> bool:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = collect()
    fd = os.open(args.output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")
    nodes = cast("dict[str, dict[str, object]]", result["nodes"])
    failed = [n for n, v in nodes.items() if v.get("inspectionFailed")]
    print("Identity audit saved privately; failed hosts: " + (", ".join(failed) or "none"))
    return bool(failed)


if __name__ == "__main__":
    raise SystemExit(main())
