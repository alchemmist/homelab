"""Read-only live block census. Not a backup or a cutover manifest."""

import json
import subprocess

NAMESPACE = "cattle-monitoring-system"
CENSUS = """
import collections, hashlib, json, os, sys
from pathlib import Path
p = Path(sys.argv[1] or os.environ['SHELF_DIRECTORY'])
groups = collections.defaultdict(list)
for f in sorted(p.glob('*/meta.json')):
    if f.parent.name.startswith('.'): continue
    m = json.loads(f.read_bytes()); assert m['ulid'] == f.parent.name
    sz = (f.parent/'index').stat().st_size + sum(x.stat().st_size for x in (f.parent/'chunks').iterdir())
    r = m.get('thanos',{}).get('downsample',{}).get('resolution',0)
    groups[(r,(f.parent/'deletion-mark.json').exists())].append((m['ulid'],m['minTime'],m['maxTime'],sz))
for (r,marked), rows in sorted(groups.items()):
    print(json.dumps(dict(resolution_ms=r,marked=marked,count=len(rows),bytes=sum(x[3] for x in rows),min_ms=min(x[1] for x in rows),max_ms=max(x[2] for x in rows),inventory_sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())))
"""


def main() -> None:
    for tier, app, node, path in [
        ("workshop", "thanos-disk", "socrat-0", "/host/var/lib/socrat-thanos"),
        ("5m", "thanos-shelf-5m", None, ""),
        ("1h", "thanos-disk", "socrat-3", "/host/var/lib/socrat-thanos-1h"),
    ]:
        cmd = ["kubectl", "--request-timeout=15s", "-n", NAMESPACE]
        args = ["get", "pod", "-l", "app=" + app, "-o", "json"]
        pods = json.loads(subprocess.check_output(cmd + args))["items"]
        candidates = [
            x
            for x in pods
            if x["status"]["phase"] == "Running"
            and not x["metadata"].get("deletionTimestamp")
            and (not node or x["spec"]["nodeName"] == node)
        ]
        assert len(candidates) == 1
        out = subprocess.check_output(
            [*cmd, "exec", candidates[0]["metadata"]["name"], "--", "python3", "-c", CENSUS, path],
            text=True,
        )
        rows = [json.loads(x) for x in out.splitlines()]
        assert rows
        print(tier, json.dumps(rows), flush=True)


if __name__ == "__main__":
    main()
