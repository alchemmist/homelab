#!/usr/bin/env python3
"""Register a providerless self-service dashboard link, never modify people."""

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
import socket
import tempfile
import urllib.request


def validate(spec: Mapping[str, object]):
    assert spec["slug"] == "password-self-service"
    assert spec["provider"] is None
    assert spec["meta_launch_url"] == "https://auth.socrat.alchemmist.xyz/change-password"
    assert spec["policy_engine_mode"] == "any"
    assert spec["name"] == "Change password" and spec["group"] == "Account"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root
    spec = json.loads((root / "password-self-service-application.json").read_text())
    validate(spec)
    token = json.loads((root / "credentials.json").read_text())["AUTHENTIK_BOOTSTRAP_TOKEN"]
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda h, *a, **kw: original(
        "109.173.40.247" if h == "auth.socrat.alchemmist.xyz" else h, *a, **kw
    )

    def api(method: str, path: str, payload: Mapping[str, object] | None = None):
        request = urllib.request.Request(
            "https://auth.socrat.alchemmist.xyz/api/v3/" + path,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)

    def existing():
        data = api("GET", "core/applications/?superuser_full_list=true&slug=password-self-service")
        assert not data.get("next") and len(data["results"]) <= 1
        return data["results"]

    before = existing()
    if before:
        assert all(before[0].get(k) == v for k, v in spec.items()), (
            "Existing application drift; stop"
        )
        bindings = api("GET", "policies/bindings/?target=" + before[0]["pk"])
        assert not bindings.get("next") and bindings["results"] == [], (
            "Unexpected admission restriction"
        )
        print("Dashboard application already matches; no changes.")
        return
    if not args.apply:
        print(
            "Plan: create providerless Change password application; no bindings, groups or user changes."
        )
        return
    os.umask(0o077)
    receipt = Path(tempfile.mkdtemp(prefix="password-dashboard-", dir=root))
    (receipt / "preimage.json").write_text(
        json.dumps({"applications": before, "desired": spec}, indent=2)
    )
    assert existing() == before, "Application appeared after plan"
    created = api("POST", "core/applications/", spec)
    (receipt / "created.json").write_text(json.dumps(created, indent=2))
    after = existing()
    assert len(after) == 1 and all(after[0].get(k) == v for k, v in spec.items())
    bindings = api("GET", "policies/bindings/?target=" + after[0]["pk"])
    assert not bindings.get("next") and bindings["results"] == []
    (receipt / "verified.json").write_text(json.dumps(after[0], indent=2))
    print(
        "Verified Change password / Account dashboard link, no provider or restrictive bindings. Receipt:",
        receipt,
    )


if __name__ == "__main__":
    main()
