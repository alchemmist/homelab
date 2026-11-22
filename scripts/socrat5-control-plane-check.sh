#!/usr/bin/env bash
# Read-only API checks before/after the VM105 role transition. Does not prove etcd membership.
set -euo pipefail
phase=${1:-before}
case "${phase}" in before|after) ;; *) echo 'usage: socrat5-control-plane-check.sh before|after' >&2; exit 2;; esac
k=(kubectl --context=Socrat --request-timeout=6s)
for ip in 10.250.0.1 10.250.0.3; do
  ready=$("${k[@]}" --server="https://${ip}:6443" get --raw=/readyz)
  test "${ready}" = ok
  echo "existing API ${ip} ready"
done
if [[ ${phase} == after ]]; then
  ready=$("${k[@]}" --server=https://10.250.0.41:6443 get --raw=/readyz)
  test "${ready}" = ok
  echo 'VM105 API ready'
fi
"${k[@]}" get nodes -o json | python3 -c '
import json, sys
nodes={n["metadata"]["name"]:n for n in json.load(sys.stdin)["items"]}
def role(r): return sorted(k for k,n in nodes.items() if "node-role.kubernetes.io/"+r in n["metadata"]["labels"])
expected=["socrat-0","socrat-1"]+(["socrat-5"] if sys.argv[1]=="after" else [])
checks={"control-plane labels": role("control-plane")==expected, "etcd labels": role("etcd")==["socrat-0","socrat-1","socrat-2"], "original VM105 UID":nodes["socrat-5"]["metadata"]["uid"]=="bb08e55e-04aa-4049-8348-6572b80b771e", "all nodes ready": all(any(c["type"]=="Ready" and c["status"]=="True" for c in n["status"]["conditions"]) for n in nodes.values())}
for k,v in checks.items(): print(k, "OK" if v else "FAIL")
sys.exit(not all(checks.values()))' "${phase}"
