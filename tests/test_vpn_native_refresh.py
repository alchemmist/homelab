from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]

def test_refresh_is_stage_first_and_promotion_is_explicit():
    s=(ROOT/'ansible/playbooks/vpn-native-image-refresh.yml').read_text();yaml.safe_load(s)
    assert 'default("stage")' in s
    assert 'vpn_native_refresh_confirmed | default(false)' in s
    assert 'Existing candidate/attempt' in s
    assert 'smoke_test.py --runtime-root' in s
    assert 'state: restarted' not in s and 'state: stopped' not in s

def test_promotion_preserves_old_image_and_never_manages_services():
    s=(ROOT/'scripts/vpn-native-image-promote.py').read_text()
    assert 'fcntl.LOCK_EX|fcntl.LOCK_NB' in s
    assert "proof['cleanup_verified']" in s
    assert 'core==running_core()' in s
    assert 'libc.renameat2' in s
    assert "'state':'intent'" in s
    assert "assert not RECEIPT.exists()" in s
    assert 'os.fsync' in s
    for forbidden in ["'stop'","'start'","'restart'","'tick'","'activate'","'failback'"]:
        assert forbidden not in s

def test_isolated_smoke_copies_db_and_never_promotes_it():
    s=(ROOT/'ansible/roles/vpn_failover/files/smoke_test.py').read_text()
    assert "source.as_uri() + '?mode=ro'" in s
    assert 'runtime_root / name' in s
    assert "runtime_root / '.isolated-smoke-accepted.json'" in s
    assert 'cleanup_verified=True' in s
    assert s.index("receipt = runtime_root") > s.index('if cleanup_errors:')
