#!/usr/bin/env python3
"""Socrat Bot OIDC registration; same guarded protocol as pgAdmin."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "oidc", Path(__file__).with_name("provision-pgadmin-oidc.py")
)
oidc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oidc)
oidc.HOST = "bot.socrat.alchemmist.xyz"
oidc.CLIENT = "socrat-bot"
oidc.APP.update(
    name="Socrat Bot",
    slug="socrat-bot",
    meta_launch_url="https://" + oidc.HOST + "/",
    meta_description="Token console for bot administrators and homelab owners.",
)
oidc.PROVIDER.update(
    name="homelab-socrat-bot",
    client_id=oidc.CLIENT,
    grant_types=["authorization_code"],
    redirect_uris=[{"matching_mode": "strict", "url": "https://" + oidc.HOST + "/oauth/callback"}],
)
READERS = "socrat-bot-admin"
ATTRS = {"homelab_public_web_role": READERS}


def reader_group(api):
    group = oidc.iam.one(api, "core/groups/", "name", READERS)
    if group:
        oidc.check(
            group["attributes"] == ATTRS
            and group["is_superuser"] is False
            and all(group[k] == [] for k in ("parents", "children", "roles")),
            "Unexpected privileged or foreign readers group",
        )
    return group


def extra_bindings(api, app):
    group = reader_group(api)
    bindings = api.rows("policies/bindings/?target=" + str(app["pk"]))
    return (
        {READERS: group["pk"]}
        if group and any(b.get("group") == group["pk"] for b in bindings)
        else {}
    )


if __name__ == "__main__":
    oidc.main(namespace="socrat-bot", extra_bindings=extra_bindings)
