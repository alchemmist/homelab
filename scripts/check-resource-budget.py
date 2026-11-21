import argparse
import copy
import json
import re
import sys
from decimal import Decimal
from typing import cast

RESOURCES = ("cpu", "memory", "ephemeral-storage")
QUANTITY = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))([eE][+-]?\d+|[numkKMGTPE]|[KMGTPE]i)?$")


def quantity(value: object):
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


def vector(values: dict[str, object] | None = None):
    return {name: quantity((values or {}).get(name, 0)) for name in RESOURCES}


def add(left: dict[str, Decimal], right: dict[str, Decimal]):
    return {name: left[name] + right[name] for name in RESOURCES}


def maximum(left: dict[str, Decimal], right: dict[str, Decimal]):
    return {name: max(left[name], right[name]) for name in RESOURCES}


def effective_requests(pod: dict[str, object]):
    spec = cast("dict[str, object]", pod.get("spec", {}))
    total, sidecars, init_peak = vector(), vector(), vector()
    for raw in cast("list[object]", spec.get("containers", [])):
        container = cast("dict[str, object]", raw)
        resources = cast("dict[str, object]", container.get("resources", {}))
        total = add(total, vector(cast("dict[str, object] | None", resources.get("requests"))))
    for raw in cast("list[object]", spec.get("initContainers", [])):
        container = cast("dict[str, object]", raw)
        resources = cast("dict[str, object]", container.get("resources", {}))
        requested = vector(cast("dict[str, object] | None", resources.get("requests")))
        if container.get("restartPolicy") == "Always":
            sidecars = add(sidecars, requested)
            init_peak = maximum(init_peak, sidecars)
        else:
            init_peak = maximum(init_peak, add(sidecars, requested))
    total = maximum(add(total, sidecars), init_peak)
    pod_resources = cast("dict[str, object]", spec.get("resources", {}))
    for name, value in cast("dict[str, object]", pod_resources.get("requests", {})).items():
        if name in RESOURCES:
            total[name] = quantity(value)
    return add(total, vector(cast("dict[str, object] | None", spec.get("overhead"))))


def proposed_pod(pod: dict[str, object], profiles: list[dict[str, object]]):
    metadata = cast("dict[str, object]", pod["metadata"])
    label = cast("str", metadata.get("namespace", "default")) + "/" + cast("str", metadata["name"])
    owner = next(
        (
            value
            for value in cast("list[dict[str, object]]", metadata.get("ownerReferences", []))
            if value.get("controller")
        ),
        cast("dict[str, object]", {}),
    )
    pod_namespace = cast("str", metadata.get("namespace", "default"))
    matches = [
        profile
        for profile in profiles
        if profile["namespace"] == pod_namespace
        and profile["ownerKind"] == owner.get("kind")
        and re.fullmatch(cast("str", profile["ownerPattern"]), cast("str", owner.get("name", "")))
    ]
    if len(matches) != 1:
        raise ValueError(label + ": " + ("ambiguous profiles" if matches else "unmatched profile"))
    expected = cast("dict[str, dict[str, object]]", matches[0]["containers"])
    result = copy.deepcopy(pod)
    present = set()
    spec = cast("dict[str, object]", result.get("spec", {}))
    for field in ("containers", "initContainers"):
        for raw in cast("list[object]", spec.get(field, [])):
            container = cast("dict[str, object]", raw)
            name = cast("str", container["name"])
            present.add(name)
            if name not in expected:
                raise ValueError(label + "/" + name + ": unmatched container")
            resources = cast("dict[str, object]", container.setdefault("resources", {}))
            for mode in ("requests", "limits"):
                cast("dict[str, object]", resources.setdefault(mode, {})).update(
                    cast("dict[str, object]", expected[name].get(mode, {}))
                )
            if expected[name].get("removeCpuLimit"):
                cast("dict[str, object]", resources["limits"]).pop("cpu", None)
    if set(expected) - present:
        raise ValueError(
            label
            + ": profile contains absent containers "
            + ", ".join(sorted(set(expected) - present))
        )
    return result


