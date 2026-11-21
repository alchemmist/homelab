"""Disposable Docker-only K3s failover acceptance; never consumes host kubeconfig."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time

VERSION = "rancher/k3s:v1.36.5-k3s1"
WORKLOAD = "nginx:1.27-alpine"
PREFIX = "lab404-" + secrets.token_hex(5)
TOKEN = secrets.token_hex(24)
created = []


def docker(*args, data=None, timeout=30):
    result = subprocess.run(
        ["docker", *args], input=data, capture_output=True, timeout=timeout
    )
    if result.returncode:
        # Never include environment, server tokens, kubeconfig or raw journals.
        raise RuntimeError(f"docker {args[0]} failed ({result.returncode})")
    return result.stdout


def shell(node, *cmd, data=None, timeout=15):
    return docker("exec", "-i", PREFIX + "-" + node, *cmd, data=data, timeout=timeout)


def kube(node, *cmd, data=None):
    return shell(node, "k3s", "kubectl", "--request-timeout=4s", *cmd, data=data)


def wait(check, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            result = check()
            if result:
                return result
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(1)
    raise TimeoutError("condition did not converge")


def start(name, flags):
    ident = PREFIX + "-" + name
    args = [
        "run",
        "-d",
        "--privileged",
        "--network",
        PREFIX,
        "--hostname",
        name,
        "--network-alias",
        name,
        "--name",
        ident,
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/var/run",
        "-e",
        "K3S_TOKEN",
        VERSION,
        "server",
        "--node-name",
        name,
        "--disable",
        "traefik,servicelb,metrics-server,local-storage",
        *flags,
    ]
    # Only an ephemeral private lab token is passed to these new containers.
    docker(*args, timeout=60)
    created.append(ident)


def apply(obj):
    kube("v0", "apply", "-f", "-", data=json.dumps(obj).encode())


def body():
    return (
        kube(
            "v0",
            "exec",
            "client",
            "--",
            "wget",
            "-T",
            "2",
            "-qO-",
            "http://canary.default.svc",
        )
        .strip()
        .decode()
    )


def targets():
    data = json.loads(
        kube(
            "api",
            "get",
            "endpointslices",
            "-l",
            "kubernetes.io/service-name=canary",
            "-o",
            "json",
        )
    )
    return {
        e["targetRef"]["name"]
        for s in data["items"]
        for e in s["endpoints"]
        if e["conditions"].get("ready")
    }


def choose_peer():
    # Test the actually connected datastore member, not merely a configured one.
    peers = {
        docker(
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            PREFIX + "-" + n,
        )
        .decode()
        .strip()
        for n in ("v0", "v1", "v2")
    }
    for line in (
        shell("api", "cat", "/proc/net/tcp", "/proc/net/tcp6").decode().splitlines()
    ):
        fields = line.split()
        if len(fields) < 4 or fields[3] != "01":
            continue
        addr, port = fields[2].split(":")
        if int(port, 16) != 2379:
            continue
        ip = socket.inet_ntoa(bytes.fromhex(addr[-8:])[::-1])
        if ip in peers:
            return ip
    raise RuntimeError(
        "no observable active remote datastore socket; trial inconclusive"
    )


def trial(mode):
    kube(
        "v0",
        "patch",
        "svc",
        "canary",
        "--type=merge",
        "-p",
        '{"spec":{"selector":{"backend":"a"}}}',
    )
    wait(lambda: targets() == {"a"} and body() == "a", 90)

    def uid():
        return kube("v0", "get", "pod", "client", "-o", "jsonpath={.metadata.uid}")

    original_uid = uid()
    peer = choose_peer()

    def sync_sample():
        try:
            lines = (
                shell(
                    "api", "wget", "-T", "2", "-qO-", "http://127.0.0.1:10249/metrics"
                )
                .decode()
                .splitlines()
            )
            return next(
                (
                    line
                    for line in lines
                    if line.startswith(
                        "kubeproxy_sync_proxy_rules_last_timestamp_seconds"
                    )
                    and "IPv6" not in line
                ),
                "unavailable",
            )
        except RuntimeError:
            return "unavailable"

    print(f"{mode} before: {sync_sample()}", flush=True)
    rv = kube(
        "api", "get", "svc", "canary", "-o", "jsonpath={.metadata.resourceVersion}"
    ).decode()
    watchpath = (
        "/api/v1/namespaces/default/services?watch=1&fieldSelector=metadata.name%3Dcanary&resourceVersion="
        + rv
        + "&timeoutSeconds=65"
    )
    rule = ["OUTPUT", "-p", "tcp", "-d", peer, "--dport", "2379", "-j", mode]
    shell("api", "iptables", "-I", *rule)
    watch = subprocess.Popen(
        [
            "docker",
            "exec",
            PREFIX + "-api",
            "k3s",
            "kubectl",
            "--request-timeout=70s",
            "get",
            "--raw",
            watchpath,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        from concurrent.futures import ThreadPoolExecutor

        def see_watch():
            for line in watch.stdout:
                obj = json.loads(line).get("object", {})
                if obj.get("spec", {}).get("selector", {}).get("backend") == "b":
                    return time.monotonic()
            raise RuntimeError("new value missing from watch")

        starttime = time.monotonic()
        with ThreadPoolExecutor(1) as ex:
            event = ex.submit(see_watch)
            try:
                kube(
                    "v0",
                    "patch",
                    "svc",
                    "canary",
                    "--type=merge",
                    "-p",
                    '{"spec":{"selector":{"backend":"b"}}}',
                )

                def converged():
                    fresh = (
                        kube(
                            "api",
                            "get",
                            "svc",
                            "canary",
                            "-o",
                            "jsonpath={.spec.selector.backend}",
                        )
                        == b"b"
                    )
                    return (
                        fresh and targets() == {"b"} and body() == "b" and event.done()
                    )

                wait(converged, 60)
                elapsed = time.monotonic() - starttime
                if elapsed > 60 or uid() != original_uid:
                    raise RuntimeError("60s or client UID acceptance failed")
                counters = (
                    shell("api", "iptables", "-L", "OUTPUT", "-v", "-n", "-x")
                    .decode()
                    .splitlines()
                )
                if not any(
                    mode in row
                    and peer in row
                    and "dpt:2379" in row
                    and int(row.split()[0]) > 0
                    for row in counters
                ):
                    raise RuntimeError(
                        "fault rule did not observe traffic; inconclusive"
                    )
                print(
                    f"{mode}: fresh API read, EndpointSlice and same-client B in {elapsed:.2f}s; watch in {event.result() - starttime:.2f}s",
                    flush=True,
                )
            finally:
                watch.kill()
                watch.wait(timeout=5)
    finally:
        shell("api", "iptables", "-D", *rule)
        print(f"{mode} after: {sync_sample()}", flush=True)


def main():
    if sys.argv[1:] != ["--local-disposable"]:
        raise SystemExit(
            "Requires --local-disposable; launches privileged containers in a dedicated local Docker VM."
        )
    endpoint = (
        os.getenv("DOCKER_HOST")
        or docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
        .decode()
        .strip()
    )
    if not endpoint.startswith("unix://"):
        raise SystemExit("local Unix Docker socket required")
    # Context variables must not override the verified socket on subsequent commands.
    os.environ.pop("DOCKER_CONTEXT", None)
    os.environ["DOCKER_HOST"] = endpoint
    for image in (VERSION, WORKLOAD):
        docker("image", "inspect", image)
    os.environ["K3S_TOKEN"] = TOKEN
    docker("network", "create", PREFIX)
    try:
        start("v0", ["--cluster-init"])
        print("initializing isolated v0", flush=True)
        wait(lambda: kube("v0", "get", "--raw", "/readyz") == b"ok", 120)
        for name in ("v1", "v2", "api"):
            start(
                name,
                [
                    "--server",
                    "https://v0:6443",
                    *(["--disable-etcd"] if name == "api" else []),
                ],
            )
            wait(lambda: kube(name, "get", "--raw", "/readyz") == b"ok", 120)
        archive = docker("save", WORKLOAD, timeout=90)
        shell("api", "k3s", "ctr", "images", "import", "-", data=archive, timeout=120)
        for name in ("a", "b", "client"):
            apply(
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": name, "labels": {"backend": name}},
                    "spec": {
                        "nodeName": "api",
                        "containers": [
                            {
                                "name": "app",
                                "image": WORKLOAD,
                                "imagePullPolicy": "Never",
                                "command": [
                                    "sh",
                                    "-c",
                                    f'echo {name} >/usr/share/nginx/html/index.html; exec nginx -g "daemon off;"',
                                ],
                            }
                        ],
                    },
                }
            )
        apply(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "canary"},
                "spec": {
                    "selector": {"backend": "a"},
                    "ports": [{"port": 80, "targetPort": 80}],
                },
            }
        )
        for mode in ("REJECT", "DROP"):
            trial(mode)
    finally:
        for name in reversed(created):
            docker("rm", "-fv", name, timeout=45)
        docker("network", "rm", PREFIX)


if __name__ == "__main__":
    main()
