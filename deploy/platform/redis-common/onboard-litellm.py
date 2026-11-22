"""Explicit first onboarding; create missing client credentials, never rotate existing ones."""

import base64
import hashlib
import json
import secrets
import subprocess
import sys

HOST = "redis-common-haproxy.redis.svc.cluster.local"
COMMANDS = (
    "info ping get set setex psetex mget mset del exists ttl pttl expire pexpire incr incrby incrbyfloat "
    "decr decrby hget hset hgetall hincrby hdel hmget eval evalsha script|load multi exec discard "
    "publish subscribe unsubscribe zadd zcount zcard zrange zrem zremrangebyscore lpush rpush lrange "
    "ltrim client|setinfo time"
).split()


def kube(ns, *args, data=None):
    return subprocess.check_output(
        ["kubectl", "--context", "Socrat", "--request-timeout=20s", "-n", ns, *args],
        input=data,
        text=True,
    ).strip()


def secret(ns, name, make):
    args = ["get", "secret", name, "-o", "json"]
    current = kube(ns, *args, "--ignore-not-found")
    if not current:
        kube(
            ns,
            "create",
            "-f",
            "-",
            data=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": name},
                    "stringData": make(),
                }
            ),
        )
        current = kube(ns, *args)
    return {
        k: base64.b64decode(v).decode() for k, v in json.loads(current)["data"].items()
    }


def main():
    if sys.argv[1:] != ["--create-missing"]:
        sys.exit("usage: onboard-litellm.py --create-missing")
    ca = base64.b64decode(
        kube(
            "redis",
            "get",
            "secret",
            "redis-common-public-ca",
            "-o",
            "jsonpath={.data.ca\\.crt}",
        )
    ).decode()
    assert ca.startswith("-----BEGIN CERTIFICATE-----")

    def url(pw):
        return f"rediss://litellm:{pw}@{HOST}:6379/0?ssl_ca_certs=/etc/redis-common/ca.crt&ssl_check_hostname=true&ssl_cert_reqs=required"

    def make():
        pw = secrets.token_hex(32)
        return {"password": pw, "url": url(pw), "ca.crt": ca}

    client = secret("llm", "redis-common-litellm", make)
    if client["ca.crt"] != ca or client["url"] != url(client["password"]):
        sys.exit("Existing client credential mismatch; use rotation runbook")
    probe = secret(
        "redis", "redis-common-probe", lambda: {"password": secrets.token_hex(32)}
    )
    users = {
        "litellm": (
            client["password"],
            ["~litellm:*", "&litellm:*", *["+" + c for c in COMMANDS]],
        ),
        "writer-probe": (
            probe["password"],
            ["~monitor:writer", "+set", "+get", "+info"],
        ),
    }
    install_rules(users)


def install_rules(users):
    rules = {
        u: ["on", "#" + hashlib.sha256(p.encode()).hexdigest(), *r]
        for u, (p, r) in users.items()
    }
    obj = json.loads(kube("redis", "get", "secret", "redis-common-users", "-o", "json"))
    lines = base64.b64decode(obj["data"]["client.conf"]).decode().splitlines()
    for u, rule in rules.items():
        line = "user " + u + " " + " ".join(rule)
        existing = [s for s in lines if s.split()[:2] == ["user", u]]
        if existing == [line]:
            continue
        prior_release = u == "litellm" and existing == [line.removesuffix(" +time")]
        if not prior_release and existing not in ([], ["user " + u + " off"]):
            sys.exit("Conflicting persistent ACL: " + u)
        lines = [s for s in lines if s not in existing] + [line]
    new = base64.b64encode(("\n".join(lines) + "\n").encode()).decode()
    if obj["data"]["client.conf"] != new:
        patch = [
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": obj["metadata"]["resourceVersion"],
            },
            {"op": "replace", "path": "/data/client.conf", "value": new},
        ]
        kube(
            "redis",
            "patch",
            "secret",
            "redis-common-users",
            "--type=json",
            "--patch-file=/dev/stdin",
            data=json.dumps(patch),
        )
    # Redis ACL changes are process-local; set each verified server (no restart or ACL SAVE).
    for ordinal in range(3):

        def cli(*args):
            return kube(
                "redis",
                "exec",
                f"redis-common-server-{ordinal}",
                "-c",
                "redis",
                "--",
                "sh",
                "-ec",
                'export REDISCLI_AUTH="$AUTH"; exec redis-cli --tls --cacert /tls-certs/ca.crt --json "$@"',
                "sh",
                *args,
            )

        for u, rule in rules.items():
            raw = cli("acl", "getuser", u)
            info = json.loads(raw)
            if info and info["passwords"] not in ([], [rule[1][1:]]):
                sys.exit("Conflicting live ACL: " + u)
            if json.loads(cli("acl", "setuser", u, "reset", *rule)) != "OK":
                sys.exit("ACL install failed")
    print(
        "Persistent ACL and all three runtimes updated."
    )


if __name__ == "__main__":
    main()
