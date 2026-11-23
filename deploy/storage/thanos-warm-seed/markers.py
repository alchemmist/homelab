"""Discover only existing source compaction marks with an independently seeded replacement."""

import json
import re

from delta import remote_objects, source_pod
from start import SeedJob, kube

SOURCE = """
import json
from pathlib import Path
p=Path('/host/var/lib/socrat-thanos');ms={f.parent.name:json.loads(f.read_bytes()) for f in p.glob('*/meta.json')};out={}
for u,a in ms.items():
 f=p/u/'deletion-mark.json'
 if not f.exists():continue
 mark=json.loads(f.read_bytes()); assert mark['id']==u and mark['version']==1
 if mark.get('details')!='source of compacted block':continue
 def covers(v,b):
  return (not (p/v/'deletion-mark.json').exists() and b['minTime']<=a['minTime'] and b['maxTime']>=a['maxTime'] and b['thanos'].get('labels')==a['thanos'].get('labels') and b['thanos'].get('downsample')==a['thanos'].get('downsample') and bool(a['compaction']['sources']) and set(a['compaction']['sources'])<=set(b['compaction']['sources']))
 out[u]=[f.stat().st_size,[v for v,b in ms.items() if covers(v,b)]]
print(json.dumps(out))
"""


def batch(jobs: list[SeedJob]) -> list[tuple[str, int]]:
    objects = remote_objects()
    verified = set()
    for job in jobs:
        if not (job.get("status") or {}).get("succeeded"):
            continue
        log = kube("logs", "job/" + job["metadata"]["name"])
        if "all files verified" in log:
            verified.update(
                re.findall(r"^verified block ([0-9A-Z]{26}) cumulative bytes", log, re.MULTILINE)
            )
    marks = json.loads(kube("exec", source_pod(), "--", "python3", "-c", SOURCE))
    out = []
    for u, (size, replacements) in marks.items():
        if u + "/meta.json" not in objects:
            continue
        choices = [
            v
            for v in replacements
            if v in verified
            and v + "/meta.json" in objects
            and v + "/deletion-mark.json" not in objects
        ]
        assert choices, (u, "no verified replacement")
        print("existing source mark", u, "covered by verified", choices[0])
        out.append((u + "/deletion-mark.json", size))
    return out
