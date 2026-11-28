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
from typing import cast

from ci.quality.closed_root_backend import entries, plain, view

ROOT = Path(__file__).resolve().parents[2]
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def install(record: dict[str, object], destination: Path) -> None:
    """Fetch and place one checksum-locked tool binary; never execute an installer."""
    name = plain(record["name"])
    if name not in {
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
        reason = "Unknown or escaping tool name"
        raise ValueError(reason)
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
            plain(record["url"]),
        ],
        capture_output=True,
        timeout=1820,
        check=True,
    )
    data = process.stdout
    if len(data) > MAX_ARCHIVE_BYTES:
        reason = "Tool archive exceeds limit"
        raise ValueError(reason)
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        reason = "Tool checksum mismatch"
        raise ValueError(reason)
    if record["member"]:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = archive.getmember(plain(record["member"]))
            if not member.isfile() or member.size > MAX_ARCHIVE_BYTES:
                reason = "Unsafe tool archive member"
                raise ValueError(reason)
            extraction = archive.extractfile(member)
            if extraction is None:
                reason = "Unsafe tool archive member"
                raise ValueError(reason)
            data = extraction.read()
    target = destination / name
    target.write_bytes(data)
    target.chmod(0o755)


def main() -> None:
    """Install the requested checksum-locked tools for this platform."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", nargs="+")
    args = parser.parse_args()
    key = f"{platform.system().lower()}-{platform.machine()}"
    lock: object = json.loads((ROOT / "ci/quality/tools.lock.json").read_text())
    platforms = view(lock)["platforms"]
    if key not in view(platforms):
        reason = f"Unsupported tool platform: {key}"
        raise ValueError(reason)
    destination = ROOT / ".quality-tools/bin"
    destination.mkdir(parents=True, exist_ok=True)
    records = cast("list[dict[str, object]]", entries(view(platforms)[key]))
    if args.tools:
        requested = set(args.tools)
        if requested - {plain(record["name"]) for record in records}:
            reason = "Unknown tool requested"
            raise ValueError(reason)
        records = [record for record in records if plain(record["name"]) in requested]
    for record in records:
        install(record, destination)
    if os.environ.get("GITHUB_PATH"):
        with Path(os.environ["GITHUB_PATH"]).open("a") as stream:
            stream.write(str(destination) + "\n")
    print(f"Installed {len(records)} checksum-locked tools in {destination}")


if __name__ == "__main__":
    main()
