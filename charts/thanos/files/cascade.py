"""Plan and apply Thanos block cascades through the compactor."""
import json
import os
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import cast

RAW_RESOLUTION = 0
FIVE_RESOLUTION = 300000
HOUR_RESOLUTION = 3600000
RAW_KEEP_MS = 5 * 86400000
FIVE_KEEP_MS = 30 * 86400000
DISK_FLOOR_BYTES = 40 * 1024**3
FIVE_BYTES_PER_DAY = int(0.35 * 1024**3)
DAY_MS = 86400000


def fully_covered(block, covers):
    """Check that unmarked intervals span the block without a gap."""
    start = block["minTime"]
    end = block["maxTime"]
    if end <= start:
        return True
    intervals = sorted(
        (cover["minTime"], cover["maxTime"])
        for cover in covers
        if not cover.get("deletionMark") and cover["maxTime"] > cover["minTime"]
    )
    cursor = start
    for left, right in intervals:
        if right <= cursor:
            continue
        if left > cursor:
            return False
        cursor = max(cursor, right)
        if cursor >= end:
            return True
    return cursor >= end


def block_bytes(block):
    """Use the recorded size, or estimate 5m bytes from the block duration."""
    if "bytes" in block and block["bytes"] is not None:
        return int(block["bytes"])
    span = max(0, block["maxTime"] - block["minTime"]) / DAY_MS
    return int(span * FIVE_BYTES_PER_DAY)


def selected(blocks):
    """Return ULIDs in stable order for the plan output."""
    return sorted(block["ulid"] for block in blocks)


