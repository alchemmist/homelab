"""Offline foundation safety checks; not runtime acceptance."""

import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

RETENTION_MARKER_COUNT = 2
ROOT_SECRET_REF_COUNT = 2
READER_SECRET_REF_COUNT = 2


class Foundation(unittest.TestCase):
    def render(self, *args):
        return subprocess.check_output(
            ["helm", "template", "rustfs", str(ROOT / "charts/rustfs"), *args], text=True
        )

    def test_default_is_off(self):
        assert self.render().strip() == ""

    def test_retention_and_placement(self):
        text = self.render("--set", "enabled=true")
        assert text.count("Prune=false,Delete=false") == RETENTION_MARKER_COUNT
        assert "reclaimPolicy: Retain" in text
        assert "volumeBindingMode: WaitForFirstConsumer" in text
        assert "kubernetes.io/hostname: socrat-0" in text
        assert "nodeName:" not in text
        assert "storage: 20Gi" in text

    def test_no_exposure(self):
        text = self.render("--set", "enabled=true")
        assert "kind: Ingress" not in text
        assert "kind: Service\n" in text
        assert "ingress:\n    []" in text
        assert "egress: []" in text
        assert "automountServiceAccountToken: false" in text
        assert "runAsUser: 10001" in text
        assert "readOnlyRootFilesystem: true" in text
        assert "sha256:ed9210d6411d77ffceb70d94b964a3cb7d225983368bc25bebe01e995293dcc2" in text

    def test_protected_routes_and_secret_boundaries(self):
        text = self.render(
            "--set",
            "enabled=true",
            "--set",
            "oidc.enabled=true",
            "--set",
            "gateway.enabled=true",
            "--set",
            "browserRoutes.enabled=true",
            "--set",
            "authEgressCIDRs[0]=192.0.2.10/32",
            "--set",
            "gateway.image=example.invalid/reader@sha256:" + "a" * 64,
        )
        assert "RUSTFS_IDENTITY_OPENID_REDIRECT_URI_DYNAMIC" in text
        assert "RUSTFS_IDENTITY_OPENID_CLAIM_NAME, value: rustfs_policy" in text
        assert "ROLE_POLICY" not in text
        assert (
            "RUSTFS_CONSOLE_CORS_ALLOWED_ORIGINS, value: 'https://rustfs.socrat.alchemmist.xyz'"
            in text
        )
        assert "RUSTFS_CORS_ALLOWED_ORIGINS, value: ''" in text
        assert "kind: Secret" not in text
        assert "kind: Role" not in text
        assert "service: {name: rustfs-console-http" in text
        assert "service: {name: authentik-server" not in text
        assert "path: /outpost.goauthentik.io/" not in text
        assert "name: AUTH_URL" in text
        assert "nodePort:" not in text
        assert "type: LoadBalancer" not in text
        # Root is referenced by storage only; gateway has its isolated reader Secret.
        assert text.count("name: rustfs-root") == ROOT_SECRET_REF_COUNT
        assert text.count("name: rustfs-reader") == READER_SECRET_REF_COUNT
        assert "rustfs-writer" not in text
        assert "path: /health/ready" in text

    def test_activation_guards(self):
        for values in [
            ["--set", "gateway.enabled=true"],
            ["--set", "browserRoutes.enabled=true"],
            ["--set", "oidc.enabled=true", "--set", "authEgressCIDRs[0]=0.0.0.0/0"],
        ]:
            result = subprocess.run(
                [
                    "helm",
                    "template",
                    "rustfs",
                    str(ROOT / "charts/rustfs"),
                    "--set",
                    "enabled=true",
                    *values,
                ],
                capture_output=True,
            )
            assert result.returncode != 0

    def test_manual_app(self):
        text = (ROOT / "deploy/argocd/apps/rustfs.yaml").read_text()
        assert "automated:" not in text


if __name__ == "__main__":
    unittest.main()
