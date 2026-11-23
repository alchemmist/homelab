"""Rebuild reviewed npm artifacts from pinned upstream bytes; never run package code."""

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

# Keys are upstream identities (also used for advisory lookup), not package aliases.
SOURCES = {
    "argocd-mcp": (
        "0.9.0",
        "5xfz8JB2ZNCcl/fvkJJnX1aH7AdmSD68cZDY/xzwRoBtoedfDXnwEKN3TBcItFkr0IDpMNR4sXwcsEE4R14trw==",
    ),
}
GROUPS = {"argo": ("argocd-mcp",)}


def rewrite(name: str, path: str, data: bytes) -> bytes:
    """Modify only reviewed runtime/manifest fields in verified release archives."""
    if path == "package/package.json":
        manifest = json.loads(data)
        if (manifest.get("name"), manifest.get("version")) != (name, SOURCES[name][0]):
            msg = f"Unexpected upstream package identity for {name}"
            raise ValueError(msg)
        if name == "argocd-mcp":
            if manifest.get("dependencies", {}).get("zod") != "^3.25.0":
                msg = "Review the new upstream Zod dependency before patching"
                raise ValueError(msg)
            manifest["dependencies"]["zod"] = "^4.6.7"
        return (json.dumps(manifest, indent=2) + "\n").encode()
    if name == "argocd-mcp" and path == "package/dist/index.js":
        for old, new, count in (
            (b'from "zod"', b'from "zod/v4"', 2),
            (b'zod: "^3.25.0"', b'zod: "^4.6.7"', 1),
            (
                b"this.tool(name, description, mergedSchema,",
                b"this.registerTool(name, { description, inputSchema: mergedSchema },",
                1,
            ),
        ):
            if data.count(old) != count:
                msg = f"Unexpected occurrences of {old!r} in {path}; review the patch"
                raise ValueError(msg)
            data = data.replace(old, new)
    return data


def materialize(name: str, directory: Path, offline: bool) -> None:
    """Make a deterministic uncompressed tar, checked by npm ci against the lock."""
    version, digest = SOURCES[name]
    stem = f"{name.rsplit('/', 1)[-1]}-{version}"
    dest = directory / f"{stem}-homelab.tar"
    if offline and dest.exists():
        if not dest.is_file() or dest.is_symlink():
            msg = f"Unsafe offline artifact: {dest.name}"
            raise ValueError(msg)
        verify(dest, name, directory)
        return
    url = f"https://registry.npmjs.org/{name}/-/{stem}.tgz"
    # The workstation installer supports fresh destinations using just npm's cache.
    with tempfile.TemporaryDirectory(dir=directory) as cached:
        subprocess.run(
            [
                "npm",
                "pack",
                "--ignore-scripts",
                "--silent",
                "--offline" if offline else "--prefer-online",
                url,
            ],
            cwd=cached,
            check=True,
            timeout=60,
            stdout=subprocess.DEVNULL,
        )
        # npm flattens scoped names when naming tarballs. Select the sole
        # regular .tgz in our newly-created private directory, not stdout.
        archives = list(Path(cached).iterdir())
        if (
            len(archives) != 1
            or archives[0].suffix != ".tgz"
            or archives[0].is_symlink()
            or not archives[0].is_file()
        ):
            msg = f"Expected one regular npm pack tarball for {name}@{version}"
            raise ValueError(msg)
        with archives[0].open("rb") as archive:
            raw = archive.read(4 * 1024 * 1024 + 1)

    if hashlib.sha512(raw).digest() != base64.b64decode(digest):
        msg = f"Unexpected upstream SHA-512 for {name}@{version}"
        raise ValueError(msg)
    with tempfile.TemporaryDirectory(dir=directory) as staging:
        tmp = Path(staging) / "patched.tar"
        with (
            tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as src,
            tarfile.open(name=tmp, mode="w", format=tarfile.GNU_FORMAT) as out,
        ):
            for member in src:
                if not member.isfile():
                    msg = f"Unexpected non-regular member: {member.name}"
                    raise ValueError(msg)
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
        msg = f"Rebuilt artifact does not match lock: {name}"
        raise ValueError(msg)


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