def _five_source_blocks(
    raw_fives: list[dict[str, object]],
    raw_hours: list[dict[str, object]],
    shelf_five_ids: set[object],
    *,
    five_reachable: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    copy_five: list[dict[str, object]] = []
    mark_five_source: list[dict[str, object]] = []
    if five_reachable:
        for block in raw_fives:
            if block.get("deletionMark") or not fully_covered(block, raw_hours):
                continue
            if block["ulid"] in shelf_five_ids:
                mark_five_source.append(block)
            else:
                copy_five.append(block)
    return copy_five, mark_five_source


def _hour_source_blocks(
    raw_hours: list[dict[str, object]],
    shelf_hour_ids: set[object],
    *,
    hour_reachable: bool,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    copy_hour: list[dict[str, object]] = []
    mark_hour_source: list[dict[str, object]] = []
    if hour_reachable:
        for block in raw_hours:
            if block.get("deletionMark"):
                continue
            if block["ulid"] in shelf_hour_ids:
                mark_hour_source.append(block)
            else:
                copy_hour.append(block)
    return copy_hour, mark_hour_source


def _five_shelf_removals(
    five_blocks: list[dict[str, object]],
    shelf_hours: list[dict[str, object]],
    *,
    hour_reachable: bool,
    now_ms: int,
    disk_free_bytes: int | None,
) -> list[dict[str, object]]:
    chosen: list[dict[str, object]] = []
    if hour_reachable:
        eligible = [
            block
            for block in five_blocks
            if block.get("resolution") == FIVE_RESOLUTION
            and not block.get("deletionMark")
            and fully_covered(block, shelf_hours)
        ]
        aged = [
            block for block in eligible if cast("int", block["maxTime"]) <= now_ms - FIVE_KEEP_MS
        ]
        chosen = list(aged)
        if disk_free_bytes is not None and disk_free_bytes < DISK_FLOOR_BYTES:
            deficit = DISK_FLOOR_BYTES - disk_free_bytes
            freed = sum(block_bytes(block) for block in chosen)
            rest = sorted(
                (block for block in eligible if block not in chosen),
                key=lambda block: (cast("int", block["minTime"]), block["ulid"]),
            )
            for block in rest:
                if freed >= deficit:
                    break
                chosen.append(block)
                freed += block_bytes(block)
    return chosen


def plan(
    raw_blocks, five_blocks, hour_blocks, now_ms, disk_free_bytes, five_reachable, hour_reachable
):
    """Choose copies and deletion marks from the supplied inventories without performing I/O."""
    raw_hours = [block for block in raw_blocks if block.get("resolution") == HOUR_RESOLUTION]
    raw_fives = [block for block in raw_blocks if block.get("resolution") == FIVE_RESOLUTION]
    shelf_five_ids = {block["ulid"] for block in five_blocks}
    shelf_hour_ids = {block["ulid"] for block in hour_blocks}
    shelf_hours = [block for block in hour_blocks if block.get("resolution") == HOUR_RESOLUTION]

    copy_five, mark_five_source = _five_source_blocks(
        raw_fives, raw_hours, shelf_five_ids, five_reachable=five_reachable
    )
    copy_hour, mark_hour_source = _hour_source_blocks(
        raw_hours, shelf_hour_ids, hour_reachable=hour_reachable
    )

    mark_raw = [
        block
        for block in raw_blocks
        if block.get("resolution") == RAW_RESOLUTION
        and not block.get("deletionMark")
        and cast("int", block["maxTime"]) <= now_ms - RAW_KEEP_MS
        and fully_covered(block, raw_fives)
    ]

    mark_five_shelf = _five_shelf_removals(
        five_blocks,
        shelf_hours,
        hour_reachable=hour_reachable,
        now_ms=now_ms,
        disk_free_bytes=disk_free_bytes,
    )

    return {
        "copyFive": selected(copy_five),
        "copyHour": selected(copy_hour),
        "markRaw": selected(mark_raw),
        "markFiveSource": selected(mark_five_source),
        "markHourSource": selected(mark_hour_source),
        "markFiveShelf": selected(mark_five_shelf),
    }


def parse_ls(text):
    """Decode consecutive Thanos metadata objects, including multiline JSON, into block rows."""
    decoder = json.JSONDecoder()
    blocks = []
    index = 0
    length = len(text)
    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            break
        meta, index = decoder.raw_decode(text, index)
        downsample = (meta.get("thanos") or {}).get("downsample") or {}
        blocks.append(
            {
                "ulid": meta["ulid"],
                "minTime": int(meta["minTime"]),
                "maxTime": int(meta["maxTime"]),
                "resolution": int(downsample.get("resolution") or 0),
                "deletionMark": False,
            }
        )
    return blocks


def apply_deletion_marks(blocks, unmarked_ulids):
    """Flag rows in place when their ULIDs are absent from the unmarked listing."""
    unmarked = set(unmarked_ulids)
    for block in blocks:
        block["deletionMark"] = block["ulid"] not in unmarked
    return blocks


def load_plan(payload):
    """Plan from CLI JSON; default missing inventories to empty and reachability flags to false."""
    return plan(
        payload.get("raw") or [],
        payload.get("five") or [],
        payload.get("hour") or [],
        int(payload["nowMs"]),
        payload.get("diskFreeBytes"),
        bool(payload.get("fiveReachable")),
        bool(payload.get("hourReachable")),
    )


def kubernetes_request(method, path, body=None, timeout=30):
    """Send an in-cluster JSON request using the service account token and CA."""
    token = Path("/var/run/secrets/kubernetes.io/serviceaccount/token").read_text().strip()
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    context = ssl.create_default_context(
        cafile="/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    )
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"https://{host}:{port}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/merge-patch+json",
        },
    )
    with urllib.request.urlopen(request, context=context, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw) if raw else {}


def scale_compactor(namespace, name, replicas):
    """Patch the deployment scale; the caller waits separately for replicas to stop."""
    kubernetes_request(
        "PATCH",
        f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}/scale",
        {"spec": {"replicas": replicas}},
    )


