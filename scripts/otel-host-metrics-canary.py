"""Bounded native four-host metrics canary. Never targets production ingestion."""

import argparse
import copy
import hashlib
import ipaddress
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Callable
import socket
import ssl
import subprocess
import time
import urllib.parse
import urllib.request


def command(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=30).stdout


def verify(path, expected):
    stat = path.lstat()
    if path.is_symlink() or not path.is_file() or stat.st_uid != 0 or stat.st_mode & 0o022:
        message = "Native canary executable must be root owned and not writable by others"
        raise ValueError(message)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
            message = "Native executable differs from pinned controller digest"
            raise ValueError(message)


def configs(root, request):
    agent = json.loads((root / "agent-source.json").read_text())
    agent["receivers"] = {"prometheus": agent["receivers"]["prometheus"]}
    agent["extensions"] = {"file_storage": agent["extensions"]["file_storage"]}
    agent["processors"] = {
        key: agent["processors"][key] for key in ("memory_limiter", "resource", "batch/metrics")
    }
    agent["service"] = {
        "extensions": ["file_storage"],
        "telemetry": {
            "metrics": {
                "readers": [
                    {"pull": {"exporter": {"prometheus": {"host": "127.0.0.1", "port": 18888}}}}
                ]
            }
        },
        "pipelines": {"metrics": agent["service"]["pipelines"]["metrics"]},
    }
    gateway = json.loads((root / "cluster-source.json").read_text())
    grpc = copy.deepcopy(gateway["receivers"]["otlp"]["protocols"]["grpc"])
    grpc["endpoint"] = request["backendIP"] + ":43170"
    gateway["receivers"] = {"otlp": {"protocols": {"grpc": grpc}}}
    gateway["extensions"] = {"file_storage": gateway["extensions"]["file_storage"]}
    gateway["processors"] = {
        key: gateway["processors"][key] for key in ("memory_limiter", "batch/metrics")
    }
    gateway["exporters"] = {"otlp_http/metrics": gateway["exporters"]["otlp_http/metrics"]}
    gateway["service"] = {
        "extensions": ["file_storage"],
        "telemetry": {
            "metrics": {
                "readers": [
                    {"pull": {"exporter": {"prometheus": {"host": "127.0.0.1", "port": 18889}}}}
                ]
            }
        },
        "pipelines": {
            "metrics": {
                "receivers": ["otlp"],
                "processors": ["memory_limiter", "batch/metrics"],
                "exporters": ["otlp_http/metrics"],
            }
        },
    }
    return agent, gateway


def context(root):
    result = ssl.create_default_context(cafile=str(root / "tls/ca.crt"))
    result.load_cert_chain(str(root / "tls/client.crt"), str(root / "tls/client.key"))
    return result


def query(root, expression, range_parameters=None):
    endpoint = "query_range" if range_parameters else "query"
    parameters = {"query": expression, **(range_parameters or {})}
    url = "https://127.0.0.1:19099/api/v1/" + endpoint + "?" + urllib.parse.urlencode(parameters)
    with urllib.request.urlopen(url, context=context(root), timeout=5) as response:
        payload = json.load(response)
    if payload.get("status") != "success":
        message = "Native shadow Prometheus query failed"
        raise ValueError(message)
    return payload["data"]["result"]


