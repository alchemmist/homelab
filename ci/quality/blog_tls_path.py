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

import yaml

from ci.quality.public_web import CATALOG

HOST = "www.alchemmist.xyz"
KUBE = ["kubectl", "--context=Socrat", "--request-timeout=8s"]
# Fixed reviewed Pod listener targets (not a general-purpose forwarder).
GROUPS = [
    ("kube-system", "app.kubernetes.io/name=traefik", 8443, {"socrat-0", "socrat-1"}),
    ("traefik-edge", "app.kubernetes.io/instance=traefik-edge", 443, {"socrat-2"}),
    ("traefik-moscow", "app.kubernetes.io/name=traefik-moscow", 8443, {"socrat-4"}),
]


def inventory():
    rows = {}
    for ns, label, port, nodes in GROUPS:
        items = json.loads(
            subprocess.check_output(
                [*KUBE, "-n", ns, "get", "pods", "-l", label, "-o", "json"], timeout=12
            )
        )["items"]
        seen = set()
        for p in items:
            node = p["spec"]["nodeName"]
            m = p["metadata"]
            ready = [c["status"] for c in p["status"]["conditions"] if c["type"] == "Ready"]
            host_network = ns == "traefik-edge"
            if bool(p["spec"].get("hostNetwork")) != host_network:
                raise ValueError("socket scope changed")
            key = ("node/" if host_network else "pod/") + node
            if node not in nodes or key in rows or m.get("deletionTimestamp") or ready != ["True"]:
                raise ValueError("candidate fleet changed")
            rows[key] = (ns, m["name"], m["uid"], port)
            seen.add(node)
        if seen != nodes:
            raise ValueError("incomplete candidate fleet")
    return rows


def forward(stack, row):
    ns, name, _, port = row
    if ns == "traefik-edge":
        # hostNetwork and UDP-only declared containerPort 443: do not pretend
        # this is a Pod-isolated TLS socket. Forward to the existing node loopback.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            local = sock.getsockname()[1]
        proc = subprocess.Popen(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ConnectTimeout=5",
                "-o",
                "ControlMaster=no",
                "-o",
                "ControlPath=none",
                "-N",
                "-L",
                f"127.0.0.1:{local}:127.0.0.1:443",
                "socrat-2",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        stack.callback(proc.wait, 5)
        stack.callback(proc.terminate)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", local), timeout=0.3):
                    pass
                return ("127.0.0.1", local)
            except OSError:
                time.sleep(0.1)
        raise ValueError("NL loopback forward failed")
    proc = subprocess.Popen(
        [
            "kubectl",
            "--context=Socrat",
            "-n",
            ns,
            "port-forward",
            "--address",
            "127.0.0.1",
            "pod/" + name,
            ":" + str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    stack.callback(proc.wait, 5)
    stack.callback(proc.terminate)
    if not select.select([proc.stdout], [], [], 10)[0]:
        raise ValueError("forward timeout")
    prefix, sep, end = proc.stdout.readline().decode().strip().partition(" -> ")
    if not sep or end != str(port) or not prefix.startswith("Forwarding from 127.0.0.1:"):
        raise ValueError("forward failed")
    return ("127.0.0.1", int(prefix.rsplit(":", 1)[1]))


def exchange(ctx, target, session=None):
    with (
        socket.create_connection(target, timeout=5) as raw,
        ctx.wrap_socket(raw, server_hostname=HOST, session=session) as tls,
    ):
        tls.sendall(
            f"GET / HTTP/1.1\r\nHost: {HOST}\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n".encode()
        )
        r = http.client.HTTPResponse(tls)
        r.begin()
        body = r.read(131073)
        if (
            r.status != 200
            or len(body) > 131072
            or b"<title>Personal blog of Anton Grishin</title>" not in body
        ):
            raise ValueError("blog not matched")
        return tls.session, tls.session_reused


def sample(source, peers):
    ctx = ssl.create_default_context()
    ctx.minimum_version = ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ticket, reused = exchange(ctx, source)
    if reused or not ticket.has_ticket:
        return {"control": "no-fresh-ticket"}
    result = {}
    for name, peer in peers.items():
        try:
            result[name] = "resumed" if exchange(ctx, peer, ticket)[1] else "full-handshake"
        except (OSError, ValueError, http.client.HTTPException):
            result[name] = "unverified"
    return result


def correlated(samples, candidates, entrances):
    """Demand positive self and negative cross controls; ambiguous is not attribution."""
    if not all(
        samples[src].get(dst) == ("resumed" if src == dst else "full-handshake")
        for src in candidates
        for dst in candidates
    ):
        return {}
    result = {}
    for src in entrances:
        row = samples[src]
        hits = [dst for dst in candidates if row.get(dst) == "resumed"]
        if len(hits) == 1 and all(
            row.get(dst) in {"resumed", "full-handshake"} for dst in candidates
        ):
            result[src] = hits[0]
    return result


def main():
    catalog = yaml.safe_load(CATALOG.read_text())
    sites = catalog["replicas"]
    public = {
        "public/" + s: (str(ipaddress.IPv4Address(sites[s]["publicIP"])), 443)
        for s in ("home", "nl", "moscow")
    }
    rows = inventory()
    with contextlib.ExitStack() as stack:
        pods = {n: forward(stack, row) for n, row in rows.items()}
        samples = {}
        for name, source in {**pods, **public}.items():
            try:
                samples[name] = sample(source, {**pods, name: source})
            except (ValueError, OSError, http.client.HTTPException):
                samples[name] = {"control": "source-unverified"}
        if inventory() != rows:
            raise ValueError("candidate fleet changed")
    domains = correlated(samples, pods, public)
    print(json.dumps({"samples": samples, "sampledDomains": domains}, sort_keys=True))
    return int(set(domains) != set(public))


if __name__ == "__main__":
    raise SystemExit(main())