def wait_compactor_idle(namespace, name, timeout=180):
    """Wait until desired, current and ready replica counts are all zero, or time out."""
    deadline = time.monotonic() + timeout
    path = f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}"
    while True:
        deployment = kubernetes_request("GET", path)
        spec = deployment.get("spec", {}).get("replicas", 0) or 0
        status = deployment.get("status", {})
        ready = status.get("readyReplicas") or 0
        current = status.get("replicas") or 0
        if spec == 0 and ready == 0 and current == 0:
            return
        if time.monotonic() >= deadline:
            message = "compactor did not scale to zero"
            raise TimeoutError(message)
        time.sleep(2)


def default_runner(argv):
    """Return command stdout, forwarding stderr and raising on a nonzero exit."""
    completed = subprocess.run(
        argv, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        raise subprocess.CalledProcessError(
            completed.returncode, argv, completed.stdout, completed.stderr
        )
    return completed.stdout


def disk_free_bytes(prometheus_url):
    """Return available bytes from a single usable query sample, or None if unknown."""
    query = (
        'max(node_filesystem_avail_bytes{job="node-exporter",mountpoint="/",fstype=~"ext4|xfs"}'
        ' * on(instance) group_left(nodename) node_uname_info{job="node-exporter",nodename="socrat-1"})'
    )
    if os.environ.get("FIVE_SHARED") == "1":
        bucket = 'socrat_five_bucket_available_bytes{backing_node="socrat-0"}'
        query = f"{bucket} and (time() - timestamp({bucket}) < 120)"
    url = prometheus_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
        result = payload.get("data", {}).get("result") or []
        if payload.get("status") != "success" or len(result) != 1:
            return None
        available = int(float(result[0]["value"][1]))
        return available if available >= 0 else None
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, OverflowError, IndexError, TypeError):
        return None


def list_blocks(config, thanos_bin, runner):
    """Compare full and unmarked bucket listings to recover deletion status."""
    common = ["--objstore.config-file=" + config, "-o", "json", "--timeout=2m", "--log.level=error"]
    listed = runner([thanos_bin, "tools", "bucket", "ls", *common])
    unmarked = runner([thanos_bin, "tools", "bucket", "ls", *common, "--exclude-delete"])
    blocks = parse_ls(listed)
    apply_deletion_marks(blocks, [block["ulid"] for block in parse_ls(unmarked)])
    return blocks


def command_code(result, label):
    """Accept text output or None from a runner; reject other results as command failures."""
    if isinstance(result, int) and result != 0:
        raise subprocess.CalledProcessError(result, label)
    if result is None:
        return
    if isinstance(result, str):
        return
    raise subprocess.CalledProcessError(1, label)


def mark_blocks(ulids, config, thanos_bin, runner):
    """Request Thanos deletion marks without removing block objects directly."""
    for ulid in ulids:
        command_code(
            runner(
                [
                    thanos_bin,
                    "tools",
                    "bucket",
                    "mark",
                    "--id=" + ulid,
                    "--marker=deletion-mark.json",
                    "--details=cascade",
                    "--objstore.config-file=" + config,
                    "--log.level=error",
                ]
            ),
            ulid,
        )


def shelf_open(url, token, method, data=None, timeout=120):
    """Open a bearer-authenticated shelf request, supplying the length for file uploads."""
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if hasattr(data, "read"):
        headers["Content-Length"] = str(os.fstat(data.fileno()).st_size)
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_shelf(base, token):
    """Return the inventory and a reachability flag so an empty shelf differs from a failed read."""
    if not base or not token:
        return [], False
    try:
        with shelf_open(base.rstrip("/") + "/v1/blocks", token, "GET") as response:
            payload = json.load(response)
        if not isinstance(payload, list):
            return [], False
        return payload, True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return [], False


