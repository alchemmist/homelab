"""Strict inventory of the retired FILESYSTEM bucket only; no symlinks or mounts."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    import os
    from pathlib import Path

ID = r"[0-9A-HJKMNP-TV-Z]{26}"
FILE = re.compile(rf"{ID}/(?:index|meta\.json|deletion-mark\.json|chunks/[0-9]{{6}})")
DIR = re.compile(rf"{ID}(?:/chunks)?")


class Manifest(TypedDict):
    """JSON inventory; each file maps to its size and SHA-256, in that order."""

    dirs: list[str]
    files: dict[str, list[int | str]]


def shape(root: Path) -> tuple[dict[str, int], list[str]]:
    """Walk the retired tree and verify every reviewed shape and boundary."""
    if not root.is_dir():
        msg = "Inventory root must be a directory"
        raise RuntimeError(msg)
    if root.is_symlink():
        msg = "Inventory root must not be a symlink"
        raise RuntimeError(msg)
    dev = root.stat().st_dev
    files = {}
    dirs = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        _require_same_mount(st, dev, rel)
        if stat.S_ISDIR(st.st_mode):
            _require_dir_shape(rel)
            dirs.append(rel)
        else:
            _require_file_shape(st, rel)
            files[rel] = st.st_size
    _verify_nonempty(files, dirs)
    _verify_blocks(root, files, dirs)
    return files, dirs


def _require_same_mount(st: os.stat_result, dev: int, rel: str) -> None:
    """Refuse to walk across mount boundaries inside a retired bucket."""
    if st.st_dev != dev:
        msg = "Crossed a mount boundary during tree walk: " + rel
        raise RuntimeError(msg)


def _require_dir_shape(rel: str) -> None:
    """Accept only reviewed block or chunk directory names."""
    if not DIR.fullmatch(rel):
        msg = "Unexpected directory rejected: " + rel
        raise RuntimeError(msg)


def _require_file_shape(st: os.stat_result, rel: str) -> None:
    """Accept only reviewed regular files inside the retired bucket."""
    if not stat.S_ISREG(st.st_mode):
        msg = "Only regular files are allowed: " + rel
        raise RuntimeError(msg)
    if not FILE.fullmatch(rel):
        msg = "Unexpected file rejected: " + rel
        raise RuntimeError(msg)


def _verify_nonempty(files: dict[str, int], dirs: list[str]) -> None:
    """Refuse an empty tree during release preparation."""
    if not files:
        msg = "Retired tree must contain files"
        raise RuntimeError(msg)
    if not dirs:
        msg = "Retired tree must contain block directories"
        raise RuntimeError(msg)


def _verify_blocks(root: Path, files: dict[str, int], dirs: list[str]) -> None:
    """Verify each ULID block carries its index, meta.json, chunk and identity."""
    for u in (d for d in dirs if "/" not in d):
        if u + "/index" not in files:
            msg = "Block is missing its index: " + u
            raise RuntimeError(msg)
        if u + "/meta.json" not in files:
            msg = "Block is missing its meta.json: " + u
            raise RuntimeError(msg)
        if not any(k.startswith(u + "/chunks/") for k in files):
            msg = "Block is missing its chunk directory: " + u
            raise RuntimeError(msg)
        if json.loads((root / u / "meta.json").read_bytes())["ulid"] != u:
            msg = "Block meta ulid mismatch: " + u
            raise RuntimeError(msg)


def checksum(p: Path) -> str:
    """Hash one retired file's bytes with SHA-256."""
    h = hashlib.sha256()
    with p.open("rb") as f:
        while b := f.read(2**20):
            h.update(b)
    return h.hexdigest()


def manifest(root: Path) -> Manifest:
    """Build the reviewed JSON inventory with per-file size and SHA-256."""
    files, dirs = shape(root)
    return {
        "dirs": dirs,
        "files": {p: [n, checksum(root / p)] for p, n in files.items()},
    }


def digest(m: Manifest) -> str:
    """Fingerprint one release manifest, immutably and order-independently."""
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
