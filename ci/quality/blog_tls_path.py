"""Compare anonymous www TLS resumption domains; never serialize session material.

A positive cross-resume proves shared resumption state, not physical process identity.
No HTTP auth, Secret reads, ticket export, cluster mutations or public DNS changes.
"""

import contextlib
import http.client
import ipaddress
import json
import select
import socket
import ssl
import subprocess
import time
from collections.abc import Iterable

import yaml

from ci.quality.closed_root_backend import entries, plain, view
from ci.quality.common import command
from ci.quality.public_web import CATALOG

HOST = "www.alchemmist.xyz"
HTTP_OK = 200
BODY_LIMIT = 131072
READY_STATUS = "True"
NODE_SCOPE_PREFIX = "node/"
POD_SCOPE_PREFIX = "pod/"
KUBE = ["kubectl", "--context=Socrat", "--request-timeout=8s"]
# The fixed reviewed listener bodies and ports these probes are allowed to see.
BLOG_TITLE = b"<title>Personal blog of Anton Grishin</title>"
FORWARD_PREFIX = "Forwarding from 127.0.0.1:"
SSH_FORWARD_TARGET = "127.0.0.1:{port}:127.0.0.1:443"
REQUEST = (
    f"GET / HTTP/1.1\r\nHost: {HOST}\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
).encode()
MSG_SCOPE_CHANGED = "socket scope changed"
MSG_FLEET_CHANGED = "candidate fleet changed"
MSG_FLEET_INCOMPLETE = "incomplete candidate fleet"
MSG_FORWARD_FAILED = "NL loopback forward failed"
MSG_FORWARD_TIMEOUT = "forward timeout"
MSG_FORWARD_PARSE = "forward failed"
MSG_BLOG_NOT_MATCHED = "blog not matched"
MSG_KUBE_PROCESS = "port-forward process must keep its output pipe"
MSG_SESSION_STATE = "a closed TLS session cannot be re-checked"

# Fixed reviewed Pod listener targets (not a general-purpose forwarder).
GROUPS = (
    ("kube-system", "app.kubernetes.io/name=traefik", 8443, {"socrat-0", "socrat-1"}),
    ("traefik-edge", "app.kubernetes.io/instance=traefik-edge", 443, {"socrat-2"}),
    ("traefik-moscow", "app.kubernetes.io/name=traefik-moscow", 8443, {"socrat-4"}),
)


def inventory() -> dict[str, tuple[str, str, str, int]]:
    """Snapshot every reviewed listener candidate: scope, name, uid and port."""
    rows: dict[str, tuple[str, str, str, int]] = {}
    for ns, label, port, nodes in GROUPS:
        listing = command([*KUBE, "-n", ns, "get", "pods", "-l", label, "-o", "json"], timeout=12)
        document = view(json.loads(listing.stdout))
        seen: set[str] = set()
        for p in entries(document["items"]):
            item = view(p)
            spec = view(item["spec"])
            metadata = view(item["metadata"])
            status = view(item["status"])
            ready = [
                view(c)["status"]
                for c in entries(status["conditions"])
                if plain(view(c)["type"]) == "Ready"
            ]
            host_network = ns == "traefik-edge"
            if bool(spec.get("hostNetwork")) != host_network:
                raise ValueError(MSG_SCOPE_CHANGED)
            node = plain(spec["nodeName"])
            key = (NODE_SCOPE_PREFIX if host_network else POD_SCOPE_PREFIX) + node
            if (
                node not in nodes
                or key in rows
                or metadata.get("deletionTimestamp")
                or ready != [READY_STATUS]
            ):
                raise ValueError(MSG_FLEET_CHANGED)
            rows[key] = (ns, plain(metadata["name"]), plain(metadata["uid"]), port)
            seen.add(node)
        if seen != nodes:
            raise ValueError(MSG_FLEET_INCOMPLETE)
    return rows


