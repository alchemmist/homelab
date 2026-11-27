#!/usr/bin/env python3
"""Explicit temporary native 3x-ui machine access. Never edits SQLite or human auth.

CLI bootstrap uses a collision-checked NEW name; normal operations use node-sync.
A TTL admin token exists only to issue/revoke our tokens. All secrets stay private.
The CLI bootstrap cannot have a native TTL: an interrupted issuance must be treated
as uncertain and recovered from its private stdout, never blindly replayed.
"""

import fcntl
import hashlib
import http.client
import importlib.util
import json
import os
import re
import socket
import sqlite3
import subprocess
import time
import typing
import urllib.parse
import urllib.request
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import TextIO, TypedDict, cast

spec = importlib.util.spec_from_file_location(
    "inventory", Path(__file__).with_name("vpn-hardening-inventory.py")
)
if spec is None or spec.loader is None or not spec.has_location:
    reason = "Cannot load inventory module"
    raise ValueError(reason)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
IMAGE = (
    "ghcr.io/mhsanaei/3x-ui@sha256:1628adbd9bed680d25d6f714bef4a20f132105f4612ea294952f6665dad32e5b"
)
DB = Path("/srv/x-ui-lab/db/x-ui.db")
KUBE = ["/usr/local/bin/kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml"]
PANEL_PORT = 18082
HTTP_OK = 200
MAX_API_BODY = 8 * 1024 * 1024
API_TIMEOUT = 20
PANEL_VERSION = "3.11.0"
CORE_PREFIX = "Xray 26.10.21 "
WORKER_TTL_MINUTES = 20
CLEANUP_TTL_MINUTES = 30


