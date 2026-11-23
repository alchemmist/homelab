"""Placement-only boundaries for the four workloads; offline, no credentials."""

import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.portable_placement import home_affinity

R = Path(__file__).resolve().parents[1]


def render(chart, values, namespace):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as f:
        yaml.safe_dump(values, f)
        f.flush()
        raw = subprocess.check_output(
            [
                "helm",
                "template",
                chart,
                str(R / "charts" / chart),
                "-n",
                namespace,
                "-f",
                f.name,
            ],
            text=True,
        )
    return {(x["kind"], x["metadata"]["name"]): x for x in yaml.safe_load_all(raw) if x}


def values(chart):
    v = yaml.safe_load((R / "charts" / chart / "values.yaml").read_text())
    # Production overrides here are top-level keys; maintain explicit queue map.
    for k, x in yaml.safe_load((R / "deploy" / chart / "values.yaml").read_text()).items():
        if isinstance(x, dict) and isinstance(v.get(k), dict):
            v[k].update(x)
        else:
            v[k] = x
    return v


class PlacementTests(unittest.TestCase):
    """Tests for PlacementTests."""

    def test_monori_only_frontend_changes(self) -> None:
        new = values("monori")
        old = copy.deepcopy(new)
        old["frontNodeName"] = "socrat-0"
        a, b = render("monori", old, "monori"), render("monori", new, "monori")
        assert [k for k in a if a[k] != b[k]] == [("Deployment", "monori")]
        for name in ["monori-back", "monori-sync"]:
            assert b["Deployment", name]["spec"]["template"]["spec"]["nodeSelector"] == {
                "kubernetes.io/hostname": new["statefulNodeName"]
            }
        pod = b["Deployment", "monori"]["spec"]["template"]["spec"]
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
        assert "volumes" not in pod

    def test_spi_only_queue_ui_changes_not_backend_jobs_rbac_or_network_policy(self) -> None:
        new = values("spi-triage")
        old = copy.deepcopy(new)
        old["queueUI"]["nodeName"] = "socrat-3"
        old["queueUI"]["hostAliases"] = []
        a, b = (
            render("spi-triage", old, "automation"),
            render("spi-triage", new, "automation"),
        )
        assert [k for k in a if a[k] != b[k]] == [("Deployment", "spi-queue-ui")]
        pod = b["Deployment", "spi-queue-ui"]["spec"]["template"]["spec"]
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
        assert pod["hostAliases"] == [
            {"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}
        ]
        assert not pod["automountServiceAccountToken"]

    def test_worker_single_recreate_no_pvc_auth_and_write_modes_preserved(self) -> None:
        for folder, expected in [("blog-updates", "false"), ("wiki-openapi", "true")]:
            docs = list(yaml.safe_load_all((R / "deploy" / folder / "worker.yaml").read_text()))
            d = next(x for x in docs if x and x["kind"] == "Deployment")
            assert d["spec"]["replicas"] == 1
            assert d["spec"]["strategy"] == {"type": "Recreate"}
            pod = d["spec"]["template"]["spec"]
            assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
            assert not pod["automountServiceAccountToken"]
            assert not any("persistentVolumeClaim" in v or "hostPath" in v for v in pod["volumes"])
            env = {e["name"]: e.get("value") for e in pod["containers"][0]["env"]}
            assert env["WRITE_ENABLED"] == expected
            if folder == "wiki-openapi":
                cron = next(x for x in docs if x and x["kind"] == "CronJob")
                broker = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
                assert "nodeSelector" not in broker
                assert broker["affinity"] == home_affinity()


if __name__ == "__main__":
    unittest.main()
