"""Offline contracts for the socrat-5 management move and Rancher provenance."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
INSERT = (
    "{{- with .Values.hostAliases }}\n      hostAliases:\n{{ toYaml . | indent 8 }}\n{{- end }}\n"
)
SUFFIX = (
    "\n# Scoped native issuer route; empty keeps upstream default rendering.\nhostAliases: []\n"
)


class ManagementMove(unittest.TestCase):
    """Keep controller placement, Rancher source, and upstream bytes unchanged."""

    def test_controller_only_placement(self) -> None:
        """Pin the controller to socrat-5 and the rest of Argo CD to socrat-0."""
        v = yaml.safe_load((ROOT / "deploy/platform/argo-cd/values.yaml").read_text())
        self.assertEqual(v["controller"]["nodeSelector"]["kubernetes.io/hostname"], "socrat-5")
        self.assertEqual(v["global"]["nodeSelector"]["kubernetes.io/hostname"], "socrat-0")
        self.assertEqual(v["controller"]["replicas"], 1)
        self.assertEqual(v["controller"]["resources"]["limits"]["memory"], "2Gi")
        app = yaml.safe_load((ROOT / "deploy/argocd/apps/argo-cd.yaml").read_text())
        self.assertEqual(app["spec"]["sources"][0]["targetRevision"], "10.11.6")

    def test_exact_rancher_source_native_route_and_security(self) -> None:
        """Require the pinned Rancher chart, native route, and verified TLS bundle."""
        chart = yaml.safe_load((ROOT / "charts/rancher/Chart.yaml").read_text())
        self.assertEqual(chart["version"], "2.15.2")
        self.assertEqual(chart["appVersion"], "v2.15.2")
        v = yaml.safe_load((ROOT / "deploy/platform/rancher/values.yaml").read_text())
        self.assertEqual(v["replicas"], 1)
        self.assertEqual(v["antiAffinity"], "preferred")
        self.assertEqual(v["extraNodeSelectorTerms"][0]["values"], ["socrat-5"])
        self.assertEqual(
            v["hostAliases"], [{"ip": "10.43.218.222", "hostnames": ["auth.socrat.alchemmist.xyz"]}]
        )
        self.assertEqual(
            v["extraEnv"],
            [{"name": "SSL_CERT_FILE", "value": "/var/lib/ca-certificates/ca-bundle.pem"}],
        )
        self.assertNotIn("CATTLE_INSECURE_SKIP_VERIFY", str(v))
        a = yaml.safe_load((ROOT / "deploy/argocd/apps/rancher.yaml").read_text())
        self.assertEqual(a["spec"]["sources"][0]["path"], "charts/rancher")
        self.assertFalse(a["spec"]["syncPolicy"]["automated"]["prune"])

    def upstream(self, target: Path) -> None:
        """Check every vendored Rancher file against its recorded upstream digest."""
        src = ROOT / "charts/rancher"
        for name, digest in json.loads((src / "UPSTREAM-SHA256.json").read_text()).items():
            data = (src / name).read_bytes()
            if name == "templates/deployment.yaml":
                self.assertEqual(data.decode().count(INSERT), 1)
                data = data.decode().replace(INSERT, "").encode()
            elif name == "values.yaml":
                self.assertTrue(data.decode().endswith(SUFFIX))
                data = data[: -len(SUFFIX.encode())]
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest, name)
            p = target / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def test_complete_upstream_provenance(self) -> None:
        """Require the full upstream digest set, not a sampled subset."""
        with tempfile.TemporaryDirectory() as d:
            self.upstream(Path(d))

    @unittest.skipUnless(shutil.which("helm"), "helm needed for render equivalence")
    def test_empty_alias_defaults_byte_identical_to_upstream(self) -> None:
        """Show empty host alias defaults render the same bytes as upstream."""
        with tempfile.TemporaryDirectory() as d:
            self.upstream(Path(d))

            def render(path: str | Path) -> bytes:
                """Render one local chart with the pinned Helm template arguments."""
                return subprocess.check_output(
                    [
                        "helm",
                        "template",
                        "rancher",
                        str(path),
                        "-n",
                        "cattle-system",
                        "--kube-version",
                        "1.36.5",
                    ]
                )

            self.assertEqual(render(d), render(ROOT / "charts/rancher"))

    def test_ansible_cannot_resurrect_unpatched_upstream_chart(self) -> None:
        """Keep the placement role on annotation, not a Helm upgrade or pod patch."""
        tasks = (ROOT / "ansible/roles/rancher_placement/tasks/main.yml").read_text()
        self.assertNotIn(
            "--reuse-values",
            "\n".join(l for l in tasks.splitlines() if not l.lstrip().startswith("#")),
        )
        self.assertNotIn("helm upgrade", tasks)
        self.assertIn("get application rancher", tasks)
        self.assertIn("annotate application rancher", tasks)
        self.assertNotIn("patch deployment", tasks)
        role = yaml.safe_load(
            (ROOT / "ansible/roles/rancher_placement/defaults/main.yml").read_text()
        )
        self.assertEqual(role["rancher_placement_nodes"], ["socrat-5"])


if __name__ == "__main__":
    unittest.main()
