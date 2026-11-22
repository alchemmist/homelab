"""Runs only inside the two-loopback-proxy canary pod (synthetic keys/DB)."""

import json
import os
import socket
import ssl
import time
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def post(port, route, key, body):
    req = Request(
        f"http://127.0.0.1:{port}/{route}",
        json.dumps(body).encode(),
        {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def generate(**limits):
    code, result = post(
        4000,
        "key/generate",
        os.environ["MASTER_KEY"],
        {"models": ["fixture"], **limits},
    )
    assert code == 200, code
    return result["key"]


def chat(port, key):
    code, result = post(
        port,
        "v1/chat/completions",
        key,
        {"model": "fixture", "messages": [{"role": "user", "content": "fixture"}]},
    )
    if code == 200:
        assert result["choices"][0]["message"]["content"] == "fixture-response"
    return code, result


key = generate(rpm_limit=1)
a, _ = chat(4000, key)
b, _ = chat(4001, key)
print(f"RPM: {a}/{b}", flush=True)
assert (a, b) == (200, 429)
key = generate(max_budget=0.000001)
a, result = chat(4000, key)
print(
    "Budget: first",
    a,
    "tokens",
    result.get("usage", {}).get("total_tokens"),
    flush=True,
)
assert a == 200
b, result = chat(4001, key)
reason = str(result.get("error", {}).get("message", "")).lower()
print(f"Budget: second {b}, budget rejection={'budget' in reason}", flush=True)
if b == 200:
    # Observe async spend persistence; do not keep submitting paid completions.
    for _ in range(24):
        req = Request(
            "http://127.0.0.1:4000/key/info?" + urlencode({"key": key}),
            headers={"Authorization": "Bearer " + os.environ["MASTER_KEY"]},
        )
        with urlopen(req, timeout=5) as resp:
            info = json.load(resp)["info"]
        if float(info["spend"]) > float(info["max_budget"]):
            break
        time.sleep(3)
    print(
        "Persisted synthetic spend:",
        info["spend"],
        "budget:",
        info["max_budget"],
        flush=True,
    )
    b, result = chat(4001, key)
    reason = str(result.get("error", {}).get("message", "")).lower()
    print(f"Budget: later {b}, budget rejection={'budget' in reason}", flush=True)
assert b in (400, 401, 402, 403, 422, 429) and "budget" in reason

# Warm worker B's key cache, revoke through A, then probe B again.
revoked = generate()
assert chat(4001, revoked)[0] == 200
code, _ = post(4000, "key/delete", os.environ["MASTER_KEY"], {"keys": [revoked]})
assert code == 200, code
for attempt in range(5):
    code, _ = chat(4001, revoked)
    if code in (401, 403):
        break
    time.sleep(1)
print(f"Revoked key on B: {code}, attempt {attempt + 1}", flush=True)
assert code in (401, 403)

host = "redis-common-haproxy.redis.svc.cluster.local"
for case, ctx, hostname in (
    ("wrong CA", ssl.create_default_context(), host),
    (
        "wrong hostname",
        ssl.create_default_context(cafile="/probe/ca.crt"),
        "incorrect.invalid",
    ),
):
    try:
        with socket.create_connection((host, 6379), timeout=3) as sock:
            ctx.wrap_socket(sock, server_hostname=hostname).close()
    except ssl.SSLCertVerificationError:
        print(f"{case}: rejected")
    else:
        raise AssertionError(case)
