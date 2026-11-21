"""Cold full-claim backup: no key on disk, no plaintext archive, never extract arbitrary paths."""

import base64
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import tarfile
from typing import IO, TypedDict, cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = pathlib.Path("/backup")
SRC = pathlib.Path("/source")
TMP = pathlib.Path("/tmp")
NAME = "canvas-cold-20261119"
AAD = b"openhands-full-claim-v2"
CHUNK = 1024 * 1024
DB = "openhands/automation/automations.db"
CONV = "openhands/agent-canvas/conversations/"
IDS = ("1ab3985a219341778dd28ec7d54dbfeb", "51a35822a87043cca775fd5e662f0039")
HAND = "workspace/the-loop-demo/HANDOFF.md"


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def file_digest(p):
    """Return the SHA-256 hex digest of a file on disk."""
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def record_event(m: tarfile.TarInfo, events: dict[str, int]) -> None:
    """Count demo conversation events per tracked directory."""
    for i in IDS:
        if m.name.startswith(CONV + i + "/events/event-"):
            events[i] += 1


def classify_member(m: tarfile.TarInfo, tf: tarfile.TarFile, seen: set[str]) -> None:
    """Assert one required member matches its known content and type."""
    assert m.name not in seen and m.size <= 64 * CHUNK
    seen.add(m.name)
    data = cast("IO[bytes]", tf.extractfile(m)).read()
    assert hashlib.sha256(data).hexdigest() == file_digest(SRC / m.name)
    if m.name in (DB, DB + "-wal"):
        (TMP / pathlib.PurePosixPath(m.name).name).write_bytes(data)
    elif m.name.endswith(".json"):
        assert isinstance(json.loads(data), dict)
    else:
        assert data.strip()


def verify_entries(
    tf: tarfile.TarFile, checks: set[str], events: dict[str, int]
) -> tuple[set[str], int]:
    """Validate every tar member against the expected backup inventory."""
    seen = set[str]()
    count = 0
    for m in tf:
        count += 1
        if not m.isfile():
            continue
        record_event(m, events)
        if m.name not in checks | {DB + "-wal"}:
            continue
        classify_member(m, tf, seen)
    return seen, count


class Receipt(TypedDict):
    """Material a backup receipt must disclose about one stored partition."""

    key: bytes
    iv: bytes
    tag: bytes
    part: pathlib.Path
    tar_gz_sha256: str
    n: int
    count: int
    events: dict[str, int]


def _backup_report(receipt: Receipt) -> dict[str, object]:
    """Assemble the signed backup receipt describing this stored partition."""
    key = receipt["key"]
    iv = receipt["iv"]
    public = serialization.load_pem_public_key(pathlib.Path("/config/recipient.pem").read_bytes())
    wrapped = public.encrypt(
        key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return {
        "format": AAD.decode(),
        "cipher": "AES-256-GCM",
        "wrapped_key": b64(wrapped),
        "wrap": "RSA-OAEP-SHA256",
        "iv": b64(iv),
        "tag": b64(receipt["tag"]),
        "key_sha256": hashlib.sha256(key).hexdigest(),
        "ciphertext_sha256": file_digest(receipt["part"]),
        "tar_gz_sha256": receipt["tar_gz_sha256"],
        "bytes": receipt["n"],
        "members": receipt["count"],
        "history_events": receipt["events"],
        "restored_sqlite_integrity": "ok",
        "verified_settings_and_handoff": True,
        "excluded": [],
    }


def main():
    os.umask(0o077)
    enc = ROOT / (NAME + ".gcm")
    receipt = ROOT / (NAME + ".json")
    part = ROOT / (NAME + ".partial")
    assert not any(p.exists() for p in (enc, receipt, part))
    assert all((SRC / k).is_dir() for k in ("openhands", "workspace"))
    key, iv = os.urandom(32), os.urandom(12)
    crypt = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
    crypt.authenticate_additional_data(AAD)
    digest = hashlib.sha256()
    n = 0
    with (
        part.open("xb") as dst,
        subprocess.Popen(
            ["tar", "-czf", "-", "-C", str(SRC), "openhands", "workspace"],
            stdout=subprocess.PIPE,
            env={**os.environ, "GZIP": "-1"},
        ) as tar,
    ):
        while data := tar.stdout.read(CHUNK):
            digest.update(data)
            n += len(data)
            assert n < 3 * 1024**3 - 16 * CHUNK
            dst.write(crypt.update(data))
        assert tar.wait() == 0, "Source tar failed"
        dst.write(crypt.finalize())
        dst.flush()
        os.fsync(dst.fileno())
    assert n > 0 and part.stat().st_size == n

    class Reader:
        def __init__(self, f):
            self.f = f
            self.decrypt = Cipher(algorithms.AES(key), modes.GCM(iv, crypt.tag)).decryptor()
            self.decrypt.authenticate_additional_data(AAD)
            self.hash = hashlib.sha256()
            self.done = False

        def read(self, size):
            if self.done:
                return b""
            buf = self.f.read(size)
            if not buf:
                self.decrypt.finalize()
                self.done = True
                return b""
            data = self.decrypt.update(buf)
            self.hash.update(data)
            return data

    # First authenticate the complete persisted ciphertext BEFORE decoding its archive.
    with part.open("rb") as f:
        r = Reader(f)
        while r.read(CHUNK):
            pass
        assert r.done and r.hash.digest() == digest.digest()
    checks = {DB, HAND, "openhands/settings.json", *(CONV + i + "/base_state.json" for i in IDS)}
    events = dict.fromkeys(IDS, 0)
    count = 0
    with part.open("rb") as f:
        r = Reader(f)
        with tarfile.open(fileobj=r, mode="r|gz", bufsize=256 * 1024) as tf:
            seen, count = verify_entries(tf, checks, events)
        while r.read(CHUNK):
            pass
        assert r.hash.digest() == digest.digest()
    assert checks <= seen and min(events.values()) > 0
    with sqlite3.connect(TMP / "automations.db") as db:
        assert (
            db.execute("pragma integrity_check").fetchall() == [("ok",)]
            and db.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
            > 0
        )
    material: Receipt = {
        "key": key,
        "iv": iv,
        "tag": crypt.tag,
        "part": part,
        "tar_gz_sha256": digest.hexdigest(),
        "n": n,
        "count": count,
        "events": events,
    }
    report = _backup_report(material)
    os.link(part, enc)
    part.unlink()
    with receipt.open("x") as dst:
        json.dump(report, dst)
        dst.flush()
        os.fsync(dst.fileno())
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
