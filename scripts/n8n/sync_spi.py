#!/usr/bin/env python3
"""Render SPI workflows. Active workflows require explicit operator deactivation."""

import copy
import json
from typing import cast
from urllib.parse import urlencode

from sync import BASE, CONFIG, api


def render(template, mapping) -> dict[str, object]:
"""Bind private SPI credentials from the mapping into a workflow copy."""
    w: dict[str, object] = copy.deepcopy(template)
    aliases = {
        "SPI_WORKER_CREDENTIAL_ID": "worker",
        "ALERT_INGRESS_CREDENTIAL_ID": "ingress",
        "SOCRAT_BOT_CREDENTIAL_ID": "bot",
    }
    for n in cast("list[dict[str, object]]", w["nodes"]):
        for kind, c in list(cast("dict[str, object]", n.get("credentials", {})).items()):
            alias = aliases[cast("str", cast("dict[str, object]", c)["id"])]
            if not mapping.get(alias, {}).get("id"):
                raise RuntimeError("Missing private SPI credential mapping: " + alias)
            cast("dict[str, object]", n["credentials"])[kind] = mapping[alias]
    return w


def sync(relative) -> dict[str, object]:
"""Upsert the reviewed workflow inactive, refusing ambiguous or active matches."""
    mapping = json.loads((CONFIG / "spi-credentials.json").read_text())
    template = json.loads((BASE / relative).read_text())
    w = render(template, mapping)
    # Search every page before resolving identity. SPI triage must never be
    # recreated when its original workflow is missing or renamed.
    matches: list[dict[str, object]] = []
    cursor = None
    seen = set()
    while True:
        query = {"limit": 250}
        if cursor:
            query["cursor"] = cursor
        page = api("GET", "workflows?" + urlencode(query))
        matches.extend(
            x for x in cast("list[dict[str, object]]", page["data"]) if x["name"] == w["name"]
        )
        cursor = page.get("nextCursor")
        if not cursor:
            break
        if cursor in seen:
            raise RuntimeError("Repeated workflow pagination cursor")
        seen.add(cursor)
    if len(matches) > 1:
        raise RuntimeError("Ambiguous workflow name")
    if relative == "docs/n8n/spi/triage-workflow.json" and not matches:
        raise RuntimeError("Existing SPI triage workflow not found; refusing creation")
    if matches and matches[0]["active"]:
        raise RuntimeError("Deactivate explicitly before syncing")
    result: dict[str, object] = api(
        "PUT" if matches else "POST",
        "workflows/" + cast("str", matches[0]["id"]) if matches else "workflows",
        {k: w[k] for k in ["name", "nodes", "connections", "settings"]},
    )
    print("Workflow synced inactive:", result["id"], result["name"])
    return result


if __name__ == "__main__":
    import sys

    sync(
        "docs/n8n/spi/triage-workflow.json"
        if "--triage" in sys.argv
        else "docs/n8n/socrat-bot/workflow.json"
    )
