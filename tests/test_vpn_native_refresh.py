"""Source contracts for staged native VPN image refresh and isolated promotion."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
# Intent and accepted receipts each fsync the receipt parent directory.
RECEIPT_PARENT_DIRECTORY_OPENS = 2


def test_refresh_is_stage_first_and_promotion_is_explicit() -> None:
    """Require the default stage phase and an explicit confirmation to promote."""
    s = (ROOT / "ansible/playbooks/vpn-native-image-refresh.yml").read_text()
    yaml.safe_load(s)
    assert 'default("stage")' in s
    assert "vpn_native_refresh_confirmed | default(false)" in s
    assert "Existing candidate/attempt" in s
    assert "smoke_test.py --runtime-root" in s
    assert "state: restarted" not in s
    assert "state: stopped" not in s


def test_promotion_preserves_old_image_and_never_manages_services() -> None:
    """Require a locked exchange that preserves the old image and service lifecycle."""
    s = (ROOT / "scripts/vpn-native-image-promote.py").read_text()
    assert "fcntl.LOCK_EX|fcntl.LOCK_NB" in s
    assert "proof['cleanup_verified']" in s
    assert "core==running_core()" in s
    assert "libc.renameat2" in s
    assert "'state':'intent'" in s
    assert "assert not RECEIPT.exists()" in s
    assert "os.fsync" in s
    assert s.count("os.open(RECEIPT.parent,os.O_DIRECTORY)") == RECEIPT_PARENT_DIRECTORY_OPENS
    for forbidden in ["'stop'", "'start'", "'restart'", "'tick'", "'activate'", "'failback'"]:
        assert forbidden not in s


def test_isolated_smoke_copies_db_and_never_promotes_it() -> None:
    """Require isolated smoke to copy the database and accept only after cleanup."""
    s = (ROOT / "ansible/roles/vpn_failover/files/smoke_test.py").read_text()
    assert "source.as_uri() + '?mode=ro'" in s
    assert "runtime_root / name" in s
    assert "runtime_root / '.isolated-smoke-accepted.json'" in s
    assert "cleanup_verified=True" in s
    assert s.index("receipt = runtime_root") > s.index("if cleanup_errors:")
