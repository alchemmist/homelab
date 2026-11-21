"""Explicit owner-admin API migration. Never run as part of normal reconciliation.

The legacy credential key remains an alias for existing consumers, not a bootstrap token.
apply/check never delete humans; retire-akadmin is a separate explicit guarded action. Never prints credentials.
"""

import argparse
import ast
import fcntl
import json
import os
import secrets
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from urllib.parse import quote

NAME = "homelab-identity-automation"
GROUP = "homelab-identity-automation-admin"
OWNER_UUID = "9e33877a-3eaa-4541-98eb-8cdc10088ef6"
BASE = "https://auth.socrat.alchemmist.xyz/api/v3/"


def _expression_matches(node: ast.AST, expected: str) -> bool:
    return ast.dump(node) == ast.dump(ast.parse(expected, mode="eval").body)


def _matches_migration_recipe(
    conditional: ast.If,
    runtime_index: int,
    journal_index: int,
    index: int,
    manifest_index: int,
) -> bool:
    """Match the reviewed active-journal recipe exactly, including statement order."""
    if not runtime_index < journal_index < index < manifest_index:
        return False
    # Require the actual source statements, not matching text in a comment,
    # string or unreachable nested function. Additional statements need review.
    if conditional.orelse or len(conditional.body) != 3:
        return False
    load, guard, removal = conditional.body
    expected_load = ast.parse("automation = json.loads(automation_path.read_text())").body[0]
    if ast.dump(load) != ast.dump(expected_load):
        return False
    if not isinstance(guard, ast.If) or not _expression_matches(
        guard.test,
        'automation.get("status") != "active" or '
        'automation.get("token") != values["AUTHENTIK_BOOTSTRAP_TOKEN"]',
    ):
        return False
    refusal = guard.body[0]
    if (
        guard.orelse
        or len(guard.body) != 1
        or not (
            isinstance(refusal, ast.Raise)
            and isinstance(refusal.exc, ast.Call)
            and isinstance(refusal.exc.func, ast.Name)
            and refusal.exc.func.id == "SystemExit"
        )
    ):
        return False
    expected_removal = ast.parse(
        'for key in ["AUTHENTIK_BOOTSTRAP_TOKEN", "AUTHENTIK_BOOTSTRAP_PASSWORD"]:\n'
        "    runtime_values.pop(key, None)"
    ).body[0]
    return ast.dump(removal) == ast.dump(expected_removal)


