#!/usr/bin/env python3
"""Dedicated n8n binary-data bucket, user and policy reconciler for RustFS.

Explicit offline-configured bootstrap; never run by chart or Argo. Requires a
reviewed mc binary and a private credentials JSON (root credentials plus the
pre-generated n8n writer identity). No secrets on argv, stdout, inherited
environment, or child output. A dedicated NEW user, never the root or SPI
service accounts. Existing users/policies must match or reconciliation stops.

Shape (additive to the SPI bootstrap; independent journal):
- bucket    n8n-binary      (private, no anonymous access)
- policy    n8n-binary      (s3:GetObject, s3:PutObject on the bucket only)
- user      n8n             (the n8n deployment writer identity)

The rendered automation-namespace Secret is written next to the credentials
file for a manual explicit kubectl apply; nothing is printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TypedDict

BUCKET = "n8n-binary"
POLICY_NAME = "n8n-binary"
IDENTITY_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": ["s3:GetObject", "s3:PutObject"],
            "Resource": [f"arn:aws:s3:::{BUCKET}/*"],
        }
    ],
}


class AccessSecret(TypedDict):
    """One machine identity's access key and secret."""

    access: str
    secret: str


class Credentials(TypedDict):
    """Parsed private credentials JSON with root and the n8n writer identity."""

    endpoint: str
    root: AccessSecret
    n8n: AccessSecret


class CommandRow(TypedDict, total=False):
    """Fields consumed from the mc JSON response records."""

    accessKey: str
    policy: str
    key: str
    status: str
    permission: str
    userStatus: str
    policyName: str
    memberOf: list[str] | None


class Command(Protocol):
    """Callable running one private mc request and returning parsed rows."""

    def __call__(self, *args: str, stdin: bytes | None = ...) -> list[CommandRow]:
        """Run one request and return its parsed JSON rows."""
        ...


def canonical_policy(document: object) -> dict[str, object]:
    """Compare policies by normalized statements, independent of ordering."""
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
        row: dict[str, object] = {"Effect": statement.get("Effect")}
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


def private_directory(path: Path) -> None:
    """Require a private, owned credentials directory."""
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise ValueError("private owned directory required")


def private(path: Path) -> None:
    """Require a private, owned regular file."""
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        raise ValueError("private owned regular credentials file required")


def run(mc: str, config: str, args: Sequence[str], stdin: bytes | None = None) -> list[CommandRow]:
    """Run one private mc request; no secrets on argv or stdout."""
    result = subprocess.run(
        [mc, "--config-dir", config, "--json", *args],
        input=stdin,
        capture_output=True,
        timeout=60,
        env={"PATH": os.defpath, "HOME": config, "LANG": "C"},
    )
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise ValueError("request failed; stop and inspect privately; no automatic retry")
    rows: list[CommandRow] = []
    decoder = json.JSONDecoder()
    text = result.stdout.decode().strip()
    while text:
        row, n = decoder.raw_decode(text)
        rows.append(row)
        text = text[n:].lstrip()
    if any(row.get("status") == "error" for row in rows):
        raise ValueError("request failed")
    return rows


def validate_credentials(c: Credentials) -> None:
    """Fail unless the parsed credentials match the private port-forward contract."""
    if c["endpoint"] != "http://127.0.0.1:19000":
        raise ValueError("private port-forward required")
    for role in ("root", "n8n"):
        row = c[role]
        if not isinstance(row, dict):
            raise ValueError("invalid credential")
        for key in ("access", "secret"):
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", row[key]):
                raise ValueError("invalid credential")
    if c["root"]["access"] == c["n8n"]["access"]:
        raise ValueError("separate identities and secrets required")


def load_journal(path: Path, intended: dict[str, str]) -> object:
    """Load the ownership journal unless absent."""
    if not path.exists():
        return None
    private(path)
    journal = json.loads(path.read_text())
    if journal != intended:
        raise ValueError("machine credentials differ from ownership journal")
    return journal


def require_private_bucket(mc: Command) -> None:
    """Verify the binary-data bucket is absent of any anonymous access."""
    anonymous = mc("anonymous", "get", f"store/{BUCKET}")
    if not anonymous or anonymous[0].get("permission") != "private":
        raise ValueError("private bucket verification failed; stop")


