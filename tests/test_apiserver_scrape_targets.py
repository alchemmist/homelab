"""Check the actual API ServiceMonitor rendered for the Prometheus Application."""

import copy
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_apiserver_scrape_targets():
    """Observe each control plane exactly once, not the old worker or LAN alias."""
    chart = ROOT / "charts/prometheus"
    rendered = subprocess.check_output(
        [
            "helm",
            "template",
            "kube-prometheus-stack",
            str(chart),
            "--namespace",
            "cattle-monitoring-system",
            "-f",
            str(chart / "alert-graphs.values.yaml"),
            "--show-only",
            "charts/kube-prometheus-stack/templates/exporters/kube-api-server/servicemonitor.yaml",
        ],
        text=True,
    )
    monitor = yaml.safe_load(rendered)
    assert monitor["kind"] == "ServiceMonitor"
    rules = monitor["spec"]["endpoints"][0]["relabelings"]
    reference = yaml.safe_load((ROOT / "deploy/monitoring/values.yaml").read_text())

    def address_filter(entries):
        (rule,) = [
            r
            for r in entries
            if r.get("action") == "keep" and r.get("sourceLabels") == ["__address__"]
        ]
        return rule

    rule = address_filter(rules)
    assert rule == address_filter(
        reference["kubeApiServer"]["serviceMonitor"]["relabelings"]
    )
    accepted = {"10.250.0.1:6443", "10.250.0.3:6443", "10.250.0.41:6443"}
    candidates = accepted | {"10.250.0.5:6443", "192.168.0.23:6443", "10.250.0.41:443"}
    assert {
        address for address in candidates if re.fullmatch(rule["regex"], address)
    } == accepted


def test_native_frozen_scrape_preserves_tls_auth_and_other_jobs():
    import runpy

    refresh = runpy.run_path(str(ROOT / "scripts/otel-scrape-config.py"))[
        "refresh_api_targets"
    ]
    job = {
        "job_name": "serviceMonitor/cattle-monitoring-system/kube-prometheus-stack-apiserver/0",
        "relabel_configs": [
            {
                "action": "keep",
                "source_labels": ["__address__"],
                "regex": r"10\.250\.0\.(1|3|5):6443",
            }
        ],
        "tls_config": {"ca_file": "ca"},
        "authorization": {"credentials_file": "token"},
    }
    original = {"scrape_configs": [job, {"job_name": "other"}]}
    expected = copy.deepcopy(original)
    expected["scrape_configs"][0]["relabel_configs"][0]["regex"] = (
        r"10\.250\.0\.(1|3|41):6443"
    )
    new = refresh(original)
    assert new == expected == refresh(new)
    assert original != expected
