#!/usr/bin/env python3
"""Explicit offline-configured bootstrap; never run by chart or Argo.

Requires a reviewed mc binary and private credentials JSON. No secrets on argv,
stdout, inherited environment, or child output. Dedicated NEW users, not root
service accounts. Existing users/policies must match or reconciliation stops.
"""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol, TypedDict


class AccessSecret(TypedDict):
    """One machine identity's access key and secret."""

    access: str
    secret: str


class Credentials(TypedDict):
    """Parsed machine credentials JSON with root and dedicated roles."""

    endpoint: str
    root: AccessSecret
    reader: AccessSecret
    writer: AccessSecret


class Command(Protocol):
    """Callable running one private mc request and returning parsed rows."""

    def __call__(self, *args: str, stdin: bytes | None = ...) -> list[dict[str, str]]:
        """Run one request and return its parsed JSON rows."""
        ...


def policy(actions):
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:" + a for a in actions],
                "Resource": ["arn:aws:s3:::spi-evidence/spi/v1/*"],
            }
        ],
    }


POLICIES = {
    "spi-reader": policy(["GetObject"]),
    "spi-writer": policy(["GetObject", "PutObject"]),
    "spi-console-reader": policy(["GetObject"]),
}


def canonical_policy(document):
    if not isinstance(document, dict) or set(document) - {"Version", "Statement", "Id"}:
        raise ValueError("unexpected policy fields")
    statements = document.get("Statement")
    if isinstance(statements, dict):
        statements = [statements]
    if not isinstance(statements, list):
        raise ValueError("invalid statements")
    normalized = []
    for statement in statements:
        if not isinstance(statement, dict) or set(statement) - {
            "Sid",
            "Effect",
            "Action",
            "Resource",
        }:
            raise ValueError("unexpected policy grants/conditions")
        row = {"Effect": statement.get("Effect")}
        for field in ("Action", "Resource"):
            values = statement.get(field)
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError("invalid policy scope")
            row[field] = sorted(set(values))
        normalized.append(row)
    return {
        "Version": document.get("Version"),
        "Statement": sorted(normalized, key=lambda x: json.dumps(x, sort_keys=True)),
    }


def private_directory(path):
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise ValueError("private owned directory required")


def private(path):
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise ValueError("private owned regular credentials file required")


def run(mc, config, args, stdin=None):
    result = subprocess.run(
        [mc, "--config-dir", config, "--json", *args],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        env={"PATH": os.defpath, "HOME": config, "LANG": "C"},
    )
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise ValueError("bootstrap request failed; stop and inspect privately; no automatic retry")
    rows = []
    decoder = json.JSONDecoder()
    text = result.stdout.decode().strip()
    while text:
        row, n = decoder.raw_decode(text)
        rows.append(row)
        text = text[n:].lstrip()
    if any(row.get("status") == "error" for row in rows):
        raise ValueError("bootstrap request failed")
    return rows


def validate_credentials(c: Credentials) -> None:
    """Fail unless the parsed credentials match the private port-forward contract."""
    # Use an operator port-forward, not a public root/admin endpoint.
    if c["endpoint"] != "http://127.0.0.1:19000":
        raise ValueError("private port-forward required")
    for role in ("root", "reader", "writer"):
        for key in ("access", "secret"):
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", c[role][key]):
                raise ValueError("invalid credential")
    if any(
        len({c[x][field] for x in ("root", "reader", "writer")}) != 3
        for field in ("access", "secret")
    ):
        raise ValueError("separate identities and secrets required")


def load_ownership_journal(path: Path, intended: dict[str, str]) -> object:
    """Load the required ownership journal unless absent."""
    if not path.exists():
        return None
    private(path)
    journal = json.loads(path.read_text())
    if journal != intended:
        raise ValueError("machine credentials differ from ownership journal")
    return journal


def create_missing_policies(
    mc: Command, tmp: Path, policy_names: set[str], names: tuple[str, ...]
) -> None:
    """Create any absent prefix policy from the pinned documents."""
    for name in names:
        if name not in policy_names:
            path = tmp / (name + ".json")
            path.write_text(json.dumps(POLICIES[name]))
            mc("admin", "policy", "create", "store", name, str(path))


def verify_existing_policies(mc: Command, tmp: Path, policy_names: set[str]) -> None:
    """Require every existing pinned policy to match its pinned document."""
    for name, document in POLICIES.items():
        if name in policy_names:
            path = tmp / (name + ".existing.json")
            mc("admin", "policy", "info", "store", name, "--policy-file", str(path))
            actual = json.loads(path.read_text())
            if canonical_policy(actual) != canonical_policy(document):
                raise ValueError("existing policy mismatch; no overwrite")