def items(value: object):
    return value["items"] if isinstance(value, dict) else value


def validate_profiles(profiles: list[object]):
    if not isinstance(profiles, list):
        raise ValueError("Profiles must be a JSON list")
    for raw in profiles:
        profile = cast("dict[str, object]", raw)
        for name in ("namespace", "ownerKind", "ownerPattern"):
            if not isinstance(profile.get(name), str) or not profile[name]:
                raise ValueError("Profile requires " + name)
        re.compile(cast("str", profile["ownerPattern"]))
        containers_raw = profile.get("containers")
        if not isinstance(containers_raw, dict) or not containers_raw:
            raise ValueError("Profile requires containers")
        containers = cast("dict[str, object]", containers_raw)
        for entry in containers.values():
            resources = cast("dict[str, object]", entry)
            requests = cast("dict[str, object]", resources.get("requests", {}))
            for name in RESOURCES:
                if name not in requests or quantity(requests[name]) <= 0:
                    raise ValueError("Profile requires positive requests/" + name)
            limits = cast("dict[str, object]", resources.get("limits", {}))
            for name, limit in limits.items():
                if name in RESOURCES and quantity(limit) < quantity(requests[name]):
                    raise ValueError("Profile limit below request: " + name)
            if not isinstance(resources.get("removeCpuLimit", False), bool):
                raise ValueError("removeCpuLimit must be boolean")
            if resources.get("removeCpuLimit") and "cpu" in cast(
                "dict[str, object]", resources.get("limits", {})
            ):
                raise ValueError("Profile cannot set and remove CPU limit")


def budget(pods: object, nodes: object, profiles: list[object]):
    validate_profiles(profiles)
    report = {
        "scope": "Current placement only; not a scheduler simulation or an N-1, rollout, peak-use or memory-safety guarantee. Requests are not actual usage. Unassigned pods are not charged to any node.",
        "nodes": {},
        "unassigned": [],
        "errors": [],
    }
    for node_raw in items(nodes):
        node = cast("dict[str, object]", node_raw)
        metadata = cast("dict[str, object]", node["metadata"])
        node_status = cast("dict[str, object]", node["status"])
        report["nodes"][cast("str", metadata["name"])] = {
            "allocatable": vector(cast("dict[str, object]", node_status.get("allocatable", {}))),
            "current_requests": vector(),
            "proposed_requests": vector(),
            "pods": 0,
        }
    for pod_raw in items(pods):
        pod = cast("dict[str, object]", pod_raw)
        status = cast("dict[str, object]", pod.get("status", {}))
        if status.get("phase") in ("Succeeded", "Failed"):
            continue
        metadata = cast("dict[str, object]", pod["metadata"])
        label = cast("str", metadata.get("namespace", "default")) + "/" + cast(
            "str", metadata["name"]
        )
        try:
            proposed = proposed_pod(pod, cast("list[dict[str, object]]", profiles))
        except ValueError as error:
            report["errors"].append(str(error))
            proposed = pod
        current, future = effective_requests(pod), effective_requests(proposed)
        pod_spec = cast("dict[str, object]", pod.get("spec", {}))
        node_name = cast("str | None", pod_spec.get("nodeName"))
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
    for name, node_raw in report["nodes"].items():
        node = cast("dict[str, object]", node_raw)
        for mode in ("current", "proposed"):
            node[mode + "_remaining"] = {
                resource: cast("dict[str, Decimal]", node["allocatable"])[resource]
                - cast("dict[str, Decimal]", node[mode + "_requests"])[resource]
                for resource in RESOURCES
            }
        for resource, remaining in cast("dict[str, Decimal]", node["proposed_remaining"]).items():
            if remaining < 0:
                report["errors"].append(name + ": proposed requests exceed allocatable " + resource)
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
