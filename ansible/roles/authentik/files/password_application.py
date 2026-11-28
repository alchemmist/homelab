#!/usr/bin/env python3
"""Register a providerless self-service dashboard link, never modify people."""

import argparse
import json
import os
import socket
import tempfile
import urllib.request
from pathlib import Path
from typing import cast

LAUNCH_URL = "https://auth.socrat.alchemmist.xyz/change-password"


def validate(spec: dict[str, object]) -> None:
    """Document the validate operation."""
    if spec["slug"] != "password-self-service":
        msg = "Application slug must stay password-self-service"
        raise RuntimeError(msg)
    if spec["provider"] is not None:
        msg = "Dashboard link must stay providerless"
        raise RuntimeError(msg)
    if spec["meta_launch_url"] != LAUNCH_URL:
        msg = "Launch URL must stay the reviewed change-password page"
        raise RuntimeError(msg)
    if spec["policy_engine_mode"] != "any":
        msg = "Policy engine mode must stay any"
        raise RuntimeError(msg)
    if spec["name"] != "Change password":
        msg = "Application name must stay Change password"
        raise RuntimeError(msg)
    if spec["group"] != "Account":
        msg = "Application group must stay Account"
        raise RuntimeError(msg)


def _verify_drift(app: dict[str, object], spec: dict[str, object], message: str) -> None:
    """Stop when an existing or created application drifts from the spec."""
    if any(app.get(k) != v for k, v in spec.items()):
        raise RuntimeError(message)


def _verify_unrestricted(bindings: dict[str, object]) -> None:
    """Stop when the dashboard link gained any admission restriction."""
    if bindings.get("next"):
        msg = "Unexpected admission restriction"
        raise RuntimeError(msg)
    if bindings["results"] != []:
        msg = "Unexpected admission restriction"
        raise RuntimeError(msg)


def main() -> None:
    """Document the main operation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root
    spec = cast(
        "dict[str, object]",
        json.loads((root / "password-self-service-application.json").read_text()),
    )
    validate(spec)
    token = json.loads((root / "credentials.json").read_text())["AUTHENTIK_BOOTSTRAP_TOKEN"]
    original = socket.getaddrinfo
    socket.getaddrinfo = lambda h, *a, **kw: original(
        "109.173.40.247" if h == "auth.socrat.alchemmist.xyz" else h, *a, **kw
    )

    def api(method: str, path: str, payload: object | None = None) -> dict[str, object]:
        request = urllib.request.Request(
            "https://auth.socrat.alchemmist.xyz/api/v3/" + path,
            method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=25) as response:
            document: dict[str, object] = json.load(response)
            return document

    def existing() -> list[dict[str, object]]:
        data = api("GET", "core/applications/?superuser_full_list=true&slug=password-self-service")
        if data.get("next"):
            msg = "Application listing must stay unpaginated"
            raise RuntimeError(msg)
        results = cast("list[dict[str, object]]", data["results"])
        if len(results) > 1:
            msg = "At most one password-self-service application may exist"
            raise RuntimeError(msg)
        return results

    before = existing()
    if before:
        _verify_drift(before[0], spec, "Existing application drift; stop")
        bindings = api("GET", "policies/bindings/?target=" + cast("str", before[0]["pk"]))
        _verify_unrestricted(bindings)
        print("Dashboard application already matches; no changes.")
        return
    if not args.apply:
        print(
            "Plan: create providerless Change password application; "
            "no bindings, groups or user changes."
        )
        return
    os.umask(0o077)
    receipt = Path(tempfile.mkdtemp(prefix="password-dashboard-", dir=root))
    (receipt / "preimage.json").write_text(
        json.dumps({"applications": before, "desired": spec}, indent=2)
    )
    if existing() != before:
        msg = "Application appeared after plan"
        raise RuntimeError(msg)
    created = api("POST", "core/applications/", spec)
    (receipt / "created.json").write_text(json.dumps(created, indent=2))
    after = existing()
    if len(after) != 1:
        msg = "Exactly one dashboard application must exist after creation"
        raise RuntimeError(msg)
    _verify_drift(after[0], spec, "Created application drifts from the desired spec")
    bindings = api("GET", "policies/bindings/?target=" + cast("str", after[0]["pk"]))
    _verify_unrestricted(bindings)
    (receipt / "verified.json").write_text(json.dumps(after[0], indent=2))
    print(
        "Verified Change password / Account dashboard link, "
        "no provider or restrictive bindings. Receipt:",
        receipt,
    )


if __name__ == "__main__":
    main()
