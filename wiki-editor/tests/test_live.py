import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parents[1]))


def command(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


class LiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.template = self.root / 'template'
        (self.template / 'content').mkdir(parents=True)
        (self.template / 'content/_index.md').write_text('---\ntitle: Home\n---\n\nInitial\n')
        self.env = patch.dict(os.environ, LIVE_MODE='1', LIVE_STATE_DIR=str(self.root / 'live'), LIVE_TEMPLATE_DIR=str(self.template), WORK_DIR=str(self.root / 'work'))
        self.env.start()
        spec = importlib.util.spec_from_file_location('live_editor_test', Path(__file__).parents[1] / 'app.py')
        self.api = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.api
        spec.loader.exec_module(self.api)
        self.live = self.api.LIVE
        self.real_build = type(self.live).build
        self.build_patch = patch.object(type(self.live), 'build', lambda live, destination: self.build(live, destination))
        self.build_patch.start()
        self.live.initialize()
        self.api.GATEWAY_TOKEN = 'gateway'
        self.client = TestClient(self.api.app, base_url=self.api.ORIGIN, headers={'X-Socrat-WG-Peer': '10.250.0.2', 'X-Socrat-Editor-Key': 'gateway'})
        csrf = self.client.get('/api/editor/session').json()['csrf_token']
        self.headers = {'Origin': self.api.ORIGIN, 'X-CSRF-Token': csrf}

    def build(self, live, destination):
        (destination / 'public').mkdir()
        (destination / 'public/index.html').write_text((self.api.WORK / 'wiki/content/_index.md').read_text())

    def tearDown(self):
        self.build_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def page(self):
        return self.client.get('/api/editor/pages', params={'path': '_index.md'}).json()

    def update(self, body='Changed'):
        return self.client.post('/api/editor/batch', json={'pages': [dict(self.page(), body=body)]}, headers=self.headers)

    def make_remote(self):
        remote = self.root / 'origin.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        command(self.api.WORK, 'push', str(remote), 'HEAD:refs/heads/main')
        self.api.REPO = str(remote)
        return remote

    def test_publish_without_network_and_restart(self):
        raw = self.api.raw_git
        def offline(*args, **kwargs):
            self.assertNotIn(args[0], ('fetch', 'clone', 'push'))
            return raw(*args, **kwargs)
        with patch.object(self.api, 'raw_git', side_effect=offline):
            result = self.update()
            self.assertEqual(result.status_code, 200, result.text)
            self.assertIn('Changed', self.client.get('/site/').text)
            self.assertEqual(self.page()['body'], 'Changed')
            self.live.started = False
            self.live.initialize()
            self.assertEqual(self.page()['body'], 'Changed')
            self.assertEqual(len(self.live.pending()), 1)

    def test_batch_conflict_rolls_back_all(self):
        before = self.page()
        result = self.client.post('/api/editor/batch', json={'pages': [dict(before, body='Lost'), {'path': 'missing.md', 'title': 'Bad', 'body': 'Bad', 'revision': '0' * 40}]}, headers=self.headers)
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.page(), before)
        self.assertEqual(len(self.live.pending()), 0)
        self.assertNotIn('Lost', self.client.get('/site/').text)

    def test_failed_render_never_acknowledges_or_changes_content(self):
        before = self.page()
        with patch.object(self.live, 'build', side_effect=self.api.HTTPException(422, 'Broken link')):
            response = self.update()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.page(), before)
        self.assertFalse(self.live.pending())

    def test_git_conflict_preserves_live_and_remote(self):
        self.make_remote()
        self.live.synchronize()
        remote_page = self.live.remote / 'wiki/content/_index.md'
        remote_page.write_text('---\ntitle: Remote\n---\n\nRemote\n')
        command(self.live.remote, 'add', '.')
        command(self.live.remote, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'remote change')
        command(self.live.remote, 'push', 'origin', 'main')
        self.assertEqual(self.update('Local').status_code, 200)
        self.live.synchronize()
        self.assertEqual(self.page()['body'], 'Local')
        self.assertIn('Remote', remote_page.read_text())
        self.assertIn('Concurrent Git changes', self.live.pending()[0][1]['error'])

    def test_outbox_preserves_unrelated_files_and_exact_bytes(self):
        self.make_remote()
        self.live.synchronize()
        unrelated = self.live.remote / 'README.md'
        unrelated.write_text('External change')
        command(self.live.remote, 'add', '.')
        command(self.live.remote, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-m', 'other change')
        command(self.live.remote, 'push', 'origin', 'main')
        self.assertEqual(self.update('Exact trailing\n\n').status_code, 200)
        self.live.synchronize()
        self.assertEqual(unrelated.read_text(), 'External change')
        self.assertEqual((self.live.remote / 'wiki/content/_index.md').read_bytes(), (self.api.WORK / 'wiki/content/_index.md').read_bytes())
        self.assertFalse(self.live.pending())

    def test_public_site_does_not_expose_editor_or_sources(self):
        public = TestClient(self.api.app, base_url=self.api.ORIGIN)
        self.assertEqual(public.get('/site/').status_code, 200)
        self.assertEqual(public.get('/healthz').status_code, 200)
        self.assertEqual(public.get('/api/editor/pages?path=_index.md').status_code, 403)
        self.assertEqual(public.get('/site/.git/config').status_code, 404)
        self.assertEqual(public.post('/site/').status_code, 403)
        (self.live.current / 'public/leak').symlink_to(self.api.WORK / 'wiki/content/_index.md')
        self.assertEqual(public.get('/site/leak').status_code, 404)

    def test_multipage_publication_is_one_pending_patch(self):
        response = self.client.post('/api/editor/batch', json={'pages': [dict(self.page(), body='Home edit'), {'section': '', 'slug': 'second', 'title': 'Second', 'body': 'Second edit'}]}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['pages']), 2)
        self.assertEqual(len(self.live.pending()), 1)
        self.assertIn('Home edit', self.client.get('/site/').text)
        second = self.client.get('/api/editor/pages', params={'path': 'second.md'}).json()
        self.assertEqual(second['body'], 'Second edit')

    def test_new_template_renders_accepted_content_without_losing_outbox(self):
        self.assertEqual(self.update('Accepted').status_code, 200)
        previous = self.live.current.resolve()
        self.live.started = False
        def newer(destination):
            (destination / 'public').mkdir()
            (destination / 'public/index.html').write_text('New template: ' + (self.api.WORK / 'wiki/content/_index.md').read_text())
        with patch.object(self.live, 'build', side_effect=newer):
            self.live.initialize()
        self.assertNotEqual(previous, self.live.current.resolve())
        self.assertIn('New template:', self.client.get('/site/').text)
        self.assertIn('Accepted', self.client.get('/site/').text)
        self.assertEqual(len(self.live.pending()), 1)

    def test_lost_push_ack_is_idempotently_recovered(self):
        self.make_remote()
        self.live.synchronize()
        self.assertEqual(self.update('Accepted').status_code, 200)
        raw = self.api.raw_git
        def lost(*args, **kwargs):
            result = raw(*args, **kwargs)
            if args[0] == 'push':
                raise RuntimeError('Lost acknowledgment')
            return result
        with patch.object(self.api, 'raw_git', side_effect=lost):
            with self.assertRaises(RuntimeError):
                self.live.synchronize()
        self.assertEqual(len(self.live.pending()), 1)
        self.live.synchronize()
        self.assertFalse(self.live.pending())
        self.assertEqual(self.page()['body'], 'Accepted')

    def test_new_save_while_previous_push_runs_remains_pending(self):
        self.make_remote()
        self.live.synchronize()
        self.assertEqual(self.update('First').status_code, 200)
        raw = self.api.raw_git
        published = []
        def interleave(*args, **kwargs):
            result = raw(*args, **kwargs)
            if args[0] == 'push' and not published:
                published.append(True)
                self.assertEqual(self.update('Second').status_code, 200)
            return result
        with patch.object(self.api, 'raw_git', side_effect=interleave):
            self.live.synchronize()
        self.assertEqual(self.page()['body'], 'Second')
        self.assertEqual(len(self.live.pending()), 1)
        self.live.synchronize()
        self.assertFalse(self.live.pending())
        self.assertEqual(self.page()['body'], 'Second')

    def test_move_deletes_old_remote_path(self):
        self.make_remote()
        self.live.synchronize()
        page = self.client.post('/api/editor/pages', json={'section': '', 'slug': 'note', 'title': 'Note', 'body': 'Body'}, headers=self.headers)
        self.assertEqual(page.status_code, 200)
        tree = self.client.get('/api/editor/tree').json()
        folder = self.client.post('/api/editor/folders', json={'parent': '', 'slug': 'folder', 'title': 'Folder', 'revision': tree['revision']}, headers=self.headers)
        self.assertEqual(folder.status_code, 200, folder.text)
        self.live.synchronize()
        moved = self.client.post('/api/editor/move', json={'source': 'note.md', 'target_parent': 'folder', 'revision': folder.json()['revision']}, headers=self.headers)
        self.assertEqual(moved.status_code, 200, moved.text)
        self.live.synchronize()
        self.assertFalse((self.live.remote / 'wiki/content/note.md').exists())
        self.assertTrue((self.live.remote / 'wiki/content/folder/note.md').exists())

    def test_build_preserves_nested_theme_content_directory(self):
        partial = self.template / '_vendor/theme/layouts/partials/content/head.html'
        partial.parent.mkdir(parents=True)
        partial.write_text('Theme partial')
        destination = self.root / 'render-check'
        destination.mkdir()
        def render(args, **kwargs):
            source = Path(args[args.index('--source') + 1])
            self.assertEqual((source / '_vendor/theme/layouts/partials/content/head.html').read_text(), 'Theme partial')
            self.assertTrue((source / 'content/_index.md').is_file())
            (destination / 'public').mkdir()
            return subprocess.CompletedProcess(args, 0, '', '')
        with patch('live.subprocess.run', side_effect=render):
            self.real_build(self.live, destination)

    def test_restart_rebuilds_missing_generated_files_from_durable_content(self):
        response = self.update('Durably accepted')
        self.assertEqual(response.status_code, 200, response.text)
        publication = response.json()['commit']
        rendered = self.live.current / 'public'
        (rendered / 'index.html').write_text('Truncated')
        (rendered / 'version.json').unlink()
        self.live.started = False
        self.live.initialize()
        self.assertIn('Durably accepted', self.client.get('/site/').text)
        self.assertEqual(self.page()['body'], 'Durably accepted')
        self.assertEqual(self.client.get('/site/version.json').json()['source_sha'], publication)
        self.assertEqual(len(self.live.pending()), 1)
        self.assertEqual(self.live.pending()[0][1]['commit'], publication)
        shutil.rmtree(self.live.current / 'public')
        self.live.started = False
        self.live.initialize()
        self.assertIn('Durably accepted', self.client.get('/site/').text)
        self.assertEqual(len(self.live.pending()), 1)
