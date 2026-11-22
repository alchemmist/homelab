"""Guard the descheduler's rendered periodic-job contract and review boundaries."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "descheduler"


def test_descheduler_render_preserves_periodic_eviction_contract() -> None:
    """Render the vendored chart and check real objects, not source values."""
    helm = shutil.which("helm")
    assert helm is not None, "helm is required for this offline render test"
    rendered = subprocess.run(
        [helm, "template", "descheduler", str(CHART), "--namespace", "kube-system"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    objects = [obj for obj in yaml.safe_load_all(rendered) if obj]
    cronjobs = [obj for obj in objects if obj.get("kind") == "CronJob"]
    assert len(cronjobs) == 1
    job = cronjobs[0]
    assert job["spec"]["schedule"] == "*/5 * * * *"
    assert job["spec"]["concurrencyPolicy"] == "Forbid"
    assert job["spec"]["jobTemplate"]["spec"]["activeDeadlineSeconds"] == 90
    pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert "readinessProbe" not in container
    assert container["livenessProbe"]["httpGet"]["path"] == "/healthz"
    assert not any(obj.get("kind") == "NetworkPolicy" for obj in objects)

    configs = [obj for obj in objects if obj.get("kind") == "ConfigMap"]
    assert len(configs) == 1
    policy = yaml.safe_load(configs[0]["data"]["policy.yaml"])
    assert policy["maxNoOfPodsToEvictTotal"] == 1
    profiles = {profile["name"]: profile for profile in policy["profiles"]}
    assert set(profiles) == {
        "stateless-preference",
        "shared-monitoring",
        "shared-pyroscope",
    }
    assert all(
        profile["pluginConfig"][-1]["args"]["nodeAffinityType"]
        == ["preferredDuringSchedulingIgnoredDuringExecution"]
        for profile in profiles.values()
    )
