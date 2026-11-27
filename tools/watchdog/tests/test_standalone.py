"""Exercise a detached installation without the repository or Ansible."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class StandaloneTests(unittest.TestCase):
    def test_detached_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            src = base / "source"
            shutil.copytree(Path(__file__).resolve().parents[1], src)
            subprocess.run(
                ["make", "install", "DESTDIR=" + str(base / "image")],
                cwd=src,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            shutil.rmtree(src)
            cli = base / "image/usr/local/bin/homelab-watchdog"
            for args in (["--help"], ["server", "--help"], ["relay", "--help"]):
                result = subprocess.run(
                    [cli, *args],
                    cwd=base,
                    env={**os.environ, "PYTHONPATH": ""},
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
