#!/usr/bin/env python3
"""Isolated pinned-Collector privacy/severity and persistent full-queue recovery probe.

Only synthetic data; prints counts/IDs, never Collector logs or payloads. Requires
Docker and PyYAML.
"""

import http.client
import json
import pathlib
import subprocess
import tempfile
import time
import urllib.request
import uuid
from concurrent import futures
from typing import cast

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGE = json.loads((ROOT / "deploy/monitoring/otel-images.lock.json").read_text())["images"][
    "collector"
]["image"]
TAG = "log-test-" + uuid.uuid4().hex[:8]
NAMES: list[str] = []
HTTP_OK = 200
RECORDS_PER_SOURCE = 9
SAFE_COUNT = 2
RECOVERY_MESSAGES = 12
COLLECTOR_STARTUP_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 2


def docker(*args: str, check: bool = True) -> "subprocess.CompletedProcess[bytes]":
    """Run one docker CLI step and return its captured completed process."""
    return subprocess.run(["docker", *args], check=check, capture_output=True)


def launch(
    name: str,
    config: dict[str, object],
    network: str | None = None,
    *,
    publish: bool = False,
) -> "str | None":
    """Create and start one pinned Collector, returning its published OTLP url."""
    NAMES.append(name)
    args = ["create", "--user", "0", "--name", name]
    if network:
        args += ["--network", network]
    if publish:
        args += ["-p", "127.0.0.1::4318"]
    docker(*args, IMAGE, "--config=/tmp/config.json")
    with tempfile.NamedTemporaryFile(mode="w") as f:
        json.dump(config, f)
        f.flush()
        docker("cp", f.name, name + ":/tmp/config.json")
    docker("start", name)
    time.sleep(COLLECTOR_STARTUP_SECONDS)
    if docker("inspect", "-f", "{{.State.Running}}", name).stdout.strip() != b"true":
        msg = "Collector failed startup (logs deliberately withheld)"
        raise RuntimeError(msg)
    if publish:
        port = docker("port", name, "4318/tcp").stdout.decode().strip().split(":")[-1]
        return "http://127.0.0.1:" + port + "/v1/logs"
    return None


def config(processors: dict[str, object], exporter: dict[str, object]) -> "dict[str, object]":
    """Render one isolated Collector config from the reviewed pipeline parts."""
    return {
        "receivers": {"otlp": {"protocols": {"http": {"endpoint": "0.0.0.0:4318"}}}},
        "processors": processors,
        "exporters": exporter,
        "service": {
            "pipelines": {
                "logs": {
                    "receivers": ["otlp"],
                    "processors": list(processors),
                    "exporters": list(exporter),
                }
            }
        },
    }


def value(v: object) -> "dict[str, object]":
    """Encode one synthetic value in the OTLP any-value shape."""
    if isinstance(v, dict):
        return {"kvlistValue": {"values": [{"key": k, "value": value(x)} for k, x in v.items()]}}
    if isinstance(v, list):
        return {"arrayValue": {"values": [value(x) for x in v]}}
    return {"stringValue": str(v)}


