"""Read-only workshop comparison. Report mismatches; never delete or repair objects."""

import json
import xml.etree.ElementTree as ET
from typing import cast
from urllib.parse import urlencode

from start import INVENTORY, Resource, kube


def remote_objects() -> dict[str, int]:
    obj = {}
    token: str | None = None
    while True:
        params = {"list-type": "2"}
        if token:
            params["continuation-token"] = token
        data = kube(
            "exec",
            "deploy/thanos-warm-api",
            "-c",
            "rustfs",
            "--",
            "sh",
            "-ec",
            'curl -fsS --cacert /tls/ca.crt --resolve thanos-warm-api:9000:127.0.0.1 --aws-sigv4 aws:amz:us-east-1:s3 -u "$RUSTFS_ACCESS_KEY:$RUSTFS_SECRET_KEY" "$1"',
            "list",
            "https://thanos-warm-api:9000/thanos-workshop?" + urlencode(params),
        )
        root = ET.fromstring(data)
        for entry in root.findall("{*}Contents"):
            # RustFS ListObjectsV2 supplies Key and Size for every Contents entry.
            key = cast("str", entry.findtext("{*}Key"))
            assert key not in obj
            obj[key] = int(cast("str", entry.findtext("{*}Size")))
        if root.findtext("{*}IsTruncated") == "false":
            return obj
        nxt = root.findtext("{*}NextContinuationToken")
        assert nxt and nxt != token
        token = nxt


def source_pod() -> str:
    pods: list[Resource] = json.loads(
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
    return pods[0]["metadata"]["name"]


if __name__ == "__main__":
    pod = source_pod()
    args = ("exec", pod, "--", "python3", "-c")
    src = dict(json.loads(kube(*args, INVENTORY)))
    dst = remote_objects()
    markers = json.loads(
        kube(
            *args,
            "import json;from pathlib import Path as P;p=P('/host/var/lib/socrat-thanos');print(json.dumps([str(f.relative_to(p)) for f in p.rglob('*mark.json')]))",
        )
    )

    inactive = {k.split("/")[0] for k in dst if k.endswith("/deletion-mark.json")}
    live_dst = {k: n for k, n in dst.items() if k.split("/")[0] not in inactive}

    def summary(keys: set[str]) -> dict[str, int | list[str]]:
        return {"objects": len(keys), "blocks": sorted({k.split("/")[0] for k in keys})}

    print(
        json.dumps(
            {
                "source_active_files": len(src),
                "s3_files": len(dst),
                "missing_on_s3": summary(src.keys() - live_dst.keys()),
                "missing_bytes": sum(src[k] for k in src.keys() - live_dst.keys()),
                "extra_active_on_s3": summary(live_dst.keys() - src.keys()),
                "s3_marked_blocks": sorted(inactive),
                "different_size": sorted(
                    k for k in src.keys() & dst.keys() if src[k] != dst[k]
                ),
                "source_markers": markers,
            },
            indent=2,
        )
    )
