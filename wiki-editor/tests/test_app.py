import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('editor', Path(__file__).parents[1] / 'app.py')
editor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(editor)


def run(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL, text=True).strip()


class EditorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        self.seed = self.root / 'seed'
        subprocess.run(['git', 'clone', str(self.remote), str(self.seed)], check=True, capture_output=True)
        run(self.seed, 'checkout', '-b', 'main')
        run(self.seed, 'config', 'user.name', 'Test')
        run(self.seed, 'config', 'user.email', 'test@example.com')
        content = self.seed / 'wiki/content'
        content.mkdir(parents=True)
        (content / '_index.md').write_text('---\ntitle: Home\nweight: 7\ncustom:\n  keep: yes\n---\n\nOriginal\n')
        run(self.seed, 'add', '.')
        run(self.seed, 'commit', '-m', 'initial')
        run(self.seed, 'push', 'origin', 'main')
        editor.WORK = self.root / 'work'
        editor.REPO = str(self.remote)
        editor.SESSIONS.clear()
        editor.GATEWAY_TOKEN = 'test-gateway-token'
        self.client = TestClient(editor.app, base_url=editor.ORIGIN, headers={'X-Socrat-WG-Peer': '10.250.0.2', 'X-Socrat-Editor-Key': editor.GATEWAY_TOKEN})
        csrf = self.client.get('/api/editor/session').json()['csrf_token']
        self.headers = {'Origin': editor.ORIGIN, 'X-CSRF-Token': csrf}

    def tearDown(self):
        self.tmp.cleanup()

    def test_update_preserves_front_matter_and_conflict(self):
        page = self.client.get('/api/editor/pages', params={'path': '_index.md'}).json()
        page.update(title='Changed', body='New body')
        response = self.client.put('/api/editor/pages', json=page, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('revision', response.json())
        text = (editor.WORK / 'wiki/content/_index.md').read_text()
        self.assertIn('weight: 7', text)
        self.assertIn('keep: yes', text)
        self.assertEqual(self.client.put('/api/editor/pages', json=page, headers=self.headers).status_code, 409)

    def test_access_and_csrf(self):
        self.assertEqual(self.client.get('/api/editor/session', headers={'X-Socrat-Editor-Key': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.get('/api/editor/session', headers={'X-Socrat-WG-Peer': '192.168.1.2'}).status_code, 403)
        self.assertEqual(self.client.post('/api/editor/preview', json={'title': 'Title', 'body': 'Body'}).status_code, 403)
        bad = dict(self.headers, Origin='https://evil.example')
        self.assertEqual(self.client.post('/api/editor/preview', json={'title': 'Title', 'body': 'Body'}, headers=bad).status_code, 403)
        self.assertEqual(self.client.post('/api/editor/preview', json={'title': 'Title', 'body': 'Body'}, headers=dict(self.headers, **{'X-Socrat-WG-Peer': '10.250.0.3'})).status_code, 403)

    def test_paths_and_symlinks(self):
        for path in ('../secret.md', '/etc/passwd.md', 'a/../../x.md', 'a\\b.md'):
            self.assertEqual(self.client.get('/api/editor/pages', params={'path': path}).status_code, 400)
        editor.sync()
        (editor.WORK / 'wiki/content/link.md').symlink_to('/etc/passwd')
        with self.assertRaises(editor.HTTPException):
            editor.checked_path('link.md')

    def test_create_and_preview(self):
        data = {'section': '', 'slug': 'new-page', 'title': 'New', 'body': '<script>alert(1)</script>\n\n# Hello'}
        response = self.client.post('/api/editor/pages', json=data, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post('/api/editor/pages', json=data, headers=self.headers).status_code, 409)
        preview = self.client.post('/api/editor/preview', json=data, headers=self.headers).json()
        self.assertNotIn('<script>', preview['html'])
        self.assertIn('<h1 id="hello">Hello</h1>', preview['html'])
        self.assertTrue(preview['approximate'])

    def test_preview_resolves_relative_root_and_fragment_references(self):
        editor.sync()
        content = editor.WORK / 'wiki/content'
        (content / 'start').mkdir()
        (content / 'start/other.md').write_text('---\ntitle: Other\n---\nOther')
        body = "[Relative]({{< relref 'other.md#hello' >}})\n\n[Root]({{< relref \"/_index.md#root\" >}})\n\n[Self]({{< relref \"#own\" >}})"
        response = self.client.post('/api/editor/preview', json={'title': 'Test', 'path': 'start/test.md', 'body': body}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        html = response.json()['html']
        self.assertIn('href="' + editor.ORIGIN + '/start/other/#hello"', html)
        self.assertIn('href="' + editor.ORIGIN + '/#root"', html)
        self.assertIn('href="#own"', html)

    def test_preview_heading_anchors_and_unsafe_content(self):
        body = '## Привет **мир**!\n\n## Привет **мир**!\n\n<script>alert(1)</script>\n\n[Bad](javascript:alert(1))'
        response = self.client.post('/api/editor/preview', json={'title': 'Test', 'body': body}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        html = response.json()['html']
        self.assertIn('id="привет-мир"', html)
        self.assertIn('id="привет-мир-1"', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('href="javascript:', html)

    def test_unrelated_push_race_retries(self):
        page = self.client.get('/api/editor/pages', params={'path': '_index.md'}).json()
        page['body'] = 'Saved despite race'
        original = editor.git
        raced = False
        def concurrent_git(*args, **kwargs):
            nonlocal raced
            if args[0] == 'push' and not raced:
                raced = True
                (self.seed / 'other.txt').write_text('Concurrent change')
                run(self.seed, 'add', '.')
                run(self.seed, 'commit', '-m', 'concurrent change')
                run(self.seed, 'push', 'origin', 'main')
            return original(*args, **kwargs)
        with patch.object(editor, 'git', concurrent_git):
            response = self.client.put('/api/editor/pages', json=page, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((editor.WORK / 'other.txt').read_text(), 'Concurrent change')

    def test_push_rejection_is_unavailable(self):
        page = self.client.get('/api/editor/pages', params={'path': '_index.md'}).json()
        page['body'] = 'My edit'
        original = editor.git
        def reject(*args, **kwargs):
            if args[0] == 'push':
                raise RuntimeError('Rejected')
            return original(*args, **kwargs)
        with patch.object(editor, 'git', reject):
            response = self.client.put('/api/editor/pages', json=page, headers=self.headers)
        self.assertEqual(response.status_code, 503)

    def test_push_lost_ack_is_success(self):
        page = self.client.get('/api/editor/pages', params={'path': '_index.md'}).json()
        page['body'] = 'Accepted remotely'
        original = editor.git
        def lost_ack(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[0] == 'push':
                raise RuntimeError('Lost acknowledgement')
            return result
        with patch.object(editor, 'git', lost_ack):
            response = self.client.put('/api/editor/pages', json=page, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['commit'], run(editor.WORK, 'rev-parse', 'origin/main'))

    def test_git_timeout_is_runtime_error(self):
        with patch.object(editor.subprocess, 'run', side_effect=subprocess.TimeoutExpired('git', 90)):
            with self.assertRaises(RuntimeError):
                editor.git('fetch', 'origin')

    def test_same_page_push_race_conflicts(self):
        page = self.client.get('/api/editor/pages', params={'path': '_index.md'}).json()
        page['body'] = 'My edit'
        original = editor.git
        raced = False
        def concurrent_git(*args, **kwargs):
            nonlocal raced
            if args[0] == 'push' and not raced:
                raced = True
                (self.seed / 'wiki/content/_index.md').write_text('---\ntitle: Other\n---\n\nTheir edit')
                run(self.seed, 'add', '.')
                run(self.seed, 'commit', '-m', 'concurrent page change')
                run(self.seed, 'push', 'origin', 'main')
            return original(*args, **kwargs)
        with patch.object(editor, 'git', concurrent_git):
            response = self.client.put('/api/editor/pages', json=page, headers=self.headers)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('Their edit', (editor.WORK / 'wiki/content/_index.md').read_text())


if __name__ == '__main__':
    unittest.main()
