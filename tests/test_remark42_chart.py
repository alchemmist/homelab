"""Offline contract checks for the Remark42 chart's pod behavior."""

import subprocess
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class Remark42ChartRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rendered = subprocess.run(
            ["helm", "template", "remark42", str(ROOT / "charts/remark42"), "--namespace", "remark42"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        cls.objects = [obj for obj in yaml.safe_load_all(rendered) if obj]

    def test_deployment_health_and_service_account_contract(self):
        deployment = next(obj for obj in self.objects if obj["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        self.assertFalse(pod["automountServiceAccountToken"])
        container = pod["containers"][0]
        for name in ("livenessProbe", "readinessProbe"):
            probe = container[name]
            self.assertEqual(probe["httpGet"], {"path": "/ping", "port": "http"})
        self.assertEqual(pod["hostNetwork"], True)
        self.assertEqual(pod["nodeSelector"]["kubernetes.io/hostname"], "socrat-2")

    def test_existing_data_and_service_contract_remains_intact(self):
        deployment = next(obj for obj in self.objects if obj["kind"] == "Deployment")
        pod = deployment["spec"]["template"]["spec"]
        container = pod["containers"][0]
        self.assertEqual(pod["volumes"][0]["hostPath"], {"path": "/srv/remark42", "type": "Directory"})
        self.assertEqual(
            [(mount["mountPath"], mount["subPath"]) for mount in container["volumeMounts"]],
            [("/srv/var", "data"), ("/srv/web/remark.css", "remark42/custom.css")],
        )
        service = next(obj for obj in self.objects if obj["kind"] == "Service")
        self.assertEqual(service["spec"]["selector"], {"app": "remark42"})
        self.assertEqual(service["spec"]["ports"][0]["targetPort"], "http")


if __name__ == "__main__":
    unittest.main()
