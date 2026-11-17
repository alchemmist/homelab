"""Offline Harbor configuration contracts for TLS, registration, storage, and edge routing."""

import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


class HarborConfigurationTests(unittest.TestCase):
    """Load Harbor values and check the published configuration pins."""

    def setUp(self):
        self.v = yaml.safe_load((ROOT / "deploy/harbor/values.yaml").read_text())

    def test_public_tls_and_no_default_admin_password(self) -> None:
        """Require the public Harbor URL, Traefik TLS secret, and no default passwords."""
        self.assertEqual(self.v["externalURL"], "https://harbor.socrat.alchemmist.xyz")
        self.assertEqual(self.v["expose"]["tls"]["certSource"], "secret")
        self.assertEqual(self.v["expose"]["ingress"]["className"], "traefik")
        self.assertNotIn("harborAdminPassword", self.v)
        self.assertNotIn("password", self.v["database"]["internal"])

    def test_private_registration(self) -> None:
        """Require self-registration to stay closed and project creation admin-only."""
        import json

        cfg = json.loads(self.v["core"]["extraEnvVars"][0]["value"])
        self.assertFalse(cfg["self_registration"])
        self.assertEqual(cfg["project_creation_restriction"], "adminonly")

    def test_local_persistent_storage_and_small_baseline(self) -> None:
        """Require local-path retention on socrat-0 and leave Trivy disabled."""
        self.assertEqual(self.v["persistence"]["resourcePolicy"], "keep")
        for claim in self.v["persistence"]["persistentVolumeClaim"].values():
            self.assertEqual(claim["storageClass"], "local-path")
        self.assertFalse(self.v["trivy"]["enabled"])
        for name in ["portal", "core", "jobservice", "registry"]:
            self.assertEqual(self.v[name]["nodeSelector"]["kubernetes.io/hostname"], "socrat-0")

    def test_edge_includes_harbor(self) -> None:
        """Require the edge chart to watch the Harbor namespace."""
        edge = yaml.safe_load((ROOT / "charts/traefik-edge/values.yaml").read_text())
        self.assertIn("harbor", edge["watchNamespaces"])


if __name__ == "__main__":
    unittest.main()
