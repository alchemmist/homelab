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

from ci.quality.closed_root_backend import servers
from ci.quality.schoolbot_entry_health import healthy

base = ["kubectl", "--context=Socrat", "--request-timeout=12s"]
ns = "public-health-staging"
sel = "app.kubernetes.io/instance=schoolbot,app.kubernetes.io/name=schoolbot"
sites = {"home": "socrat-0", "nl": "socrat-2", "moscow": "socrat-4"}


def get(ns, *args):
    return json.loads(sp.check_output([*base, "-n", ns, "get", *args, "-o", "json"], timeout=16))


def discovery():
    svc = get("schoolbot", "svc", "schoolbot")
    if not (
        svc["spec"]["selector"] == dict((x.split("=") for x in sel.split(",")))
        and svc["spec"]["ports"]
        == [{"name": "http", "protocol": "TCP", "port": 80, "targetPort": 8000}]
    ):
        raise ValueError("unexpected Schoolbot path topology; discard this sample set")
    ip = IPv4Address(svc["spec"]["clusterIP"])
    if not (ip in IPv4Network("10.43.0.0/16")):
        raise ValueError("unexpected Schoolbot path topology; discard this sample set")
    ps = get("schoolbot", "pods", "-l", sel)["items"]
    eps = servers(
        svc,
        get("schoolbot", "endpointslice", "-l", "kubernetes.io/service-name=schoolbot")["items"],
        ps,
        expected=("schoolbot", "schoolbot", 80),
        pod_network=IPv4Network("10.42.0.0/16"),
    )
    if not (len(eps) == 1):
        raise ValueError("unexpected Schoolbot path topology; discard this sample set")
    endpoint = eps[0]["url"].split("/")[2].split(":")
    ep = next(p for p in ps if p["status"].get("podIP") == endpoint[0])
    pods = get(ns, "pods", "-l", "app=closed-health")["items"]
    if not (len(pods) == 3):
        raise ValueError("unexpected Schoolbot path topology; discard this sample set")
    src = {
        p["metadata"]["labels"]["entrance"]: (p["metadata"]["name"], p["metadata"]["uid"])
        for p in pods
        if p["spec"]["nodeName"] == sites[p["metadata"]["labels"]["entrance"]]
        and not p["metadata"].get("deletionTimestamp")
        and p["status"]["phase"] == "Running"
        and not p["spec"].get("hostNetwork")
    }
    if not (set(src) == set(sites)):
        raise ValueError("unexpected Schoolbot path topology; discard this sample set")
    return (
        src,
        {
            "listener": ["127.0.0.1", "8181"],
            "fqdn": ["schoolbot.schoolbot.svc.cluster.local", "80"],
            "vip": [str(ip), "80"],
            "pod": endpoint,
        },
        (svc["metadata"]["uid"], ep["metadata"]["uid"], ep["spec"]["nodeName"]),
    )


shell = """{ printf 'GET /api/health HTTP/1.0\\r\\nHost: inform.sch1357.ru\\r\\nConnection: close\\r\\n\\r\\n'; sleep 6; } | timeout 6 nc "$1" "$2" | head -c 8193"""


def classify(raw):
    if not raw:
        return "no-http-response"
    head, sep, body = raw.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = lines[0].split()
    hdr = {k.lower(): v.strip() for k, _, v in (x.partition(b":") for x in lines[1:])}
    if (
        len(status) < 2
        or status[0] not in {b"HTTP/1.0", b"HTTP/1.1"}
        or len(status[1]) != 3
        or not status[1].isdigit()
        or len(hdr) != len(lines) - 1
        or b"transfer-encoding" in hdr
    ):
        return "invalid-http"
    code = int(status[1])
    if not sep or len(raw) > 8192:
        return "incomplete"
    if code != 200:
        return "http-" + str(code)
    return (
        "healthy"
        if hdr.get(b"content-length") == str(len(body)).encode()
        and healthy(code, hdr.get(b"content-type", b"").decode("ascii", errors="replace"), body)
        else "invalid-health"
    )


def read(key, src, targets):
    site, path = key
    try:
        r = sp.run(
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
            stdout=sp.PIPE,
            stderr=sp.DEVNULL,
            timeout=14,
        )
    except sp.TimeoutExpired:
        return key, "exec-timeout"
    if r.returncode:
        return key, "exec-error"
    return key, classify(r.stdout)


def main():
    src, targets, identity = discovery()
    pairs = [(s, t) for s in sites for t in targets]
    counts = collections.defaultdict(collections.Counter)
    start = time.monotonic()
    for i in range(12):
        with concurrent.futures.ThreadPoolExecutor(12) as ex:
            for key, result in ex.map(lambda key: read(key, src, targets), pairs):
                counts[key][result] += 1
                if result != "healthy":
                    print("round", i + 1, *key, result, flush=True)
        if not (discovery() == (src, targets, identity)):
            raise ValueError("unexpected Schoolbot path topology; discard this sample set")
    print("seconds", round(time.monotonic() - start), "backend node", identity[-1])
    print(json.dumps({"/".join(k): v for k, v in counts.items()}, indent=1))
    return int(any(set(c) != {"healthy"} for c in counts.values()))


if __name__ == "__main__":
    raise SystemExit(main())
