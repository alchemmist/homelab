"""Run an explicit reviewed suite; Linux CI has loopback-only network and no SSH agent."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    """Execute main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite")
    parser.add_argument("--isolate-network", action="store_true")
    args = parser.parse_args()
    catalog = json.loads((ROOT / "ci/quality/test-suites.json").read_text())
    paths = catalog["suites"][args.suite]
    if not paths or any(
        not p.startswith("tests/") or not Path(p).name.startswith("test_") or ".." in Path(p).parts
        for p in paths
    ):
        msg = "Invalid test suite"
        raise ValueError(msg)
    output = ROOT / f"reports/tests-{args.suite}.xml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)  # A failed setup must never admit yesterday's report.
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("AWS_", "AZURE_", "GOOGLE_", "SSH_")) or key in {
            "KUBECONFIG",
            "ANSIBLE_VAULT_PASSWORD_FILE",
            "SPI_SORT_FIXTURE",
            "QUALITY_SYNTHETIC_SPI_SORT",
        }:
            env.pop(key)
    env["KUBECONFIG"] = "/dev/null"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-o",
        "junit_family=xunit2",
        "--junitxml=" + str(output),
        *paths,
    ]
    if args.isolate_network and platform.system() == "Darwin":
        # Apply to pytest and every child; only allow IP sockets on loopback.
        # ansible-core's controller hosts its local worker RPC API on an AF_UNIX
        # socket under TMPDIR (https://github.com/ansible/ansible/issues/87031).
        # Unix-domain sockets are local IPC only, so allow them unconditionally.
        policy = (
            "(version 1)(allow default)(deny network*)"
            '(allow network-outbound (remote ip "localhost:*"))'
            '(allow network-bind network-inbound (local ip "localhost:*"))'
            "(allow network-outbound (remote unix-socket))"
            "(allow network-bind (local unix-socket))"
        )
        argv = ["/usr/bin/sandbox-exec", "-p", policy, *argv]
    elif args.isolate_network and platform.system() == "Linux":
        # No external interfaces/routes. This prevents accidents, not hostile code with runner sudo.
        argv = [
            "sudo",
            "-n",
            "unshare",
            "--net",
            "--",
            "sh",
            "-c",
            'ip link set lo up && exec "$@"',
            "quality-tests",
            "runuser",
            "-u",
            getpass.getuser(),
            "--",
            "env",
            "PATH=" + env["PATH"],
            "KUBECONFIG=/dev/null",
            "PYTHONDONTWRITEBYTECODE=1",
            *(["QUALITY_SYNTHETIC_SPI_SORT=1"] if args.suite == "fast" else []),
            *argv,
        ]
    elif args.isolate_network:
        msg = "No loopback-only isolation available for this platform"
        raise ValueError(msg)
    return subprocess.run(
        argv, cwd=ROOT, env=env, check=False, timeout=840 if args.suite == "cluster" else 240
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
