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
from collections.abc import Callable

import yaml

from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.common import command
from ci.quality.public_web import CATALOG, ROOT

CONFIG = ROOT / "deploy/vpn-hardening/moscow-transit.json"
FILE = "/etc/homelab-vpn-transit/user.json"
HOST = "www.alchemmist.xyz"
# HTTP response cap (bytes): the trusted page fits below this, anything larger is not reviewed.
HTTP_MAX_BODY = 131_072
# Socket read chunk (bytes) used by the TLS pump.
TLS_READ_CHUNK = 16384
SSH_CONNECT_TIMEOUT = 4
SSH_COMMAND_TIMEOUT = 8
KUBECTL_TIMEOUT = 9
TLS_CONNECT_TIMEOUT = 5
TLS_DRIVE_SECONDS = 10
COUNTER_SETTLE_SECONDS = 0.3
CONTAINERD_PREFIX = "containerd://"
CRI_CID_PATTERN = "[0-9a-f]{64}"
NATIVE_UNIT = "homelab-vpn-transit-native.service"
LISTENER_CGROUP_PREFIX = "cgroup:/"
# One reading is the socket inode mapped to its acknowledged byte counter.
Readings = dict[int, int]


def require(ok: object) -> None:
    """Fail closed when any reviewed invariant of the witness is missing."""
    if not ok:
        incomplete = "witness incomplete"
        raise ValueError(incomplete)


def remote(cmd: str) -> str:
    """Run one bounded read-only command on the Moscow host."""
    return command(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={SSH_CONNECT_TIMEOUT}",
            "socrat-4",
            cmd,
        ],
        allowed={0},
        timeout=SSH_COMMAND_TIMEOUT,
    ).stdout.strip()


def pod_owner() -> str:
    """Return the CRI scope unit owning the single host-network relay pod."""
    data = entries(
        view(
            json.loads(
                command(
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
                    timeout=KUBECTL_TIMEOUT,
                ).stdout
            )
        )["items"]
    )
    (pod_item,) = data
    pod = view(pod_item)
    spec = view(pod["spec"])
    meta = view(pod["metadata"])
    (status_item,) = entries(view(view(pod["status"])["containerStatuses"]))
    status = view(status_item)
    (container_item,) = entries(view(spec)["containers"])
    container = view(container_item)
    mounted = {"name": "user-config", "mountPath": "/etc/relay/user.json", "readOnly": True}
    mounted_volume = {"name": "user-config", "hostPath": {"path": FILE, "type": "File"}}
    require(
        spec["nodeName"] == "socrat-4"
        and spec["hostNetwork"] is True
        and not meta.get("deletionTimestamp")
        and status["ready"] is True
        and status["name"] == container["name"] == "relay"
        and container["args"] == ["run", "-config", "/etc/relay/user.json"]
        and mounted in entries(container["volumeMounts"])
        and mounted_volume in entries(spec["volumes"])
    )
    cid = plain(status["containerID"]).removeprefix(CONTAINERD_PREFIX)
    require(re.fullmatch(CRI_CID_PATTERN, cid))
    return "cri-containerd-" + cid + ".scope"


def owner() -> tuple[str, str]:
    """Identify the one TLS listener owner: the native unit or the host-network pod."""
    listener = remote(
        "ss -Hlnte sport = :443 | awk '{for(i=1;i<=NF;i++) if($i ~ /^cgroup:/) print $i}'"
    )
    (group,) = listener.splitlines()
    require(group.startswith(LISTENER_CGROUP_PREFIX))
    if group == LISTENER_CGROUP_PREFIX + "system.slice/" + NATIVE_UNIT:
        state = remote("systemctl show " + NATIVE_UNIT + " -p ActiveState -p ExecStart")
        started_argv = "argv[]=/usr/local/libexec/xray-transit run -config " + FILE + " ;"
        require("ActiveState=active" in state.splitlines())
        require(started_argv in state)
        return "native", group
    require(group.endswith("/" + pod_owner()))
    return "host-network-pod", group


