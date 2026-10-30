from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('helm'), 'helm is required')
class CatsImageTest(unittest.TestCase):
    def render(self, *args):
        return subprocess.check_output(
            ['helm', 'template', 'cats', str(ROOT / 'charts/cats'), *args], text=True)

    def test_default_image_is_immutable_and_cacheable(self):
        manifest = self.render()
        self.assertIn('image: alchemmist/cats@sha256:a85ce9a2ade6edad537e920303b171c8a7dd5c60ce072edf981ff2fe4b52b4b8', manifest)
        self.assertIn('imagePullPolicy: IfNotPresent', manifest)
        self.assertNotIn('image: alchemmist/cats:latest', manifest)

    def test_empty_digest_preserves_explicit_tag_support(self):
        manifest = self.render('--set', 'image.digest=', '--set', 'image.tag=test-version')
        self.assertIn('image: alchemmist/cats:test-version', manifest)


if __name__ == '__main__':
    unittest.main()
