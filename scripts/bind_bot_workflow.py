"""Render an offline n8n template with its instance-specific credential reference."""

import argparse
import json
from pathlib import Path


def bind(document, credential_id):
    if not credential_id.isalnum() and not credential_id.replace("-", "").isalnum():
        raise ValueError(
            "supply the actual n8n credential ID, not the secret or placeholder"
        )
    count = 0
    for node in document["nodes"]:
        ref = node.get("credentials", {}).get("httpHeaderAuth", {})
        if (
            node.get("parameters", {})
            .get("url", "")
            .startswith("https://bot.socrat.alchemmist.xyz/api/")
        ):
            if ref.get("id") not in {"SOCRAT_BOT_FAILURES_ID", "SOCRAT_BOT_ALERTS_ID"}:
                raise ValueError("unexpected bot credential reference")
            ref["id"] = credential_id
            count += 1
    if count != 1:
        raise ValueError("expected exactly one bot credential placeholder")
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", type=Path)
    parser.add_argument("credential_id")
    args = parser.parse_args()
    print(
        json.dumps(
            bind(json.loads(args.template.read_text()), args.credential_id), indent=2
        )
    )
