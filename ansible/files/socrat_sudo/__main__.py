"""Ask the socrat-bot broker to approve a command, then exec it.

BROKER_URL and INTERNAL_TOKEN come from /etc/socrat-sudo.env (mode 0600).
This module does not create that file and does not change sudoers.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import stat
import sys
import time
import urllib.error
import urllib.request

ENV_PATH = "/etc/socrat-sudo.env"
POLL_SECONDS = 2
WAIT_SECONDS = 300


def fail(message: str) -> None:
    sys.stderr.write(f"socrat-sudo: {message}\n")
    raise SystemExit(1)


def load_env(path: str = ENV_PATH) -> dict[str, str]:
    try:
        info = os.stat(path)
    except FileNotFoundError:
        fail(f"{path} is missing")
    except PermissionError:
        fail(f"cannot read {path}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        fail(f"{path} must be mode 0600")
    values: dict[str, str] = {}
    try:
        handle = open(path, encoding="utf-8")
    except PermissionError:
        fail(f"cannot read {path}")
    with handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export ") :].strip()
            values[key] = value.strip().strip('"').strip("'")
    return values


def call(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("X-Internal-Token", token)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        fail(f"broker HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        fail(f"broker unreachable: {exc.reason}")
    if not isinstance(payload, dict):
        fail("broker returned a non-object response")
    return payload


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        sys.stderr.write("usage: socrat-sudo <command> [args...]\n")
        raise SystemExit(2)
    env = load_env()
    base = env.get("BROKER_URL", "").rstrip("/")
    token = env.get("INTERNAL_TOKEN", "")
    if not base or not token:
        fail("BROKER_URL and INTERNAL_TOKEN are required in /etc/socrat-sudo.env")
    created = call(
        "POST",
        f"{base}/v1/sudo",
        token,
        {
            "user_name": getpass.getuser(),
            "node": socket.gethostname(),
            "argv": args,
        },
    )
    request_id = str(created.get("id") or created.get("request_id") or "")
    if not request_id:
        fail("broker response has no id")
    deadline = time.monotonic() + WAIT_SECONDS
    status = str(created.get("status") or "pending")
    current = created
    while status == "pending":
        if time.monotonic() >= deadline:
            fail("timed out waiting for a decision")
        time.sleep(POLL_SECONDS)
        current = call("GET", f"{base}/v1/sudo/{request_id}", token)
        status = str(current.get("status") or "")
    if status != "approved":
        fail(status or "unexpected broker status")
    returned = current.get("argv")
    if returned is not None and list(returned) != args:
        fail("broker returned a different command")
    try:
        os.execvp(args[0], args)
    except OSError as exc:
        fail(f"cannot exec {args[0]}: {exc.strerror}")


if __name__ == "__main__":
    main()