def counters(group: str) -> Readings:
    """Project kernel counters on-host. Fixed destination only: no client tuples or payloads."""
    data = remote(
        """ss -HOntei state established dst 10.250.0.2:443 | awk '{g=i=b=""; for(j=1;j<=NF;j++){"""
        """if($j~/^cgroup:/)g=$j;if($j~/^ino:/)i=$j;if($j~/^bytes_acked:/)b=$j} """
        """if(g!="" && i!="" && b!="")print g,i,b}' """
    )
    out: Readings = {}
    for line in data.splitlines():
        cgroup, ino, acked = line.split()
        if cgroup == group:
            out[int(ino.removeprefix("ino:"))] = int(acked.removeprefix("bytes_acked:"))
    return out


def matches(
    before: Readings,
    opened: Readings,
    first: tuple[Readings, int],
    second: tuple[Readings, int],
) -> set[int]:
    """Return inodes whose two exact TLS write deltas landed on one new socket."""
    first_counter, n1 = first
    second_counter, n2 = second
    return {
        i
        for i in opened.keys() - before.keys()
        if i in first_counter
        and i in second_counter
        and first_counter[i] - opened[i] == n1
        and second_counter[i] - first_counter[i] == n2
    }


def exchange(ip: str, group: str) -> int:
    """Open the reviewed TLS flow and count matching per-socket write deltas."""
    before = counters(group)
    incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
    ctx = ssl.create_default_context()
    tls = ctx.wrap_bio(incoming, outgoing, server_hostname=HOST)
    with socket.create_connection((ip, 443), timeout=TLS_CONNECT_TIMEOUT) as raw:

        def flush() -> int:
            data = outgoing.read()
            raw.sendall(data)
            return len(data)

        def drive(fn: Callable[[], bytes | None]) -> bytes | None:
            while True:
                require(time.monotonic() < deadline)
                try:
                    result = fn()
                except ssl.SSLWantReadError:
                    flush()
                    data = raw.recv(TLS_READ_CHUNK)
                    require(data)
                    incoming.write(data)
                else:
                    flush()
                    return result

        deadline = time.monotonic() + TLS_DRIVE_SECONDS
        drive(tls.do_handshake)
        time.sleep(COUNTER_SETTLE_SECONDS)
        opened = counters(group)

        def fragment(data: bytes) -> tuple[int, Readings]:
            require(tls.write(data) == len(data))
            n = flush()
            time.sleep(COUNTER_SETTLE_SECONDS)
            return n, counters(group)

        n1, first = fragment(b"GET / HTTP/1.1\r\nHost: " + HOST.encode() + b"\r\n")
        n2, second = fragment(b"Accept-Encoding: identity\r\nConnection: close\r\n")
        require(n1 != n2)
        tls.write(b"\r\n")
        flush()
        deadline = time.monotonic() + TLS_DRIVE_SECONDS
        body = bytearray()
        while len(body) < HTTP_MAX_BODY:
            part = drive(lambda: tls.read(TLS_READ_CHUNK))
            if part:
                body.extend(part)
            else:
                break
        hdr, sep, page = body.partition(b"\r\n\r\n")
        trusted_title = b"<title>Personal blog of Anton Grishin</title>"
        require(
            sep
            and hdr.startswith(b"HTTP/1.1 200 ")
            and len(body) < HTTP_MAX_BODY
            and trusted_title in page
        )
    return len(matches(before, opened, (first, n1), (second, n2)))


def run() -> dict[str, object]:
    """Witness the two reviewed exchanges and return the exact outcome record."""
    config = CONFIG.read_bytes()
    digest = hashlib.sha256(config).hexdigest()
    replicas = view(view(yaml.safe_load(CATALOG.read_text()))["replicas"])
    ip, control = (
        str(ipaddress.IPv4Address(view(replicas[name])["publicIP"])) for name in ("moscow", "home")
    )
    require(ip != control)
    w = owner()

    def check() -> None:
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
    except (
        ValueError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        http.client.HTTPException,
    ):
        print('{"witness":"incomplete"}')
        raise SystemExit(1) from None
