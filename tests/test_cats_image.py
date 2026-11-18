"""Offline helm-template checks for the cats chart image pin."""

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED_CATS_IMAGE = (
    "image: harbor.socrat.alchemmist.xyz/homelab/cats@sha256:"
    "af42b0edabcbbfa0541b6ee427ec8ba649ea7aa72429f7245f95c8dbfdb61a18"
)


@unittest.skipUnless(shutil.which("helm"), "helm is required")
class CatsImageTest(unittest.TestCase):
    """Verify the cats chart image pin and pull policy."""

    def render(self, *args: str) -> str:
        """Render the cats chart, forwarding extra helm arguments."""
        return subprocess.check_output(
            ["helm", "template", "cats", str(ROOT / "charts/cats"), *args],
            text=True,
        )

    def test_default_image_is_immutable_and_cacheable(self) -> None:
        """Require the digest pin, IfNotPresent, and no floating latest tag."""
        manifest = self.render()
        assert PINNED_CATS_IMAGE in manifest
        assert "imagePullPolicy: IfNotPresent" in manifest
        assert "image: alchemmist/cats:latest" not in manifest

    def test_empty_digest_preserves_explicit_tag_support(self) -> None:
        """Keep an explicit fallback tag when the digest is set empty."""
        manifest = self.render(
            "--set",
            "image.digest=",
            "--set",
            "image.fallback=alchemmist/cats:test-version",
        )
        assert "image: alchemmist/cats:test-version" in manifest


if __name__ == "__main__":
    unittest.main()
