"""Offline exact SPI-only DNS addition across all ingress health combinations."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SPIOnlyDNSTests(unittest.TestCase):
    def test_only_spi_changes_for_all_four_health_states(self):
        new = load(ROOT / "scripts/public_dns_zone.py", "spi_zone")
        old = load(ROOT / "scripts/public_dns_zone.py", "previous_zone")
        old.FAILOVER.remove("spi.socrat")
        guard = load(ROOT / "scripts/spi-public-dns.py", "spi_guard")
        guard.delta(old, new)
        for home, vps in ((True, True), (True, False), (False, True), (False, False)):
            with self.subTest(home=home, vps=vps):
                before = old.render(123, home, vps).splitlines()
                after = new.render(123, home, vps).splitlines()
                self.assertEqual(
                    [r for r in after if not r.startswith("spi.socrat IN A ")], before
                )
                self.assertEqual(
                    [r for r in after if r.startswith("spi.socrat IN A ")],
                    ["spi.socrat IN A " + a for a in old.healthy_addresses(home, vps)],
                )
                self.assertNotIn("*.socrat", "\n".join(after))
        new.TTL += 1
        with self.assertRaisesRegex(RuntimeError, "Unrelated DNS record change"):
            guard.delta(old, new)


class DNSPreflightSafetyTests(unittest.TestCase):
    def test_loader_rejects_directories_and_symlinks(self):
        import tempfile

        guard = load(ROOT / "scripts/spi-public-dns.py", "safe_loader")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            renderer = base / "renderer.py"
            renderer.write_text("VALUE = 1\n")
            link = base / "linked.py"
            link.symlink_to(renderer)
            for path in (base, link):
                with (
                    self.subTest(path=path.name),
                    self.assertRaisesRegex(RuntimeError, "Unsafe renderer"),
                ):
                    guard.load(path, "invalid")

    def test_malformed_renderer_has_controlled_error(self):
        import tempfile

        guard = load(ROOT / "scripts/spi-public-dns.py", "syntax_guard")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "proposed.py"
            for content in ("def broken(:", 'raise ValueError("private diagnostic")'):
                path.write_text(content)
                with (
                    self.subTest(content=content),
                    self.assertRaisesRegex(
                        RuntimeError, "^Invalid DNS renderer: proposed.py$"
                    ),
                ):
                    guard.load(path, "malformed")

    def test_uncertain_marker_is_checked_after_lock_acquisition(self):
        import tempfile
        from unittest.mock import Mock, patch

        guard = load(ROOT / "scripts/spi-public-dns.py", "lock_guard")
        require = guard.require
        previous_umask = guard.os.umask(0o077)
        self.addCleanup(guard.os.umask, previous_umask)

        def fixture_permissions(ok, message):
            # Fixture files are user-owned; retain every non-ownership safety check.
            if message not in ("Unsafe renderer", "Unsafe state directory"):
                require(ok, message)

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            current = base / "current.py"
            current.write_text("VALUE = 1\n")
            (base / "proposed.py").write_text("VALUE = 2\n")

            def acquired(fd, operation):
                self.assertEqual(operation, guard.fcntl.LOCK_EX)
                # Simulate a prior writer leaving an uncertain marker before releasing its lock.
                (base / "uncertain.json").write_text("{}")

            loader = Mock()
            with (
                patch.object(guard, "CURRENT", current),
                patch.object(guard, "ROOT", base),
                patch.object(guard, "require", side_effect=fixture_permissions),
                patch.object(guard.fcntl, "flock", side_effect=acquired),
                patch.object(guard, "load", loader),
                patch("sys.argv", ["spi-public-dns"]),
                self.assertRaisesRegex(RuntimeError, "Uncertain prior write"),
            ):
                guard.main()
            loader.assert_not_called()
            self.assertFalse((base / "before.py").exists())
            self.assertEqual(current.read_text(), "VALUE = 1\n")

    def test_missing_state_directory_has_controlled_stop(self):
        import tempfile
        from unittest.mock import patch

        guard = load(ROOT / "scripts/spi-public-dns.py", "missing_state_guard")
        previous = guard.os.umask(0o077)
        self.addCleanup(guard.os.umask, previous)
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            with (
                patch.object(guard, "ROOT", missing),
                patch("sys.argv", ["spi-public-dns"]),
                self.assertRaisesRegex(RuntimeError, "Unsafe state directory"),
            ):
                guard.main()
            self.assertFalse(missing.exists())
