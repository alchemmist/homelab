#!/usr/bin/env python3
"""Additive native External password self-service. Never handles human passwords."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import urllib.request
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root
    token = json.loads((root / "credentials.json").read_text())["AUTHENTIK_BOOTSTRAP_TOKEN"]
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda host, *a, **kw: original(
        "109.173.40.247" if host == HOST else host, *a, **kw
    )
    os.umask(0o077)
    journal = Path(tempfile.mkdtemp(prefix="password-self-service-", dir=root))

    def api(method, path, data=None) -> dict[str, object]:
        if method != "GET":
            assert args.apply and method == "POST", "Additive creation only"
        request = urllib.request.Request(
            "https://" + HOST + "/api/v3/" + path,
            data=json.dumps(data).encode() if data is not None else None,
            method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result: dict[str, object] = json.load(response)
        if method != "GET":
            (
                journal / ("created-" + str(len(list(journal.glob("created-*")))) + ".json")
            ).write_text(json.dumps({"path": path, "result": result}, indent=2))
        return result

    def all_rows(path) -> list[dict[str, object]]:
        data = api("GET", path + "?page_size=100")
        assert not data.get("next"), "Pagination requires review"
        return cast("list[dict[str, object]]", data["results"])

    snapshot = {
        p: all_rows(p)
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

    def exact(path, name) -> dict[str, object]:
        matches = [r for r in snapshot[path] if r.get("name") == name]
        assert len(matches) == 1, "Missing/ambiguous native object: " + name
        return matches[0]

    native = exact("flows/instances/", "Change Password")
    assert (
        native["authentication"] == "require_authenticated"
        and native["slug"] == "default-password-change"
    )
    prompt = exact("stages/prompt/stages/", "default-password-change-prompt")
    write = exact("stages/user_write/", "default-password-change-write")
    assert write["user_creation_mode"] == "never_create" and write["create_users_group"] is None
    fields = [
        p for p in snapshot["stages/prompt/prompts/"] if p["pk"] in cast("list[object]", prompt["fields"])
    ]
    assert {p["field_key"] for p in fields} == {"password", "password_repeat"}
    assert all(p["type"] == "password" and p["required"] for p in fields)
    assert prompt["validation_policies"], "Password policy must be preserved"
    print(
        "Verified native authenticated-only password/repeat, validation policy, never-create writer."
    )
    if not args.apply:
        print("GET-only preflight; receipt:", journal)
        return

    def ensure(path, key, value, spec) -> dict[str, object]:
        matches = [r for r in all_rows(path) if r.get(key) == value]
        assert len(matches) <= 1, "Ambiguous owned object"
        if matches:
            obj = matches[0]
            assert all(obj.get(k) == v for k, v in spec.items()), "Owned object drift: " + value
            return obj
        # Absence rechecked immediately before additive create.
        obj = api("POST", path, spec)
        verified = [r for r in all_rows(path) if r.get(key) == value]
        assert len(verified) == 1 and all(verified[0].get(k) == v for k, v in spec.items())
        return verified[0]

    flow = ensure(
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
    success = ensure(
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
    done_stage = ensure(
        "stages/prompt/stages/",
        "name",
        "socrat-password-updated",
        {"name": "socrat-password-updated", "fields": [success["pk"]], "validation_policies": []},
    )
    expected = [(0, prompt["pk"]), (10, write["pk"]), (20, done_stage["pk"])]
    existing = [b for b in all_rows("flows/bindings/") if b["target"] == flow["pk"]]
    assert all((b["order"], b["stage"]) in expected for b in existing), "Unexpected flow binding"
    for order, stage in expected:
        matches = [b for b in existing if b["order"] == order and b["stage"] == stage]
        assert len(matches) <= 1
        if not matches:
            api(
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
    bindings = [b for b in all_rows("flows/bindings/") if b["target"] == flow["pk"]]
    assert sorted((b["order"], b["stage"]) for b in bindings) == expected
    # No updates to shared prompts, password policy, write stage, brand or login flow.
    for path, name in [
        ("flows/instances/", "Change Password"),
        ("stages/prompt/stages/", "default-password-change-prompt"),
        ("stages/user_write/", "default-password-change-write"),
    ]:
        current = [r for r in all_rows(path) if r["name"] == name][0]
        before = exact(path, name)
        # flow_set is a derived reverse reference to our newly added flow.
        assert {k: v for k, v in current.items() if k != "flow_set"} == {
            k: v for k, v in before.items() if k != "flow_set"
        }
    k = ["kubectl", "--kubeconfig", "/etc/rancher/k3s/k3s.yaml"]
    env = {**os.environ, "K3S_CONFIG_FILE": "/dev/null"}
    resources = route()
    for obj in resources:
        result = subprocess.run(
            k
            + ["-n", "identity", "get", obj["kind"].lower(), obj["metadata"]["name"], "-o", "json"],
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
                k + ["create", "-f", "-"], input=json.dumps(obj), text=True, env=env, check=True
            )
    (journal / "verified.json").write_text(
        json.dumps({"flow": flow, "bindings": bindings, "route": resources}, indent=2)
    )
    print("Verified additive native self-service and exact-path entry route. Receipt:", journal)


if __name__ == "__main__":
    main()
