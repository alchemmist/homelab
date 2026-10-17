import argparse
import csv
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time


FIELDS = (
    ("temperature.gpu", "temperature_celsius", 1),
    ("utilization.gpu", "utilization_ratio", 0.01),
    ("utilization.memory", "memory_utilization_ratio", 0.01),
    ("memory.used", "memory_used_bytes", 1048576),
    ("memory.total", "memory_total_bytes", 1048576),
    ("power.draw", "power_watts", 1),
    ("power.limit", "power_limit_watts", 1),
    ("fan.speed", "fan_speed_ratio", 0.01),
    ("clocks.current.graphics", "clock_graphics_hertz", 1000000),
    ("clocks.current.memory", "clock_memory_hertz", 1000000),
    ("pstate", "performance_state", 1),
)
REASONS = (
    "sw_thermal_slowdown",
    "hw_thermal_slowdown",
    "sw_power_cap",
    "hw_power_brake_slowdown",
)
QUERY = ["uuid", "name", "index"] + [field[0] for field in FIELDS] + [
    "clocks_event_reasons." + reason for reason in REASONS
]


def sample(name, labels, value):
    suffix = "{" + ",".join(key + "=" + json.dumps(value) for key, value in labels.items()) + "}" if labels else ""
    return name + suffix + " " + format(value, ".15g") + "\n"


def parse_metrics(output):
    metrics = []
    count = 0
    for row in csv.reader(io.StringIO(output), skipinitialspace=True):
        if not row:
            continue
        if len(row) != len(QUERY):
            raise ValueError("Unexpected NVIDIA query column count")
        row = [value.strip() for value in row]
        if not row[0].startswith("GPU-"):
            raise ValueError("Invalid NVIDIA GPU identity")
        labels = dict(zip(("uuid", "name", "index"), row[:3]))
        count += 1
        for (_, metric, factor), raw in zip(FIELDS, row[3:]):
            if metric == "performance_state" and raw.startswith("P"):
                raw = raw[1:]
            try:
                value = float(raw) * factor
            except ValueError:
                continue
            if math.isfinite(value):
                metrics.append(sample("socrat_gpu_" + metric, labels, value))
        for reason, raw in zip(REASONS, row[3 + len(FIELDS):]):
            if raw in ("Active", "Not Active"):
                metrics.append(sample("socrat_gpu_throttle_active", {**labels, "reason": reason}, float(raw == "Active")))
    if not count:
        raise ValueError("No NVIDIA GPU returned")
    return "".join(metrics)


def atomic_write(destination, content):
    destination = Path(destination)
    descriptor, temporary = tempfile.mkstemp(prefix=".nvidia-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect(binary, destination):
    success = 0
    metrics = ""
    try:
        result = subprocess.run(
            [binary, "--query-gpu=" + ",".join(QUERY), "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=20,
            env={**os.environ, "LC_ALL": "C"},
        )
        metrics = parse_metrics(result.stdout)
        success = 1
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    metrics += sample("socrat_gpu_collection_success", {}, success)
    metrics += sample("socrat_gpu_collection_timestamp_seconds", {}, time.time())
    atomic_write(destination, metrics)
    return success


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="/usr/bin/nvidia-smi")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(0 if collect(args.binary, args.output) else 1)


if __name__ == "__main__":
    main()
