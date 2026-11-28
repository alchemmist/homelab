"""Cold full-claim backup: no key on disk, no plaintext archive, never extract arbitrary paths."""

import base64
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import tarfile
from typing import IO, cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = pathlib.Path("/backup")
SRC = pathlib.Path("/source")
TMP = pathlib.Path("/tmp")
NAME = "canvas-cold-20261119"
AAD = b"openhands-full-claim-v2"
CHUNK = 1024 * 1024
MAX_CIPHERTEXT_BYTES = 3 * 1024**3 - 16 * CHUNK
MAX_MEMBER_BYTES = 64 * CHUNK
STREAM_BUFSIZE = 256 * 1024
DB = "openhands/automation/automations.db"
CONV = "openhands/agent-canvas/conversations/"
IDS = ("1ab3985a219341778dd28ec7d54dbfeb", "51a35822a87043cca775fd5e662f0039")
IDS_WITH_PREFIX = tuple(CONV + i + "/" for i in IDS)
HAND = "workspace/the-loop-demo/HANDOFF.md"
CHECKS = {
    DB,
    HAND,
    "openhands/settings.json",
    *(CONV + i + "/base_state.json" for i in IDS),
}


def b64(b: bytes) -> str:
    """Encode raw bytes for the JSON receipt."""
    return base64.b64encode(b).decode("ascii")


def file_digest(p: pathlib.Path) -> str:
    """Return the SHA-256 hex digest of one file on disk."""
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


class _DecryptReader:
    """Streaming decrypt-and-hash reader over one persisted ciphertext part."""

    def __init__(self, f: IO[bytes], key: bytes, iv: bytes, tag: bytes) -> None:
        self.f = f
        self.decrypt = Cipher(algorithms.AES(key), modes.GCM(iv, tag)).decryptor()
        self.decrypt.authenticate_additional_data(AAD)
        self.hash = hashlib.sha256()
        self.done = False

    def read(self, size: int = -1) -> bytes:
        """Decrypt up to size bytes, finishing the tag exactly once at EOF."""
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


def main() -> None:
    """Produce, verify in place, and only then publish one cold backup."""
    os.umask(0o077)
    enc = ROOT / (NAME + ".gcm")
    receipt = ROOT / (NAME + ".json")
    part = ROOT / (NAME + ".partial")
    if any(p.exists() for p in (enc, receipt, part)):
        msg = "Refusing to overwrite an existing cold backup artifact"
        raise RuntimeError(msg)
    if not all((SRC / k).is_dir() for k in ("openhands", "workspace")):
        msg = "Source trees are missing"
        raise RuntimeError(msg)
    key, iv, tag, digest, n = _encrypt_archive(part)
    _verify_ciphertext(part, key, iv, tag, digest)
    seen, events, count = _verify_archive(part, key, iv, tag, digest)
    _verify_receipt_paths(seen, events)
    _verify_sqlite_integrity()
    report = _build_report(key, iv, tag, part, digest, n, events, count)
    os.link(part, enc)
    part.unlink()
    with receipt.open("x") as out:
        json.dump(report, out)
        out.flush()
        os.fsync(out.fileno())
    print(json.dumps(report), flush=True)


def _encrypt_archive(
    part: pathlib.Path,
) -> tuple[bytes, bytes, bytes, "hashlib._Hash", int]:
    """Encrypt the two reviewed source trees into the partial part file."""
    key = os.urandom(32)
    iv = os.urandom(12)
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
        stdout = tar.stdout
        if stdout is None:
            msg = "Tar pipe vanished before reading"
            raise RuntimeError(msg)
        while data := stdout.read(CHUNK):
            digest.update(data)
            n += len(data)
            if n >= MAX_CIPHERTEXT_BYTES:
                msg = "Ciphertext exceeds the reviewed size bound"
                raise RuntimeError(msg)
            dst.write(crypt.update(data))
        if tar.wait() != 0:
            msg = "Source tar failed"
            raise RuntimeError(msg)
        dst.write(crypt.finalize())
        dst.flush()
        os.fsync(dst.fileno())
    if n <= 0:
        msg = "Archive must not be empty"
        raise RuntimeError(msg)
    if part.stat().st_size != n:
        msg = "Persisted ciphertext size mismatch"
        raise RuntimeError(msg)
    return key, iv, crypt.tag, digest, n


def _verify_ciphertext(
    part: pathlib.Path, key: bytes, iv: bytes, tag: bytes, digest: "hashlib._Hash"
) -> None:
    """Authenticate the complete persisted ciphertext BEFORE decoding it."""
    with part.open("rb") as f:
        r = _DecryptReader(f, key, iv, tag)
        while r.read(CHUNK):
            pass
        if not r.done:
            msg = "Decrypting reader stopped before the end of the ciphertext"
            raise RuntimeError(msg)
        if r.hash.digest() != digest.digest():
            msg = "Persisted ciphertext GCM authentication failed"
            raise RuntimeError(msg)


