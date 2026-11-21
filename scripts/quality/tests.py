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
    catalog = json.loads((ROOT / "quality/test-suites.json").read_text())
    paths = catalog["suites"][args.suite]
    if not paths or any(
        not p.startswith("tests/") or not Path(p).name.startswith("test_") or ".." in Path(p).parts
        for p in paths
    ):
        raise ValueError("Invalid test suite")
    output = ROOT / f"reports/tests-{args.suite}.xml"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)  # A failed setup must never admit yesterday's report.
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("AWS_", "AZURE_", "GOOGLE_", "SSH_")) or key in {
            "KUBECONFIG",
            "ANSIBLE_VAULT_PASSWORD_FILE",
        }:
            env.pop(key)
    env["KUBECONFIG"] = "/dev/null"
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
        policy = (
            '(version 1)(allow default)(deny network*)'
            '(allow network-outbound (remote ip "localhost:*"))'
            '(allow network-bind network-inbound (local ip "localhost:*"))'
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
            *argv,
        ]
    elif args.isolate_network:
        raise ValueError("No loopback-only isolation available for this platform")
    return subprocess.run(
        argv, cwd=ROOT, env=env, check=False, timeout=840 if args.suite == "cluster" else 240
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
