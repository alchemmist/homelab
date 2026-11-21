"""Root-only, scoped Authentik SSH pre/postflight. Never rewrite unsupported hosts.

The playbook holds a host-wide mkdir lock from preflight through postflight.
No marker is inferred from usernames, email, groups or keys.
"""

import argparse
import glob
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import uuid

DIRECTORY = Path("/var/lib/homelab-authentik-ssh-bindings")
CONFIG = Path("/etc/ssh/sshd_config")


def reject_contextual_config(path: Path = CONFIG, seen: set[Path] | None = None) -> None:
    """We cannot prove all Match contexts via one sshd -T -C probe. Reject them.

    Follow OpenSSH Include globs, including inside included files. This deliberately
    supports less than sshd, instead of silently checking one client address only.
    """
    seen = set() if seen is None else seen
    path = path.resolve(strict=True)
    if path in seen or len(seen) >= 100:
        message = "Recursive/oversized SSH configuration unsupported"
        raise ValueError(message)
    seen.add(path)
    for line in path.read_text().splitlines():
        # Deliberately accept a strict subset rather than emulate OpenSSH with
        # shell tokenization: an unquoted # may be literal in an Include path.
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        directive = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)(?:\s*=\s*|\s+)(.*)", stripped)
        if directive is None:
            message = "Unsupported SSH directive syntax"
            raise ValueError(message)
        keyword, arguments = directive.groups()
        if keyword.lower() == "match":
            message = "Contextual SSH configuration unsupported"
            raise ValueError(message)
        if keyword.lower() == "include":
            _reject_included_files(arguments, seen)


def _reject_included_files(arguments: str, seen: set[Path]) -> None:
    """Reject quoted/escaped Include syntax and recurse into pattern matches."""
    # No quotes, escapes, hash, tilde, percent expansions or comments.
    # Administrators may use those with sshd, but this importer refuses
    # them instead of possibly checking a different effective key file.
    patterns = arguments.split()
    if not patterns or any(not re.fullmatch(r"[A-Za-z0-9_./*?\[\]-]+", p) for p in patterns):
        message = "Unsupported SSH Include syntax"
        raise ValueError(message)
    for pattern in patterns:
        if not pattern.startswith("/"):
            pattern = "/etc/ssh/" + pattern
        for included in sorted(glob.glob(pattern)):
            reject_contextual_config(Path(included), seen)


def verify_key_location(name, config=CONFIG):
    'Verify key location.'
    reject_contextual_config(config)
    parsed = subprocess.run(
        [shutil.which("sshd") or "/usr/sbin/sshd", "-T"], text=True, capture_output=True, check=True
    )
    settings = dict(line.split(None, 1) for line in parsed.stdout.splitlines() if line.strip())
    allowed = {
        ".ssh/authorized_keys",
        "%h/.ssh/authorized_keys",
        "/home/" + name + "/.ssh/authorized_keys",
    }
    if (
        settings.get("authorizedkeysfile") not in allowed
        or settings.get("authorizedkeyscommand") != "none"
        or settings.get("trustedusercakeys") != "none"
        or settings.get("pubkeyauthentication") != "yes"
        or any(
            settings.get(k) != "no"
            for k in [
                "passwordauthentication",
                "kbdinteractiveauthentication",
                "hostbasedauthentication",
                "gssapiauthentication",
                "kerberosauthentication",
            ]
        )
    ):
        message = "Unsupported effective SSH key source/authentication policy"
        raise ValueError(message)
    # Do not follow home/key symlinks and then mistake an unrelated file for revocation.
    for path in [
        Path("/home"),
        Path("/home") / name,
        Path("/home") / name / ".ssh",
        Path("/home") / name / ".ssh/authorized_keys",
    ]:
        if path.is_symlink():
            message = "Symlink home/key location unsupported"
            raise ValueError(message)
    return Path("/home") / name / ".ssh/authorized_keys"


def _reject_bad_username(name: str) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", name) or name in {
        "root",
        "alchemmist",
        "ghactions",
    }:
        message = "Restricted username required"
        raise ValueError(message)


