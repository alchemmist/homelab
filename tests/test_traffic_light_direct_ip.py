"""Live source expressions, stock exporter isolation, and gray-vs-down contracts."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

PROBE_RUN_AS_UID = 19091
PUBLIC_IP_TARGET_COUNT = 3
DASH = json.loads((ROOT / "charts/monitoring-k3s/dashboards/traffic-light.json").read_text())


def panel(n) -> dict[str, object]:
    return next(p for p in DASH["panels"] if p["id"] == n)


def series(name, value, labels='job="node-exporter",node="socrat-4"', samples=20) -> dict[str, str]:
    return {
        "series": name + "{" + labels + "}",
        "values": str(value) + ("x" + str(samples) if samples else ""),
    }


class DirectIpTest(unittest.TestCase):
    """Tests for DirectIpTest."""

    def test_rendered_probe_and_existing_authenticated_pipeline(self) -> None:
        rendered = subprocess.check_output(
            [
                "helm",
                "template",
                "monitoring-k3s",
                str(ROOT / "charts/monitoring-k3s"),
                "--namespace",
                "cattle-monitoring-system",
            ],
            text=True,
        )
        docs = [d for d in yaml.safe_load_all(rendered) if d]

        def obj(kind, name):
            return next(d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name)

        pod = obj("Deployment", "socrat-public-ip-probes")["spec"]["template"]["spec"]
        assert pod["hostNetwork"]
        assert not pod["automountServiceAccountToken"]
        assert pod["securityContext"]["runAsUser"] == PROBE_RUN_AS_UID
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-0"}
        c = pod["containers"][0]
        assert "--web.listen-address=192.168.0.23:19116" in c["args"]
        assert c["securityContext"]["capabilities"] == {"drop": ["ALL"]}
        assert not c["securityContext"]["allowPrivilegeEscalation"]
        cfg = yaml.safe_load(obj("ConfigMap", "socrat-public-ip-probes")["data"]["blackbox.yml"])
        assert cfg["modules"]["direct_tcp"]["tcp"]["source_ip_address"] == "192.168.0.23"
        assert "http" not in cfg["modules"]["direct_tcp"]
        native = yaml.safe_load(
            obj("ConfigMap", "socrat-tv-native-metrics")["data"]["collector.yaml"]
        )
        jobs = native["receivers"]["prometheus"]["config"]["scrape_configs"]
        direct = [j for j in jobs if j["job_name"].startswith("public-ip-")]
        assert len(direct) == PUBLIC_IP_TARGET_COUNT
        assert {j["params"]["target"][0] for j in direct} == {
            "109.173.40.247:443",
            "109.120.141.60:443",
            "91.189.82.238:443",
        }
        assert all(j["static_configs"][0]["targets"] == ["192.168.0.23:19116"] for j in direct)
        (activity,) = [j for j in jobs if j["job_name"] == "n8n-activity-db"]
        assert activity["static_configs"] == [
            {"targets": ["pg-common-primary-metrics.postgres.svc:9187"]}
        ]
        assert activity["metric_relabel_configs"] == [
            {
                "source_labels": ["__name__"],
                "regex": "cnpg_n8n_activity_starts",
                "action": "keep",
            }
        ]
        assert native["exporters"]["otlp"]["tls"]["cert_file"] == "/tls/tls.crt"
        assert {j["job_name"] for j in jobs if j not in direct} == {
            "socrat-n8n-activity",
            "n8n-activity-db",
            "socrat-argocd",
            "wishlist",
        }
        assert (
            "checksum/native-pipeline"
            in obj("Deployment", "socrat-n8n-activity")["spec"]["template"]["metadata"][
                "annotations"
            ]
        )

    def test_host4_is_a_real_kubernetes_worker_again(self) -> None:
        e = panel(926)["targets"][0]["expr"]
        assert "kube_node_status_condition" in e
        assert 'node="socrat-4"' in e
        assert "timestamp(" in e
        assert "or vector(-2)" in e

    @unittest.skipUnless(shutil.which("promtool"), "promtool required")
    def test_actual_panel_expressions_down_pressure_stale_and_no_vpn_coupling(
        self,
    ) -> None:
        cases = []

        def add(expr, data, value, when="3m") -> None:
            cases.append(
                {
                    "interval": "15s",
                    "input_series": data,
                    "promql_expr_test": [
                        {
                            "expr": expr,
                            "eval_time": when,
                            "exp_samples": [{"labels": "{}", "value": value}],
                        }
                    ],
                }
            )

        e = panel(926)["targets"][0]["expr"]

        def ready(value, samples=20):
            return series(
                "kube_node_status_condition",
                value,
                'node="socrat-4",condition="Ready",status="true"',
                samples,
            )

        add(e, [ready(1)], 0)
        add(e, [ready(0)], 2)
        add(
            e,
            [
                ready(1),
                series(
                    "kube_node_status_condition",
                    1,
                    'node="socrat-4",condition="MemoryPressure",status="true"',
                ),
            ],
            1,
        )
        add(e, [], -2)
        add(e, [ready(1, 0)], -2)
        for pid, sid in [(905, "edge-home"), (906, "edge-vps"), (928, "edge-moscow")]:
            e = panel(pid)["targets"][0]["expr"]
            lab = f'job="public-ip-probes",service_id="{sid}",probe_observer="socrat-0",probe_path="direct-home-wan-v2"'
            add(e, [series("up", 1, lab), series("probe_success", 1, lab)], 0)
            add(e, [series("up", 1, lab), series("probe_success", 0, lab)], 2)
            add(e, [series("up", 0, lab), series("probe_success", 1, lab)], -2)
            add(e, [series("up", 1, lab)], -2)
            add(
                e,
                [series("up", 1, lab), series("probe_success", 1, lab, samples=0)],
                -2,
            )
            add(e, [], -2)
            # Even firing old VPN/edge alerts cannot override a direct green.
            add(
                e,
                [
                    series("up", 1, lab),
                    series("probe_success", 1, lab),
                    series(
                        "ALERTS",
                        1,
                        'alertname="SocratServiceEdgeVpsUnavailable",alertstate="firing",service_id="edge-vps"',
                    ),
                ],
                0,
            )
            # Legacy in-cluster probe alone cannot falsely supply direct telemetry.
            add(
                e,
                [series("probe_success", 1, f'job="service-probes",service_id="{sid}"')],
                -2,
            )
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "cases.yml"
            p.write_text(
                yaml.safe_dump({"rule_files": [], "evaluation_interval": "15s", "tests": cases})
            )
            r = subprocess.run(
                ["promtool", "test", "rules", str(p)], capture_output=True, text=True
            )
            assert r.returncode == 0, r.stdout + r.stderr

    @unittest.skipUnless(shutil.which("promtool"), "promtool required")
    def test_mode_missing_is_not_off(self) -> None:
        e = panel(9)["targets"][0]["expr"]

        def case(data, value) -> dict[str, object]:
            return {
                "interval": "15s",
                "input_series": data,
                "promql_expr_test": [
                    {
                        "expr": e,
                        "eval_time": "3m",
                        "exp_samples": [{"labels": "{}", "value": value}],
                    }
                ],
            }

        cases = [
            case([], -2),
            case([series("socrat_vpn_fallback_active", 0, 'job="node-exporter"')], -2),
            case([series("socrat_vpn_fallback_active", 1, 'job="node-exporter"')], -2),
            case(
                [
                    series(
                        "socrat_vpn_fallback_active",
                        0,
                        'job="node-exporter"',
                        samples=0,
                    )
                ],
                -2,
            ),
        ]
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "cases.yml"
            p.write_text(yaml.safe_dump({"rule_files": [], "tests": cases}))
            r = subprocess.run(
                ["promtool", "test", "rules", str(p)], capture_output=True, text=True
            )
            assert r.returncode == 0, r.stdout + r.stderr
