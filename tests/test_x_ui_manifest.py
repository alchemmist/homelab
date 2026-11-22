"""Offline render checks for x-ui's API-token and process health contracts."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_x_ui_render_disables_api_token_and_probes_real_service_ports() -> None:
    """Keep the node-local panel/Trojan checks while avoiding unused API credentials."""
    rendered = subprocess.run(
        ["helm", "template", "x-ui", str(ROOT / "charts/x-ui"), "--namespace", "x-ui"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    docs = [doc for doc in yaml.safe_load_all(rendered) if doc]
    deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
    pod_spec = deployment["spec"]["template"]["spec"]
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_spec["hostNetwork"] is True

    primary = next(c for c in pod_spec["containers"] if c["name"] == "primary")
    assert primary["livenessProbe"]["tcpSocket"] == {
        "host": "127.0.0.1",
        "port": "primary-panel",
    }
    assert primary["readinessProbe"]["tcpSocket"] == {
        "host": "127.0.0.1",
        "port": "primary-trojan",
    }
    assert {port["name"] for port in primary["ports"]} == {
        "primary-panel",
        "primary-sub",
        "primary-trojan",
    }