def _reject_bad_ident(ident: str) -> None:
    if str(uuid.UUID(ident)) != ident or uuid.UUID(ident).int == 0:
        message = "Canonical UUID required"
        raise ValueError(message)


def _reject_unsafe_directory(directory: Path) -> None:
    if os.path.lexists(directory):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            message = "Enrollment directory must be root-owned and private"
            raise ValueError(message)


def _reject_marker_mismatch(marker: Path, name: str, ident: str) -> None:
    if os.path.lexists(marker):
        info = marker.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_mode & 0o077
            or info.st_size > 1024
        ):
            message = "Enrollment marker must be a private root-owned regular file"
            raise ValueError(message)
        if json.loads(marker.read_text()) != {"name": name, "uuid": ident}:
            message = "Immutable host binding mismatch"
            raise ValueError(message)


def verify(name, ident, directory=DIRECTORY):
    'Verify.'
    _reject_bad_username(name)
    _reject_bad_ident(ident)
    try:
        account = pwd.getpwnam(name)
        exists = True
    except KeyError:
        account = None
        exists = False
    marker = directory / (name + ".json")
    _reject_unsafe_directory(directory)
    _reject_marker_mismatch(marker, name, ident)
    if not os.path.lexists(marker) and exists:
        message = "Existing unbound Linux account: stop for separately reviewed migration"
        raise ValueError(message)
    if account is not None and account.pw_dir != "/home/" + name:
        message = "Nonstandard passwd home unsupported"
        raise ValueError(message)
    verify_key_location(name)
    return {"bindingVerified": True, "accountExists": exists}


def fingerprints(path):
    """Parse every non-comment line; reject options, duplicates and invalid keys."""
    result = []
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not re.fullmatch(
            r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256|sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com) [A-Za-z0-9+/]+={0,3}( .*)?",
            line,
        ):
            message = "Unsupported effective key line"
            raise ValueError(message)
        with tempfile.NamedTemporaryFile(mode="w") as key:
            key.write(line + "\n")
            key.flush()
            parsed = subprocess.run(
                ["ssh-keygen", "-lf", key.name, "-E", "sha256"],
                text=True,
                capture_output=True,
                check=True,
            )
        match = re.fullmatch(r"\d+ (SHA256:[A-Za-z0-9+/]+) .+\n?", parsed.stdout)
        if not match or match[1] in result:
            message = "Invalid/duplicate effective key"
            raise ValueError(message)
        result.append(match[1])
    return sorted(result)


def verify_keys(name, ident, state, expected, directory=DIRECTORY):
    'Verify keys.'
    if (
        state not in {"present", "disabled"}
        or not isinstance(expected, list)
        or any(
            not isinstance(x, str) or not re.fullmatch(r"SHA256:[A-Za-z0-9+/]+", x)
            for x in expected
        )
        or len(expected) != len(set(expected))
        or (state == "disabled" and expected)
        or (state == "present" and not expected)
    ):
        message = "Invalid expected key state"
        raise ValueError(message)
    if not verify(name, ident, directory)["accountExists"]:
        message = "Applied account missing"
        raise ValueError(message)
    actual = fingerprints(verify_key_location(name))
    if actual != sorted(expected):
        message = "Effective key fingerprints differ from reviewed assignment"
        raise ValueError(message)
    if state == "disabled" and pwd.getpwnam(name).pw_shell != "/usr/sbin/nologin":
        message = "Disabled shell mismatch"
        raise ValueError(message)
    return {"effectiveKeysVerified": True, "keyCount": len(actual)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("uuid")
    parser.add_argument("--state", choices=["present", "disabled"])
    parser.add_argument("--expected-fingerprints")
    args = parser.parse_args()
    try:
        if args.state is not None:
            result = verify_keys(
                args.name, args.uuid, args.state, json.loads(args.expected_fingerprints)
            )
        else:
            result = verify(args.name, args.uuid)
        print(json.dumps(result))
    except (ValueError, OSError, TypeError, subprocess.SubprocessError) as exc:
        # Never print raw files/exception text from a host.
        message = (
            "SSH binding/key verification refused; inspect supported host policy and root enrollment marker"
        )
        raise SystemExit(message) from exc
