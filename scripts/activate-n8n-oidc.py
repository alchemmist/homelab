#!/usr/bin/env python3
"""Activate n8n's DB-backed native OIDC login for the Authentik client socrat-n8n.

n8n 1.x stores the OIDC client config in its own database (settings key
`features.oidc`), encrypted with N8N_ENCRYPTION_KEY, plus the single
authentication-method switch. The owner UI is the normal path; this script is
the operator equivalent for locked-down instances:

- reads client credentials from Secret automation/socrat-authentik-n8n
  (provisioned by scripts/provision-n8n-oidc.py) and the early verified
  private journal in ~/.config/homelab/n8n-oidc/oidc/client.json;
- never prints secrets (only digests/lengths);
- snapshots both touched rows to a private, reversible before-file;
- refuses to run if OIDC is already configured (owner-owned area);
- writes both rows in one transaction: features.oidc and
  userManagement.authenticationMethod='oidc' (password login stays available
  for the instance owner; non-owner users need SSO or the manual-login flag).

Requires the chart's authentikPublicAlias hostAlias to be live (n8n must be
able to reach the Authentik discovery endpoint)."""

import argparse
import base64
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

ROOT = Path(__file__).resolve().parents[1]
PG_NS, PG_POD, PG_DB = "postgres", "pg-common-1", "n8n"
SECRET = ["-n", "automation", "secret", "socrat-authentik-n8n"]
DISCOVERY = (
    "https://auth.socrat.alchemmist.xyz/application/o/n8n/"
    ".well-known/openid-configuration"
)
FEATURES_KEY = "features.oidc"
METHOD_KEY = "userManagement.authenticationMethod"


def kubectl(*args, check=True, input=None) -> str:
    out = subprocess.run(
        ["kubectl", *args], capture_output=True, input=input, check=False
    )
    if check and out.returncode:
        raise SystemExit("kubectl failed: " + out.stderr.decode())
    return out.stdout.decode()


def private(path) -> None:
    info = path.lstat()
    if path.is_symlink() or info.st_nlink != 1 or info.st_mode & 0o077:
        raise SystemExit("Refusing non-private file: " + str(path))


def cipher_encrypt(plain, key) -> str:
    """Replicate n8n packages/core Cipher (CryptoJS-compatible)."""
    salt = os.urandom(8)
    password = key.encode("latin-1") + salt
    hash1 = hashlib.md5(password).digest()
    hash2 = hashlib.md5(hash1 + password).digest()
    iv = hashlib.md5(hash2 + password).digest()
    enc_key = hash1 + hash2
    padder = PKCS7(128).padder()
    data = padder.update(plain.encode()) + padder.finalize()
    enc = Cipher(algorithms.AES(enc_key), modes.CBC(iv)).encryptor()
    out = enc.update(data) + enc.finalize()
    return base64.b64encode(b"Salted__" + salt + out).decode()


def rows_sql() -> tuple[str, str]:
    select = (
        'SELECT key, value, "loadOnStartup" FROM settings '
        f"WHERE key IN ('{FEATURES_KEY}', '{METHOD_KEY}') ORDER BY key;"
    )
    out = kubectl("exec", "-n", PG_NS, PG_POD, "--", "psql", "-U", "postgres", "-d", PG_DB, "-At", "-c", select)
    return out.strip(), select


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    state = Path.home() / ".config/homelab/n8n-oidc/activate"
    p.add_argument("--state-dir", type=Path, default=state)
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    os.umask(0o077)
    a.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = kubectl("get", *SECRET, "-o", "json")
    sec = json.loads(raw)["data"]
    client_id = base64.b64decode(sec["client-id"]).decode()
    client_secret = base64.b64decode(sec["client-secret"]).decode()
    journal_path = Path.home() / ".config/homelab/n8n-oidc/oidc/client.json"
    private(journal_path)
    journal = json.loads(journal_path.read_text())
    if journal.get("status") != "active" or journal["client_secret"] != client_secret:
        raise SystemExit("Secret/journal drift; run scripts/provision-n8n-oidc.py first")
    ekey = base64.b64decode(
        json.loads(kubectl("-n", "automation", "get", "secret", "n8n-secrets", "-o", "json"))[
            "data"
        ]["encryption-key"]
    ).decode()
    before, _ = rows_sql()
    already = FEATURES_KEY in before
    plan = {
        "rows_to_write": 2 if not already else 0,
        "client_id": client_id,
        "discovery": DISCOVERY,
        "auth_method_switch": "email -> oidc" if "email" in before else None,
        "client_secret_sha256": hashlib.sha256(client_secret.encode()).hexdigest()[:12],
    }
    if not a.apply:
        print(json.dumps({"plan": plan, "existing_rows": before}))
        return
    if already:
        raise SystemExit("features.oidc already present; owner-UI owns changes from here")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snap = a.state_dir / ("settings-before-" + stamp + ".json")
    fd = os.open(snap, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"sel": before, "observedAt": datetime.now(UTC).isoformat()}, f)
    value_payload = json.dumps(
        {
            "clientId": client_id,
            "clientSecret": cipher_encrypt(client_secret, ekey),
            "discoveryEndpoint": DISCOVERY,
            "loginEnabled": True,
            "prompt": "select_account",
            "authenticationContextClassReference": [],
        }
    )
    sql = (
        "BEGIN;"
        "INSERT INTO settings (key, value, \"loadOnStartup\") "
        "VALUES ('"
        + FEATURES_KEY
        + "', $secret$"
        + value_payload
        + "$secret$, true);"
        "INSERT INTO settings (key, value, \"loadOnStartup\") "
        "VALUES ('"
        + METHOD_KEY
        + "', 'oidc', true) "
        "ON CONFLICT (key) DO UPDATE SET value='oidc', \"loadOnStartup\"=true;"
        "COMMIT;"
    )
    kubectl(
        "exec",
        "-n",
        PG_NS,
        PG_POD,
        "--",
        "psql",
        "-U",
        "postgres",
        "-d",
        PG_DB,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    )
    after, _ = rows_sql()
    ok = FEATURES_KEY in after and "'oidc'" in after + kubectl(
        "exec", "-n", PG_NS, PG_POD, "--", "psql", "-U", "postgres", "-d", PG_DB, "-At", "-c",
        "SELECT value FROM settings WHERE key='" + METHOD_KEY + "';",
    )
    print(json.dumps({"applied": bool(ok), "snapshot": str(snap)}))


if __name__ == "__main__":
    main()
