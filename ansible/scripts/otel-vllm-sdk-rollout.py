"""Proof-gated minimal native vLLM SDK rollout; model/DB/GPU settings untouched.

Requires early-bootstrap, privacy, same-instance renewal and backend receipts.
Preserves long-request drain, requires observed idle running/waiting gauges,
never kills draining pods, never reduces retention or edits application keys.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "bootstrap", ROOT / "scripts/otel-production-bootstrap.py"
)
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)
ENDPOINT = "https://10.250.0.3:44318/v1/traces"


def source_data():
    return {
        "source_privacy.py": (ROOT / "scripts/otel-sdk-source-privacy.py").read_text(),
        "sitecustomize.py": (ROOT / "deploy/monitoring/otel/vllm-sitecustomize.py").read_text(),
    }


def source_configmap_name():
    return (
        "vllm-otel-source-"
        + hashlib.sha256(json.dumps(source_data(), sort_keys=True).encode()).hexdigest()[:16]
    )


def sdk_environment():
    return {
        "PYTHONPATH": "/etc/otel-source",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOMELAB_VLLM_TRACE_ENDPOINT": ENDPOINT,
        "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://10.250.0.3:44318",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": ENDPOINT,
        "OTEL_EXPORTER_OTLP_CERTIFICATE": "/etc/otel-client/ca.crt",
        "OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE": "/etc/otel-client/tls.crt",
        "OTEL_EXPORTER_OTLP_CLIENT_KEY": "/etc/otel-client/tls.key",
        "OTEL_EXPORTER_OTLP_INSECURE": "false",
        "OTEL_EXPORTER_OTLP_HEADERS": "Connection=close",
        "OTEL_SERVICE_NAME": "vllm",
        "OTEL_TRACES_SAMPLER": "always_on",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "NO_CONTENT",
    }


def trace_arguments(original):
    flags = [i for i, arg in enumerate(original) if arg.startswith("--otlp-traces-endpoint")]
    if flags:
        if len(flags) != 1 or original[flags[0] : flags[0] + 2] != [
            "--otlp-traces-endpoint",
            ENDPOINT,
        ]:
            msg = "Unexpected existing tracing arguments; refuse overwrite"
            raise ValueError(msg)
        return list(original)
    return [*list(original), "--otlp-traces-endpoint", ENDPOINT]


def renewal_gate_passed(renewal) -> bool:
    """Return True only when the pinned same-instance leaf renewal receipts passed."""
    return (
        renewal["sameInstanceSameExporterNativeLeafRenewalVerified"]
        and len(renewal["backend"]) == 2
        and all(x["success"] for x in renewal["backend"])
    )


def source_gate_passed(security, bootstrap) -> bool:
    """Return True only when the pinned privacy-guard and early-bootstrap gates passed."""
    return (
        security["guardSourceSHA256"]
        == hashlib.sha256(source_data()["source_privacy.py"].encode()).hexdigest()
        and bootstrap["source"]["success"]
        and bootstrap["source"]["sourceGuardFactoryActive"]
        and bootstrap["backend"]["success"]
        and bootstrap["sourceConfigMapData"] == source_data()
    )


def require_healthy_baseline(deployment, container, security) -> None:
    """Fail unless the live vLLM runtime is the pinned single healthy replica."""
    if container["image"].split("@")[-1] != security["installedRuntime"]["image"].split("@")[-1]:
        msg = "Pinned runtime image differs from tested SDK image"
        raise ValueError(msg)
    if (
        deployment["spec"].get("replicas", 1) != 1
        or deployment.get("status", {}).get("availableReplicas") != 1
    ):
        msg = "Expected one healthy original GPU replica"
        raise ValueError(msg)


def require_no_env_conflicts(container, environment) -> None:
    """Fail if an existing env entry would conflict with the SDK settings."""
    current_env = {e["name"]: e for e in container.get("env", [])}
    for name, value in environment.items():
        if name in current_env and current_env[name] != {"name": name, "value": value}:
            msg = "Conflicting SDK environment; never overwrite unreviewed settings"
            raise ValueError(msg)


def require_no_volume_conflicts(deployment, container, desired) -> None:
    """Fail if an existing volume or mount would conflict with the SDK additions."""
    for desired_entries, current in [
        (desired[0], deployment["spec"]["template"]["spec"].get("volumes", [])),
        (desired[1], container.get("volumeMounts", [])),
    ]:
        for entry in desired_entries:
            if any(v["name"] == entry["name"] and v != entry for v in current):
                msg = "Conflicting existing SDK volume or mount"
                raise ValueError(msg)


def reconciled_state(template, container, args, volumes, mounts, environment, fingerprint) -> bool:
    """Return True if the live deployment already matches this SDK configuration."""
    current_env = {e["name"]: e for e in container.get("env", [])}
    return bool(
        template.get("metadata", {})
        .get("annotations", {})
        .get("homelab.alchemmist.xyz/sdk-configuration-sha256")
        == fingerprint
        and container["args"] == args
        and all(
            current_env.get(name) == {"name": name, "value": value}
            for name, value in environment.items()
        )
        and all(entry in template["spec"].get("volumes", []) for entry in volumes)
        and all(entry in container.get("volumeMounts", []) for entry in mounts)
        and template["spec"].get("terminationGracePeriodSeconds", 0) >= 7200
    )


def observe_idle(kube, receipt, record) -> None:
    """Sample native running/waiting gauges three times, refusing active traffic."""
    # Read only numeric native running/waiting gauges, never prompts or keys.
    code = """import urllib.request,re,json
