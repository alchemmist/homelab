"""Install reviewed Ansible parsing dependencies locally, never managed-host code."""

import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    records = json.loads((ROOT / "quality/collections.lock.json").read_text())["collections"]
    executable = shutil.which("ansible-galaxy")
    if executable is None:
        raise ValueError("Locked ansible-galaxy is required")
    destination = ROOT / ".quality-tools/collections"
    with tempfile.TemporaryDirectory(prefix="qg-collections-") as directory:
        for item in records:
            if item["name"] not in {"community-general", "ansible-posix"}:
                raise ValueError("Unreviewed collection")
            filename = item["name"] + "-" + item["version"] + ".tar.gz"
            data = subprocess.run(  # noqa: S603 -- fixed HTTPS artifact origin, checksum verified
                [
                    "/usr/bin/curl",
                    "--proto",
                    "=https",
                    "--proto-redir",
                    "=https",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--max-time",
                    "60",
                    "https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/collections/artifacts/"
                    + filename,
                ],
                capture_output=True,
                check=True,
                timeout=65,
            ).stdout
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("Collection checksum mismatch")
            archive = Path(directory) / filename
            archive.write_bytes(data)
            subprocess.run(  # noqa: S603 -- only the verified local archive, no implicit dependencies
                [
                    executable,
                    "collection",
                    "install",
                    str(archive),
                    "--offline",
                    "--no-deps",
                    "--collections-path",
                    str(destination),
                ],
                check=True,
                timeout=60,
            )


if __name__ == "__main__":
    main()
