"""Add only the owner UI's read-only ACL and private storage key. No control ACL in the UI."""

import importlib.util
import secrets
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "acl", Path(__file__).resolve().parents[1] / "redis-common/onboard-litellm.py"
)
acl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acl)
if __name__ == "__main__":
    if sys.argv[1:] != ["--create-missing"]:
        sys.exit("usage: onboard.py --create-missing")
    secret = acl.secret(
        "redis",
        "redisinsight-runtime",
        lambda: {"password": secrets.token_hex(32), "encryption-key": secrets.token_hex(32)},
    )
    # SCAN reveals key names across the instance; value access is prefix-scoped.
    # No @read wildcard, EVAL, KEYS, CONFIG, MONITOR, writes or Pub/Sub.
    commands = [
        "ping",
        "hello",
        "select",
        "info",
        "command",
        "scan",
        "type",
        "ttl",
        "pttl",
        "exists",
        "get",
        "strlen",
        "hscan",
        "hlen",
        "hget",
        "hgetall",
        "llen",
        "lrange",
        "scard",
        "sscan",
        "zcard",
        "zscan",
        "zrange",
        "xlen",
        "xrange",
        "xrevrange",
        "memory|usage",
        "dbsize",
        "client|setname",
        "client|setinfo",
        "cluster|info",
        "module|list",
    ]
    acl.install_rules(
        {
            "insight-browser": (
                secret["password"],
                ["~litellm:*", "~monitor:writer", *["+" + c for c in commands]],
            )
        }
    )
