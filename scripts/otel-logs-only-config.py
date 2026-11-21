#!/usr/bin/env python3
"""Merge log-only Collector changes; refuse any shared component mutation.
Reads YAML files, emits YAML (config may contain credentials: keep output private).
Never changes metric/trace pipelines, existing exporters, TLS, storage or receivers.
"""

import argparse
import copy
import pathlib
from typing import cast

import yaml


def require(expected: object, message: str) -> None:
    """Enforce an invariant, failing with the given message."""
    if not expected:
        raise ValueError(message)


def narrow_selflog_exclude(candidate: dict[str, object], receiver: dict[str, object]) -> None:
    """Move the known overbroad self-log exclusion to the narrow cluster path."""
    broad = "/var/log/pods/*_otel-*_*/*/*.log"
    narrow = (
        "/var/log/pods/cattle-monitoring-system_"
        "prometheus-kube-prometheus-stack-prometheus-*_*/otel-cluster/*.log"
    )
    if candidate.get("exclude") == [narrow]:
        existing = cast("list[object]", receiver.get("exclude", []))
        receiver["exclude"] = [narrow if p == broad else p for p in existing]


def merge(live, desired):
    result = copy.deepcopy(live)
    target = desired["service"]["pipelines"]["logs"]
    other = [v for k, v in live["service"]["pipelines"].items() if k != "logs"]
    for section in ("receivers", "processors", "exporters"):
        shared = {name for pipeline in other for name in pipeline.get(section, [])}
        for name in target[section]:
            candidate = desired[section][name]
            if section == "receivers":
                # Keep cursor paths, ingestion bounds and live host adaptations.
                require(name in live[section], "Missing live receiver: " + name)
                # Only migrate the known overbroad self-log exclusion. Preserve
                # all cursor, include, parsing and host-specific receiver settings.
                if name == "filelog" and name not in shared:
                    narrow_selflog_exclude(candidate, result[section][name])
                continue
            if name in shared:
                require(candidate == live[section][name], "Shared component differs: " + name)
                continue
            if section == "exporters" and name in live[section]:
                # Existing live endpoint/TLS is authoritative; enable backpressure only.
                candidate = copy.deepcopy(live[section][name])
                candidate.setdefault("sending_queue", {})["block_on_overflow"] = True
            result.setdefault(section, {})[name] = copy.deepcopy(candidate)
    result["service"]["pipelines"]["logs"] = copy.deepcopy(target)
    for name, pipeline in ((k, v) for k, v in live["service"]["pipelines"].items() if k != "logs"):
        require(
            result["service"]["pipelines"][name] == pipeline,
            "Live pipeline was mutated: " + name,
        )
        for section in ("receivers", "processors", "exporters"):
            for component in pipeline.get(section, []):
                require(
                    result[section][component] == live[section][component],
                    "Live component was mutated: " + component,
                )
    require(result.get("extensions") == live.get("extensions"), "Live extensions were mutated")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("live")
    p.add_argument("desired")
    p.add_argument("output")
    args = p.parse_args()
    result = merge(
        yaml.safe_load(pathlib.Path(args.live).read_text()),
        yaml.safe_load(pathlib.Path(args.desired).read_text()),
    )
    pathlib.Path(args.output).write_text(yaml.safe_dump(result, sort_keys=False))
    pathlib.Path(args.output).chmod(0o600)
