from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class WishlistImages(unittest.TestCase):
    def test_private_resource_isolation_no_external_optimizer(self):
        source = (ROOT / "charts/wishlist/templates/image-optimizer.yaml").read_text()
        self.assertIn("if .Values.images.enabled", source)
        self.assertEqual(source.count('argocd.argoproj.io/sync-wave: "-1"'), 3)
        for value in [
            "type: ClusterIP",
            "kind: NetworkPolicy",
            "egress: []",
            "automountServiceAccountToken: false",
            "readOnlyRootFilesystem: true",
            "runAsNonRoot: true",
            "/opt/image-optimizer/server.cjs",
        ]:
            self.assertIn(value, source)
        self.assertNotIn("kind: Ingress", source)
        self.assertNotIn("hostPort:", source)
        self.assertNotIn("secretRef:", source)
        self.assertNotIn("persistentVolumeClaim:", source)
        self.assertIn("name.startsWith('wishlist-image-')", source)
        self.assertIn("postStart:", source)
        self.assertIn("sizeLimit: 4Gi", source)
        ingress = (ROOT / "charts/wishlist/templates/ingress.yaml").read_text()
        self.assertNotIn("optimizer", ingress)

    def test_app_image_and_same_namespace_only(self):
        source = (ROOT / "charts/wishlist/templates/image-optimizer.yaml").read_text()
        self.assertIn(".Values.image.digest", source)
        self.assertIn("app.kubernetes.io/name: {{ .Chart.Name }}", source)
        self.assertIn("app.kubernetes.io/instance: {{ .Release.Name }}", source)
        self.assertNotIn("namespaceSelector:", source)
        app = (ROOT / "charts/wishlist/templates/deployment.yaml").read_text()
        self.assertIn("IMAGE_OPTIMIZER_URL", app)
        self.assertIn("mountPath: /data/media-cache", app)
        self.assertIn(
            "      volumes:\n        - name: media-cache\n          emptyDir:\n            sizeLimit: 2Gi",
            app,
        )

    def test_native_memory_limit_no_application_job_semaphore(self):
        values = yaml.safe_load((ROOT / "charts/wishlist/values.yaml").read_text())["images"]
        self.assertEqual(values["optimizerPort"], 8081)
        self.assertEqual(values["resources"]["limits"]["memory"], "2Gi")
        self.assertEqual(values["resources"]["limits"]["ephemeral-storage"], "4Gi")
        self.assertNotIn("cpu", values["resources"]["limits"])
