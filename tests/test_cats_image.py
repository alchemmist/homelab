"""Offline helm-template checks for the cats chart image pin."""

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("helm"), "helm is required")
class CatsImageTest(unittest.TestCase):
    """Verify the cats chart image pin and pull policy."""

    def render(self, *args):
        return subprocess.check_output(
            ["helm", "template", "cats", str(ROOT / "charts/cats"), *args], text=True
        )

    def test_default_image_is_immutable_and_cacheable(self) -> None:
        """Require the digest pin, IfNotPresent, and no floating latest tag."""
        manifest = self.render()
        self.assertIn(
            "image: harbor.socrat.alchemmist.xyz/homelab/cats@sha256:af42b0edabcbbfa0541b6ee427ec8ba649ea7aa72429f7245f95c8dbfdb61a18",
            manifest,
        )
        self.assertIn("imagePullPolicy: IfNotPresent", manifest)
        self.assertNotIn("image: alchemmist/cats:latest", manifest)

    def test_empty_digest_preserves_explicit_tag_support(self) -> None:
        """Keep an explicit fallback tag when the digest is set empty."""
        manifest = self.render(
            "--set", "image.digest=", "--set", "image.fallback=alchemmist/cats:test-version"
        )
        self.assertIn("image: alchemmist/cats:test-version", manifest)


if __name__ == "__main__":
    unittest.main()