def _verify_archive(
    part: pathlib.Path, key: bytes, iv: bytes, tag: bytes, digest: "hashlib._Hash"
) -> tuple[set[str], dict[str, int], int]:
    """Walk the decrypted archive, checking only the reviewed member paths."""
    seen: set[str] = set()
    events = dict.fromkeys(IDS, 0)
    count = 0
    with part.open("rb") as f:
        r = _DecryptReader(f, key, iv, tag)
        with tarfile.open(fileobj=cast("IO[bytes]", r), mode="r|gz", bufsize=STREAM_BUFSIZE) as tf:
            for m in tf:
                count += 1
                if m.isfile():
                    _verify_member(tf, m, seen, events)
        while r.read(CHUNK):
            pass
        if r.hash.digest() != digest.digest():
            msg = "Archive pass GCM authentication failed"
            raise RuntimeError(msg)
    return seen, events, count


def _verify_member(
    tf: tarfile.TarFile,
    m: tarfile.TarInfo,
    seen: set[str],
    events: dict[str, int],
) -> None:
    """Verify one reviewed archive member or count its history events."""
    _count_history_event(m, events)
    if m.name not in CHECKS | {DB + "-wal"}:
        return
    if m.name in seen:
        msg = "Archive member listed twice: " + m.name
        raise RuntimeError(msg)
    if m.size > MAX_MEMBER_BYTES:
        msg = "Reviewed member exceeds the size bound: " + m.name
        raise RuntimeError(msg)
    seen.add(m.name)
    stream = tf.extractfile(m)
    if stream is None:
        msg = "Reviewed member must be a regular readable file: " + m.name
        raise RuntimeError(msg)
    data = stream.read()
    if hashlib.sha256(data).hexdigest() != file_digest(SRC / m.name):
        msg = "Archive member digest mismatch: " + m.name
        raise RuntimeError(msg)
    if m.name in (DB, DB + "-wal"):
        (TMP / pathlib.PurePosixPath(m.name).name).write_bytes(data)
    elif m.name.endswith(".json"):
        if type(json.loads(data)) is not dict:
            msg = "Reviewed JSON member must hold an object: " + m.name
            raise RuntimeError(msg)
    elif not data.strip():
        msg = "Reviewed member must not be empty: " + m.name
        raise RuntimeError(msg)


def _count_history_event(m: tarfile.TarInfo, events: dict[str, int]) -> None:
    """Count one history event member toward its owning conversation id."""
    for i in IDS_WITH_PREFIX:
        if m.name.startswith(i + "events/event-"):
            events[i.rsplit("/", 1)[0]] += 1
            return


def _verify_receipt_paths(seen: set[str], events: dict[str, int]) -> None:
    """Confirm every reviewed member matched and each conversation has events."""
    if not CHECKS.issubset(seen):
        msg = "Some reviewed members are missing from the archive"
        raise RuntimeError(msg)
    if min(events.values()) <= 0:
        msg = "Each reviewed conversation must keep its history events"
        raise RuntimeError(msg)


def _verify_sqlite_integrity() -> None:
    """Check the restored automation database trustingly, inside the sandbox."""
    with sqlite3.connect(TMP / "automations.db") as db:
        if db.execute("pragma integrity_check").fetchall() != [("ok",)]:
            msg = "Restored sqlite integrity check failed"
            raise RuntimeError(msg)
        if db.execute("select count(*) from sqlite_master where type='table'").fetchone()[0] <= 0:
            msg = "Restored sqlite database must keep its tables"
            raise RuntimeError(msg)


def _build_report(
    key: bytes,
    iv: bytes,
    tag: bytes,
    part: pathlib.Path,
    digest: "hashlib._Hash",
    n: int,
    events: dict[str, int],
    count: int,
) -> dict[str, object]:
    """Wrap the symmetric key with the reviewed RSA-OAEP recipient."""
    public = serialization.load_pem_public_key(pathlib.Path("/config/recipient.pem").read_bytes())
    if isinstance(public, rsa.RSAPublicKey):
        wrapped = public.encrypt(
            key,
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
    else:
        msg = "Recipient key must be an RSA public key"
        raise RuntimeError(msg)
    return {
        "format": AAD.decode(),
        "cipher": "AES-256-GCM",
        "wrapped_key": b64(wrapped),
        "wrap": "RSA-OAEP-SHA256",
        "iv": b64(iv),
        "tag": b64(tag),
        "key_sha256": hashlib.sha256(key).hexdigest(),
        "ciphertext_sha256": file_digest(part),
        "tar_gz_sha256": digest.hexdigest(),
        "bytes": n,
        "members": count,
        "history_events": events,
        "restored_sqlite_integrity": "ok",
        "verified_settings_and_handoff": True,
        "excluded": [],
    }


if __name__ == "__main__":
    main()
