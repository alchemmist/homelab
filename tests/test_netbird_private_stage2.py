import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('stage2', Path(__file__).resolve().parents[1] / 'scripts/netbird-private-stage2.py')
stage2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage2)


def test_settings_schema_and_private_local_auth():
    body = stage2.settings_body({'settings': {'local_auth_disabled': False, 'embedded_idp_enabled': True, 'peer_expose_enabled': False}})
    assert body['settings']['jwt_allow_groups'] == ['netbird-pilot-login']
    assert body['settings']['peer_login_expiration'] == 28800
    assert 'local_auth_disabled' not in body['settings']
    assert body['settings']['peer_expose_enabled'] is False


def test_only_exact_native_default_can_be_deleted():
    rule = dict(action='accept', protocol='all', bidirectional=True, sources=[{'name': 'All'}], destinations=[{'name': 'All'}])
    policy = dict(id='exact-id', name='Default', enabled=True, rules=[rule])
    assert stage2.default_policy([policy]) == 'exact-id'
    with pytest.raises(ValueError):
        stage2.default_policy([policy, policy])
    rule['sources'] = [{'name': 'Other'}]
    with pytest.raises(ValueError):
        stage2.default_policy([policy])


def test_private_files_never_overwrite(tmp_path):
    path = tmp_path / 'secret.json'
    stage2.private(path, {'secret': 'fixture'})
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        stage2.private(path, {})