def bootstrap_is_migration_aware(source: str) -> bool:
    """Check the reviewed credential-removal recipe without executing bootstrap.

    Whitespace, quote style and comments carry no authority. The active-journal
    check and removal loop must precede the manifest that uses runtime_values.
    This is a bounded source prerequisite, not proof of live identity state.
    """
    if len(source) > 1_048_576:
        return False
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return False

    assignments = {
        node.targets[0].id: (index, node.value)
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    if not {"runtime_values", "automation_path", "manifest"} <= assignments.keys():
        return False
    runtime_index, runtime = assignments["runtime_values"]
    journal_index, journal = assignments["automation_path"]
    manifest_index, manifest = assignments["manifest"]
    if not _expression_matches(runtime, "dict(values)") or not _expression_matches(
        journal, 'root / "automation-api.json"'
    ):
        return False
    if not isinstance(manifest, ast.Dict) or not any(
        isinstance(key, ast.Constant)
        and key.value == "stringData"
        and _expression_matches(value, "runtime_values")
        for key, value in zip(manifest.keys, manifest.values)
    ):
        return False
    for index, conditional in enumerate(tree.body):
        if not isinstance(conditional, ast.If) or not _expression_matches(
            conditional.test, "automation_path.exists()"
        ):
            continue
        if _matches_migration_recipe(
            conditional, runtime_index, journal_index, index, manifest_index
        ):
            return True
    return False


def save(path: Path, data: object) -> None:
    """Save."""
    tmp = path.with_name(path.name + ".tmp-" + secrets.token_hex(8))
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def api(token: str, method: str, path: str, data: object | None = None) -> dict[str, object]:
    """Api."""
    req = urllib.request.Request(
        BASE + path,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read()
        if not raw:
            return {}
        return cast("dict[str, object]", json.loads(raw))


def exact(token: str, endpoint: str, field: str, value: str) -> dict[str, object] | None:
    """Exact."""
    payload = api(
        token, "GET", endpoint + "?" + field + "=" + quote(value, safe="") + "&page_size=1000"
    )
    matches = [
        row for row in cast("list[dict[str, object]]", payload["results"]) if row[field] == value
    ]
    if len(matches) > 1:
        msg = "Ambiguous managed identity"
        raise RuntimeError(msg)
    return matches[0] if matches else None


def verify(token: str, journal: dict[str, object]) -> dict[str, object]:
    """Verify."""
    user = api(token, "GET", "core/users/" + str(journal["user_pk"]) + "/")
    group = api(token, "GET", "core/groups/" + str(journal["group_pk"]) + "/")
    marker = {"homelab_automation_journal": journal["nonce"]}
    if not (
        user["uuid"] == journal["user_uuid"]
        and user["username"] == NAME
        and user["type"] == "service_account"
        and user["is_active"]
        and user["is_superuser"]
        and user["attributes"] == marker
        and user["groups"] == [journal["group_pk"]]
        and group["name"] == GROUP
        and group["is_superuser"]
        and group["attributes"] == marker
        and set(cast("list[object]", group["users"])) == {user["pk"]}
    ):
        msg = "Managed account/group drift"
        raise RuntimeError(msg)
    t = api(token, "GET", "core/tokens/" + quote(NAME, safe="") + "/")
    if t["user"] != user["pk"] or t["intent"] != "api" or t["expiring"]:
        msg = "Managed token drift"
        raise RuntimeError(msg)
    owner = exact(token, "core/users/", "username", "alchemmist")
    if (
        not owner
        or owner["uuid"] != OWNER_UUID
        or not owner["is_active"]
        or not owner["is_superuser"]
    ):
        msg = "Owner admin prerequisite failed"
        raise RuntimeError(msg)
    for endpoint in [
        "providers/all/",
        "core/applications/",
        "flows/instances/",
        "outposts/instances/",
    ]:
        api(token, "GET", endpoint + "?page_size=1")
    return user


def _require_owner_admin(owner: dict[str, object] | None) -> None:
    """Require the personal owner admin the migration expects to stay intact."""
    if (
        not owner
        or owner["uuid"] != OWNER_UUID
        or not owner["is_superuser"]
        or not owner["is_active"]
    ):
        msg = "Owner admin prerequisite failed"
        raise RuntimeError(msg)


def _verify_active_journal(path: Path, journal: dict[str, object], old: object) -> None:
    """Re-verify an already-active journal without touching any consumer."""
    if path.stat().st_mode & 0o077:
        msg = "Journal is not private"
        raise RuntimeError(msg)
    verify(cast("str", journal["token"]), journal)
    if old != journal["token"]:
        msg = "Consumer credential alias drift"
        raise RuntimeError(msg)
    print("PASS: dedicated machine API identity and consumer alias verified; read-only check")


def _create_journal(
    root: Path, path: Path, old: str, values: dict[str, object]
) -> dict[str, object]:
    """Reject adoption of foreign identities, back up credentials, persist a journal."""
    if exact(old, "core/users/", "username", NAME) or exact(old, "core/groups/", "name", GROUP):
        msg = "Refusing adoption of existing identity"
        raise RuntimeError(msg)
    # List metadata only; never overwrite an existing token identifier.
    matches = [
        t
        for t in cast(
            "list[dict[str, object]]", api(old, "GET", "core/tokens/?page_size=1000")["results"]
        )
        if t["identifier"] == NAME
    ]
    if matches:
        msg = "Foreign token identifier"
        raise RuntimeError(msg)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = root / ("credentials-before-automation-" + stamp + ".json")
    if backup.exists():
        msg = "Backup already exists"
        raise RuntimeError(msg)
    save(backup, values)
    journal = {
        "version": 1,
        "nonce": secrets.token_hex(24),
        "status": "preparing",
        "previous_credentials": backup.name,
        "token_identifier": NAME,
    }
    save(path, journal)
    return journal


def _ensure_group(
    old: str, path: Path, journal: dict[str, object], marker: dict[str, object]
) -> dict[str, object]:
    """Create the dedicated automation group or validate the existing one."""
    group = exact(old, "core/groups/", "name", GROUP)
    if group and group["attributes"] != marker:
        msg = "Foreign group"
        raise RuntimeError(msg)
    if group is None:
        group = api(
            old, "POST", "core/groups/", {"name": GROUP, "is_superuser": True, "attributes": marker}
        )
    if not group["is_superuser"]:
        msg = "Group permission drift"
        raise RuntimeError(msg)
    journal["group_pk"] = group["pk"]
    save(path, journal)
    return group


def _ensure_user(
    old: str,
    path: Path,
    group: dict[str, object],
    journal: dict[str, object],
    marker: dict[str, object],
) -> dict[str, object]:
    """Create the dedicated service account or validate the existing one."""
    user = exact(old, "core/users/", "username", NAME)
    if user and user["attributes"] != marker:
        msg = "Foreign user"
        raise RuntimeError(msg)
    if user is None:
        if group["users"]:
            msg = "Foreign group member"
            raise RuntimeError(msg)
        user = api(
            old,
            "POST",
            "core/users/",
            {
                "username": NAME,
                "name": "Homelab identity automation",
                "type": "service_account",
                "path": "service-accounts/homelab",
                "is_active": True,
                "groups": [group["pk"]],
                "attributes": marker,
            },
        )
    journal.update(user_pk=user["pk"], user_uuid=user["uuid"])
    save(path, journal)
    return user


def _ensure_token(old: str, user: dict[str, object], journal: dict[str, object]) -> None:
    """Create the dedicated API token or validate an existing exact match."""
    matches = [
        t
        for t in cast(
            "list[dict[str, object]]", api(old, "GET", "core/tokens/?page_size=1000")["results"]
        )
        if t["identifier"] == NAME
    ]
    if matches:
        if (
            len(matches) != 1
            or matches[0]["user"] != user["pk"]
            or matches[0].get("description") != journal["nonce"]
        ):
            msg = "Foreign token"
            raise RuntimeError(msg)
    else:
        api(
            old,
            "POST",
            "core/tokens/",
            {
                "identifier": NAME,
                "user": user["pk"],
                "intent": "api",
                "expiring": False,
                "description": journal["nonce"],
            },
        )


def migrate(root, action):
    """Migrate."""
    if root.stat().st_mode & 0o077:
        msg = "Deployment directory is not private"
        raise RuntimeError(msg)
    path = root / "automation-api.json"
    credentials = root / "credentials.json"
    if credentials.stat().st_mode & 0o077:
        msg = "Credential file is not private"
        raise RuntimeError(msg)
    values = json.loads(credentials.read_text())
    old = values["AUTHENTIK_BOOTSTRAP_TOKEN"]
    journal = json.loads(path.read_text()) if path.exists() else None
    if journal and journal.get("status") == "active":
        _verify_active_journal(path, journal, old)
        return
    if action == "check":
        print("NOT MIGRATED: no active machine API journal")
        return
    _require_owner_admin(exact(old, "core/users/", "username", "alchemmist"))
    if journal is None:
        journal = _create_journal(root, path, old, values)
    marker = {"homelab_automation_journal": journal["nonce"]}
    group = _ensure_group(old, path, journal, marker)
    user = _ensure_user(old, path, group, journal, marker)
    _ensure_token(old, user, journal)
    journal["token"] = api(old, "GET", "core/tokens/" + NAME + "/view_key/")["key"]
    verify(cast("str", journal["token"]), journal)
    # Validate new access before atomically switching any existing consumer.
    values["AUTHENTIK_BOOTSTRAP_TOKEN"] = journal["token"]
    save(credentials, values)
    journal["status"] = "active"
    save(path, journal)
    print(
        "PASS: dedicated machine API access activated; old akadmin/token retained for guarded rollback"
    )


def _require_recovery_evidence(journal: dict[str, object]) -> None:
    """Require the recorded recovery drill and off-node encrypted backup proof."""
    evidence = cast("dict[str, object]", journal.get("recovery_evidence", {}))
    if not (
        evidence.get("fixture_admin_session_verified") is True
        and evidence.get("fixture_cleanup_verified") is True
        and evidence.get("owner_uuid") == OWNER_UUID
        and journal.get("encrypted_backup_sha256")
    ):
        msg = "Recovery and off-node backup prerequisites not recorded"
        raise RuntimeError(msg)


def _require_no_bootstrap_credentials() -> None:
    """Reject any surviving bootstrap credential in the runtime Secret or pods."""
    import subprocess

    env = dict(os.environ, K3S_CONFIG_FILE="/dev/null")
    k = ["kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml", "-n", "identity"]
    secret = json.loads(
        subprocess.check_output(k + ["get", "secret", "authentik-runtime", "-o", "json"], env=env)
    )
    keys = {"AUTHENTIK_BOOTSTRAP_TOKEN", "AUTHENTIK_BOOTSTRAP_PASSWORD"}
    if keys.intersection(secret.get("data", {})):
        msg = "Runtime Secret still contains bootstrap credentials"
        raise RuntimeError(msg)
    metadata = cast("dict[object, dict[str, object]]", secret)["metadata"]
    annotations = cast("dict[str, object]", metadata.get("annotations", {}))
    annotation = cast(
        "str", annotations.get("kubectl.kubernetes.io/last-applied-configuration", "{}")
    )
    applied = json.loads(annotation)
    if keys.intersection(applied.get("data", {})) or keys.intersection(
        applied.get("stringData", {})
    ):
        msg = "Runtime Secret annotation still contains bootstrap credentials"
        raise RuntimeError(msg)
    for name in ["authentik-server", "authentik-worker"]:
        deploy = json.loads(
            subprocess.check_output(k + ["get", "deploy", name, "-o", "json"], env=env)
        )
        for c in deploy["spec"]["template"]["spec"]["containers"]:
            if keys.intersection(e["name"] for e in c.get("env", [])):
                msg = "Explicit pod bootstrap environment remains"
                raise RuntimeError(msg)


def _require_reviewed_default_admin(target: dict[str, object]) -> None:
    """Only ever delete the exact reviewed default-admin identity."""
    if target["uuid"] != "fc86d87d-3a72-4cfb-8ba1-aa6bf6b017e7" or target["pk"] != 4:
        msg = "Refusing deletion of an unreviewed identity"
        raise RuntimeError(msg)


def _require_clean_default_tokens(token: str, target: dict[str, object]) -> None:
    """Permit only the reviewed authentik-bootstrap-token under the default admin."""
    owned = [
        t
        for t in cast(
            "list[dict[str, object]]", api(token, "GET", "core/tokens/?page_size=1000")["results"]
        )
        if t["user"] == target["pk"]
    ]
    if any(t["identifier"] != "authentik-bootstrap-token" for t in owned):
        msg = "Unexpected default-admin token dependency"
        raise RuntimeError(msg)


def retire_default_admin(root):
    """Only after an independent node-admin recovery drill and encrypted backup."""
    migrate(root, "check")
    path = root / "automation-api.json"

    journal = json.loads(path.read_text())
    _require_recovery_evidence(cast("dict[str, object]", journal))
    _require_no_bootstrap_credentials()
    bootstrap = (root / "bootstrap.py").read_text()
    if not bootstrap_is_migration_aware(bootstrap):
        msg = "Future bootstrap reconciliation is not migration-aware"
        raise RuntimeError(msg)
    token = journal["token"]
    target = exact(token, "core/users/", "username", "akadmin")
    if target is None:
        if journal.get("akadmin_retired_at"):
            print("PASS: akadmin already retired")
            return
        msg = "Default admin missing without retirement journal"
        raise RuntimeError(msg)
    _require_reviewed_default_admin(target)
    _require_clean_default_tokens(token, target)
    journal["retired_user_before"] = target
    save(path, journal)
    api(token, "DELETE", "core/users/" + str(target["pk"]) + "/")
    if exact(token, "core/users/", "username", "akadmin") is not None:
        msg = "Default admin removal not confirmed"
        raise RuntimeError(msg)
    if any(
        t["user"] == target["pk"]
        for t in cast(
            "list[dict[str, object]]", api(token, "GET", "core/tokens/?page_size=1000")["results"]
        )
    ):
        msg = "Default-admin token survived deletion"
        raise RuntimeError(msg)
    verify(token, journal)
    values = json.loads((root / "credentials.json").read_text())
    if values["AUTHENTIK_BOOTSTRAP_TOKEN"] != token:
        msg = "Consumer alias changed during retirement"
        raise RuntimeError(msg)
    values.pop("AUTHENTIK_BOOTSTRAP_PASSWORD", None)
    save(root / "credentials.json", values)
    journal["akadmin_retired_at"] = datetime.now(UTC).isoformat()
    save(path, journal)
    print(
        "PASS: exact reviewed akadmin and its bootstrap token retired; machine access and personal owner verified"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    p.add_argument("--action", choices=["check", "apply", "retire-akadmin"], default="check")
    p.add_argument("--confirm-delete-akadmin", action="store_true")
    a = p.parse_args()
    if a.action == "retire-akadmin" and not a.confirm_delete_akadmin:
        p.error("retire-akadmin requires --confirm-delete-akadmin")
    try:
        # Serialize migration and retries; consumers only read atomically replaced files.
        with (a.root / "automation-migration.lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if a.action == "retire-akadmin":
                retire_default_admin(a.root)
            else:
                migrate(a.root, a.action)
    except Exception as e:
        print(
            "Migration stopped safely ("
            + type(e).__name__
            + "); inspect protected journal, never print keys",
            file=sys.stderr,
        )
        sys.exit(1)