def send(url: str, ident: str, body: object) -> None:
    """Send one synthetic log record and require an OK ingest response."""
    payload = {
        "resourceLogs": [
            {
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "body": value(body),
                                "attributes": [
                                    {"key": "test.id", "value": value(ident)},
                                    {
                                        "key": "nested",
                                        "value": value(
                                            {
                                                "headers": {"x-custom": "PRIVATE_SENTINEL"},
                                                "prompt": "PRIVATE_SENTINEL",
                                                "status": "safe-attribute",
                                            }
                                        ),
                                    },
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    req = urllib.request.Request(
        url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != HTTP_OK:
            msg = "Collector rejected the synthetic log request"
            raise RuntimeError(msg)


def output(name: str) -> "list[dict[str, object]]":
    """Copy the container's recorded output and decode every log record."""
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "out"
        docker("cp", name + ":/tmp/output.json", str(path))
        return [
            r
            for line in path.read_text().splitlines()
            for resource in json.loads(line)["resourceLogs"]
            for scope in resource["scopeLogs"]
            for r in scope["logRecords"]
        ]


def ids(records: "list[dict[str, object]]") -> "set[str]":
    """Collect the synthetic test.id attribute values from decoded records."""
    return {
        cast("str", cast("dict[str, object]", a["value"])["stringValue"])
        for r in records
        for a in cast("list[dict[str, object]]", r.get("attributes", []))
        if a["key"] == "test.id"
    }


def main() -> None:
    """Run the privacy/severity and queue-recovery probes against pinned images."""
    agent = yaml.safe_load((ROOT / "deploy/monitoring/otel/agent.yaml").read_text())
    cluster = yaml.safe_load(
        (ROOT / "deploy/monitoring/otel/cluster-logs-candidate.yaml").read_text()
    )
    active = yaml.safe_load((ROOT / "deploy/monitoring/otel/cluster.yaml").read_text())
    if (
        active["processors"]["transform/log-privacy"]
        != cluster["processors"]["transform/log-privacy"]
    ):
        msg = "promoted privacy differs from tested candidate"
        raise RuntimeError(msg)
    if active["service"]["pipelines"]["logs"] != cluster["service"]["pipelines"]["logs"]:
        msg = "promoted logs pipeline differs from tested candidate"
        raise RuntimeError(msg)
    if "batch/logs" in cluster["service"]["pipelines"]["logs"]["processors"]:
        msg = "tested candidate must not add a logs batch processor"
        raise RuntimeError(msg)
    if not cluster["exporters"]["otlp_http/loki"]["sending_queue"]["block_on_overflow"]:
        msg = "tested candidate must block on queue overflow"
        raise RuntimeError(msg)
    _verify_privacy_and_severity(agent, cluster)
    sink = TAG + "-sink"
    sender = TAG + "-sender"
    _verify_persistent_recovery(cluster, sink, sender)
    for name in NAMES:
        docker("rm", "-f", name, check=False)
    docker("network", "rm", TAG + "-net", check=False)


def _verify_privacy_and_severity(agent: object, cluster: object) -> None:
    """Probe per-source privacy of injected sentinels and agent severity mapping."""
    for source, source_config in [("agent", agent), ("cluster", cluster)]:
        proc = cast("dict[str, object]", cast("dict[str, object]", source_config)["processors"])
        processors: dict[str, object] = {}
        if source == "agent":
            processors["transform/log-identity"] = proc["transform/log-identity"]
        processors["transform/log-privacy"] = proc["transform/log-privacy"]
        name = TAG + "-" + source
        url = cast(
            "str",
            launch(
                name,
                config(processors, {"file": {"path": "/tmp/output.json"}}),
                publish=True,
            ),
        )
        for level in ["INFO", "WARN", "ERROR"]:
            send(url, level, level + " synthetic healthy operation")
        sensitive = {
            "event": "safe-event",
            "nested": {
                "prompt": "PRIVATE_SENTINEL",
                "headers": {"x-custom": "PRIVATE_SENTINEL"},
                "request": {"body": "PRIVATE_SENTINEL"},
                "response.body": "PRIVATE_SENTINEL",
                "ok": "safe-value",
            },
            "items": [{"completion": "PRIVATE_SENTINEL", "status": "safe-status"}],
        }
        send(url, "invalid-json", '{"prompt":"PRIVATE_SENTINEL')
        send(url, "map", sensitive)
        send(url, "json", json.dumps(sensitive))
        send(url, "json-array", json.dumps([sensitive]))
        send(url, "array", [sensitive])
        send(url, "freeform", "INFO request.body: PRIVATE_SENTINEL\nPRIVATE_SENTINEL")
        time.sleep(1)
        docker("stop", "-t", "3", name)
        records = output(name)
        if len(records) != RECORDS_PER_SOURCE:
            msg = source + ": expected " + str(RECORDS_PER_SOURCE) + " records"
            raise RuntimeError(msg)
        encoded = json.dumps(records)
        if "PRIVATE_SENTINEL" in encoded:
            msg = source + ": privacy sentinel leaked through the pipeline"
            raise RuntimeError(msg)
        if encoded.count("safe-event") != SAFE_COUNT:
            msg = source + ": safe-event count changed"
            raise RuntimeError(msg)
        if encoded.count("safe-value") != SAFE_COUNT:
            msg = source + ": safe-value count changed"
            raise RuntimeError(msg)
        if source == "agent":
            actual = {
                cast(
                    "str",
                    next(
                        cast("dict[str, object]", a["value"])["stringValue"]
                        for a in cast("list[dict[str, object]]", r["attributes"])
                        if a["key"] == "test.id"
                    ),
                ): r["severityText"]
                for r in records
            }
            if any(actual[level] != level.lower() for level in ["INFO", "WARN", "ERROR"]):
                msg = "agent: severity mapping drifted"
                raise RuntimeError(msg)
        print(source + ": privacy=9/9; severity=" + ("3/3" if source == "agent" else "agent-owned"))


def _verify_persistent_recovery(cluster: object, sink: str, sender: str) -> None:
    """Verify full-queue backpressure and persistent storage across a restart."""
    network = TAG + "-net"
    docker("network", "create", "--internal", network)
    try:
        export_cfg = cast(
            "dict[str, dict[str, dict[str, object]]]",
            cast("dict[str, object]", cluster)["exporters"],
        )
        q = dict(export_cfg["otlp_http/loki"]["sending_queue"])
        q.update(sizer="requests", queue_size=SAFE_COUNT, num_consumers=1)
        exporter = {
            "otlp_http": {
                "endpoint": "http://" + sink + ":4318",
                "sending_queue": q,
                "retry_on_failure": {
                    "enabled": True,
                    "initial_interval": "1s",
                    "max_interval": "1s",
                    "max_elapsed_time": "0s",
                },
                "timeout": "1s",
            }
        }
        privacy = cast(
            "dict[str, dict[str, object]]",
            cast("dict[str, object]", cluster)["processors"],
        )["transform/log-privacy"]
        cfg = config({"transform/log-privacy": privacy}, cast("dict[str, object]", exporter))
        cfg["extensions"] = {
            "file_storage": {
                "directory": "/tmp/queue",
                "create_directory": True,
                "fsync": True,
            }
        }
        cast("dict[str, dict[str, object]]", cfg)["service"]["extensions"] = ["file_storage"]
        url = cast("str", launch(sender, cfg, network, publish=True))

        def retry(i: int) -> int:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    send(url, str(i), "INFO recovery-id-" + str(i))
                except (OSError, ValueError, http.client.HTTPException):
                    time.sleep(0.2)
                else:
                    return i
            msg = "request retry deadline"
            raise AssertionError(msg)

        with futures.ThreadPoolExecutor(max_workers=RECOVERY_MESSAGES) as pool:
            pending = [pool.submit(retry, i) for i in range(RECOVERY_MESSAGES)]
            time.sleep(4)
            acknowledged = sum(f.done() for f in pending)
            if not 0 < acknowledged < RECOVERY_MESSAGES:
                msg = "queue did not exert backpressure"
                raise RuntimeError(msg)
            print(
                "outage: sent=12 acknowledged="
                + str(acknowledged)
                + " blocked="
                + str(RECOVERY_MESSAGES - acknowledged)
            )
            docker("kill", sender)
            docker("start", sender)
            launch(sink, config({}, {"file": {"path": "/tmp/output.json"}}), network)
            if len([f.result() for f in pending]) != RECOVERY_MESSAGES:
                msg = "not every blocked request completed after queue drain"
                raise RuntimeError(msg)
        time.sleep(5)
        docker("stop", "-t", "3", sender)
        docker("stop", "-t", "3", sink)
        records = output(sink)
        recovered = ids(records)
        if recovered != {str(i) for i in range(RECOVERY_MESSAGES)}:
            msg = "missing recovery IDs"
            raise RuntimeError(msg)
        print(
            "restart recovery: unique=12/12 total="
            + str(len(records))
            + " IDs="
            + ",".join(sorted(recovered, key=int))
        )
    finally:
        for name in NAMES:
            docker("rm", "-f", name, check=False)
        docker("network", "rm", network, check=False)


if __name__ == "__main__":
    try:
        main()
    finally:
        for name in NAMES:
            docker("rm", "-f", name, check=False)
