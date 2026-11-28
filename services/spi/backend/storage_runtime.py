"""Fail-closed dedicated file credentials; no ambient AWS credential discovery."""

import json
import os
import stat
from collections.abc import Sequence
from typing import cast

from s3_evidence import S3Evidence

MAX_CREDENTIAL_BYTES = 8192
MAX_CREDENTIAL_VALUE_BYTES = 2048
MIN_PRINTABLE_ORD = 33
MAX_PRINTABLE_ORD = 126
REASON_DUPLICATE_KEY = "invalid credentials"
REASON_BAD_BACKEND = "unknown evidence backend"
REASON_BAD_PATH = "unpinned credentials path"
REASON_BAD_INODE = "unsafe credential inode"
REASON_BAD_SIZE = "oversized credentials"
REASON_BAD_BODY = "invalid credentials body"
CODE_INVALID = "S3_WRITER_CONFIGURATION_INVALID"
CREDENTIALS_PATH = "/s3-writer/credentials.json"


def unique_object(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    """Reject duplicate JSON keys instead of letting the parser keep the last."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            msg = REASON_DUPLICATE_KEY
            raise ValueError(msg)
        result[key] = value
    return result


def _validate_inode(st: os.stat_result) -> None:
    """Accept only the reviewed projected-Secret inode ownership and mode."""
    # Follow projected Secret symlinks, then validate the opened inode (not
    # the symlink mode). Kubernetes root:fsGroup 0440 is intentional.
    if (
        not stat.S_ISREG(st.st_mode)
        or st.st_mode & 0o007
        or st.st_mode & 0o022
        or st.st_uid not in (0, os.getuid())
        or (st.st_mode & 0o040 and st.st_gid not in (os.getgid(), *os.getgroups()))
        or st.st_size > MAX_CREDENTIAL_BYTES
    ):
        raise ValueError(REASON_BAD_INODE)


def _load_credentials(path: object, backend: str) -> tuple[S3Evidence | None, str]:
    """Open the pinned credentials path and build the S3 evidence client."""
    if backend not in ("legacy", "s3"):
        raise ValueError(REASON_BAD_BACKEND)
    if path is None and backend == "legacy":
        return None, backend
    if path != CREDENTIALS_PATH:
        raise ValueError(REASON_BAD_PATH)
    fd = os.open(cast("str", path), os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        st = os.fstat(stream.fileno())
        _validate_inode(st)
        raw = stream.read(MAX_CREDENTIAL_BYTES + 1)
    if len(raw) > MAX_CREDENTIAL_BYTES:
        raise ValueError(REASON_BAD_SIZE)
    value = json.loads(raw, object_pairs_hook=unique_object)
    if (
        not isinstance(value, dict)
        or set(value) != {"access", "secret"}
        or any(
            not isinstance(item, str)
            or not 1 <= len(item) <= MAX_CREDENTIAL_VALUE_BYTES
            or any(ord(char) < MIN_PRINTABLE_ORD or ord(char) > MAX_PRINTABLE_ORD for char in item)
            for item in value.values()
        )
    ):
        raise ValueError(REASON_BAD_BODY)
    return S3Evidence(value["access"], value["secret"]), backend


def load_storage() -> tuple[S3Evidence | None, str]:
    """Resolve the reviewed evidence backend from its fail-closed credentials."""
    backend = os.environ.get("SPI_EVIDENCE_BACKEND", "legacy")
    path = os.environ.get("SPI_S3_WRITER_FILE")
    try:
        return _load_credentials(path, backend)
    except Exception:
        msg = CODE_INVALID
        raise RuntimeError(msg) from None
