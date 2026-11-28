"""Read fixed Cats build assets without executing them or following HTML links."""

import hashlib
import ipaddress
import json
import subprocess

import yaml

from ci.quality.public_web import CATALOG

HOST = "cats.alchemmist.xyz"
BUILD = {
    "/": ("text/html", 567, "f59b6c414b83add8828db1689f29231a6bc4a6978dbac0705890b4e40545207f"),
    "/assets/index-BPBWC2yJ.css": (
        "text/css",
        4447,
        "f6462c2fb2607579c706eab17f87de48a8959b30cb9001588442ee48ac8a1c98",
    ),
    "/assets/index-BubsrN33.js": (
        "application/javascript",
        228781,
        "d6fb19d532a66f53ce2815aff98c85c68d4cd232a1776f7c236081cdae17c077",
    ),
}


def matches(path, output):
    body, sep, meta = output.rpartition(b"\n")
    mime, size, digest = BUILD[path]
    return bool(
        sep
        and meta.partition(b";")[0] == ("200 " + mime).encode()
        and len(body) == size
        and hashlib.sha256(body).hexdigest() == digest
    )


def sample(*, ip=None, port=None):
    if (ip is None) == (port is None):
        raise ValueError("choose one reviewed transport")
    if ip is not None:
        args = ["--proto", "=https", "--resolve", f"{HOST}:443:{ipaddress.IPv4Address(ip)}"]
        base = "https://" + HOST
    else:
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("invalid loopback port")
        args = ["--proto", "=http", "--header", "Host: " + HOST]
        base = f"http://127.0.0.1:{port}"
    rows = {}
    for path, (_, size, _) in BUILD.items():
        try:
            r = subprocess.run(
                [
                    "curl",
                    "--disable",
                    "--noproxy",
                    "*",
                    "--silent",
                    "--max-time",
                    "8",
                    "--max-filesize",
                    str(size),
                    "--header",
                    "Accept-Encoding: identity",
                    "--write-out",
                    "\\n%{response_code} %{content_type}",
                    *args,
                    base + path,
                ],
                timeout=10,
                capture_output=True,
            )
            rows[path] = r.returncode == 0 and matches(path, r.stdout)
        except (OSError, subprocess.TimeoutExpired):
            rows[path] = False
    return rows


def main():
    sites = yaml.safe_load(CATALOG.read_text())["replicas"]
    ips = {s: str(ipaddress.IPv4Address(d["publicIP"])) for s, d in sites.items()}
    if set(ips) != {"home", "nl", "moscow"} or len(set(ips.values())) != 3:
        raise ValueError("unexpected entrance inventory")
    rows = {s: sample(ip=ip) for s, ip in ips.items()}
    print(json.dumps(rows, sort_keys=True))
    return int(not all(all(d.values()) for d in rows.values()))


if __name__ == "__main__":
    raise SystemExit(main())