class _Credential(TypedDict, total=False):
    """Machine credential fields consumed by this tool (JSON payloads stay dynamic)."""

    id: object
    name: str
    scope: str
    token: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow HTTP redirects."""

    @typing.override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: object,
        msg: object,
        headers: object,
        newurl: object,
    ) -> typing.NoReturn:
        """Refuse API redirects instead of following them."""
        msg = "API redirect refused"
        raise ValueError(msg)


def command(args: Sequence[str], *, check: bool = False) -> str:
    """Run one reviewed host command and return its captured stdout text."""
    result = subprocess.run(args, check=check, capture_output=True, text=True, timeout=25)
    if result.returncode:
        msg = "Native read failed"
        raise RuntimeError(msg)
    output: str = result.stdout
    return output


def token_rows(database: Path = DB) -> "list[dict[str, object]]":
    """Return all API token rows ordered by id."""
    with closing(sqlite3.connect(h.check_path(database).as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM api_tokens ORDER BY id")]


def api_path(database: Path = DB) -> str:
    """Return the validated loopback panel API base URL."""
    with closing(sqlite3.connect(h.check_path(database).as_uri() + "?mode=ro", uri=True)) as con:
        settings = dict(con.execute("SELECT key,value FROM settings"))
    path = settings["webBasePath"]
    if not re.fullmatch(r"/[A-Za-z0-9_/-]*/?", path) or ".." in path or "//" in path:
        msg = "Unexpected API base path"
        raise ValueError(msg)
    if int(settings["webPort"]) != PANEL_PORT:
        msg = "Unexpected panel port"
        raise ValueError(msg)
    url: str = "http://127.0.0.1:" + str(PANEL_PORT) + "/" + path.strip("/") + "/panel/api"
    return url


def _audit_api_call(method: str, path: str) -> None:
    """Refuse any unreviewed native API operation or method pairing."""
    if not re.fullmatch(
        r"/(?:setting/apiTokens(?:/create|/delete/[0-9]+)?|inbounds/(?:list|update/[0-9]+)|clients/(?:add|del/[A-Za-z0-9_.@-]+)|hosts/(?:list|raw|get/[A-Za-z0-9_-]{1,64}|update/[A-Za-z0-9_-]{1,64}))",
        path,
    ):
        msg = "Unreviewed native API operation"
        raise ValueError(msg)
    if path.startswith("/hosts/") and (
        (path.startswith("/hosts/update/") and method != "POST")
        or (not path.startswith("/hosts/update/") and method != "GET")
    ):
        msg = "Unreviewed host API method"
        raise ValueError(msg)


def request(base: str, token: str, method: str, path: str, body: object = None) -> object:
    """Call one audited loopback panel API operation, refusing any redirect."""
    _audit_api_call(method, path)
    if not re.fullmatch(r"[A-Za-z0-9]{48}", token):
        msg = "Invalid machine credential"
        raise ValueError(msg)
    if not base.startswith("http://127.0.0.1:" + str(PANEL_PORT) + "/"):
        msg = "Unexpected API base"
        raise ValueError(msg)
    parts = urllib.parse.urlsplit(base + path)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.port != PANEL_PORT:
        msg = "Unexpected API base"
        raise ValueError(msg)
    target = parts.path + ("?" + parts.query if parts.query else "")
    payload = None if body is None else h.canonical(body).encode()
    connection = http.client.HTTPConnection("127.0.0.1", PANEL_PORT, timeout=API_TIMEOUT)

    def _parse(status: int, data: bytes) -> object:
        if status != HTTP_OK or len(data) > MAX_API_BODY:
            msg = "Unexpected native API response"
            raise ValueError(msg)
        obj = json.loads(data)
        if obj.get("success") is not True:
            msg = "Native API rejected operation"
            raise ValueError(msg)
        return obj.get("obj")

    try:
        connection.request(
            method,
            target,
            payload,
            {
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "Host": "vpn.alchemmist.xyz",
            },
        )
        response = connection.getresponse()
        resolved = _parse(response.status, response.read(MAX_API_BODY + 1))
    except (OSError, ValueError, http.client.HTTPException):
        msg = "Native API operation failed; inspect private receipts, never retry writes blindly"
        raise RuntimeError(msg) from None
    else:
        return resolved
    finally:
        connection.close()


def pod_identity() -> "dict[str, object]":
    """Return the identity of the one expected running primary panel pod."""
    items = json.loads(
        command(
            [*KUBE, "-n", "x-ui", "get", "pods", "-l", "app.kubernetes.io/name=x-ui", "-o", "json"]
        )
    )["items"]
    if len(items) != 1:
        msg = "Expected one primary pod"
        raise ValueError(msg)
    p = items[0]
    if (
        p["spec"]["nodeName"] != "socrat-2"
        or p["status"]["phase"] != "Running"
        or p["spec"]["containers"][0]["image"] != IMAGE
        or not all(c["ready"] for c in p["status"]["containerStatuses"])
    ):
        msg = "Unexpected primary workload"
        raise ValueError(msg)
    ex = [*KUBE, "-n", "x-ui", "exec", p["metadata"]["name"], "-c", "primary", "--"]
    if command([*ex, "/app/x-ui", "-v"]).strip() != PANEL_VERSION:
        msg = "Panel version drift"
        raise ValueError(msg)
    if (
        not command([*ex, "/app/bin/xray-linux-amd64", "version"])
        .splitlines()[0]
        .startswith(CORE_PREFIX)
    ):
        msg = "Core version drift"
        raise ValueError(msg)
    return {"name": p["metadata"]["name"], "uid": p["metadata"]["uid"], "image": IMAGE}


def _bootstrap_token(returncode: int, text: str) -> str:
    """Return the one bootstrap token printed by the native CLI, or fail uncertain."""
    found = re.findall(r"^apiToken:\s*([A-Za-z0-9]{48})\s*$", text, re.MULTILINE)
    if returncode or len(found) != 1:
        msg = "Bootstrap issuance uncertain"
        raise RuntimeError(msg)
    token: str = found[0]
    return token


def _issued_row(rows: "list[dict[str, object]]", name: str) -> "dict[str, object]":
    """Return the single token row with exactly the planned temporary name."""
    matches = [r for r in rows if r["name"] == name]
    if len(matches) != 1:
        msg = "Bootstrap row uncertain"
        raise RuntimeError(msg)
    return matches[0]


class NativeSession:
    """Panel session reconciler backed by the native VPN database."""

    def __init__(self, state: Path, database: Path = DB, worker_scope: str = "node-sync") -> None:
        """Initialize the native panel session."""
        if worker_scope not in ("node-sync", "admin"):
            msg = "Unreviewed worker scope"
            raise ValueError(msg)
        self.worker_scope = worker_scope
        self.state = Path(state).absolute()
        self.database = Path(database)
        label = self.state.name
        if not re.fullmatch(r"vpn83-[a-z0-9-]{8,32}", label):
            msg = "Use a fresh explicit vpn83-* session name"
            raise ValueError(msg)
        self.names = {kind: label + "-" + kind for kind in ("bootstrap", "cleanup", "worker")}
        self.base: str | None = None
        self.credentials: dict[str, _Credential] = {}
        self.original: list[dict[str, object]] = []
        self.lock: TextIO | None = None

    def preview(self) -> "dict[str, object]":
        """Check planned panel tokens against existing names before writing."""
        original = token_rows(self.database)
        if any(r["name"] in self.names.values() for r in original):
            msg = "Temporary token name collision; never rotate"
            raise ValueError(msg)
        return {
            "pod": pod_identity(),
            "configuration_sha256": h.inspect(self.database)["configuration_sha256"],
            "existing_tokens_sha256": h.digest(original),
            "names": self.names,
            "scope": self.worker_scope,
            "worker_ttl_minutes": 20,
            "cleanup_ttl_minutes": 30,
        }

    def _save_credential(self, kind: str, value: _Credential) -> None:
        h.save(self.state / (kind + ".json"), value)
        self.credentials[kind] = value

    def _require_owned(self, kind: str) -> None:
        """Fail if a freshly issued credential is not owned by this session."""
        if self.owned(kind) is None:
            msg = "Bootstrap ownership missing"
            raise RuntimeError(msg)

    def _require_open(self) -> str:
        """Return the opened panel API base, refusing an unopened session."""
        if self.base is None:
            msg = "Session not opened"
            raise RuntimeError(msg)
        return self.base

    def owned(self, kind: str) -> "dict[str, object] | None":
        expected = self.credentials[kind]
        rows = [r for r in token_rows(self.database) if r["id"] == expected["id"]]
        if not rows:
            return None
        row = rows[0]
        if (
            row["name"] != self.names[kind]
            or row["scope"] != expected["scope"]
            or row["token"] != hashlib.sha256(expected["token"].encode()).hexdigest()
        ):
            msg = "Credential ownership changed; refusing deletion"
            raise ValueError(msg)
        return row

    def _delete(self, kind: str, actor: str) -> None:
        row = self.owned(kind)
        if row is not None:
            request(
                self._require_open(),
                self.credentials[actor]["token"],
                "POST",
                "/setting/apiTokens/delete/" + str(row["id"]),
                {"expectedScope": row["scope"]},
            )
        if self.owned(kind) is not None:
            msg = "Credential deletion did not converge"
            raise RuntimeError(msg)

    def _create(self, kind: str, scope: str, minutes: int, actor: str) -> None:
        expires = int(time.time() * 1000) + minutes * 60000
        # Write intent BEFORE remote creation. An ambiguous result stays uncertain.
        h.save(
            self.state / (kind + "-intent.json"),
            {"name": self.names[kind], "scope": scope, "expiresAt": expires},
        )
        obj = request(
            self._require_open(),
            self.credentials[actor]["token"],
            "POST",
            "/setting/apiTokens/create",
            {"name": self.names[kind], "scope": scope, "expiresAt": expires},
        )
        if not isinstance(obj, dict):
            reason = "Unexpected created credential"
            raise TypeError(reason)
        if (
            obj.get("name") != self.names[kind]
            or obj.get("scope") != scope
            or obj.get("expiresAt") != expires
        ):
            msg = "Unexpected created credential"
            raise RuntimeError(msg)
        token_value = obj.get("token")
        if not isinstance(token_value, str):
            reason = "Unexpected created credential"
            raise TypeError(reason)
        credential: _Credential = {
            "id": obj.get("id"),
            "name": self.names[kind],
            "scope": scope,
            "token": token_value,
        }
        self._save_credential(kind, credential)
        if self.owned(kind) is None:
            msg = "Missing created credential"
            raise RuntimeError(msg)

    def open(self, approval: str) -> "NativeSession":
        """Create the session tokens once, after explicit root approval."""
        if socket.gethostname() != "socrat-2" or os.geteuid() != 0:
            msg = "Explicit session creation requires root on socrat-2"
            raise ValueError(msg)
        self.state = h.private_directory(self.state)
        fd = os.open(self.state / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, "w")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any(p.name != "lock" for p in self.state.iterdir()):
            msg = "Existing session state; inspect instead of replaying"
            raise ValueError(msg)
        plan = self.preview()
        if approval != h.digest(plan):
            msg = "Fresh approval hash required"
            raise ValueError(msg)
        self.original = token_rows(self.database)
        self.base = api_path(self.database)
        h.inspect(self.database, self.state / "backup")
        if self.preview() != plan:
            msg = "State drift before credential creation"
            raise ValueError(msg)
        h.save(self.state / "before-tokens.json", self.original)
        h.save(self.state / "uncertain.json", {"approval": approval, "names": self.names})
        p = cast("dict[str, str]", plan["pod"])
        # Native CLI stdout contains a credential. Direct it to a private file,
        # not a terminal, environment, shell argument or exception message.
        fd = os.open(
            self.state / "bootstrap.stdout",
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
            0o600,
        )
        args = [
            *KUBE,
            "-n",
            "x-ui",
            "exec",
            p["name"],
            "-c",
            "primary",
            "--",
            "/app/x-ui",
            "setting",
            "-getApiToken",
            "-tokenName",
            self.names["bootstrap"],
            "-tokenScope",
            "admin",
        ]
        try:
            with os.fdopen(fd, "w") as output:
                result = subprocess.run(
                    args,
                    check=False,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=30,
                )
            text = (self.state / "bootstrap.stdout").read_text()
            token = _bootstrap_token(result.returncode, text)
            rows = [r for r in token_rows(self.database) if r["name"] == self.names["bootstrap"]]
            bootstrap_credential: _Credential = {
                "id": _issued_row(rows, self.names["bootstrap"])["id"],
                "name": self.names["bootstrap"],
                "scope": "admin",
                "token": token,
            }
            self._save_credential("bootstrap", bootstrap_credential)
            self._require_owned("bootstrap")
            self._create("cleanup", "admin", CLEANUP_TTL_MINUTES, "bootstrap")
            self._delete("bootstrap", "cleanup")
            self._create("worker", self.worker_scope, WORKER_TTL_MINUTES, "cleanup")
        except Exception:
            self.cleanup()
            raise
        return self

    def call(self, method: str, path: str, body: object = None) -> object:
        """Call the unprivileged dashboard token endpoints by exact path."""
        if path.startswith("/setting/"):
            msg = "Worker cannot use administrative token endpoints"
            raise ValueError(msg)
        if self.owned("worker") is None:
            msg = "Worker credential unavailable"
            raise RuntimeError(msg)
        return request(
            self._require_open(), self.credentials["worker"]["token"], method, path, body
        )

    def _delete_generated_tokens(self) -> list[str]:
        """Delete each generated token; report kinds that did not converge."""
        errors: list[str] = []
        actor = "cleanup" if "cleanup" in self.credentials else "bootstrap"
        if actor not in self.credentials:
            return errors
        for kind in ("worker", "bootstrap", "cleanup"):
            if kind not in self.credentials:
                continue
            try:
                self._delete(kind, actor)
            except (RuntimeError, ValueError, OSError, sqlite3.Error):
                errors.append(kind)
        return errors

    def _remove_private_artifacts(self) -> None:
        """Delete the private credential files and close the state lock."""
        for name in (
            "bootstrap.stdout",
            "bootstrap.json",
            "cleanup.json",
            "worker.json",
        ):
            path = self.state / name
            if path.exists():
                path.unlink()
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def cleanup(self) -> None:
        """Drop generated tokens and log out created sessions."""
        errors = self._delete_generated_tokens()
        rows = token_rows(self.database)
        if any(r["name"] in self.names.values() for r in rows):
            errors.append("temporary-row-remains")
        # Untouched tokens must remain byte-identical, not just still enabled.
        original_ids = {r["id"] for r in self.original}
        if self.original and [r for r in rows if r["id"] in original_ids] != self.original:
            errors.append("original-token-drift")
        if errors:
            msg = "Temporary credential cleanup uncertain; inspect private state"
            raise RuntimeError(msg)
        if (self.state / "uncertain.json").exists():
            h.save(
                self.state / "credential-cleanup.json",
                {"temporary_rows_removed": True, "existing_tokens_unchanged": True},
            )
            (self.state / "uncertain.json").unlink()
        self._remove_private_artifacts()

    def __enter__(self) -> typing.Self:
        """Return this session as the active context manager resource."""
        enter: typing.Self = self
        return enter

    def __exit__(self, *args: object) -> None:
        """Clean up the session when leaving its context manager block."""
        self.cleanup()
