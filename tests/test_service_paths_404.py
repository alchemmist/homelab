"""Exercise path classification and the rendered alerts without live failures."""

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/monitoring-k3s"
spec = importlib.util.spec_from_file_location("paths", CHART / "files/service_paths.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_snapshot_turnover_and_failures():
    a, b = ("a", [("192.0.2.1", 8082)]), ("b", [("192.0.2.2", 8082)])
    for snapshots, results, expected in [
        ([a, a], ["ok", "ok"], "ok"),
        ([("empty", [])], [], "no_endpoint"),
        ([a, b, b, b], ["failed", "ok", "ok", "ok"], "ok"),
        ([a, a], ["dns", "ok"], "service_dns"),
        ([a, a], ["failed", "failed"], "endpoint_failed"),
        ([a, a], ["failed", "ok"], "service_only_failed"),
    ]:
        with (
            patch.object(probe, "snapshot", Mock(side_effect=snapshots)),
            patch.object(probe, "health", Mock(side_effect=results)),
        ):
            assert probe.pair() == expected


def test_prometheus_rules(tmp_path):
    rendered = subprocess.check_output(
        [
            "helm",
            "template",
            "monitoring-k3s",
            str(CHART),
            "-s",
            "templates/service-paths.yaml",
        ],
        text=True,
    )
    docs = list(yaml.safe_load_all(rendered))
    groups = next(d["spec"] for d in docs if d["kind"] == "PrometheusRule")
    (tmp_path / "rules.yml").write_text(yaml.safe_dump(groups))
    subprocess.run(
        ["promtool", "check", "rules", "rules.yml"], cwd=tmp_path, check=True
    )
    series = [
        {"series": f'up{{job="apiserver",instance="10.250.0.{ip}:6443"}}', "values": v}
        for ip, v in [(1, "1+0x6"), (3, "0+0x6")]
    ]
    for source, streak in [("socrat-3", "0+0x6"), ("socrat-5", "0+1x6")]:
        for metric, vals in [
            ("socrat_service_path_divergence_streak", streak),
            ("socrat_service_path_sample_seconds", "0+60x6"),
        ]:
            series.append({"series": f'{metric}{{source="{source}"}}', "values": vals})

    def case(name, labels, annotations=None):
        return {
            "eval_time": "3m",
            "alertname": name,
            "exp_alerts": [
                {
                    "exp_labels": {"severity": "warning", **labels},
                    "exp_annotations": annotations
                    or next(
                        r["annotations"]
                        for r in groups["groups"][0]["rules"]
                        if r["alert"] == name
                    ),
                }
            ],
        }

    cases = [
        case(
            "SocratApiScrapeUnavailable",
            {"job": "apiserver", "instance": "10.250.0.3:6443"},
        ),
        case(
            "SocratApiScrapeMissing",
            {
                "job": "apiserver",
                "instance": "10.250.0.41:6443",
            },
        ),
        case(
            "SocratServicePathDiverged",
            {"source": "socrat-5"},
            groups["groups"][0]["rules"][0]["annotations"],
        ),
    ]
    fixture = {
        "rule_files": ["rules.yml"],
        "evaluation_interval": "1m",
        "tests": [{"interval": "1m", "input_series": series, "alert_rule_test": cases}],
    }
    (tmp_path / "suite.yml").write_text(yaml.safe_dump(fixture))
    subprocess.run(["promtool", "test", "rules", "suite.yml"], cwd=tmp_path, check=True)
