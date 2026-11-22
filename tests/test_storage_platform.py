"""Offline platform/tier guards; no network or production writes."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCS = list(yaml.safe_load_all((ROOT / "deploy/storage/tiers/platform.yaml").read_text()))
CM = next(d for d in DOCS if d["kind"] == "ConfigMap")


class StoragePlatformTest(unittest.TestCase):
    """Validate storage tier classes stay dynamic, retained, and local."""

    def test_explicit_dynamic_retained_local_tiers(self):
        for d in yaml.safe_load_all((ROOT / "deploy/storage/tiers/classes.yaml").read_text()):
            assert d["provisioner"] == "rancher.io/local-path"
            assert d["reclaimPolicy"] == "Retain"
            assert d["volumeBindingMode"] == "WaitForFirstConsumer"
            assert d["metadata"]["annotations"]["defaultVolumeType"] == "local"
            assert (
                d["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"]
                == "false"
            )
            assert d["allowedTopologies"][0]["matchLabelExpressions"][0]["values"] == ["socrat-5"]

    def test_preserve_legacy_classes_and_default_node_mapping(self):
        c = json.loads(CM["data"]["config.json"])
        assert c["nodePathMap"] == []
        for name in [
            "local-path",
            "lms-db-retain",
            "rustfs-retain",
            "socrat-bot-retain",
            "venice-browser-retain",
            "pg-local-retain",
        ]:
            assert name in c["storageClassConfigs"]
        local = c["storageClassConfigs"]["local-path"]["nodePathMap"]
        assert {"node": "socrat-5", "paths": ["/mnt/files/homelab/volumes"]} in local
        for name in ["local-hdd", "local-ssd"]:
            assert {"node": "DEFAULT_PATH_FOR_NON_LISTED_NODES", "paths": []} in c[
                "storageClassConfigs"
            ][name]["nodePathMap"]

    def test_legacy_is_not_default(self):
        sc = next(d for d in DOCS if d["kind"] == "StorageClass")
        assert (
            sc["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"] == "false"
        )

    def run_setup(self, device, marker):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            parent = root / "volumes"
            parent.mkdir()
            (parent / ".homelab-filesystem-id").write_text(marker)
            tools = root / "bin"
            tools.mkdir()
            stat = tools / "stat"
            stat.write_text('#!/bin/sh\nprintf "%s\\n" "$TEST_DEVICE_ID"\n')
            stat.chmod(0o755)
            script = CM["data"]["setup"].replace("/mnt/files/homelab/volumes", str(parent))
            p = subprocess.run(
                ["sh", "-c", script],
                env={
                    **os.environ,
                    "VOL_DIR": str(parent / "pvc-test"),
                    "TEST_DEVICE_ID": str(device),
                    "PATH": str(tools) + ":" + os.environ["PATH"],
                },
                capture_output=True,
                text=True,
            )
            return p.returncode, (parent / "pvc-test").exists()

    def test_missing_hdd_rejects_even_copied_identity_marker(self):
        code, created = self.run_setup(2049, "3ec3263e-32e3-4b38-84e6-17cd168244b9")
        assert code != 0
        assert not created

    def test_wrong_marker_rejects_even_correct_device(self):
        code, created = self.run_setup(2065, "wrong-filesystem")
        assert code != 0
        assert not created

    def test_matching_identity_allows_directory_creation(self):
        code, created = self.run_setup(2065, "3ec3263e-32e3-4b38-84e6-17cd168244b9")
        assert code == 0
        assert created

    def test_teardown_guard_precedes_removal(self):
        text = CM["data"]["teardown"]
        assert text.index("HDD_DEVICE_MISMATCH") < text.index("rm -rf")

    def test_rancher_native_cache_can_reach_exact_node5_api(self):
        text = (
            ROOT / "deploy/platform/rancher/public-entry/templates/observer-membership.yaml"
        ).read_text()
        assert "ipBlock: {cidr: 10.250.0.41/32}" in text
        assert "port: 6443" in text

    def test_archive_day2_refuses_unaccepted_mounts_and_never_restarts(self):
        text = (ROOT / "ansible/playbooks/socrat-5-runtime-storage.yml").read_text()
        assert "Require already accepted archive binds" in text
        assert "/mnt/files/homelab/openhands-archives/cold-backups" in text
        assert "state: restarted" not in text
        guard = (ROOT / "ansible/files/socrat5-containerd-hdd-check").read_text()
        assert "/dev/sdb1[/homelab/openhands-archives/cold-backups]" in guard
        assert "/dev/sdb1[/homelab/openhands-archives/upgrade-backups]" in guard

    def test_containerd_guard_requires_both_stat_probes_to_succeed(self):
        """Identical output is not proof of identity if stat failed."""
        guard = ROOT / "ansible/files/socrat5-containerd-hdd-check"
        with tempfile.TemporaryDirectory() as temp:
            tools = Path(temp)
            findmnt = tools / "findmnt"
            findmnt.write_text(
                "#!/bin/sh\ncase $4 in\n"
                " /mnt/files) echo /dev/sdb1;;\n"
                " */containerd) echo '/dev/sdb1[/homelab/runtime/containerd]';;\n"
                " *-cold-backups) echo '/dev/sdb1[/homelab/openhands-archives/cold-backups]';;\n"
                " *-upgrade-backups) echo '/dev/sdb1[/homelab/openhands-archives/upgrade-backups]';;\n"
                " *) exit 1;;\nesac\n"
            )
            stat = tools / "stat"
            stat.write_text('#!/bin/sh\necho 1:2\nif [ "$3" = "$FAIL_PATH" ]; then exit 42; fi\n')
            for executable in (findmnt, stat):
                executable.chmod(0o755)
            for fail_path, status in (
                ("", 0),
                ("/var/lib/rancher/k3s/agent/containerd", 42),
                ("/mnt/files/homelab/runtime/containerd", 42),
            ):
                result = subprocess.run(
                    ["/bin/sh", str(guard)],
                    env={"PATH": temp, "FAIL_PATH": fail_path},
                    check=False,
                )
                assert result.returncode == status

    def test_inventory_matches_claim_namespace_not_only_name(self):
        spec = importlib.util.spec_from_file_location(
            "audit_storage", ROOT / "scripts/audit_storage.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        pv = {
            "metadata": {"name": "fixture"},
            "spec": {
                "claimRef": {"namespace": "a", "name": "data"},
                "capacity": {"storage": "1Gi"},
                "persistentVolumeReclaimPolicy": "Retain",
            },
        }
        pods = [
            {
                "metadata": {"namespace": ns, "name": ns},
                "spec": {
                    "nodeName": "socrat-5",
                    "volumes": [{"persistentVolumeClaim": {"claimName": "data"}}],
                },
            }
            for ns in ["a", "b"]
        ]
        assert module.inventory([pv], pods)[0]["consumers"] == [{"pod": "a", "node": "socrat-5"}]

    def test_storage_dashboard_keeps_missing_as_unknown(self):
        d = json.loads((ROOT / "charts/monitoring-k3s/dashboards/storage.json").read_text())
        assert d["uid"] == "socrat-storage"
        for p in d["panels"]:
            assert "{{mountpoint}}" in p["targets"][0]["legendFormat"]
            assert "or vector(0)" not in p["targets"][0]["expr"]


if __name__ == "__main__":
    unittest.main()
