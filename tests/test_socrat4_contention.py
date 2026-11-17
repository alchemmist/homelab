"""Native PromQL regression for owner-approved socrat-4 PSI exception."""

import shutil
import tempfile
from pathlib import Path

import yaml

from scripts.quality.common import command


def test_socrat4_contention() -> None:
    """Exercise all eleven PSI cases and the original hardware-alert regression."""
    helm = shutil.which("helm")
    promtool = shutil.which("promtool")
    if helm is None or promtool is None:
        message = "Native PSI regression requires Helm and promtool; no fallback"
        raise FileNotFoundError(message)
    rendered = command([helm, "template", "monitoring", "charts/monitoring-k3s"]).stdout
    groups = [
        g
        for d in yaml.safe_load_all(rendered)
        if d and d["kind"] == "PrometheusRule"
        for g in d["spec"]["groups"]
    ]
    group = next(g for g in groups if g["name"] == "socrat.nodes.hardware")
    rules = [r for r in group["rules"] if r.get("alert") == "SocratNodeResourceContention"]
    expected_rule_variants = 2
    assert len(rules) == expected_rule_variants
    tests = []
    for node, resource, value, duration, firing in [
        ("socrat-4", "cpu", 0.82, 60, False),
        ("socrat-4", "cpu", 0.90, 60, False),
        ("socrat-4", "memory", 0.50, 60, False),
        ("socrat-4", "io", 0.60, 60, False),
        ("socrat-4", "cpu", 0.95, 29, False),
        ("socrat-4", "cpu", 0.95, 31, True),
        ("socrat-4", "memory", 0.55, 31, True),
        ("socrat-4", "io", 0.65, 31, True),
        ("socrat-0", "cpu", 0.60, 11, True),
        ("socrat-0", "memory", 0.30, 11, True),
        ("socrat-0", "io", 0.30, 11, True),
    ]:
        rule = rules[1] if node == "socrat-4" else rules[0]
        annotations = {
            k: v.replace("{{ $labels.node }}", node).replace("{{ $labels.resource }}", resource)
            for k, v in rule["annotations"].items()
        }
        tests.append(
            {
                "name": f"{node}-{resource}-{value}-{duration}",
                "interval": "1m",
                "input_series": [
                    {
                        "series": (
                            "socrat:node_pressure_waiting:ratio5m"
                            f'{{node="{node}",resource="{resource}"}}'
                        ),
                        "values": f"{value}x65",
                    }
                ],
                "alert_rule_test": [
                    {
                        "eval_time": f"{duration}m",
                        "alertname": rule["alert"],
                        "exp_alerts": [
                            {
                                "exp_labels": {
                                    "node": node,
                                    "resource": resource,
                                    "severity": "warning",
                                },
                                "exp_annotations": annotations,
                            }
                        ]
                        if firing
                        else [],
                    }
                ],
            }
        )
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "rules.yml").write_text(yaml.safe_dump({"groups": [{"name": "psi", "rules": rules}]}))
        (p / "test.yml").write_text(
            yaml.safe_dump(
                {"rule_files": ["rules.yml"], "evaluation_interval": "1m", "tests": tests}
            )
        )
        command([promtool, "test", "rules", "test.yml"], cwd=p)
        (p / "node-hardware.rules.yml").write_text(yaml.safe_dump({"groups": [group]}))
        (p / "old.yml").write_text(Path("tests/node-hardware.test.yml").read_text())
        command([promtool, "test", "rules", "old.yml"], cwd=p)


if __name__ == "__main__":
    test_socrat4_contention()