def identity(labels):
    return hashlib.sha256(
        json.dumps(labels, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def unit(root, label):
    return root.name + "-" + label + ".service"


def stop(root, labels):
    for label in labels:
        if (
            command(["systemctl", "show", unit(root, label), "-p", "MainPID", "--value"]).strip()
            != "0"
        ):
            command(["systemctl", "stop", unit(root, label)])


def start(root, label, executable, arguments, memory, environment=None, extra=None):
    properties = [
        f"MemoryMax={memory}",
        "MemorySwapMax=0",
        "RuntimeMaxSec=900",
        "CPUQuota=100%",
        "OOMPolicy=kill",
    ] + (extra or [])
    argv = ["systemd-run", "--no-block", "--collect", "--unit=" + unit(root, label)]
    argv += ["--property=" + item for item in properties]
    argv += ["--setenv=" + key + "=" + value for key, value in (environment or {}).items()]
    command(argv + [str(executable)] + arguments)


def wait_port(ip, port):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((ip, port), timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    message = "Owned native listener did not become ready"
    raise RuntimeError(message)


def environment(root, request):
    return {
        "GOMAXPROCS": "2",
        "GOMEMLIMIT": "192MiB",
        "OTEL_TLS_DIR": str(root / "tls"),
        "OTEL_STORAGE_DIR": str(root / "queues"),
        "OTEL_SCRAPE_CONFIG": str(root / "scrape.json"),
        "OTEL_NODE_NAME": socket.gethostname(),
        "OTEL_CLUSTER_ENDPOINT": request["backendIP"] + ":43170",
        "OTEL_CLUSTER_TLS_NAME": "localhost",
        "OTEL_METRICS_ENDPOINT": "https://127.0.0.1:19099/api/v1/otlp",
    }


def telemetry(root):
    with urllib.request.urlopen("http://127.0.0.1:18888/metrics", timeout=5) as response:
        lines = response.read(4 * 1024 * 1024 + 1).decode().splitlines()
    selected = {}
    for line in lines:
        if line.startswith("otelcol_exporter_") and not line.startswith("#"):
            metric, value = line.rsplit(" ", 1)
            name = metric.split("{", 1)[0]
            if any(
                part in name
                for part in (
                    "queue_size",
                    "queue_capacity",
                    "sent_metric_points",
                    "enqueue_failed_metric_points",
                )
            ):
                selected[name] = selected.get(name, 0) + float(value)
    if not selected:
        message = "Native exporter telemetry is absent"
        raise ValueError(message)
    return selected


def classify_shutdown_replay(text):
    # Pinned upstream 0.164 logs every Send error as "Dropping data", but
    # persistent_queue.onDone retains IsShutdownErr items for startup replay.
    # Never exempt generic send failures or merely trust the log wording.
    shutdown, unexpected, replayed = 0, 0, 0
    storage_errors = 0
    for line in text.splitlines():
        if any(
            marker in line
            for marker in (
                "Failed getting metadata",
                "Failed to dispatch item",
                "Errors occurred while moving items",
                "Error deleting item from queue",
            )
        ):
            storage_errors += 1
        if (
            "Exporting failed. Dropping data." in line
            or "Moved items for dispatching back to queue" in line
        ):
            try:
                fields = json.loads(line[line.index("{") :])
            except (ValueError, json.JSONDecodeError):
                unexpected += 1
                continue
            if "Exporting failed. Dropping data." in line:
                if (
                    fields.get("error", "").startswith("interrupted due to shutdown:")
                    and fields.get("resource", {}).get("service.version") == "0.164.0"
                    and fields.get("otelcol.component.id") == "otlp"
                    and fields.get("otelcol.signal") == "metrics"
                ):
                    shutdown += 1
                else:
                    unexpected += 1
            else:
                count = fields.get("numberOfItems")
                if not isinstance(count, int) or count < 0:
                    unexpected += 1
                else:
                    replayed += count
    return {
        "shutdownSendErrorEvents": shutdown,
        "restoredInFlightRequests": replayed,
        "unexpectedDropEvents": unexpected,
        "persistentStorageErrors": storage_errors,
        "shutdownReplayAccounted": shutdown == replayed and unexpected == 0 and storage_errors == 0,
    }


def validate_contract(root, request, now=None):
    collected = datetime.fromisoformat(request["scrapeContractCollectedAt"])
    age = ((now or datetime.now(timezone.utc)) - collected).total_seconds()
    if not 0 <= age <= 900:
        message = "Native host scrape contract is stale or future-dated"
        raise ValueError(message)
    node = socket.gethostname()
    document = json.loads((root / "scrape.json").read_text())
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(encoded).hexdigest() != request["hostScrapeSHA256"][node]:
        message = "Frozen native host source config changed after compilation"
        raise ValueError(message)


def require(expected: object, message: str) -> None:
    """Enforce an invariant, failing with the given message."""
    if not expected:
        raise ValueError(message)


def prepare_phase(root, request, result):
    """Validate the contract and write validated agent/gateway configurations."""
    validate_contract(root, request)
    available = (
        int(
            dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())[
                "MemAvailable"
            ].split()[0]
        )
        * 1024
    )
    minimum = request["minimumAvailableMemoryBytes"][socket.gethostname()]
    require(
        available >= minimum,
        "Native canary would breach preserved memory reserve",
    )
    verify(root / "otelcol-contrib", request["collectorSHA256"])
    verify(Path(request["exporterPath"]), request["exporterSHA256"])
    agent, gateway = configs(root, request)
    for name, value in [("agent.json", agent), ("gateway.json", gateway)]:
        (root / name).write_text(json.dumps(value))
        completed = subprocess.run(
            [str(root / "otelcol-contrib"), "validate", "--config=" + str(root / name)],
            env={**os.environ, **environment(root, request)},
            capture_output=True,
            timeout=60,
        )
        require(
            not completed.returncode,
            "Pinned Collector rejected native canary configuration; inspect private config",
        )
    result["availableMemoryBytes"] = available


def backend_start_phase(root, request, _result):
    """Start the private Prometheus OTLP backend and the gateway collector."""
    verify(root / "prometheus", request["prometheusSHA256"])
    for port in (19099, 43170, 18889):
        with socket.socket() as handle:
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            handle.bind((request["backendIP"] if port == 43170 else "127.0.0.1", port))
    tls = {
        "cert_file": str(root / "tls/server.crt"),
        "key_file": str(root / "tls/server.key"),
        "client_ca_file": str(root / "tls/ca.crt"),
        "client_auth_type": "RequireAndVerifyClientCert",
    }
    (root / "web.json").write_text(json.dumps({"tls_server_config": tls}))
    (root / "prometheus.json").write_text(
        json.dumps(
            {
                "global": {"evaluation_interval": "5s"},
                "scrape_configs": [],
                "storage": {"tsdb": {"out_of_order_time_window": "30m"}},
                "otlp": {
                    "translation_strategy": "NoTranslation",
                    "promote_scope_metadata": False,
                },
            }
        )
    )
    start(
        root,
        "prometheus",
        root / "prometheus",
        [
            "--config.file=" + str(root / "prometheus.json"),
            "--storage.tsdb.path=" + str(root / "tsdb"),
            "--storage.tsdb.retention.time=2h",
            "--web.listen-address=127.0.0.1:19099",
            "--web.config.file=" + str(root / "web.json"),
            "--web.enable-otlp-receiver",
        ],
        512 * 2**20,
        {"GOMEMLIMIT": "384MiB", "GOMAXPROCS": "2"},
    )
    env = {**environment(root, request), "GOMEMLIMIT": "768MiB"}
    start(
        root,
        "gateway",
        root / "otelcol-contrib",
        ["--config=" + str(root / "gateway.json")],
        2**30,
        env,
    )
    wait_port("127.0.0.1", 19099)
    wait_port(request["backendIP"], 43170)


def agents_start_phase(root, request, _result):
    """Start the node exporter and its private agent collector."""
    for port in (19100, 18888):
        with socket.socket() as handle:
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            handle.bind(("127.0.0.1", port))
    start(
        root,
        "exporter",
        Path(request["exporterPath"]),
        [
            "--web.listen-address=127.0.0.1:19100",
            "--path.procfs=/proc",
            "--path.sysfs=/sys",
            "--path.rootfs=/",
            "--path.udev.data=/run/udev/data",
            "--collector.textfile.directory=/host/root/var/lib/node_exporter/textfile_collector",
            "--collector.systemd",
            "--collector.systemd.enable-restarts-metrics",
        ],
        64 * 2**20,
        {"TZ": "UTC", "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/run/dbus/system_bus_socket"},
        [
            "User=65534",
            "Group=65534",
            "NoNewPrivileges=yes",
            "BindReadOnlyPaths=/var/lib/node_exporter/textfile_collector:/host/root/var/lib/node_exporter/textfile_collector",
        ],
    )
    wait_port("127.0.0.1", 19100)
    start(
        root,
        "agent",
        root / "otelcol-contrib",
        ["--config=" + str(root / "agent.json")],
        256 * 2**20,
        environment(root, request),
    )
    wait_port("127.0.0.1", 18888)


def probe_phase(root, request, result):
    """Poll until all four agents report equivalent fresh targets."""
    expected = {
        identity({**labels, "__name__": "up"}) for labels in request["expectedLabels"].values()
    }
    consecutive = 0
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        actual = query(root, "up")
        ages = query(root, "time() - timestamp(up)")
        if (
            {identity(point["metric"]) for point in actual} == expected
            and all(point["value"][1] == "1" for point in actual)
            and len(ages) == 4
            and all(0 <= float(point["value"][1]) < 15 for point in ages)
        ):
            consecutive += 1
            if consecutive >= 3:
                break
        else:
            consecutive = 0
        time.sleep(5)
    require(
        consecutive >= 3,
        "Four native agents did not preserve all target labels and fresh up values",
    )
    result.update(
        {
            "healthyTargetCount": 4,
            "allTargetLabelsEquivalent": True,
            "maximumUpAgeSeconds": max(float(point["value"][1]) for point in ages),
        }
    )


def outage_proof_phase(root, request, result):
    """Prove pre-restart outage samples survived the durable queues."""
    stops = json.loads((root / "gateway-stop-result.json").read_text())["timeUnixSeconds"]
    restarts = json.loads((root / "restarts.json").read_text())
    points = query(root, "up[10m]")
    by_identity = {identity(point["metric"]): point for point in points}
    counts = {}
    for node, labels in request["expectedLabels"].items():
        series = by_identity[identity({**labels, "__name__": "up"})]
        restart = restarts[node]["restartStartedAt"]
        count = sum(
            stops < float(timestamp) < restart and value == "1"
            for timestamp, value in series["values"]
        )
        require(
            count >= 1,
            "No pre-restart outage samples survived durable queue on one host",
        )
        counts[node] = count
    result["preRestartOutageSamplesRecovered"] = counts
    result["allFourPersistentQueuesSurvivedAgentRestart"] = True


def cleanup_phase(root, _request, result):
    """Stop every owned service and remove the temporary credentials."""
    labels = ["agent", "exporter"] + (
        ["gateway", "prometheus"] if socket.gethostname() == "socrat-1" else []
    )
    # Cleanup credentials only after an explicit all-agent barrier and backend-last stop.
    states = [
        command(["systemctl", "show", unit(root, name), "-p", "MainPID", "--value"]).strip()
        for name in labels
    ]
    require(
        all(state == "0" for state in states),
        "Owned native canary process did not stop",
    )
    for path in (root / "tls").iterdir():
        require(
            all([not path.is_symlink(), path.is_file()]),
            "Unexpected canary credential file",
        )
        path.unlink()
    result["allOwnedProcessesStopped"] = True
    result["temporaryTLSRemoved"] = True


def await_queue_phase(root, _request, result):
    """Await the durable exporter queue reaching its expected bounded state."""
    phase = result["phase"]
    started = time.monotonic()
    while time.monotonic() - started < 60:
        current = telemetry(root)
        size = sum(value for name, value in current.items() if "queue_size" in name)
        if phase == "await-queued":
            converged = size > 0 and time.monotonic() - started >= 12
        else:
            converged = size == 0
        if converged:
            result["exporterTelemetry"] = current
            break
        time.sleep(1)
    else:
        message = "Persistent exporter queue did not reach expected bounded state"
        raise ValueError(message)


def drain_start_phase(root, request, _result):
    """Start the agent collector with its OTLP drain receiver configuration."""
    agent = json.loads((root / "agent.json").read_text())
    agent["receivers"] = {"otlp": {"protocols": {"grpc": {"endpoint": "127.0.0.1:18887"}}}}
    agent["service"]["pipelines"]["metrics"]["receivers"] = ["otlp"]
    (root / "agent-drain.json").write_text(json.dumps(agent))
    start(
        root,
        "agent",
        root / "otelcol-contrib",
        ["--config=" + str(root / "agent-drain.json")],
        256 * 2**20,
        environment(root, request),
    )
    wait_port("127.0.0.1", 18888)


def selected_cleanup_phase(root, _request, result):
    """Stop the phase's selected services and require them to be gone."""
    phase = result["phase"]
    labels = ["agent", "exporter"] if phase == "agents-cleanup" else ["gateway", "prometheus"]
    stop(root, labels)
    require(
        all(
            command(["systemctl", "show", unit(root, name), "-p", "MainPID", "--value"]).strip()
            == "0"
            for name in labels
        ),
        "Owned native service did not stop",
    )
    result["allSelectedProcessesStopped"] = True


def journal_phase(root, _request, result):
    """Record rejection counts and queue evidence from the agent journal."""
    text = command(["journalctl", "--no-pager", "-o", "cat", "-u", unit(root, "agent")])
    markers = {
        "droppedExportBatches": "Exporting failed. Dropping data.",
        "memoryRefusals": "Refusing data.",
        "failedScrapeCommits": "Scrape commit failed",
    }
    result["rejections"] = {key: text.count(marker) for key, marker in markers.items()}
    files = [p for p in (root / "queues").rglob("*") if p.is_file() and not p.is_symlink()]
    result["queueLogicalBytesAfterDrain"] = sum(p.stat().st_size for p in files)
    result["queueAllocatedBytesAfterDrain"] = sum(p.stat().st_blocks * 512 for p in files)
    result["queueSaturationOrFullHighWaterVerified"] = False
    result["strictUnclassifiedLogGatePassed"] = not any(result["rejections"].values())
    result["shutdownReplay"] = classify_shutdown_replay(text)


def telemetry_phase(root, _request, result):
    """Record current exporter telemetry and the agent cgroup memory peak."""
    result["exporterTelemetry"] = telemetry(root)
    result["agentCgroup"] = command(
        ["systemctl", "show", unit(root, "agent"), "-p", "ControlGroup", "--value"]
    ).strip()
    peak = Path("/sys/fs/cgroup") / result["agentCgroup"].lstrip("/") / "memory.peak"
    result["agentMemoryPeakBytes"] = int(peak.read_text()) if peak.is_file() else None


def gateway_start_phase(root, request, _result):
    """Start the gateway collector against the private OTLP backend."""
    start(
        root,
        "gateway",
        root / "otelcol-contrib",
        ["--config=" + str(root / "gateway.json")],
        2**30,
        {**environment(root, request), "GOMEMLIMIT": "768MiB"},
    )
    wait_port(request["backendIP"], 43170)


def agent_restart_phase(root, _request, result):
    """Restart the agent collector and record the restart instant."""
    result["restartStartedAt"] = time.time()
    result["telemetryBeforeRestart"] = telemetry(root)
    command(["systemctl", "restart", unit(root, "agent")])
    wait_port("127.0.0.1", 18888)


def gateway_stop_phase(root, _request, _result):
    """Stop the gateway collector."""
    stop(root, ["gateway"])


DISPATCH: "dict[str, Callable[[object, object, object], None]]" = {
    "prepare": prepare_phase,
    "backend-start": backend_start_phase,
    "agents-start": agents_start_phase,
    "probe": probe_phase,
    "await-queued": await_queue_phase,
    "await-drained": await_queue_phase,
    "outage-proof": outage_proof_phase,
    "telemetry": telemetry_phase,
    "gateway-stop": gateway_stop_phase,
    "gateway-start": gateway_start_phase,
    "agent-restart": agent_restart_phase,
    "drain-start": drain_start_phase,
    "agents-cleanup": selected_cleanup_phase,
    "backend-cleanup": selected_cleanup_phase,
    "journal-evidence": journal_phase,
    "cleanup": cleanup_phase,
}


def run(root, phase):
    require(
        all(
            [
                os.geteuid() == 0,
                not root.is_symlink(),
                root.parent == Path("/var/tmp"),
                root.name.startswith("otel-host-metrics-canary-"),
            ]
        ),
        "Explicit private native canary workspace required",
    )
    stat = root.lstat()
    require(
        all([stat.st_uid == 0, not stat.st_mode & 0o077]),
        "Canary workspace must be root-only",
    )
    request = json.loads((root / "request.json").read_text())
    require(
        ipaddress.ip_address(request["backendIP"]) in ipaddress.ip_network("10.250.0.0/24"),
        "Backend must bind only the existing private WireGuard range",
    )
    result = {"phase": phase, "hostname": socket.gethostname(), "productionIngestionChanged": False}
    dispatch = DISPATCH.get(phase)
    require(dispatch is not None, "Unknown explicit canary phase")
    handler = cast("Callable[[object, object, object], None]", dispatch)
    handler(root, request, result)
    result["timeUnixSeconds"] = time.time()
    (root / (phase + "-result.json")).write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--phase", required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.directory, args.phase)))
