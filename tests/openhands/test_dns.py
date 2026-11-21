"""The DNS addition may change only OpenHands' A records in all health states."""

import importlib.util
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "openhands_dns", ROOT / "scripts/openhands-public-dns.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def renderer(source):
    module = types.ModuleType("renderer_fixture")
    exec(compile(source, "<renderer fixture>", "exec"), module.__dict__)
    return module


class DNSDelta(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "scripts/public_dns_zone.py").read_text()
        self.before = self.source.replace('    "openhands.socrat",\n', "")

    def test_exact_addition_all_health_states(self):
        guard.delta(renderer(self.before), renderer(self.source))

    def test_unrelated_record_rejected(self):
        with self.assertRaises(RuntimeError):
            guard.delta(
                renderer(self.before),
                renderer(self.source.replace('    "www",', '    "wrong-www",')),
            )

    def test_changed_entrance_rejected(self):
        with self.assertRaises(RuntimeError):
            guard.delta(
                renderer(self.before),
                renderer(self.source.replace("109.173.40.247", "203.0.113.1")),
            )

    def test_missing_new_record_rejected(self):
        with self.assertRaises(RuntimeError):
            guard.delta(renderer(self.before), renderer(self.before))


if __name__ == "__main__":
    unittest.main()
