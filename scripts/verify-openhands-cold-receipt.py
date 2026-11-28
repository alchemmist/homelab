"""Verify a completed cold-archive receipt using the operator's recovery key (never sent to pod)."""

import base64
import hashlib
import json
import os
import pathlib
import subprocess

os.umask(0o077)
ns = "openhands"
job = "openhands-cold-backup-20261119"
home = pathlib.Path.home() / ".config/homelab/openhands/backups"
RECOVERY_KEY_BYTES = 32


def k(*args: str) -> bytes:
    """Run one reviewed kubectl call in the openhands namespace."""
    return subprocess.check_output(["kubectl", "-n", ns, *args])


state = json.loads(k("get", "job", job, "-o", "json"))
if not any(
    c["type"] == "Complete" and c["status"] == "True" for c in state["status"]["conditions"]
):
    msg = "cold-backup job has not completed successfully"
    raise RuntimeError(msg)
lines = k("logs", "job/" + job).splitlines()
r = json.loads(next(line for line in reversed(lines) if line.startswith(b"{")))
if r["format"] != "openhands-full-claim-v2":
    msg = "receipt claim format changed"
    raise RuntimeError(msg)
if r["restored_sqlite_integrity"] != "ok":
    msg = "restored sqlite integrity failed"
    raise RuntimeError(msg)
if not r["verified_settings_and_handoff"]:
    msg = "settings and handoff verification failed"
    raise RuntimeError(msg)
if min(r["history_events"].values()) <= 0:
    msg = "history events counters are empty"
    raise RuntimeError(msg)
if r["excluded"] != []:
    msg = "receipt lists excluded members"
    raise RuntimeError(msg)
key = subprocess.check_output(
    [
        "openssl",
        "pkeyutl",
        "-decrypt",
        "-inkey",
        str(home / "upgrade-rsa.pem"),
        "-pkeyopt",
        "rsa_padding_mode:oaep",
        "-pkeyopt",
        "rsa_oaep_md:sha256",
    ],
    input=base64.b64decode(r["wrapped_key"], validate=True),
)
if len(key) != RECOVERY_KEY_BYTES:
    msg = "unwrapped recovery key has the wrong length"
    raise RuntimeError(msg)
if hashlib.sha256(key).hexdigest() != r["key_sha256"]:
    msg = "operator-side unwrap digest mismatch"
    raise RuntimeError(msg)
del key
r.update(
    job_uid=state["metadata"]["uid"],
    completed_at=state["status"]["completionTime"],
    operator_unwrap_verified=True,
    claim="openhands-cold-backups",
    archive="canvas-cold-20261119.gcm",
)
p = home / "canvas-cold-20261119-receipt.json"
if p.exists():
    if json.loads(p.read_bytes()) != r:
        msg = "receipt on disk differs from the verified claim"
        raise RuntimeError(msg)
else:
    with p.open("x") as out:
        json.dump(r, out)
        out.flush()
        os.fsync(out.fileno())
print(
    "verified",
    r["bytes"],
    "ciphertext bytes;",
    r["members"],
    "archive members; events:",
    r["history_events"],
    "; local private-key unwrap OK; sha256:",
    r["ciphertext_sha256"],
)
