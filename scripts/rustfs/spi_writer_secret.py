#!/usr/bin/env python3
"""OFFLINE ONLY: render the dedicated SPI writer Secret; no API calls."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import stat
from pathlib import Path


def private_json(path: Path) -> object:
    """Execute private_json."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.getuid()
            or st.st_mode & 0o077
            or st.st_size > 65536
        ):
            raise ValueError
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError
    return json.loads(raw)


def render(directory: str | Path) -> None:
    """Execute render."""
    try:
        d = Path(directory)
        st = d.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise ValueError
        raw = private_json(d / "storage.json")
        if not isinstance(raw, dict):
            raise ValueError
        storage: dict[str, dict[str, str]] = {}
        for role in ("root", "reader", "writer"):
            row = raw.get(role)
            if not isinstance(row, dict):
                raise ValueError
            storage[role] = {}
            for field in ("access", "secret"):
                value = row.get(field)
                if (
                    not isinstance(value, str)
                    or not 1 <= len(value) <= 2048
                    or any(ord(c) < 33 or ord(c) > 126 for c in value)
                ):
                    raise ValueError
                storage[role][field] = value
        for field in ("access", "secret"):
            if len({row[field] for row in storage.values()}) != 3:
                raise ValueError
        intended = {
            storage[r]["access"]: hashlib.sha256(storage[r]["secret"].encode()).hexdigest()
            for r in ("reader", "writer")
        }
        if private_json(d / "bootstrap-journal.json") != intended:
            raise ValueError
        payload = json.dumps(
            {k: storage["writer"][k] for k in ("access", "secret")},
            separators=(",", ":"),
        ).encode()
        doc = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "spi-evidence-writer", "namespace": "automation"},
            "type": "Opaque",
            "data": {"credentials.json": base64.b64encode(payload).decode()},
        }
        output = d / "spi-evidence-writer.secret.json"
        if output.exists() or output.is_symlink():
            if private_json(output) != doc:
                raise ValueError
            return
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(doc, stream)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        raise ValueError("SPI_WRITER_SECRET_PREPARATION_REFUSED") from None


def main() -> None:
    """Execute main."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        render(args.private_dir)
    except (OSError, ValueError):
        raise SystemExit("SPI_WRITER_SECRET_PREPARATION_REFUSED") from None


if __name__ == "__main__":
    main()
