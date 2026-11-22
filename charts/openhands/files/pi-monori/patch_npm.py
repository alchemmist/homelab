"""Rebuild reviewed npm artifacts from pinned upstream bytes; never run package code."""

import argparse
import base64
import hashlib
import io
import json
import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# Keys are upstream identities (also used for advisory lookup), not package aliases.
SOURCES = {
    "argocd-mcp": (
        "0.9.0",
        "5xfz8JB2ZNCcl/fvkJJnX1aH7AdmSD68cZDY/xzwRoBtoedfDXnwEKN3TBcItFkr0IDpMNR4sXwcsEE4R14trw==",
    ),
    "@google/genai": (
        "2.32.0",
        "60c79uXpR0a47bmGqDxbXEBuQUalNmwo5mx5kqb91jIW4FoqpsLSt86DeVhRhtH5+s/16Wqxt3sXzFQn2U1OHQ==",
    ),
    "protobufjs": (
        "7.6.6",
        "dYDWdjSl5RNb7SgPxGQcRU+GtvP7s2fpkrY0r432PcOIaZ0/rBcxEZnQN67iJhFuQiVw754JDoPruPCNdGsbjg==",
    ),
}
GROUPS = {"argo": ("argocd-mcp",), "pi": ("@google/genai", "protobufjs")}


def rewrite(name: str, path: str, data: bytes) -> bytes:
    """Modify only reviewed runtime/manifest fields in verified release archives."""
    if path == "package/package.json":
        manifest = json.loads(data)
        if name == "argocd-mcp":
            manifest["dependencies"]["zod"] = "^4.6.7"
        elif name == "protobufjs":
            # This optional range-style warning does not build or install anything.
            del manifest["scripts"]["postinstall"]
        else:
            # Upstream literally echoes 'preinstall: no-op'.
            del manifest["scripts"]["preinstall"]
        return (json.dumps(manifest, indent=2) + "\n").encode()
    if name == "argocd-mcp" and path == "package/dist/index.js":
        return (
            data.replace(b'from "zod"', b'from "zod/v4"')
            .replace(b'zod: "^3.25.0"', b'zod: "^4.6.7"')
            .replace(
                b"this.tool(name, description, mergedSchema,",
                b"this.registerTool(name, { description, inputSchema: mergedSchema },",
            )
        )
    return data


def materialize(name: str, directory: Path, offline: bool) -> None:
    """Make a deterministic uncompressed tar, checked by npm ci against the lock."""
    version, digest = SOURCES[name]
    stem = f"{name.rsplit('/', 1)[-1]}-{version}"
    dest = directory / f"{stem}-homelab.tar"
    if offline:
        # npm ci verifies the materialized artifact integrity even on offline installs.
        if not dest.is_file() or dest.is_symlink():
            raise ValueError(f"Offline setup needs {dest.name} from a previous setup")
        verify(dest, name, directory)
        return
    with urllib.request.urlopen(
        f"https://registry.npmjs.org/{name}/-/{stem}.tgz", timeout=30
    ) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if hashlib.sha512(raw).digest() != base64.b64decode(digest):
        raise ValueError(f"Unexpected upstream bytes for {name}")
    with tempfile.TemporaryDirectory(dir=directory) as staging:
        tmp = Path(staging) / "patched.tar"
        with (
            tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as src,
            tarfile.open(name=tmp, mode="w", format=tarfile.GNU_FORMAT) as out,
        ):
            for member in src:
                if not member.isfile():
                    raise ValueError(f"Unexpected non-regular member: {member.name}")
                body = rewrite(name, member.name, src.extractfile(member).read())
                header = tarfile.TarInfo(member.name)
                header.size = len(body)
                header.mode = member.mode
                out.addfile(header, io.BytesIO(body))
        verify(tmp, name, directory)
        os.replace(tmp, dest)


def verify(path: Path, name: str, directory: Path) -> None:
    """Bind the bytes consumed by npm to its actual lock, including offline reuse."""
    lock = json.loads((directory / "package-lock.json").read_text())
    expected = lock["packages"][f"node_modules/{name}"]["integrity"]
    if (
        "sha512-" + base64.b64encode(hashlib.sha512(path.read_bytes()).digest()).decode()
        != expected
    ):
        raise ValueError(f"Rebuilt artifact does not match lock: {name}")


def main() -> None:
    """Materialize only the requested consumer's patches."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("consumer", choices=GROUPS)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    for name in GROUPS[args.consumer]:
        materialize(name, Path.cwd(), args.offline)


if __name__ == "__main__":
    main()
