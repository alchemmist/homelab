"""Secret-free rendering/storage/backup contracts for worker5 migration."""

import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import override

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _mapping(value: object) -> dict[str, object]:
    """Return the assert-verified mapping view of a parsed YAML value."""
    assert isinstance(value, dict)
    result: dict[str, object] = value
    return result


def _documents(value: object) -> list[dict[str, object]]:
    """Return the assert-verified list-of-documents view of a parsed YAML value."""
    assert isinstance(value, list)
    documents: list[dict[str, object]] = value
    return documents


def _mapping_path(document: dict[str, object], *keys: str) -> dict[str, object]:
    """Walk nested mappings of a parsed document and return the final mapping."""
    value: object = document
    for key in keys:
        value = _mapping(value)[key]
    return _mapping(value)


class Worker5MigrationTest(unittest.TestCase):
    """Check the n8n migration to worker node 5 renders safely."""

    @classmethod
    @override
    def setUpClass(cls) -> None:
        """Load the chart values and rendered documents once."""
        cls.values = yaml.safe_load((ROOT / "charts/n8n/values.yaml").read_text())
        cls.docs = list(
            yaml.safe_load_all(
                subprocess.check_output(
                    ["helm", "template", "n8n", str(ROOT / "charts/n8n")], text=True
                )
            )
        )

    def resource(self, kind, name) -> dict[str, object]:
        """Return the rendered document of the given kind and name."""
        document: dict[str, object] = next(
            d for d in self.docs if d and d["kind"] == kind and d["metadata"]["name"] == name
        )
        return document

    def test_single_writer_local_retained_and_legacy_preserved(self) -> None:
        """A single writer on retained local storage preserves the legacy claim."""
        deployment = _mapping(self.resource("Deployment", "n8n")["spec"])
        assert deployment["replicas"] in (0, 1)
        assert _mapping(deployment["strategy"])["type"] == "Recreate"
        spec = _mapping(_mapping(deployment["template"])["spec"])
        assert _mapping(spec["nodeSelector"])["kubernetes.io/hostname"] == self.values["nodeName"]
        volumes = _documents(spec["volumes"])
        assert _mapping(volumes[-1]["persistentVolumeClaim"])["claimName"] == _mapping(self.values["persistence"])["claimName"]
        pv = _mapping(self.resource("PersistentVolume", "n8n-socrat5")["spec"])
        assert pv["persistentVolumeReclaimPolicy"] == "Retain"
        assert _mapping(pv["local"])["path"] == "/var/lib/rancher/k3s/storage/n8n-socrat5"
        self.resource("PersistentVolumeClaim", "n8n")  # rollback PVC stays in desired state

    def test_backup_daily_readonly_no_api_access(self) -> None:
        """The daily backup is read-only with no API access."""
        cron = _mapping(self.resource("CronJob", "n8n-backup")["spec"])
        assert cron["schedule"] == "15 3 * * *"
        assert cron["timeZone"] == "Europe/Moscow"
        assert cron["concurrencyPolicy"] == "Forbid"
        spec = _mapping_path(cron, "jobTemplate", "spec", "template", "spec")
        assert not spec["automountServiceAccountToken"]
        containers = _documents(spec["containers"])
        volume_mounts = _documents(containers[0]["volumeMounts"])
        assert volume_mounts[0]["readOnly"]
        assert _mapping(spec["nodeSelector"])["kubernetes.io/hostname"] == self.values["nodeName"]
        volumes = _documents(spec["volumes"])
        assert _mapping(volumes[0]["persistentVolumeClaim"])["claimName"] == _mapping(self.values["persistence"])["claimName"]
        env = _documents(containers[0]["env"])
        assert _mapping(_mapping(env[0]["valueFrom"])["fieldRef"])["fieldPath"] == "spec.nodeName"

    def test_recovery_is_separate_retained_and_node_affine(self) -> None:
        """Recovery storage is separate, retained and node-affine."""
        config = self.values["recoveryStorage"]
        assert config["name"] != "n8n-socrat5"
        pv = _mapping(self.resource("PersistentVolume", config["name"])["spec"])
        assert pv["persistentVolumeReclaimPolicy"] == "Retain"
        assert _mapping(pv["local"])["path"] == config["path"]
        assert _mapping(pv["claimRef"])["name"] == config["name"]
        required = _mapping(_mapping(pv["nodeAffinity"])["required"])
        terms = _documents(required["nodeSelectorTerms"])
        affinity = _documents(_mapping(terms[0])["matchExpressions"])[0]
        assert affinity["values"] == [config["nodeName"]]
        pvc = self.resource("PersistentVolumeClaim", config["name"])
        assert _mapping(pvc["spec"])["volumeName"] == config["name"]
        assert _mapping(_mapping(pvc["metadata"])["annotations"])["argocd.argoproj.io/sync-options"] == "Prune=false,Delete=false"

    def test_legacy_volume_does_not_move_when_deployment_moves(self) -> None:
        """The legacy volume stays put when the deployment moves."""
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

    def test_receiver_rejects_commands_and_uses_private_append_versions(self) -> None:
        """The receiver rejects commands and appends private versions."""
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
            assert len(archives) == 2
            assert all(p.stat().st_mode & 63 == 0 for p in archives)
            assert len(list(archives[0].parent.glob("*.sha256"))) == 2

    def test_only_named_local_claim_is_admitted(self) -> None:
        """Only the named local claim is admitted by the policy."""
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
