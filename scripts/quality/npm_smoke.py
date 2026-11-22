"""Reproduce patched artifacts and exercise real clients with isolated local fixtures."""

import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PI = ROOT / "charts/openhands/files/pi-monori"


def smoke(group: str, directory: Path) -> None:
    """Install exactly what the consumer installs, without any real credentials."""
    source = PI if group == "pi" else ROOT / "tools/official-mcp"
    env = {"HOME": str(directory), "PATH": os.environ["PATH"], "PI_OFFLINE": "1"}

    def run(*args: str) -> str:
        return subprocess.check_output(args, cwd=directory, env=env, text=True, timeout=120)

    shutil.copy(source / "package.json", directory)
    lock = directory / "package-lock.json"
    if group == "pi":
        lock.write_bytes(gzip.decompress((source / "package-lock.json.gz").read_bytes()))
    else:
        shutil.copy(source / lock.name, lock)
    run(sys.executable, "-I", str(PI / "patch_npm.py"), group)
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
    else:
        pi = "node_modules/.bin/pi"
        agent = directory / ".pi/agent"
        agent.mkdir(parents=True, exist_ok=True)
        shutil.copy(PI / "models.json", agent)
        version = json.loads((directory / "package.json").read_text())["dependencies"][
            "@earendil-works/pi-coding-agent"
        ]
        if run(pi, "--version").strip() != version or "v-deepseek-uc" not in run(
            pi, "--no-extensions", "--no-mcp", "--no-session", "--list-models", "v-deepseek-uc"
        ):
            raise ValueError("Pi CLI did not load the installed version and relay model")
        run(
            "node",
            "--input-type=module",
            "-e",
            "import { GoogleGenAI } from '@google/genai'; new GoogleGenAI({apiKey:'fixture'}); import pb from 'protobufjs'; const T=pb.parse('message T {required int32 n=1;}').root.lookupType('T'); if(T.decode(T.encode({n:42}).finish()).n!==42)throw Error('codec');",
        )
    print(f"{group}: clean install and fixture smoke passed", flush=True)


if __name__ == "__main__":
    for consumer in ("argo", "pi"):
        with tempfile.TemporaryDirectory() as temp:
            smoke(consumer, Path(temp))
