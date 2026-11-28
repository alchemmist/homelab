"""Sample four fixed anonymous Schoolbot paths from the permanent closed listeners.

Operator-only diagnostic: Kubernetes exec is required. No cluster mutations.
Run with python -m ci.quality.closed_schoolbot_samples; exit 1 on any missed sample.
"""

import collections
import concurrent.futures
import json
import subprocess as sp
import time
from ipaddress import IPv4Address, IPv4Network

from ci.quality.closed_root_backend import Obj, entries, plain, servers, view
from ci.quality.common import command
from ci.quality.schoolbot_entry_health import healthy

base = ["kubectl", "--context=Socrat", "--request-timeout=12s"]
ns = "public-health-staging"
sel = "app.kubernetes.io/instance=schoolbot,app.kubernetes.io/name=schoolbot"
sites = {"home": "socrat-0", "nl": "socrat-2", "moscow": "socrat-4"}
TOPOLOGY = "unexpected Schoolbot path topology; discard this sample set"
POD_COUNT = 3
BODY_LIMIT = 8192
HTTP_OK = 200
MIN_HTTP_STATUS_WORDS = 2
STATUS_CODE_WIDTH = 3


def get(namespace: str, *args: str) -> Obj:
    """Read one reviewed object graph from the live cluster as JSON."""
    argv = [*base, "-n", namespace, "get", *args, "-o", "json"]
    document: Obj = json.loads(command(argv, timeout=16).stdout)
    return document


Source = dict[str, tuple[str, str]]
Targets = dict[str, list[str]]
Identity = tuple[str, str, str]


def discovery() -> tuple[Source, Targets, Identity]:
    """Resolve the fixed Schoolbot VIP plus the three closed listener pods."""
    svc = get("schoolbot", "svc", "schoolbot")
    spec = view(svc["spec"])
    if not (
        spec["selector"] == dict(x.split("=") for x in sel.split(","))
        and spec["ports"] == [{"name": "http", "protocol": "TCP", "port": 80, "targetPort": 8000}]
    ):
        raise ValueError(TOPOLOGY)
    ip = IPv4Address(plain(spec["clusterIP"]))
    if ip not in IPv4Network("10.43.0.0/16"):
        raise ValueError(TOPOLOGY)
    ps = entries(get("schoolbot", "pods", "-l", sel)["items"])
    slices = entries(
        get("schoolbot", "endpointslice", "-l", "kubernetes.io/service-name=schoolbot")["items"]
    )
    pods = [view(pod) for pod in ps]
    eps = servers(
        svc,
        [view(item) for item in slices],
        pods,
        expected=("schoolbot", "schoolbot", 80),
        pod_network=IPv4Network("10.42.0.0/16"),
    )
    if len(eps) != 1:
        raise ValueError(TOPOLOGY)
    endpoint = plain(eps[0]["url"]).split("/")[2].split(":")
    ep = view(next(p for p in pods if view(p["status"]).get("podIP") == endpoint[0]))
    listener_pods = [
        view(pod) for pod in entries(get(ns, "pods", "-l", "app=closed-health")["items"])
    ]
    if len(listener_pods) != POD_COUNT:
        raise ValueError(TOPOLOGY)
    src: Source = {
        plain(view(view(pod["metadata"])["labels"])["entrance"]): (
            plain(view(pod["metadata"])["name"]),
            plain(view(pod["metadata"])["uid"]),
        )
        for pod in listener_pods
        if plain(view(pod["spec"])["nodeName"])
        == sites[plain(view(view(pod["metadata"])["labels"])["entrance"])]
        and not view(pod["metadata"]).get("deletionTimestamp")
        and plain(view(pod["status"])["phase"]) == "Running"
        and not view(pod["spec"]).get("hostNetwork")
    }
    if set(src) != set(sites):
        raise ValueError(TOPOLOGY)
    targets: Targets = {
        "listener": ["127.0.0.1", "8181"],
        "fqdn": ["schoolbot.schoolbot.svc.cluster.local", "80"],
        "vip": [str(ip), "80"],
        "pod": endpoint,
    }
    identity: Identity = (
        plain(view(svc["metadata"])["uid"]),
        plain(view(ep["metadata"])["uid"]),
        plain(view(ep["spec"])["nodeName"]),
    )
    return src, targets, identity


shell = (
    """{ printf 'GET /api/health HTTP/1.0\\r\\n"""
    """Host: inform.sch1357.ru\\r\\n"""
    """Connection: close\\r\\n\\r\\n'; sleep 6; } | timeout 6 nc "$1" "$2" | head -c 8193"""
)


def classify(raw: bytes) -> str:
    """Classify one raw HTTP exchange as a printable outcome label."""
    if not raw:
        return "no-http-response"
    head, sep, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = lines[0].split()
    hdr = {k.lower(): v.strip() for k, _, v in (x.partition(b":") for x in lines[1:])}
    if (
        len(status) < MIN_HTTP_STATUS_WORDS
        or status[0] not in {b"HTTP/1.0", b"HTTP/1.1"}
        or len(status[1]) != STATUS_CODE_WIDTH
        or not status[1].isdigit()
        or len(hdr) != len(lines) - 1
        or b"transfer-encoding" in hdr
    ):
        return "invalid-http"
    code = int(status[1])
    if not sep or len(raw) > BODY_LIMIT:
        return "incomplete"
    if code != HTTP_OK:
        return "http-" + str(code)
    return (
        "healthy"
        if hdr.get(b"content-length") == str(len(body)).encode()
        and healthy(code, hdr.get(b"content-type", b"").decode("ascii", errors="replace"), body)
        else "invalid-health"
    )


def read(
    key: tuple[str, str],
    src: Source,
    targets: Targets,
) -> tuple[tuple[str, str], str]:
    """Probe one (entrance, target path) pair from a listener pod; keep errors opaque."""
    site, path = key
    try:
        process = command(
            [
                *base,
                "-n",
                ns,
                "exec",
                src[site][0],
                "-c",
                "listener",
                "--",
                "sh",
                "-c",
                shell,
                "probe",
                *targets[path],
            ],
            allowed=tuple(range(256)),
            timeout=14,
        )
    except sp.TimeoutExpired:
        return key, "exec-timeout"
    if process.returncode:
        return key, "exec-error"
    return key, classify(process.stdout.encode("latin-1"))


def main() -> int:
    """Run the fixed sample rounds; exit 1 when any sample misses its shape."""
    src, targets, identity = discovery()
    pairs = [(entrance, path) for entrance in sites for path in targets]
    counts: dict[tuple[str, str], collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    start = time.monotonic()
    for i in range(12):
        with concurrent.futures.ThreadPoolExecutor(12) as ex:
            for key, result in ex.map(lambda key: read(key, src, targets), pairs):
                counts[key][result] += 1
                if result != "healthy":
                    print("round", i + 1, *key, result, flush=True)
        if discovery() != (src, targets, identity):
            raise ValueError(TOPOLOGY)
    print("seconds", round(time.monotonic() - start), "backend node", identity[-1])
    print(json.dumps({"/".join(k): v for k, v in counts.items()}, indent=1))
    return int(any(set(c) != {"healthy"} for c in counts.values()))


if __name__ == "__main__":
    raise SystemExit(main())
