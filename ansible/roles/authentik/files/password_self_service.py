#!/usr/bin/env python3
"""Additive native External password self-service. Never handles human passwords."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import cast
from urllib.parse import quote

SLUG = "socrat-change-password"
HOST = "auth.socrat.alchemmist.xyz"


def route():
    # Constant destination: user-supplied next/username cannot select another account.
    flow = (
        "/if/flow/"
        + SLUG
        + "/?next="
        + quote("/if/flow/default-invalidation-flow/?next=/change-password", safe="")
    )
    login = "https://" + HOST + "/if/flow/default-authentication-flow/?next=" + quote(flow, safe="")
    meta = {
        "name": "socrat-password-self-service",
        "namespace": "identity",
        "labels": {"app.kubernetes.io/managed-by": "homelab-password-self-service"},
    }
    return [
        {
            "apiVersion": "traefik.io/v1alpha1",
            "kind": "Middleware",
            "metadata": meta,
            "spec": {
                "redirectRegex": {
                    "regex": "^https?://[^/]+/change-password/?(\\?.*)?$",
                    "replacement": login,
                    "permanent": False,
                }
            },
        },
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                **meta,
                "annotations": {
                    "traefik.ingress.kubernetes.io/router.priority": "150",
                    "traefik.ingress.kubernetes.io/router.middlewares": "identity-socrat-password-self-service@kubernetescrd",
                },
            },
            "spec": {
                "ingressClassName": "traefik",
                "tls": [{"hosts": [HOST], "secretName": "authentik-tls"}],
                "rules": [
                    {
                        "host": HOST,
                        "http": {
                            "paths": [
                                {
                                    "path": p,
                                    "pathType": "Exact",
                                    "backend": {
                                        "service": {
                                            "name": "authentik-server",
                                            "port": {"number": 80},
                                        }
                                    },
                                }
                                for p in ["/change-password", "/change-password/"]
                            ]
                        },
                    }
                ],
            },
        },
    ]


class _Client:
    """Authentik v3 client restricted to GET plus reviewed additive POSTs."""

    def __init__(self, *, applier: bool, journal: Path, token: str) -> None:
        self.applier = applier
        self.journal = journal
        self.token = token

    def api(self, method: str, path: str, data: object | None = None) -> object:
        """Perform one API request, refusing unreviewed write methods."""
        if method != "GET":
            assert self.applier and method == "POST", "Additive creation only"
        request = urllib.request.Request(
            "https://" + HOST + "/api/v3/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        if method != "GET":
            index = self.journal / (
                "created-" + str(len(list(self.journal.glob("created-*")))) + ".json"
            )
            index.write_text(json.dumps({"path": path, "result": result}, indent=2))
        return result

    def all_rows(self, path: str) -> list[dict[str, object]]:
        """Read one reviewed list endpoint, refusing unreviewed pagination."""
        data = cast("dict[str, object]", self.api("GET", path + "?page_size=100"))
        assert not data.get("next"), "Pagination requires review"
        return cast("list[dict[str, object]]", data["results"])


def _exact(snapshot: dict[str, list[dict[str, object]]], path: str, name: str) -> dict[str, object]:
    """Return the one snapshot row with the given name; ambiguity is fatal."""
    matches = [r for r in snapshot[path] if r.get("name") == name]
    assert len(matches) == 1, "Missing/ambiguous native object: " + name
    return matches[0]


def _verify_native(
    snapshot: dict[str, list[dict[str, object]]],
) -> tuple[dict[str, object], dict[str, object]]:
    """Verify the reviewed native password-change flow, prompts and writer stage."""
    native = _exact(snapshot, "flows/instances/", "Change Password")
    assert (
        native["authentication"] == "require_authenticated"
        and native["slug"] == "default-password-change"
    )
    prompt = _exact(snapshot, "stages/prompt/stages/", "default-password-change-prompt")
    write = _exact(snapshot, "stages/user_write/", "default-password-change-write")
    assert write["user_creation_mode"] == "never_create" and write["create_users_group"] is None
    rows = snapshot["stages/prompt/prompts/"]
    fields = [p for p in rows if p["pk"] in cast("list[object]", prompt["fields"])]
    assert {p["field_key"] for p in fields} == {"password", "password_repeat"}
    assert all(p["type"] == "password" and p["required"] for p in fields)
    assert prompt["validation_policies"], "Password policy must be preserved"
    return prompt, write


def _ensure(
    client: _Client, path: str, key: str, value: object, spec: dict[str, object]
) -> dict[str, object]:
    """Create-or-verify one owned object additively, never touching shared ones."""
    matches = [r for r in client.all_rows(path) if r.get(key) == value]
    assert len(matches) <= 1, "Ambiguous owned object"
    if matches:
        obj = matches[0]
        assert all(obj.get(k) == v for k, v in spec.items()), "Owned object drift: " + cast(
            "str", value
        )
        return matches[0]
    # Absence rechecked immediately before additive create.
    client.api("POST", path, spec)
    verified = [r for r in client.all_rows(path) if r.get(key) == value]
    assert len(verified) == 1 and all(verified[0].get(k) == v for k, v in spec.items())
    return verified[0]


def _ensure_bindings(
    client: _Client,
    flow: dict[str, object],
    prompt: dict[str, object],
    write: dict[str, object],
    done_stage: dict[str, object],
) -> list[dict[str, object]]:
    """Create the reviewed flow ordering additively and return the live bindings."""
    expected: list[tuple[object, object]] = [
        (0, prompt["pk"]),
        (10, write["pk"]),
        (20, done_stage["pk"]),
    ]
    existing = [b for b in client.all_rows("flows/bindings/") if b["target"] == flow["pk"]]
    assert all((b["order"], b["stage"]) in expected for b in existing), "Unexpected flow binding"
    for order, stage in expected:
        matches = [b for b in existing if b["order"] == order and b["stage"] == stage]
        assert len(matches) <= 1
        if not matches:
            client.api(
                "POST",
                "flows/bindings/",
                {
                    "target": flow["pk"],
                    "stage": stage,
                    "order": order,
                    "evaluate_on_plan": True,
                    "re_evaluate_policies": True,
                    "policy_engine_mode": "all",
                },
            )
    bindings = [b for b in client.all_rows("flows/bindings/") if b["target"] == flow["pk"]]
    assert sorted((b["order"], b["stage"]) for b in bindings) == expected
    return bindings


def _verify_shared_unchanged(client: _Client, snapshot: dict[str, list[dict[str, object]]]) -> None:
    """Re-read every shared native object and compare it to the snapshot."""
    # No updates to shared prompts, password policy, write stage, brand or login flow.
    for path, name in [
        ("flows/instances/", "Change Password"),
        ("stages/prompt/stages/", "default-password-change-prompt"),
        ("stages/user_write/", "default-password-change-write"),
    ]:
        current = [r for r in client.all_rows(path) if r["name"] == name][0]
        before = _exact(snapshot, path, name)
        # flow_set is a derived reverse reference to our newly added flow.
        assert {k: v for k, v in current.items() if k != "flow_set"} == {
            k: v for k, v in before.items() if k != "flow_set"
        }


def _apply_route(resources: list[dict[str, object]]) -> None:
    """Create the exact-path entry route only when it does not already exist."""
    k = ["kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml"]
    env = {**os.environ, "K3S_CONFIG_FILE": "/dev/null"}
    for obj in resources:
        result = subprocess.run(
            k
            + [
                "-n",
                "identity",
                "get",
                cast("str", obj["kind"]).lower(),
                cast("str", cast("dict[str, object]", obj["metadata"])["name"]),
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode == 0:
            current = json.loads(result.stdout)
            assert current["spec"] == obj["spec"], "Existing route drift"
        else:
            assert "NotFound" in result.stderr, "Route inspection failed"
            subprocess.run(
                k + ["create", "-f", "-"],
                input=json.dumps(obj),
                text=True,
                env=env,
                check=True,
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root
    token = cast(
        "str",
        cast("dict[str, object]", json.loads((root / "credentials.json").read_text()))[
            "AUTHENTIK_BOOTSTRAP_TOKEN"
        ],
    )
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original(
        "109.173.40.247" if host == HOST else host, *a, **kw
    )
    os.umask(0o077)
    journal = Path(tempfile.mkdtemp(prefix="password-self-service-", dir=root))
    client = _Client(applier=args.apply, journal=journal, token=token)
    snapshot = {
        p: client.all_rows(p)
        for p in [
            "flows/instances/",
            "flows/bindings/",
            "stages/prompt/stages/",
            "stages/prompt/prompts/",
            "stages/user_write/",
            "policies/password/",
        ]
    }
    (journal / "preimage.json").write_text(json.dumps(snapshot, indent=2))
    prompt, write = _verify_native(snapshot)
    print(
        "Verified native authenticated-only password/repeat, validation policy, never-create writer."
    )
    if not args.apply:
        print("GET-only preflight; receipt:", journal)
        return

    flow = _ensure(
        client,
        "flows/instances/",
        "slug",
        SLUG,
        {
            "name": "Socrat password self-service",
            "slug": SLUG,
            "title": "Update password",
            "designation": "stage_configuration",
            "authentication": "require_authenticated",
            "background": "",
            "layout": "stacked",
            "policy_engine_mode": "all",
            "denied_action": "message_continue",
        },
    )
    success = _ensure(
        client,
        "stages/prompt/prompts/",
        "name",
        "socrat-password-updated-message",
        {
            "name": "socrat-password-updated-message",
            "field_key": "password_updated",
            "label": "Password updated",
            "type": "static",
            "required": False,
            "initial_value": "Your password has been updated. Continue to sign out. Use your new password next time.",
            "order": 0,
        },
    )
    done_stage = _ensure(
        client,
        "stages/prompt/stages/",
        "name",
        "socrat-password-updated",
        {"name": "socrat-password-updated", "fields": [success["pk"]], "validation_policies": []},
    )
    bindings = _ensure_bindings(client, flow, prompt, write, done_stage)
    _verify_shared_unchanged(client, snapshot)
    resources = route()
    _apply_route(cast("list[dict[str, object]]", resources))
    (journal / "verified.json").write_text(
        json.dumps({"flow": flow, "bindings": bindings, "route": resources}, indent=2)
    )
    print("Verified additive native self-service and exact-path entry route. Receipt:", journal)


if __name__ == "__main__":
    main()