def upload_block(base, token, directory, ulid):
    """Stream the local block into shelf staging, then commit after all files were sent."""
    root = os.path.join(directory, ulid)
    if not os.path.isdir(root):
        raise FileNotFoundError(ulid)
    prefix = base.rstrip("/") + "/v1/blocks/" + ulid
    with shelf_open(prefix, token, "POST", b"") as response:
        response.read()
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            full = os.path.join(dirpath, filename)
            relative = os.path.relpath(full, root).replace(os.sep, "/")
            with (
                open(full, "rb") as handle,
                shelf_open(
                    prefix + "/files/" + relative, token, "PUT", handle, timeout=600
                ) as response,
            ):
                response.read()
    with shelf_open(prefix + "/commit", token, "POST", b"") as response:
        response.read()


def mark_shelf(base, token, ulids):
    """Post deletion markers for the selected shelf blocks without removing their data."""
    for ulid in ulids:
        with shelf_open(
            base.rstrip("/") + "/v1/blocks/" + ulid + "/deletion-mark", token, "POST", b"{}"
        ) as response:
            response.read()


def read_token():
    """Read the shelf bearer token, or return an empty string if no token file is configured."""
    path = os.environ.get("SHELF_TOKEN_FILE", "")
    if not path:
        return ""
    return Path(path).read_text().strip()


def execute():
    """Pause compaction, copy blocks, then relist and replan before marking any source."""
    thanos_bin = os.environ.get("THANOS_BIN", "/usr/local/bin/thanos")
    namespace = os.environ.get("NAMESPACE", "cattle-monitoring-system")
    compactor = os.environ.get("COMPACTOR_NAME", "thanos-compactor")
    raw_config = os.environ["OBJSTORE_RAW"]
    raw_directory = os.environ.get("RAW_DIRECTORY", "/var/lib/socrat-thanos")
    five_url = os.environ.get("SHELF_FIVE_URL", "")
    hour_url = os.environ.get("SHELF_HOUR_URL", "")
    token = read_token()
    prometheus_url = os.environ["PROMETHEUS_URL"]

    scale_compactor(namespace, compactor, 0)
    try:
        wait_compactor_idle(namespace, compactor)
        raw_blocks = list_blocks(raw_config, thanos_bin, default_runner)
        five_blocks, five_reachable = fetch_shelf(five_url, token)
        hour_blocks, hour_reachable = fetch_shelf(hour_url, token)
        current = plan(
            raw_blocks,
            five_blocks,
            hour_blocks,
            int(time.time() * 1000),
            disk_free_bytes(prometheus_url),
            five_reachable,
            hour_reachable,
        )
        if five_reachable:
            for ulid in current["copyFive"]:
                upload_block(five_url, token, raw_directory, ulid)
        if hour_reachable:
            for ulid in current["copyHour"]:
                upload_block(hour_url, token, raw_directory, ulid)
        five_blocks, five_reachable = fetch_shelf(five_url, token)
        hour_blocks, hour_reachable = fetch_shelf(hour_url, token)
        raw_blocks = list_blocks(raw_config, thanos_bin, default_runner)
        confirmed = plan(
            raw_blocks,
            five_blocks,
            hour_blocks,
            int(time.time() * 1000),
            disk_free_bytes(prometheus_url),
            five_reachable,
            hour_reachable,
        )
        mark_blocks(
            confirmed["markRaw"] + confirmed["markFiveSource"] + confirmed["markHourSource"],
            raw_config,
            thanos_bin,
            default_runner,
        )
        if five_reachable:
            mark_shelf(five_url, token, confirmed["markFiveShelf"])
    finally:
        scale_compactor(namespace, compactor, 1)
    return 0


def main(argv=None):
    """Print a plan from stdin or run the cascade, translating stop signals to exits."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("plan", "run"):
        print("usage: cascade.py plan|run", file=sys.stderr)
        return 2
    if argv[0] == "plan":
        json.dump(load_plan(json.load(sys.stdin)), sys.stdout)
        sys.stdout.write("\n")
        return 0

    def stop(signum, frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    return execute()


if __name__ == "__main__":
    sys.exit(main())
