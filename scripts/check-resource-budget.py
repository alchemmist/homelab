"""Check that cluster resource requests stay within the configured budget."""
import argparse
import copy
import json
import re
import sys
from decimal import Decimal
from typing import cast

RESOURCES = ("cpu", "memory", "ephemeral-storage")
QUANTITY = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))([eE][+-]?\d+|[numkKMGTPE]|[KMGTPE]i)?$")


def quantity(value):
    match = QUANTITY.fullmatch(str(value))
    if not match:
        raise ValueError("Invalid resource quantity: " + str(value))
    number = Decimal(match[1])
    suffix = match[2] or ""
    if suffix.startswith(("e", "E")) and len(suffix) > 1 and not suffix.endswith("i"):
        result = number * Decimal(10) ** int(suffix[1:])
    elif suffix.endswith("i"):
        result = number * Decimal(1024) ** ("KMGTPE".index(suffix[0]) + 1)
    else:
        result = (
            number
            * Decimal(10)
            ** {
                "": 0,
                "n": -9,
                "u": -6,
                "m": -3,
                "k": 3,
                "K": 3,
                "M": 6,
                "G": 9,
                "T": 12,
                "P": 15,
                "E": 18,
            }[suffix]
        )
    if result < 0:
        raise ValueError("Negative resource quantity: " + str(value))
    return result


def vector(values=None):
    return {name: quantity((values or {}).get(name, 0)) for name in RESOURCES}


def add(left, right):
    return {name: left[name] + right[name] for name in RESOURCES}


def maximum(left, right):
    return {name: max(left[name], right[name]) for name in RESOURCES}


def effective_requests(pod):
    spec = pod.get("spec", {})
    total, sidecars, init_peak = vector(), vector(), vector()
    for container in spec.get("containers", []):
        total = add(total, vector(container.get("resources", {}).get("requests")))
    for container in spec.get("initContainers", []):
        requested = vector(container.get("resources", {}).get("requests"))
        if container.get("restartPolicy") == "Always":
            sidecars = add(sidecars, requested)
            init_peak = maximum(init_peak, sidecars)
        else:
            init_peak = maximum(init_peak, add(sidecars, requested))
    total = maximum(add(total, sidecars), init_peak)
    for name, value in spec.get("resources", {}).get("requests", {}).items():
        if name in RESOURCES:
            total[name] = quantity(value)
    return add(total, vector(spec.get("overhead")))


def proposed_pod(pod, profiles):
    label = pod["metadata"].get("namespace", "default") + "/" + pod["metadata"]["name"]
    owner = next(
        (value for value in pod["metadata"].get("ownerReferences", []) if value.get("controller")),
        {},
    )
    matches = [
        profile
        for profile in profiles
        if profile["namespace"] == pod["metadata"].get("namespace", "default")
        and profile["ownerKind"] == owner.get("kind")
        and re.fullmatch(profile["ownerPattern"], owner.get("name", ""))
    ]
    if len(matches) != 1:
        raise ValueError(label + ": " + ("ambiguous profiles" if matches else "unmatched profile"))
    expected = matches[0]["containers"]
    result = copy.deepcopy(pod)
    present = set()
    for field in ("containers", "initContainers"):
        for container in result.get("spec", {}).get(field, []):
            name = container["name"]
            present.add(name)
            if name not in expected:
                raise ValueError(label + "/" + name + ": unmatched container")
            resources = container.setdefault("resources", {})
            for mode in ("requests", "limits"):
                resources.setdefault(mode, {}).update(expected[name].get(mode, {}))
            if expected[name].get("removeCpuLimit"):
                resources["limits"].pop("cpu", None)
    if set(expected) - present:
        raise ValueError(
            label
            + ": profile contains absent containers "
            + ", ".join(sorted(set(expected) - present))
        )
    return result


def items(value):
    return value["items"] if isinstance(value, dict) else value


