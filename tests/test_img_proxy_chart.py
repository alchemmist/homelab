"""Render-time security and health contracts for the img-proxy chart."""

import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "img-proxy"


def test_rendered_img_proxy_identity_and_dependency_free_probes() -> None:
    """Use a tokenless dedicated identity and probe nginx locally, not its upstream."""
    rendered = subprocess.check_output(
        ["helm", "template", "img-proxy", str(CHART), "--namespace", "img-proxy"],
        text=True,
    )
    objects = [item for item in yaml.safe_load_all(rendered) if isinstance(item, dict)]
    service_account = next(item for item in objects if item["kind"] == "ServiceAccount")
    assert service_account["metadata"]["name"] == "img-proxy"
    assert service_account["automountServiceAccountToken"] is False

    deployment = next(item for item in objects if item["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    assert pod["serviceAccountName"] == "img-proxy"
    assert pod["automountServiceAccountToken"] is False
    container = pod["containers"][0]
    for probe_name in ("livenessProbe", "readinessProbe"):
        probe = container[probe_name]
        assert probe["httpGet"] == {"path": "/healthz", "port": 8080}

    config = next(item for item in objects if item["kind"] == "ConfigMap")
    nginx = config["data"]["default.conf"]
    assert "location = /healthz" in nginx
    assert "return 204;" in nginx
    health_location = nginx.split("location = /healthz", maxsplit=1)[1].split("location /", maxsplit=1)[0]
    assert "proxy_pass" not in health_location
    assert "proxy_pass https://images.weserv.nl;" in nginx
