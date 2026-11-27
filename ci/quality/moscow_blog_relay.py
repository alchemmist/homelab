"""Read-only Moscow TCP/443 www path witness. Never capture traffic or export session bytes."""

import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import time

import yaml

from ci.quality.public_web import CATALOG, ROOT

CONFIG = ROOT / "deploy/vpn-hardening/moscow-transit.json"
FILE = "/etc/homelab-vpn-transit/user.json"
HOST = "www.alchemmist.xyz"


def require(ok):
    if not ok:
        raise ValueError("witness incomplete")


def remote(cmd):
    return subprocess.check_output(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", "socrat-4", cmd],
        text=True,
        timeout=8,
        stderr=subprocess.DEVNULL,
    ).strip()


def pod_owner():
    items = json.loads(
        subprocess.check_output(
            [
                "kubectl",
                "--context=Socrat",
                "--request-timeout=6s",
                "-n",
                "vpn-transit",
                "get",
                "pods",
                "-l",
                "app.kubernetes.io/name=vpn-transit",
                "-o",
                "json",
            ],
            timeout=9,
        )
    )["items"]
    (p,) = items
    s = p["spec"]
    (c,) = s["containers"]
    (cs,) = p["status"]["containerStatuses"]
    require(
        s["nodeName"] == "socrat-4"
        and s["hostNetwork"] is True
        and not p["metadata"].get("deletionTimestamp")
        and cs["ready"] is True
        and cs["name"] == c["name"] == "relay"
        and c["args"] == ["run", "-config", "/etc/relay/user.json"]
        and {"name": "user-config", "mountPath": "/etc/relay/user.json", "readOnly": True}
        in c["volumeMounts"]
        and {"name": "user-config", "hostPath": {"path": FILE, "type": "File"}} in s["volumes"]
    )
    cid = cs["containerID"].removeprefix("containerd://")
    require(re.fullmatch("[0-9a-f]{64}", cid))
    return "cri-containerd-" + cid + ".scope"


def owner():
    listener = remote(
        "ss -Hlnte sport = :443 | awk '{for(i=1;i<=NF;i++) if($i ~ /^cgroup:/) print $i}'"
    )
    (group,) = listener.splitlines()
    require(group.startswith("cgroup:/"))
    unit = "homelab-vpn-transit-native.service"
    if group == "cgroup:/system.slice/" + unit:
        state = remote("systemctl show " + unit + " -p ActiveState -p ExecStart")
        require(
            "ActiveState=active" in state.splitlines()
            and "argv[]=/usr/local/libexec/xray-transit run -config " + FILE + " ;" in state
        )
        return "native", group
    require(group.endswith("/" + pod_owner()))
    return "host-network-pod", group


def counters(group):
    # Fixed destination only. Project kernel counters on-host: no client tuples or payloads.
    data = remote(
        """ss -HOntei state established dst 10.250.0.2:443 | awk '{g=i=b=""; for(j=1;j<=NF;j++){if($j~/^cgroup:/)g=$j;if($j~/^ino:/)i=$j;if($j~/^bytes_acked:/)b=$j} if(g!="" && i!="" && b!="")print g,i,b}' """
    )
    out = {}
    for line in data.splitlines():
        g, i, b = line.split()
        if g == group:
            out[int(i.removeprefix("ino:"))] = int(b.removeprefix("bytes_acked:"))
    return out


def matches(before, opened, first, second, n1, n2):
    return {
        i
        for i in opened.keys() - before.keys()
        if i in first and i in second and first[i] - opened[i] == n1 and second[i] - first[i] == n2
    }


def exchange(ip, group):
    before = counters(group)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    ctx = ssl.create_default_context()
    tls = ctx.wrap_bio(incoming, outgoing, server_hostname=HOST)
    with socket.create_connection((ip, 443), timeout=5) as raw:

        def flush():
            data = outgoing.read()
            raw.sendall(data)
            return len(data)

        def drive(fn):
            while True:
                require(time.monotonic() < deadline)
                try:
                    r = fn()
                    flush()
                    return r
                except ssl.SSLWantReadError:
                    flush()
                    data = raw.recv(16384)
                    require(data)
                    incoming.write(data)

        deadline = time.monotonic() + 10
        drive(tls.do_handshake)
        time.sleep(0.3)
        opened = counters(group)

        def fragment(data):
            require(tls.write(data) == len(data))
            n = flush()
            time.sleep(0.3)
            return n, counters(group)

        n1, first = fragment(b"GET / HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\n")
        n2, second = fragment(b"Accept-Encoding: identity\r\nConnection: close\r\n")
        require(n1 != n2)
        tls.write(b"\r\n")
        flush()
        deadline = time.monotonic() + 10
        body = bytearray()
        while len(body) < 131072:
            part = drive(lambda: tls.read(16384))
            if not part:
                break
            body.extend(part)
        hdr, sep, page = body.partition(b"\r\n\r\n")
        require(
            sep
            and hdr.startswith(b"HTTP/1.1 200 ")
            and len(body) < 131072
            and b"<title>Personal blog of Anton Grishin</title>" in page
        )
    return len(matches(before, opened, first, second, n1, n2))


def run():
    config = CONFIG.read_bytes()
    digest = hashlib.sha256(config).hexdigest()
    reps = yaml.safe_load(CATALOG.read_text())["replicas"]
    ip, control = (str(ipaddress.IPv4Address(reps[s]["publicIP"])) for s in ("moscow", "home"))
    require(ip != control)
    w = owner()

    def check():
        require(
            remote("sha256sum " + FILE).split()[0] == digest
            and "dev wg-socrat src 10.250.0.40" in remote("ip -4 route get 10.250.0.2")
            and owner() == w
        )

    check()
    require(exchange(control, w[1]) == 0)
    check()
    require(exchange(ip, w[1]) == 1)
    check()
    return {
        "homeControlMatchedNoFlow": True,
        "owner": w[0],
        "installedConfigMatchesGit": True,
        "uniqueNewFlowMatchedBothTlsWriteDeltas": True,
        "destination": "NL mesh TCP/443",
        "trustedBlog": True,
    }


if __name__ == "__main__":
    try:
        print(json.dumps(run(), sort_keys=True))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, http.client.HTTPException):
        print('{"witness":"incomplete"}')
        raise SystemExit(1) from None
