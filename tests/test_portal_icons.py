"""Icon metadata updates must not become provider or access reconciliation."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'ansible/roles/authentik/files/icons.py'
ASSETS = ROOT / 'assets/service-icons'
MANIFEST = json.loads((ASSETS / 'sources.json').read_text())


def targets():
    result = {}
    for filename, source in MANIFEST['files'].items():
        name = 'service-icons/' + Path(filename).stem + '-' + source['sha256'][:12] + '.svg'
        for slug in source.get('applications', [Path(filename).stem]):
            assert slug not in result
            result[slug] = name
    return result


def test_current_application_coverage_and_asset_checksums():
    mapping = targets()
    assert set(mapping) == {'grafana','harbor','rancher','open-webui','wiki',
                            'litellm','lms','argocd','netbird-pilot','spi-rustfs-native'}
    for filename, record in MANIFEST['files'].items():
        assert hashlib.sha256((ASSETS / filename).read_bytes()).hexdigest() == record['sha256']


class Response:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


class FakeAPI:
    def __init__(self):
        self.apps = {s: {'slug': s, 'pk': 'fixture-' + s, 'name': s, 'meta_icon': '',
                         'provider': 42, 'provider_obj': {'property_mappings': ['mapping-b', 'mapping-a']},
                         'policy_engine_mode': 'any', 'meta_hide': True,
                         'meta_launch_url': 'https://example.invalid/'} for s in targets()}
        self.apps['unmanaged'] = {'slug': 'unmanaged', 'pk': 'fixture-unmanaged', 'meta_icon': 'keep.svg'}
        self.patches = []
        self.files = []
        self.content = {}
        for filename, record in MANIFEST['files'].items():
            name = 'service-icons/' + Path(filename).stem + '-' + record['sha256'][:12] + '.svg'
            url = 'https://auth.socrat.alchemmist.xyz/files/media/public/' + name
            self.files.append({'name': name, 'url': url})
            self.content[url] = (ASSETS / filename).read_bytes()

    def __call__(self, request, timeout=None):
        if isinstance(request, str):
            # No API bearer token is sent when reading media.
            return Response(self.content[request])
        url = request.full_url
        path = urlsplit(url).path.split('/api/v3/', 1)[1]
        if path == 'admin/file/':
            assert request.get_method() == 'GET'
            return Response(self.files)
        if path == 'core/applications/':
            return Response({'pagination': {'total_pages': 1}, 'results': list(self.apps.values())})
        slug = path.removeprefix('core/applications/').strip('/')
        if request.get_method() == 'PATCH':
            payload = json.loads(request.data)
            assert set(payload) == {'meta_icon'}
            self.apps[slug].update(payload)
            self.patches.append(slug)
        detail = copy.deepcopy(self.apps[slug])
        if 'provider_obj' in detail:
            detail['provider_obj']['property_mappings'].reverse()
        return Response(detail)


def run(tmp_path, api, expected=None):
    shutil.copytree(ASSETS, tmp_path / 'service-icons')
    (tmp_path / 'credentials.json').write_text(json.dumps({'AUTHENTIK_BOOTSTRAP_TOKEN': 'fixture-only'}))
    argv = [str(SCRIPT), str(tmp_path)]
    if expected is not None:
        pin = tmp_path / 'expected.json'
        pin.write_text(json.dumps(expected))
        argv += ['--expected-inventory', str(pin)]
    with patch.object(sys, 'argv', argv), patch('urllib.request.urlopen', api):
        runpy.run_path(str(SCRIPT), run_name='__main__')


def test_updates_only_icons_and_keeps_unmanaged_app(tmp_path):
    api = FakeAPI()
    before = copy.deepcopy(api.apps)
    run(tmp_path, api, list(before.values()))
    assert len(api.patches) == 10
    for slug, app in api.apps.items():
        assert {k: v for k, v in app.items() if k != 'meta_icon'} == {
            k: v for k, v in before[slug].items() if k != 'meta_icon'}
    assert api.apps['unmanaged'] == before['unmanaged']
    assert not (tmp_path / 'portal-icons-uncertain.json').exists()
    assert len(list(tmp_path.glob('portal-icons-receipt-*.json'))) == 1


def test_reviewed_uid_mismatch_stops_before_any_patch(tmp_path):
    api = FakeAPI()
    expected = copy.deepcopy(list(api.apps.values()))
    expected[0]['pk'] = 'different-identity'
    with pytest.raises(RuntimeError, match='differs from reviewed audit'):
        run(tmp_path, api, expected)
    assert not api.patches
    assert not (tmp_path / 'portal-icons-uncertain.json').exists()


def test_uncertain_prior_run_cannot_be_replayed(tmp_path):
    api = FakeAPI()
    (tmp_path / 'portal-icons-uncertain.json').write_text('{}')
    with pytest.raises(RuntimeError, match='explicit receipt/state review'):
        run(tmp_path, api)
    assert not api.patches


def test_served_checksum_mismatch_leaves_review_marker(tmp_path):
    api = FakeAPI()
    api.content[next(iter(api.content))] = b'not-the-pinned-svg'
    with pytest.raises(RuntimeError, match='Served media checksum mismatch'):
        run(tmp_path, api)
    assert not api.patches
    assert (tmp_path / 'portal-icons-uncertain.json').exists()


def test_property_mapping_membership_change_is_not_ignored(tmp_path):
    api = FakeAPI()
    expected = copy.deepcopy(list(api.apps.values()))
    expected[0]['provider_obj']['property_mappings'].append('different-mapping')
    with pytest.raises(RuntimeError, match='differs from reviewed audit'):
        run(tmp_path, api, expected)
    assert not api.patches
