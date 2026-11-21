"""Secret-free rendering/storage/backup contracts for worker5 migration."""

from pathlib import Path
import io
import tarfile
import os
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class Worker5MigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.values = yaml.safe_load((ROOT / "charts/n8n/values.yaml").read_text())
        cls.docs = list(
            yaml.safe_load_all(
                subprocess.check_output(
                    ["helm", "template", "n8n", str(ROOT / "charts/n8n")], text=True
                )
            )
        )

    def resource(self, kind, name):
        return next(
            d for d in self.docs if d and d["kind"] == kind and d["metadata"]["name"] == name
        )

    def test_single_writer_local_retained_and_legacy_preserved(self):
        deployment = self.resource("Deployment", "n8n")["spec"]
        assert deployment["replicas"] in (0, 1)
        assert deployment["strategy"]["type"] == "Recreate"
        spec = deployment["template"]["spec"]
        assert spec["nodeSelector"]["kubernetes.io/hostname"] == self.values["nodeName"]
        assert (
            spec["volumes"][-1]["persistentVolumeClaim"]["claimName"]
            == self.values["persistence"]["claimName"]
        )
        pv = self.resource("PersistentVolume", "n8n-socrat5")["spec"]
        assert pv["persistentVolumeReclaimPolicy"] == "Retain"
        assert pv["local"]["path"] == "/var/lib/rancher/k3s/storage/n8n-socrat5"
        self.resource("PersistentVolumeClaim", "n8n")  # rollback PVC stays in desired state

    def test_backup_daily_readonly_no_api_access(self):
        cron = self.resource("CronJob", "n8n-backup")["spec"]
        assert cron["schedule"] == "15 3 * * *"
        assert cron["timeZone"] == "Europe/Moscow"
        assert cron["concurrencyPolicy"] == "Forbid"
        spec = cron["jobTemplate"]["spec"]["template"]["spec"]
        assert not spec["automountServiceAccountToken"]
        assert spec["containers"][0]["volumeMounts"][0]["readOnly"]
        assert spec["nodeSelector"]["kubernetes.io/hostname"] == self.values["nodeName"]
        assert (
            spec["volumes"][0]["persistentVolumeClaim"]["claimName"]
            == self.values["persistence"]["claimName"]
        )
        env = spec["containers"][0]["env"]
        assert env[0]["valueFrom"]["fieldRef"]["fieldPath"] == "spec.nodeName"

    def test_recovery_is_separate_retained_and_node_affine(self):
        config = self.values["recoveryStorage"]
        assert config["name"] != "n8n-socrat5"
        pv = self.resource("PersistentVolume", config["name"])["spec"]
        assert pv["persistentVolumeReclaimPolicy"] == "Retain"
        assert pv["local"]["path"] == config["path"]
        assert pv["claimRef"]["name"] == config["name"]
        affinity = pv["nodeAffinity"]["required"]["nodeSelectorTerms"][0]["matchExpressions"][0]
        assert affinity["values"] == [config["nodeName"]]
        pvc = self.resource("PersistentVolumeClaim", config["name"])
        assert pvc["spec"]["volumeName"] == config["name"]
        assert (
            pvc["metadata"]["annotations"]["argocd.argoproj.io/sync-options"]
            == "Prune=false,Delete=false"
        )

    def test_legacy_volume_does_not_move_when_deployment_moves(self):
        docs = list(
            yaml.safe_load_all(
                subprocess.check_output(
                    [
                        "helm",
                        "template",
                        "n8n",
                        str(ROOT / "charts/n8n"),
                        "--set",
                        "nodeName=socrat-0",
                    ],
                    text=True,
                )
            )
        )
        pv = next(
            x
            for x in docs
            if x and x["kind"] == "PersistentVolume" and x["metadata"]["name"] == "n8n-socrat5"
        )
        expr = pv["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0]["matchExpressions"][0]
        assert expr["values"] == ["socrat-5"]
        recovery = next(
            x
            for x in docs
            if x
            and x["kind"] == "PersistentVolume"
            and x["metadata"]["name"] == self.values["recoveryStorage"]["name"]
        )
        expr = recovery["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0][
            "matchExpressions"
        ][0]
        assert expr["values"] == [self.values["recoveryStorage"]["nodeName"]]

    def test_receiver_rejects_commands_and_uses_private_append_versions(self):
        receiver = ROOT / "scripts/n8n/backup_receiver.py"
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, SSH_ORIGINAL_COMMAND="rm -rf /")
            p = subprocess.run(
                ["python3", str(receiver)], env=env, input=b"not an archive", capture_output=True
            )
            assert p.returncode != 0
            env["SSH_ORIGINAL_COMMAND"] = "receive-n8n-backup"
            content = io.BytesIO()
            with tarfile.open(fileobj=content, mode="w:gz") as archive:
                for name in ["data/database.sqlite", "manifest.json", "encryption-key"]:
                    member = tarfile.TarInfo(name)
                    member.size = 4
                    archive.addfile(member, io.BytesIO(b"test"))
            for _ in range(2):
                p = subprocess.run(
                    ["python3", str(receiver)],
                    env=env,
                    input=content.getvalue(),
                    capture_output=True,
                )
                assert p.returncode == 0, p.stderr
            archives = list((Path(home) / "backups/n8n").glob("*.tar.gz"))
            expected_archive_count = 2
            assert len(archives) == expected_archive_count
            assert all(p.stat().st_mode & 63 == 0 for p in archives)
            assert len(list(archives[0].parent.glob("*.sha256"))) == expected_archive_count

    def test_only_named_local_claim_is_admitted(self):
        policy = next(
            yaml.safe_load_all((ROOT / "deploy/admission/socrat5-local-storage.yaml").read_text())
        )
        expression = policy["spec"]["validations"][0]["expression"]
        assert "request.namespace == 'automation'" in expression
        assert "claimName == 'n8n-socrat5'" in expression
        assert "has(v.nfs)" not in expression
        assert "has(v.csi)" not in expression


if __name__ == "__main__":
    unittest.main()
