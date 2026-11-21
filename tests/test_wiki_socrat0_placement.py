"""Tests for the socrat0 wiki placement rules."""

from pathlib import Path
import shutil
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class WikiCurrentPlacementTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
