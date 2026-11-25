"""Offline contract checks for the Remark42 chart's pod behavior."""

import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class Remark42ChartRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rendered = subprocess.run(
            [
                "helm",
                "template",
                "remark42",
                str(ROOT / "charts/remark42"),
                "--namespace",
                "remark42",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        cls.objects = [obj for obj in yaml.safe_load_all(rendered) if obj]

    def test_deployment_health_and_service_account_contract(self) -> None:
        deployment = next(obj for obj in self.objects if obj["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        assert not pod["automountServiceAccountToken"]
        container = next(item for item in pod["containers"] if item["name"] == "remark42")
        for name in ("livenessProbe", "readinessProbe"):
            probe = container[name]
            assert probe["httpGet"] == {"path": "/ping", "port": "http"}
        assert "hostNetwork" not in pod
        assert pod["nodeSelector"]["kubernetes.io/hostname"] == "socrat-1"
        env = {item["name"]: item["value"] for item in container["env"]}
        assert env["HTTPS_PROXY"] == "http://127.0.0.1:18443"
        assert env["NO_PROXY"] == "127.0.0.1,localhost"

    def test_existing_data_and_service_contract_remains_intact(self) -> None:
        deployment = next(obj for obj in self.objects if obj["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        container = next(item for item in pod["containers"] if item["name"] == "remark42")
        assert pod["volumes"][0]["persistentVolumeClaim"] == {"claimName": "remark42-data"}
        claim = next(obj for obj in self.objects if obj["kind"] == "PersistentVolumeClaim")
        assert claim["spec"]["storageClassName"] == "nfs-shared"
        assert claim["spec"]["accessModes"] == ["ReadWriteOnce"]
        assert [(mount["mountPath"], mount["subPath"]) for mount in container["volumeMounts"]] == [
            ("/srv/var", "data"),
            ("/srv/web/remark.css", "remark42/custom.css"),
        ]
        service = next(obj for obj in self.objects if obj["kind"] == "Service")
        assert service["spec"]["selector"] == {"app": "remark42"}
        assert service["spec"]["ports"][0]["targetPort"] == "http"


if __name__ == "__main__":
    unittest.main()
