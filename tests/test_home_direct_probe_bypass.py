"""Tests for the home direct probe bypass policy."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "egress", ROOT / "ansible/scripts/vpn-home-transit-egress.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_only_home0_local_probe_uid_tcp443_is_exempt() -> None:
    """Require only the home-0 local probe uid on tcp/443 to bypass DNAT."""
    with patch.object(m.socket, "gethostname", return_value="socrat-0"):
        new = m.rules()
    with patch.object(m.socket, "gethostname", return_value="socrat-1"):
        legacy = m.rules()
    bypass = (
        ' ip daddr 109.120.141.60 tcp dport 443 meta skuid 19091 '
        'counter return comment "homelab-direct-ip-probe"\n'
    )
    assert new.replace(bypass, "") == legacy == m.rules(direct_probe=False)
    assert new.count(bypass) == 1
    assert (
        new.index("chain output")
        < new.index(bypass)
        < new.index("tcp dport 53", new.index("chain output"))
    )
    assert "skuid" not in new.split("chain output")[0]


def test_cas_migration_preserves_receipts_and_rejects_unreviewed_drift() -> None:
    """Require the migration source to keep its receipt checks and refuse flush."""
    source = (ROOT / "ansible/scripts/vpn-home-transit-egress.py").read_text()
    assert "Not the reviewed legacy source" in source
    assert "Unrelated change: inspect" in source
    assert "Direct probe bypass must be the first output rule" in source
    assert "if receipt.exists():" in source
    assert "Unexpected inserted rule: inspect" in source
    assert "Existing attempt: inspect receipts, never replay" in source
    assert "delete table" not in source
    assert "flush ruleset" not in source
    assert RuntimeError.__name__ in source
