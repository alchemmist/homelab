"""Reproduce patched artifacts and exercise real clients with isolated local fixtures."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MCP = ROOT / "tools/official-mcp"


def smoke(group: str, directory: Path) -> None:
    """Install exactly what the consumer installs, without any real credentials."""
    source = MCP
    env = {"HOME": str(directory), "PATH": os.environ["PATH"], "PI_OFFLINE": "1"}

    def run(*args: str) -> str:
        return subprocess.check_output(args, cwd=directory, env=env, text=True, timeout=120)

    shutil.copy(source / "package.json", directory)
    lock = directory / "package-lock.json"
    shutil.copy(source / lock.name, lock)
    run(sys.executable, "-I", str(MCP / "patch_npm.py"), group)
    run("npm", "ci", "--strict-peer-deps", "--ignore-scripts", "--no-fund", "--no-audit")
    run("npm", "ls", "--all")
    for path in json.loads(lock.read_text())["packages"]:
        package = directory / path / "package.json"
        if not package.is_file():
            raise ValueError(f"Locked package missing from {group} install: {path}")
        manifest = json.loads(package.read_text())
        if {"preinstall", "install", "postinstall"}.intersection(manifest.get("scripts", {})):
            raise ValueError(f"Install hook in installed {manifest['name']}")
    if group == "argo":
        shutil.copy(ROOT / "tests/fixtures/npm/mcp-smoke.mjs", directory)
        run("node", "mcp-smoke.mjs")
        # A fresh destination needs only the warmed npm cache, not a previous patch tar.
        offline = directory / "offline"
        offline.mkdir()
        for filename in ("package.json", "package-lock.json"):
            shutil.copy(directory / filename, offline)
        subprocess.run(
            [sys.executable, "-I", str(MCP / "patch_npm.py"), group, "--offline"],
            cwd=offline,
            env=env,
            timeout=120,
            check=True,
        )
        subprocess.run(
            [
                "npm",
                "ci",
                "--offline",
                "--strict-peer-deps",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
            ],
            cwd=offline,
            env=env,
            timeout=120,
            check=True,
        )
    print(f"{group}: clean install and fixture smoke passed", flush=True)


if __name__ == "__main__":
    for consumer in ("argo",):
        with tempfile.TemporaryDirectory() as temp:
            smoke(consumer, Path(temp))
