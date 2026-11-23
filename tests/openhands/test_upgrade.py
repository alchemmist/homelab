"""Tests for the OpenHands upgrade safety checks."""

import pathlib
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]


class UpgradeSafety(unittest.TestCase):
    """Tests for safe offline upgrade backups."""

    def test_backup_is_separate_retained_readonly_source_and_offline(self) -> None:
        """Verify the backup job isolates a read-only source and has no network."""
        r = subprocess.check_output(
            [
                "helm",
                "template",
                "openhands",
                str(ROOT / "charts/openhands"),
                "-n",
                "openhands",
                "-f",
                str(ROOT / "deploy/openhands/values.yaml"),
            ],
            text=True,
        )

        objs = [x for x in yaml.safe_load_all(r) if x]
        # The completed 2026-11-19 cold backup Job stays retired (immutable spec):
        # only its retained claim and sealed cold-config ConfigMap still render.
        assert not [
            x
            for x in objs
            if x["kind"] == "Job" and x["metadata"]["name"] == "openhands-cold-backup-20261119"
        ]
        claim = next(
            x
            for x in objs
            if x["kind"] == "PersistentVolumeClaim"
            and x["metadata"]["name"] == "openhands-cold-backups"
        )
        assert claim["metadata"]["annotations"]["argocd.argoproj.io/sync-options"] == (
            "Prune=false,Delete=false"
        )
        np = next(
            x
            for x in objs
            if x["kind"] == "NetworkPolicy" and x["metadata"]["name"] == "openhands-backup-pre142"
        )
        assert np["spec"]["egress"] == []
        boundary = next(
            x
            for x in objs
            if x["kind"] == "NetworkPolicy" and x["metadata"]["name"] == "openhands-boundary"
        )
        assert {
            "key": "app",
            "operator": "NotIn",
            "values": ["openhands-backup-pre142"],
        } in boundary["spec"]["podSelector"]["matchExpressions"]
        assert (
            "PRIVATE KEY" not in (ROOT / "charts/openhands/files/backup-recipient.pem").read_text()
        )

    def test_otel_remains_sole_scraper(self) -> None:
        """Verify OTEL stays the sole Prometheus scraper after upgrades."""
        v = yaml.safe_load((ROOT / "charts/prometheus/values.yaml").read_text())[
            "kube-prometheus-stack"
        ]["prometheus"]["prometheusSpec"]
        assert (
            v["serviceMonitorSelector"]["matchLabels"]["homelab.alchemmist.xyz/scrape-owner"]
            == "retired-legacy-prometheus"
        )
        c = next(x for x in v["containers"] if x["name"] == "otel-cluster")
        assert c["args"] == [
            "--config=/etc/otel/config/collector.yaml",
            "--config=/etc/otel/software-updates/collector.yaml",
        ]
        addon = yaml.safe_load(
            (ROOT / "charts/prometheus/templates/software-update-otel.yaml")
            .read_text()
            .replace("{{ .Release.Namespace }}", "cattle-monitoring-system")
        )
        config = yaml.safe_load(addon["data"]["collector.yaml"])
        assert config["service"]["pipelines"]["metrics"]["receivers"] == [
            "prometheus",
            "otlp",
            "prometheus/software_updates",
        ]
        assert (
            config["receivers"]["prometheus/software_updates"]["config"]["scrape_configs"][0][
                "job_name"
            ]
            == "monitoring-update-watch"
        )


if __name__ == "__main__":
    unittest.main()
