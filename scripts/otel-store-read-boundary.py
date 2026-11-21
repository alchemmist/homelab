"""Repair only the raw Store's query gap; never changes samples or retention.

Preserves the full original Deployment privately, removes only the known -12h
read clamp and verifies native raw queries with/without query deduplication.
"""

import argparse
import importlib.util
import json
import os
import time
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "store_boundary_bootstrap", ROOT / "scripts/otel-production-bootstrap.py"
)
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)
NS = "cattle-monitoring-system"
_SAMPLE_PAIR_LENGTH = 2


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        message = "Native query responses must be JSON objects"
        raise TypeError(message)
    return dict(value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        message = "Native query results must be JSON arrays"
        raise TypeError(message)
    return list(value)


def _sample_value(record: object) -> float:
    series = _mapping(record)
    sample = _list(series["value"])
    if len(sample) != _SAMPLE_PAIR_LENGTH:
        message = "Native query samples must pair a timestamp with a value"
        raise TypeError(message)
    value = sample[1]
    if not isinstance(value, (int, float, str)):
        message = "Native query sample value must be numeric"
        raise TypeError(message)
    return float(value)


def unclamped(arguments) -> object:
    limits = [value for value in arguments if value.startswith("--max-time")]
    if limits not in [[], ["--max-time=-12h"]]:
        raise ValueError("Unexpected raw Store limit; manual review required")
    return [value for value in arguments if value != "--max-time=-12h"]


def query(stamp, dedup) -> list[object]:
    params = urllib.parse.urlencode(
        {
            "query": "count(up)",
            "time": stamp,
            "max_source_resolution": "0s",
            "partial_response": "false",
            "dedup": str(dedup).lower(),
        }
    )
    result = BOOTSTRAP.kube(
        "get",
        "--raw",
        "/api/v1/namespaces/"
        + NS
        + "/services/http:thanos-query:9090/proxy/api/v1/query?"
        + params,
    )
    if result.get("status") != "success" or result.get("warnings"):
        raise ValueError("Native query failed or was partial")
    return list(result["data"]["result"])


def run(output) -> None:
    os.umask(0o077)
    output.mkdir(mode=0o700)
    status = {
        "success": False,
        "samplesModified": False,
        "retentionChanged": False,
        "prometheusOrCollectorRestarted": False,
        "datasourceUidChanged": False,
    }
    try:
        before = BOOTSTRAP.kube("-n", NS, "get", "deployment", "thanos-store", "-o", "json")
        (output / "deployment-before-private.json").write_text(json.dumps(before, indent=2) + "\n")
        container = next(
            item
            for item in before["spec"]["template"]["spec"]["containers"]
            if item["name"] == "thanos"
        )
        arguments = unclamped(container["args"])
        stamps = ["2026-10-31T19:00:00Z", "2026-10-31T19:50:00Z", "2026-10-31T20:15:00Z"]
        prior = {stamp: query(stamp, True) for stamp in stamps}
        (output / "queries-before.json").write_text(json.dumps(prior, indent=2) + "\n")
        if arguments != container["args"]:
            BOOTSTRAP.kube(
                "-n",
                NS,
                "patch",
                "deployment",
                "thanos-store",
                "--type=strategic",
                "-p",
                json.dumps(
                    {
                        "spec": {
                            "template": {
                                "spec": {"containers": [{"name": "thanos", "args": arguments}]}
                            }
                        }
                    }
                ),
                "-o",
                "json",
            )
        deadline = time.monotonic() + 240
        while True:
            current = BOOTSTRAP.kube("-n", NS, "get", "deployment", "thanos-store", "-o", "json")
            state = current.get("status", {})
            if (
                state.get("observedGeneration", 0) >= current["metadata"]["generation"]
                and state.get("updatedReplicas") == 1
                and state.get("availableReplicas") == 1
                and state.get("replicas") == 1
                and not state.get("unavailableReplicas", 0)
            ):
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Native raw Store rollout deadline exceeded")
            time.sleep(3)
        while True:
            restored = query(stamps[1], True)
            if restored and _sample_value(restored[0]) == 78:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Native raw query did not recover captured historical interval")
            time.sleep(3)
        after = {
            stamp: {"dedupTrue": query(stamp, True), "dedupFalse": query(stamp, False)}
            for stamp in stamps
        }
        for stamp, grouped in after.items():
            for rows in grouped.values():
                if len(rows) != 1 or _sample_value(rows[0]) != 78:
                    raise ValueError("Native historical series count changed or was doubled")
        status.update(
            success=True,
            removedFlag="--max-time=-12h",
            queriesBefore=prior,
            queriesAfter=after,
            completedAt=datetime.now(UTC).isoformat(),
            newContinuousSoakRequired=True,
        )
    except Exception as error:
        status["errorType"] = type(error).__name__
        raise
    finally:
        (output / "result.json").write_text(json.dumps(status, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: status[key]
                for key in [
                    "success",
                    "samplesModified",
                    "retentionChanged",
                    "prometheusOrCollectorRestarted",
                    "newContinuousSoakRequired",
                ]
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