def verify_existing_users(
    mc: Command, names: set[str], journal: object, accesses: dict[str, str]
) -> None:
    """Require existing journaled users to match the pinned user contract."""
    for role, access in accesses.items():
        if access in names:
            if journal is None:
                raise ValueError("existing user without ownership journal; no adoption")
            info = mc("admin", "user", "info", "store", access)[0]
            if (
                info.get("policyName", "") not in ("", "spi-" + role)
                or info.get("memberOf")
                or info.get("userStatus") != "enabled"
            ):
                raise ValueError("existing user mismatch; no modification")


def require_private_bucket(mc: Command) -> None:
    """Verify the evidence bucket is absent of any anonymous access."""
    # No anonymous policy is created. Verify it is private before granting credentials.
    anonymous = mc("anonymous", "get", "store/spi-evidence")
    if not anonymous or anonymous[0].get("permission") != "private":
        raise ValueError("private bucket verification failed; stop")


def attach_spi_users(
    mc: Command, names: set[str], accesses: dict[str, str], secrets: dict[str, str]
) -> None:
    """Create the journaled users when absent and attach their prefix policy."""
    for role in ("reader", "writer"):
        if accesses[role] not in names:
            mc(
                "admin",
                "user",
                "add",
                "store",
                stdin=(accesses[role] + "\n" + secrets[role] + "\n").encode(),
            )
        # Attach only our journaled users; safe to resume after interrupted creation.
        info = mc("admin", "user", "info", "store", accesses[role])[0]
        if not info.get("policyName"):
            mc("admin", "policy", "attach", "store", "spi-" + role, "--user", accesses[role])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--credentials", type=Path, required=True)
    p.add_argument("--mc", required=True)
    p.add_argument("--mc-sha256", required=True)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    private_directory(args.credentials.parent)
    private(args.credentials)
    if hashlib.sha256(Path(args.mc).read_bytes()).hexdigest() != args.mc_sha256:
        raise ValueError("mc binary digest mismatch")
    c = json.loads(args.credentials.read_text())
    validate_credentials(c)
    if not args.apply:
        print(
            "Plan: private spi-evidence bucket; dedicated reader/writer users; three prefix policies. No changes."
        )
        return
    os.umask(0o077)
    journal_path = args.credentials.with_name("bootstrap-journal.json")
    intended = {
        c[role]["access"]: hashlib.sha256(c[role]["secret"].encode()).hexdigest()
        for role in ("reader", "writer")
    }
    journal = load_ownership_journal(journal_path, intended)
    with tempfile.TemporaryDirectory(prefix="rustfs-private-") as tmp:
        Path(tmp, "config.json").write_text(
            json.dumps(
                {
                    "version": "10",
                    "aliases": {
                        "store": {
                            "url": c["endpoint"],
                            "accessKey": c["root"]["access"],
                            "secretKey": c["root"]["secret"],
                            "api": "S3v4",
                            "path": "on",
                        }
                    },
                }
            )
        )

        def mc(*a, stdin=None) -> list[dict[str, object]]:
            result: list[dict[str, object]] = run(args.mc, tmp, list(a), stdin)
            return result

        # Inventories must succeed before any mutation. No failure means 'absent'.
        users = mc("admin", "user", "list", "store")
        names = {r["accessKey"] for r in users}
        policies = mc("admin", "policy", "list", "store")
        policy_names = {r["policy"] for r in policies}
        buckets = mc("ls", "store")
        bucket_names = {r["key"].rstrip("/") for r in buckets}
        verify_existing_policies(mc, Path(tmp), policy_names)
        verify_existing_users(
            mc,
            names,
            journal,
            {role: c[role]["access"] for role in ("reader", "writer")},
        )
        if journal is None:
            fd = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump(intended, output)
        if "spi-evidence" not in bucket_names:
            mc("mb", "store/spi-evidence")
        require_private_bucket(mc)
        create_missing_policies(mc, Path(tmp), policy_names, tuple(POLICIES))
        attach_spi_users(
            mc,
            names,
            {role: c[role]["access"] for role in ("reader", "writer")},
            {role: c[role]["secret"] for role in ("reader", "writer")},
        )
        print("Bootstrap reconciled. Run live credential and negative IAM tests before activation.")


if __name__ == "__main__":
    try:
        main()
    except (
        ImportError,
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        raise SystemExit(
            "Bootstrap stopped safely; inspect private state; no secrets or response bodies printed."
        ) from None
