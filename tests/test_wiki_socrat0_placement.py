"""Tests for the socrat0 wiki placement rules."""

import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class WikiCurrentPlacementTest(unittest.TestCase):
    """Tests for WikiCurrentPlacementTest."""

    def test_retained_volume_matches_values_and_existing_directory(self) -> None:
        values = yaml.safe_load((ROOT / "deploy/wiki-runtime/values.yaml").read_text())
        pv, pvc = list(
            yaml.safe_load_all((ROOT / "deploy/storage/wiki-runtime-socrat5.yaml").read_text())
        )
        assert values["persistence"]["existingClaim"] == pvc["metadata"]["name"]
        assert pvc["spec"]["volumeName"] == pv["metadata"]["name"]
        assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
        assert pv["spec"]["local"]["path"] == "/mnt/files/homelab/wiki-runtime/data"
        assert pv["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0]["matchExpressions"][
            0
        ]["values"] == ["socrat-5"]
        assert values["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}

    @unittest.skipUnless(shutil.which("helm"), "helm is required")
    def test_rendered_deployment_has_one_writer_and_new_claim(self) -> None:
        result = subprocess.check_output(
            [
                "helm",
                "template",
                "wiki-runtime",
                str(ROOT / "deploy/wiki-runtime/chart"),
                "-n",
                "wiki",
                "-f",
                str(ROOT / "deploy/wiki-runtime/values.yaml"),
            ],
            text=True,
        )
        deployment = next(
            item for item in yaml.safe_load_all(result) if item and item["kind"] == "Deployment"
        )
        assert deployment["spec"]["replicas"] == 1
        assert deployment["spec"]["strategy"]["type"] == "Recreate"
        pod = deployment["spec"]["template"]["spec"]
        assert pod["nodeSelector"] == {"kubernetes.io/hostname": "socrat-5"}
        data = next(volume for volume in pod["volumes"] if volume["name"] == "data")
        assert data["persistentVolumeClaim"]["claimName"] == "wiki-runtime-socrat5"

    @unittest.skipUnless(shutil.which("helm"), "helm is required")
    def test_rendered_wiki_containers_are_read_only_with_bounded_writable_tmp(self) -> None:
        result = subprocess.check_output(
            [
                "helm",
                "template",
                "wiki-runtime",
                str(ROOT / "deploy/wiki-runtime/chart"),
                "-n",
                "wiki",
                "-f",
                str(ROOT / "deploy/wiki-runtime/values.yaml"),
            ],
            text=True,
        )
        deployment = next(
            item for item in yaml.safe_load_all(result) if item and item["kind"] == "Deployment"
        )
        pod = deployment["spec"]["template"]["spec"]
        tmp = next(volume for volume in pod["volumes"] if volume["name"] == "tmp")
        assert tmp["emptyDir"]["sizeLimit"] == "128Mi"
        containers = pod.get("initContainers", []) + pod["containers"]
        assert {container["name"] for container in containers} == {
            "preserve-native-oidc",
            "require-existing-wiki",
            "wiki",
        }
        for container in containers:
            assert container["securityContext"]["readOnlyRootFilesystem"] is True
            assert any(
                mount["name"] == "tmp"
                for mount in container.get("volumeMounts", [])
            )
            assert "cpu" in container["resources"]["requests"]
            assert "memory" in container["resources"]["requests"]
            assert "cpu" in container["resources"]["limits"]
            assert "memory" in container["resources"]["limits"]
        wiki = next(container for container in containers if container["name"] == "wiki")
        assert any(
            mount["name"] == "data" and mount["mountPath"] == "/data"
            for mount in wiki["volumeMounts"]
        )
        assert wiki["envFrom"] == [
            {"secretRef": {"name": "socrat-authentik-wiki"}},
            {"secretRef": {"name": "wiki-postgres"}},
        ]


if __name__ == "__main__":
    unittest.main()