def _validate_container(resources: dict[str, dict[str, object]]) -> None:
    """Require positive requests, ordered limits and boolean CPU-limit removal."""
    requests = resources.get("requests", {})
    for name in RESOURCES:
        if name not in requests or quantity(requests[name]) <= 0:
            raise ValueError("Profile requires positive requests/" + name)
    for name, limit in resources.get("limits", {}).items():
        if name in RESOURCES and quantity(limit) < quantity(requests[name]):
            raise ValueError("Profile limit below request: " + name)
    remove = resources.get("removeCpuLimit", False)
    if not isinstance(remove, bool):
        raise ValueError("removeCpuLimit must be boolean")
    if remove and "cpu" in resources.get("limits", {}):
        raise ValueError("Profile cannot set and remove CPU limit")


def _validate_profile(profile: dict[str, object]) -> None:
    """Check one budget profile's identifying fields and container contracts."""
    for name in ("namespace", "ownerKind", "ownerPattern"):
        if not isinstance(profile.get(name), str) or not profile[name]:
            raise ValueError("Profile requires " + name)
    # The loop above established that ownerPattern is a non-empty string.
    re.compile(cast("str", profile["ownerPattern"]))
    containers = profile.get("containers")
    if not isinstance(containers, dict) or not containers:
        raise ValueError("Profile requires containers")
    for resources in containers.values():
        _validate_container(resources)


def validate_profiles(profiles: object) -> None:
    """Validate the shape and content of every budget profile."""
    if not isinstance(profiles, list):
        raise ValueError("Profiles must be a JSON list")
    for profile in profiles:
        _validate_profile(profile)


def _node_table(nodes: object) -> dict[str, dict[str, object]]:
    """Summarize each node's allocatable capacity keyed by its name."""
    table: dict[str, dict[str, object]] = {}
    for node in items(nodes):
        table[node["metadata"]["name"]] = {
            "allocatable": vector(node["status"]["allocatable"]),
            "current_requests": vector(),
            "proposed_requests": vector(),
            "pods": 0,
        }
    return table


def _flag_overcommit(nodes: dict[str, dict[str, dict[str, Decimal]]], errors: list[object]) -> None:
    """Compute remaining capacity per node and record every deficit."""
    for name, node in nodes.items():
        for mode in ("current", "proposed"):
            node[mode + "_remaining"] = {
                resource: node["allocatable"][resource] - node[mode + "_requests"][resource]
                for resource in RESOURCES
            }
        for resource, remaining in node["proposed_remaining"].items():
            if remaining < 0:
                errors.append(name + ": proposed requests exceed allocatable " + resource)


def budget(pods, nodes, profiles):
    validate_profiles(profiles)
    report = {
        "scope": "Current placement only; not a scheduler simulation or an N-1, rollout, peak-use or memory-safety guarantee. Requests are not actual usage. Unassigned pods are not charged to any node.",
        "nodes": _node_table(nodes),
        "unassigned": [],
        "errors": [],
    }
    for pod in items(pods):
        if pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
            continue
        label = pod["metadata"].get("namespace", "default") + "/" + pod["metadata"]["name"]
        try:
            proposed = proposed_pod(pod, profiles)
        except ValueError as error:
            report["errors"].append(str(error))
            proposed = pod
        current, future = effective_requests(pod), effective_requests(proposed)
        node_name = pod.get("spec", {}).get("nodeName")
        if not node_name:
            report["unassigned"].append(
                {"pod": label, "current_requests": current, "proposed_requests": future}
            )
            continue
        if node_name not in report["nodes"]:
            report["errors"].append(label + ": unknown node " + node_name)
            continue
        entry = report["nodes"][node_name]
        entry["pods"] += 1
        entry["current_requests"] = add(entry["current_requests"], current)
        entry["proposed_requests"] = add(entry["proposed_requests"], future)
    _flag_overcommit(report["nodes"], report["errors"])
    report["ok"] = not report["errors"]
    report["units"] = {"cpu": "cores", "memory": "bytes", "ephemeral-storage": "bytes"}
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Read-only current-placement request budget comparison"
    )
    for name in ("pods", "nodes", "profiles"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        values = []
        for path in (args.pods, args.nodes, args.profiles):
            with open(path) as source:
                values.append(json.load(source))
        report = budget(*values)
        print(
            json.dumps(
                report,
                indent=2,
                default=lambda value: str(value) if isinstance(value, Decimal) else value,
            )
        )
        return 0 if report["ok"] else 1
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