text=urllib.request.urlopen('http://127.0.0.1:8000/metrics',timeout=4).read(8388609)
if len(text)>8388608:raise ValueError('Metric budget exceeded')
result={}
for kind in ['running','waiting']:
 values=re.findall(r'^vllm:num_requests_'+kind+r'(?:\\{[^\\n]*\\})?\\s+([0-9.eE+-]+)\\s*$',text.decode(),re.M)
 if not values:raise ValueError('Required idle gauge absent')
 result[kind]=sum(float(value)for value in values)
print(json.dumps(result))"""
    receipt["idleObservations"] = []
    for _ in range(3):
        observed = kube("-n", "llm", "exec", "deploy/vllm", "--", "python3", "-c", code)
        receipt["idleObservations"].append(observed)
        record()
        if observed != {"running": 0.0, "waiting": 0.0}:
            msg = "Active or queued inference; do not restart or force drain"
            raise ValueError(msg)
        time.sleep(5)


def ready_sdk_pods(pods, fingerprint) -> list:
    """Return the running pods already carrying this SDK configuration fingerprint."""
    return [
        p
        for p in pods
        if p["metadata"]
        .get("annotations", {})
        .get("homelab.alchemmist.xyz/sdk-configuration-sha256")
        == fingerprint
        and any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in p.get("status", {}).get("conditions", [])
        )
    ]


def rollout_settled(live, matching) -> bool:
    """Return True once the rollout generation is observed with a ready SDK pod."""
    return bool(
        live.get("status", {}).get("observedGeneration", 0) >= live["metadata"]["generation"]
        and matching
    )


def wait_sdk_rollout(kube, receipt, fingerprint) -> bool:
    """Poll until the new SDK pod is ready; return True on success, False on timeout."""
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        live = kube("-n", "llm", "get", "deployment", "vllm", "-o", "json")
        pods = kube("-n", "llm", "get", "pods", "-l", "app=vllm", "-o", "json")["items"]
        matching = ready_sdk_pods(pods, fingerprint)
        if rollout_settled(live, matching):
            receipt.update(newSdkPodReady=True, sdkPods=[p["metadata"]["name"] for p in matching])
            return True
        time.sleep(5)
    return False


def run(output, apply, switcher_receipt=None) -> None:
    os.umask(0o077)
    controller = Path.home() / "Library/Application Support/homelab/otel-controller"
    if not output.resolve().is_relative_to(controller.resolve()):
        msg = "Private preimages must remain in durable controller root"
        raise ValueError(msg)
    evidence = ROOT / "deploy/monitoring/migration-evidence"
    security = json.loads(
        (evidence / "vllm-native-sdk-security-canaries-20261101.json").read_text()
    )
    renewal = json.loads((evidence / "vllm-sdk-leaf-renewal-20261101.json").read_text())
    bootstrap = json.loads((evidence / "vllm-sdk-early-bootstrap-20261101.json").read_text())
    if not (renewal_gate_passed(renewal) and source_gate_passed(security, bootstrap)):
        msg = "Pinned source privacy/bootstrap/renewal/backend gates have not passed"
        raise ValueError(msg)
    kube = BOOTSTRAP.kube
    deployment = kube("-n", "llm", "get", "deployment", "vllm", "-o", "json")
    container = next(
        c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "vllm"
    )
    require_healthy_baseline(deployment, container, security)
    environment = sdk_environment()
    args = trace_arguments(container["args"])
    require_no_env_conflicts(container, environment)
    cm_name = source_configmap_name()
    volumes = [
        {"name": "otel-source", "configMap": {"name": cm_name, "defaultMode": 420}},
        {"name": "otel-client", "secret": {"secretName": "otel-app-tls-vllm", "defaultMode": 256}},
    ]
    mounts = [
        {"name": "otel-source", "mountPath": "/etc/otel-source", "readOnly": True},
        {"name": "otel-client", "mountPath": "/etc/otel-client", "readOnly": True},
    ]
    require_no_volume_conflicts(deployment, container, (volumes, mounts))
    fingerprint = hashlib.sha256(
        json.dumps(
            {"env": environment, "source": source_data(), "endpoint": ENDPOINT},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    patch = {
        "metadata": {"resourceVersion": deployment["metadata"]["resourceVersion"]},
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"homelab.alchemmist.xyz/sdk-configuration-sha256": fingerprint}
                },
                "spec": {
                    "terminationGracePeriodSeconds": max(
                        7200,
                        deployment["spec"]["template"]["spec"].get(
                            "terminationGracePeriodSeconds", 30
                        ),
                    ),
                    "volumes": volumes,
                    "containers": [
                        {
                            "name": "vllm",
                            "args": args,
                            "env": [
                                {"name": name, "value": value}
                                for name, value in environment.items()
                            ],
                            "volumeMounts": mounts,
                        }
                    ],
                },
            }
        },
    }
    output.mkdir(mode=0o700)
    (output / "deployment-before-private.json").write_text(json.dumps(deployment, indent=2))
    receipt = {
        "applied": False,
        "configurationSHA256": fingerprint,
        "sourceConfigMap": cm_name,
        "modelDatabaseCacheGpuAndMetricsOwnershipChanged": False,
        "oldPodsForceKilled": False,
        "productionSdkCoverageVerified": False,
    }

    def record() -> None:
        (output / "result.json").write_text(json.dumps(receipt, indent=2) + "\n")

    record()
    if not apply:
        print(json.dumps(receipt))
        return
    current_cm = kube("-n", "llm", "get", "configmap", cm_name, "--ignore-not-found", "-o", "json")
    if current_cm:
        if current_cm.get("data") != source_data() or not current_cm.get("immutable"):
            msg = "Immutable privacy bootstrap ConfigMap mismatch"
            raise ValueError(msg)
    else:
        kube(
            "create",
            "-f",
            "-",
            "-o",
            "json",
            document={
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "immutable": True,
                "metadata": {"name": cm_name, "namespace": "llm"},
                "data": source_data(),
            },
        )
    template = deployment["spec"]["template"]
    if reconciled_state(template, container, args, volumes, mounts, environment, fingerprint):
        receipt.update(alreadyReconciled=True, newSdkPodReady=True)
        record()
        print(json.dumps(receipt))
        return
    observe_idle(kube, receipt, record)
    kube(
        "-n",
        "llm",
        "patch",
        "deployment",
        "vllm",
        "--type=strategic",
        "-p",
        json.dumps(patch),
        "--dry-run=server",
        "-o",
        "json",
    )
    kube(
        "-n",
        "llm",
        "patch",
        "deployment",
        "vllm",
        "--type=strategic",
        "-p",
        json.dumps(patch),
        "-o",
        "json",
    )
    receipt["applied"] = True
    record()
    if wait_sdk_rollout(kube, receipt, fingerprint):
        record()
        print(json.dumps(receipt))
        return
    msg_0 = "Candidate readiness/drain pending; preimages retained, no force kill or destructive automatic rollback"
    raise ValueError(msg_0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--switcher-receipt", type=Path)
    args = parser.parse_args()
    run(args.output, args.apply, args.switcher_receipt)
