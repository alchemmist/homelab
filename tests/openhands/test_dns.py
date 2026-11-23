"""The DNS addition may change only OpenHands' A records in all health states."""

import importlib.util
import types
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "openhands_dns", ROOT / "ansible/scripts/openhands-public-dns.py"
)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def renderer(source):
    """Run renderer."""
    module = types.ModuleType("renderer_fixture")
    exec(compile(source, "<renderer fixture>", "exec"), module.__dict__)
    return module


class DNSDelta(unittest.TestCase):
    """Tests for OpenHands DNS record changes."""

    def setUp(self) -> None:
        """Load the rendered DNS zone sources."""
        self.source = (ROOT / "ansible/scripts/public_dns_zone.py").read_text()
        self.before = self.source.replace('    "openhands.socrat",\n', "")

    def test_exact_addition_all_health_states(self) -> None:
        """Verify the draft adds exactly one record for every health state."""
        guard.delta(renderer(self.before), renderer(self.source))

    def test_unrelated_record_rejected(self) -> None:
        """Verify any unrelated record change is rejected."""
        with pytest.raises(RuntimeError):
            guard.delta(
                renderer(self.before),
                renderer(self.source.replace('    "www",', '    "wrong-www",')),
            )

    def test_changed_entrance_rejected(self) -> None:
        """Verify changes to the entrance record are rejected."""
        with pytest.raises(RuntimeError):
            guard.delta(
                renderer(self.before),
                renderer(self.source.replace("109.173.40.247", "203.0.113.1")),
            )

    def test_missing_new_record_rejected(self) -> None:
        """Verify omitting the new record from the draft is rejected."""
        with pytest.raises(RuntimeError):
            guard.delta(renderer(self.before), renderer(self.before))


if __name__ == "__main__":
    unittest.main()