def verify_existing_policy(mc: Command, tmp: Path, policy_names: set[str]) -> None:
    """Require an existing pinned policy to match its pinned document."""
    if POLICY_NAME in policy_names:
        path = tmp / "n8n-binary.existing.json"
        mc("admin", "policy", "info", "store", POLICY_NAME, "--policy-file", str(path))
        actual = json.loads(path.read_text())
        if canonical_policy(actual) != canonical_policy(IDENTITY_POLICY):
            raise ValueError("existing policy mismatch; no overwrite")


def verify_existing_user(mc: Command, journal: object, access: str, exists: bool) -> None:
    """Require an existing journaled user to match the pinned user contract."""
    if not exists:
        return
    if journal is None:
        raise ValueError("existing user without ownership journal; no adoption")
    row = mc("admin", "user", "info", "store", access)[0]
    if (
        row.get("policyName", "") not in ("", POLICY_NAME)
        or row.get("memberOf")
        or row.get("userStatus") != "enabled"
    ):
        raise ValueError("existing user mismatch; no modification")


def attach_user(
    mc: Command, names: set[str], journal: object, access: str, secret: str
) -> None:
    """Create the journaled user when absent and attach the bucket policy."""
    if access not in names:
        mc("admin", "user", "add", "store", stdin=(access + "\n" + secret + "\n").encode())
    info = mc("admin", "user", "info", "store", access)[0]
    if not info.get("policyName"):
        mc("admin", "policy", "attach", "store", POLICY_NAME, "--user", access)


def render_secret(c: Credentials) -> dict[str, object]:
    """Render the automation-namespace Secret for n8n binary data.

    Flat accessKey/accessSecret data keys: the chart mounts them with
    secretKeyRef, not as a JSON file.
    """
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "n8n-s3-storage", "namespace": "automation"},
        "type": "Opaque",
        "data": {
            "accessKey": base64.b64encode(c["n8n"]["access"].encode()).decode(),
            "accessSecret": base64.b64encode(c["n8n"]["secret"].encode()).decode(),
        },
    }


def main() -> None:
    """Plan or reconcile the n8n RustFS bucket, policy and user."""
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
            f"Plan: private {BUCKET} bucket; dedicated n8n user; {POLICY_NAME} policy. No changes."
        )
        return
    os.umask(0o077)
    journal_path = args.credentials.with_name("n8n-objectstore-journal.json")
    intended = {c["n8n"]["access"]: hashlib.sha256(c["n8n"]["secret"].encode()).hexdigest()}
    journal = load_journal(journal_path, intended)
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

        def mc(*a: str, stdin: bytes | None = None) -> list[CommandRow]:
            return run(args.mc, tmp, list(a), stdin)

        users = mc("admin", "user", "list", "store")
        names = {r["accessKey"] for r in users}
        policies = mc("admin", "policy", "list", "store")
        policy_names = {r["policy"] for r in policies}
        buckets = mc("ls", "store")
        bucket_names = {r["key"].rstrip("/") for r in buckets}
        verify_existing_policy(mc, Path(tmp), policy_names)
        verify_existing_user(mc, journal, c["n8n"]["access"], c["n8n"]["access"] in names)
        if journal is None:
            fd = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as output:
                json.dump(intended, output)
        if BUCKET not in bucket_names:
            mc("mb", f"store/{BUCKET}")
        require_private_bucket(mc)
        if POLICY_NAME not in policy_names:
            path = Path(tmp) / "n8n-binary.json"
            path.write_text(json.dumps(IDENTITY_POLICY))
            mc("admin", "policy", "create", "store", POLICY_NAME, str(path))
        attach_user(mc, names, journal, c["n8n"]["access"], c["n8n"]["secret"])
        output = args.credentials.with_name("n8n-s3.secret.json")
        if output.exists() or output.is_symlink():
            private(output)
            if json.loads(output.read_text()) != render_secret(c):
                raise ValueError("existing rendered Secret differs; no overwrite")
        else:
            fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as out:
                json.dump(render_secret(c), out)
        print(
            "n8n object store reconciled. Run live credential and negative tests before activation."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Bootstrap stopped safely; inspect private state; no secrets or response bodies printed."
        )
