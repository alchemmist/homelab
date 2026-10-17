#!/usr/bin/env python3
import json
import sys

import yaml

from dashboard_descriptions import apply_descriptions


DASHBOARD_UIDS = {
    "7e0a61e486f727d763fb1d86fdd629c2",
    "629701ea43bf69291922ea45f4a87d37",
    "7d57716318ee0dddbac5a7f451fb7753",
    "3e97d1d02672cdd0861f4c97c64f89b2",
    "fac67cfbe174d3ef53eb473d73d9212f",
}
AGGREGATION = "avg without (pod, namespace, container, endpoint, service)"


def rewrite_panels(panels):
    for panel in panels:
        for target in panel.get("targets", []):
            expression = target.get("expr", "")
            if expression and not expression.startswith(AGGREGATION):
                target["expr"] = f"{AGGREGATION} (\n{expression.strip()}\n)"
        rewrite_panels(panel.get("panels", []))


def render(resources):
    for resource in resources:
        if not isinstance(resource, dict) or resource.get("kind") != "ConfigMap":
            continue
        for key, value in resource.get("data", {}).items():
            if not key.endswith(".json"):
                continue
            try:
                dashboard = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(dashboard, dict) and dashboard.get("uid") and 'panels' in dashboard:
                if dashboard['uid'] in DASHBOARD_UIDS:
                    rewrite_panels(dashboard.get("panels", []))
                apply_descriptions(dashboard)
                resource["data"][key] = json.dumps(dashboard, separators=(",", ":"))
    return resources


def main():
    resources = list(yaml.safe_load_all(sys.stdin))
    yaml.safe_dump_all(render(resources), sys.stdout, sort_keys=False)


if __name__ == "__main__":
    main()
