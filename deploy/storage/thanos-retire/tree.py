"""Strict inventory of the retired FILESYSTEM bucket only; no symlinks or mounts."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from pathlib import Path

ID = r"[0-9A-HJKMNP-TV-Z]{26}"
FILE = re.compile(rf"{ID}/(?:index|meta\.json|deletion-mark\.json|chunks/[0-9]{{6}})")
DIR = re.compile(rf"{ID}(?:/chunks)?")


class Manifest(TypedDict):
    """JSON inventory; each file maps to its size and SHA-256, in that order."""

    dirs: list[str]
    files: dict[str, list[int | str]]


def shape(root: Path) -> tuple[dict[str, int], list[str]]:
    assert root.is_dir()
    assert not root.is_symlink()
    dev = root.stat().st_dev
    files = {}
    dirs = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        assert st.st_dev == dev
        if stat.S_ISDIR(st.st_mode):
            assert DIR.fullmatch(rel), rel
            dirs.append(rel)
        else:
            assert stat.S_ISREG(st.st_mode) and FILE.fullmatch(rel), rel
            files[rel] = st.st_size
    assert files
    assert dirs
    for u in (d for d in dirs if "/" not in d):
        assert u + "/index" in files
        assert u + "/meta.json" in files
        assert any(k.startswith(u + "/chunks/") for k in files)
        assert json.loads((root / u / "meta.json").read_bytes())["ulid"] == u
    return files, dirs


def checksum(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while b := f.read(2**20):
            h.update(b)
    return h.hexdigest()


def manifest(root: Path) -> Manifest:
    files, dirs = shape(root)
    return {
        "dirs": dirs,
        "files": {p: [n, checksum(root / p)] for p, n in files.items()},
    }


def digest(m: Manifest) -> str:
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