def _loopback_forward(stack: contextlib.ExitStack) -> tuple[str, int]:
    """Bind a free loopback port so the reviewed ssh tunnel can target it."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        local = sock.getsockname()[1]
    tunnel = ["ssh"]
    tunnel += ["-o", "BatchMode=yes"]
    tunnel += ["-o", "ExitOnForwardFailure=yes"]
    tunnel += ["-o", "ConnectTimeout=5"]
    tunnel += ["-o", "ControlMaster=no"]
    tunnel += ["-o", "ControlPath=none"]
    tunnel += ["-N", "-L", SSH_FORWARD_TARGET.format(port=local), "socrat-2"]
    # S603/S607: a live reviewed ssh forwarder operand (no partial-path shell),
    # mirroring the audited forwarders this probe exists to exercise.
    proc = subprocess.Popen(tunnel, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stack.callback(proc.wait, 5)
    stack.callback(proc.terminate)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with socket.create_connection(("127.0.0.1", local), timeout=0.3):
                pass
        except OSError:
            time.sleep(0.1)
        else:
            return ("127.0.0.1", local)
    raise ValueError(MSG_FORWARD_FAILED)


def _pod_forward(stack: contextlib.ExitStack, row: tuple[str, str, str, int]) -> tuple[str, int]:
    """Open kubectl port-forward for one reviewed Pod listener and verify its banner."""
    ns, name, _, port = row
    forwarded = [
        *KUBE,
        "-n",
        ns,
        "port-forward",
        "--address",
        "127.0.0.1",
        POD_SCOPE_PREFIX + name,
        ":" + str(port),
    ]
    # S603: the reviewed kubectl forward operand, same audited gate as inventory().
    proc = subprocess.Popen(forwarded, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    stack.callback(proc.wait, 5)
    stack.callback(proc.terminate)
    if proc.stdout is None:
        raise RuntimeError(MSG_KUBE_PROCESS)
    stream = proc.stdout
    if select.select([stream], [], [], 10)[0]:
        prefix, sep, end = stream.readline().decode().strip().partition(" -> ")
        if sep and end == str(port) and prefix.startswith(FORWARD_PREFIX):
            return ("127.0.0.1", int(prefix.rsplit(":", 1)[1]))
    raise ValueError(MSG_FORWARD_TIMEOUT)


def forward(stack: contextlib.ExitStack, row: tuple[str, str, str, int]) -> tuple[str, int]:
    """Forward to one reviewed listener edge, node-loopback or Pod port-forward."""
    ns = row[0]
    if ns == "traefik-edge":
        # hostNetwork and UDP-only declared containerPort 443: do not pretend
        # this is a Pod-isolated TLS socket. Forward to the existing node loopback.
        return _loopback_forward(stack)
    return _pod_forward(stack, row)


def exchange(
    ctx: ssl.SSLContext,
    target: tuple[str, int],
    session: ssl.SSLSession | None = None,
) -> tuple[ssl.SSLSession, bool]:
    """Run one TLS visit and return the observed session plus its resumption state."""
    with (
        socket.create_connection(target, timeout=5) as raw,
        ctx.wrap_socket(raw, server_hostname=HOST, session=session) as tls,
    ):
        tls.sendall(REQUEST)
        response = http.client.HTTPResponse(tls)
        response.begin()
        body = response.read(BODY_LIMIT + 1)
        if response.status != HTTP_OK or len(body) > BODY_LIMIT or BLOG_TITLE not in body:
            raise ValueError(MSG_BLOG_NOT_MATCHED)
        session = tls.session
        session_reused_flag = tls.session_reused
        if session is None or session_reused_flag is None:
            raise RuntimeError(MSG_SESSION_STATE)
        return session, session_reused_flag


def sample(source: tuple[str, int], peers: dict[str, tuple[str, int]]) -> dict[str, str]:
    """Probe one listener with a fresh ticket, then check every other listener."""
    ctx = ssl.create_default_context()
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ticket, reused = exchange(ctx, source)
    if reused or not ticket.has_ticket:
        return {"control": "no-fresh-ticket"}
    result: dict[str, str] = {}
    for name, peer in peers.items():
        try:
            result[name] = "resumed" if exchange(ctx, peer, ticket)[1] else "full-handshake"
        except (OSError, ValueError, http.client.HTTPException):
            result[name] = "unverified"
    return result


def correlated(
    samples: dict[str, dict[str, str]],
    candidates: Iterable[str],
    entrances: Iterable[str],
) -> dict[str, str]:
    """Demand positive self and negative cross controls; ambiguous is not attribution."""
    names = list(candidates)
    if not all(
        samples[src].get(dst) == ("resumed" if src == dst else "full-handshake")
        for src in names
        for dst in names
    ):
        return {}
    result: dict[str, str] = {}
    for src in entrances:
        row = samples[src]
        hits = [dst for dst in names if row.get(dst) == "resumed"]
        if len(hits) == 1 and all(row.get(dst) in {"resumed", "full-handshake"} for dst in names):
            result[src] = hits[0]
    return result


def main() -> int:
    """Compare resumption domains across all reviewed listener and public edges."""
    catalog = yaml.safe_load(CATALOG.read_text())
    sites = view(view(catalog)["replicas"])
    public = {
        "public/" + s: (str(ipaddress.IPv4Address(plain(view(sites[s])["publicIP"]))), 443)
        for s in ("home", "nl", "moscow")
    }
    rows = inventory()
    with contextlib.ExitStack() as stack:
        pods = {n: forward(stack, row) for n, row in rows.items()}
        samples: dict[str, dict[str, str]] = {}
        for name, source in {**pods, **public}.items():
            try:
                samples[name] = sample(source, {**pods, name: source})
            except (ValueError, OSError, http.client.HTTPException):
                samples[name] = {"control": "source-unverified"}
        if inventory() != rows:
            raise ValueError(MSG_FLEET_CHANGED)
    domains = correlated(samples, pods, public)
    print(json.dumps({"samples": samples, "sampledDomains": domains}, sort_keys=True))
    return int(set(domains) != set(public))


if __name__ == "__main__":
    raise SystemExit(main())
