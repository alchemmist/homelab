"""Offline regression checks for Venice chart namespace and service-account boundaries."""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def render(chart: str, release: str, namespace: str) -> list[dict]:
    helm = shutil.which("helm")
    if helm is None:
        msg = "helm is required for Venice chart render tests"
        raise RuntimeError(msg)
    result = subprocess.run(
        [helm, "template", release, str(ROOT / chart), "--namespace", namespace],
        check=True,
        capture_output=True,
        text=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def test_venice_api_has_dedicated_tokenless_service_account() -> None:
    docs = render("charts/venice-api", "venice-api", "venice-review")
    resources = {(doc["kind"], doc["metadata"]["name"]): doc for doc in docs}
    service_account = resources[("ServiceAccount", "venice-api")]
    assert service_account["automountServiceAccountToken"] is False
    deployment = resources[("Deployment", "venice-api")]
    pod = deployment["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "venice-api"
    assert pod["automountServiceAccountToken"] is False
    assert all(doc["metadata"].get("namespace") == "venice-review" for doc in docs)
    # Keep the application's required key/cookie inputs and readiness contract intact.
    app = pod["containers"][0]
    api_key = next(env for env in app["env"] if env["name"] == "API_KEY")
    assert api_key["valueFrom"]["secretKeyRef"] == {"name": "venice-api-env", "key": "API_KEY"}
    assert app["readinessProbe"]["httpGet"]["path"] == "/"
    assert {mount["name"] for mount in app["volumeMounts"]} >= {"cookies", "profile", "shm"}


def test_venice_agent_lab_renders_only_in_release_namespace() -> None:
    docs = render("charts/venice-agent-lab", "venice-agent-lab", "venice-review")
    assert {doc["kind"] for doc in docs} == {
        "ServiceAccount",
        "StatefulSet",
        "Role",
        "RoleBinding",
        "NetworkPolicy",
    }
    assert all(doc["metadata"].get("namespace") == "venice-review" for doc in docs)
    resources = {(doc["kind"], doc["metadata"]["name"]): doc for doc in docs}
    worker = resources[("StatefulSet", "venice-agent-worker")]["spec"]["template"]["spec"]
    assert worker["serviceAccountName"] == "venice-agent-worker"
    assert worker["automountServiceAccountToken"] is False
    policy = resources[("NetworkPolicy", "venice-agent-worker-deny-all")]["spec"]
    assert policy["ingress"] == []
    assert policy["egress"] == []
    rules = resources[("Role", "venice-agent-controller")]["rules"]
    assert rules == [
        {
            "apiGroups": [""],
            "resources": ["pods"],
            "resourceNames": ["venice-agent-worker-0"],
            "verbs": ["get", "delete"],
        },
        {
            "apiGroups": [""],
            "resources": ["pods/exec"],
            "resourceNames": ["venice-agent-worker-0"],
            "verbs": ["get", "create"],
        },
    ]
