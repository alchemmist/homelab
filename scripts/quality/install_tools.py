"""Install only checksum-locked standalone tools; never execute downloaded installers."""

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def install(record, destination):
    if record["name"] not in {
        "promtool",
        "kubectl",
        "kind",
        "actionlint",
        "kubeconform",
        "gitleaks",
        "hadolint",
        "shellcheck",
        "kube-linter",
    }:
        raise ValueError("Unknown or escaping tool name")
    process = subprocess.run(
        [
            "/usr/bin/curl",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--max-filesize",
            "268435456",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout",
            "10",
            "--max-time",
            "45",
            record["url"],
        ],
        capture_output=True,
        timeout=50,
        check=True,
    )
    data = process.stdout
    if len(data) > 256 * 1024 * 1024:
        raise ValueError("Tool archive exceeds limit")
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("Tool checksum mismatch")
    if record["member"]:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = archive.getmember(record["member"])
            if not member.isfile() or member.size > 256 * 1024 * 1024:
                raise ValueError("Unsafe tool archive member")
            data = archive.extractfile(member).read()
    target = destination / record["name"]
    target.write_bytes(data)
    target.chmod(0o755)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", nargs="+")
    args = parser.parse_args()
    key = f"{platform.system().lower()}-{platform.machine()}"
    lock = json.loads((ROOT / "quality/tools.lock.json").read_text())
    if key not in lock["platforms"]:
        raise ValueError(f"Unsupported tool platform: {key}")
    destination = ROOT / ".quality-tools/bin"
    destination.mkdir(parents=True, exist_ok=True)
    records = lock["platforms"][key]
    if args.tools:
        if set(args.tools) - {r["name"] for r in records}:
            raise ValueError("Unknown tool requested")
        records = [r for r in records if r["name"] in args.tools]
    for record in records:
        install(record, destination)
    if os.environ.get("GITHUB_PATH"):
        with open(os.environ["GITHUB_PATH"], "a") as stream:
            stream.write(str(destination) + "\n")
    print(f"Installed {len(records)} checksum-locked tools in {destination}")


if __name__ == "__main__":
    main()
