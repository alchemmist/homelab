import json
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import cast

PANEL_UNITS = {
    "3e97d1d02672cdd0861f4c97c64f89b2": {9: "pps", 12: "short"},
    "fac67cfbe174d3ef53eb473d73d9212f": {9: "pps", 12: "short"},
    "6be0s85Mk": {4: "s"},
    "vkQ0UHxik": {22: "short"},
}
READINESS_SUBJECTS = {
    "KubePodNotReady": "Pod {{ $labels.namespace }}/{{ $labels.pod }}",
    "KubeNodeNotReady": "Node {{ $labels.node }}",
}


def apply_alert_descriptions(resource) -> None:
    if not isinstance(resource, dict) or resource.get("kind") != "PrometheusRule":
        return
    for group in resource.get("spec", {}).get("groups", []):
        for rule in group.get("rules", []):
            subject = READINESS_SUBJECTS.get(rule.get("alert"))
            if subject:
                annotations = rule.setdefault("annotations", {})
                annotations["summary"] = subject.split()[0] + " is not ready."
                annotations["description"] = (
                    subject
                    + " is not Ready. The alert becomes Firing after "
                    + str(rule.get("for", "0s"))
                    + " in this state."
                )


@lru_cache(maxsize=1)
def load_descriptions() -> dict[str, dict[str, str]]:
    descriptions = {}
    for path in sorted(Path(__file__).with_name("dashboard-descriptions").glob("*.json")):
        entries = json.loads(path.read_text())
        overlap = descriptions.keys() & entries.keys()
        if overlap:
            raise ValueError("Duplicate dashboard descriptions: " + ", ".join(sorted(overlap)))
        descriptions.update(entries)
    return descriptions


def panels(dashboard) -> Iterator[dict[str, object]]:
    for panel in dashboard.get("panels", []):
        if panel.get("type") not in {"row", "text"}:
            yield panel
        yield from panels(panel)


def apply_descriptions(dashboard, descriptions=None) -> None:
    catalog = load_descriptions() if descriptions is None else descriptions
    uid = dashboard["uid"]
    entries = catalog.get(uid, {})
    for panel in panels(dashboard):
        description = entries.get(str(panel["id"]))
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Missing description for dashboard {uid}, panel {panel['id']}")
        panel["description"] = description
        units = PANEL_UNITS.get(uid, {})
        unit = units.get(cast("int", panel["id"]))
        if unit:
            fields = cast("dict[str, object]", panel.setdefault("fieldConfig", {}))
            cast("dict[str, object]", fields.setdefault("defaults", {}))["unit"] = unit
