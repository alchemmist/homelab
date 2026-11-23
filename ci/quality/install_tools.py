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


def install(record, destination) -> None:
    """Execute install."""
    if record["name"] not in {
        "trivy",
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
        msg = "Unknown or escaping tool name"
        raise ValueError(msg)
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
            "--retry",
            "2",
            "--connect-timeout",
            "10",
            "--max-time",
            "600",
            record["url"],
        ],
        capture_output=True,
        timeout=1820,
        check=True,
    )
    data = process.stdout
    if len(data) > 256 * 1024 * 1024:
        msg = "Tool archive exceeds limit"
        raise ValueError(msg)
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        msg = "Tool checksum mismatch"
        raise ValueError(msg)
    if record["member"]:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = archive.getmember(record["member"])
            if not member.isfile() or member.size > 256 * 1024 * 1024:
                msg = "Unsafe tool archive member"
                raise ValueError(msg)
            data = archive.extractfile(member).read()
    target = destination / record["name"]
    target.write_bytes(data)
    target.chmod(0o755)


def main() -> None:
    """Execute main."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", nargs="+")
    args = parser.parse_args()
    key = f"{platform.system().lower()}-{platform.machine()}"
    lock = json.loads((ROOT / "ci/quality/tools.lock.json").read_text())
    if key not in lock["platforms"]:
        msg = f"Unsupported tool platform: {key}"
        raise ValueError(msg)
    destination = ROOT / ".quality-tools/bin"
    destination.mkdir(parents=True, exist_ok=True)
    records = lock["platforms"][key]
    if args.tools:
        if set(args.tools) - {r["name"] for r in records}:
            msg = "Unknown tool requested"
            raise ValueError(msg)
        records = [r for r in records if r["name"] in args.tools]
    for record in records:
        install(record, destination)
    if os.environ.get("GITHUB_PATH"):
        with open(os.environ["GITHUB_PATH"], "a") as stream:
            stream.write(str(destination) + "\n")
    print(f"Installed {len(records)} checksum-locked tools in {destination}")


if __name__ == "__main__":
    main()
