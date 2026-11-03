import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/wiki_openapi'))
from engine import spec_changed, select_closable, page_ok, UnsafeInput
from stages import stage

SHA = 'a'*40
BEFORE = 'b'*40

class Bot:
    def __init__(self, files):
        self._files = files
        self.calls = 0
    def files(self, before, after):
        self.calls += 1
        return self._files
    def text(self, sha, path):
        if path.endswith('openapi.yaml'):
            return 'openapi: 3.0.3\ninfo:\n  title: x\npaths:\n  /v1/messages:\n    post:\n      summary: Send\n      responses:\n        "200":\n          description: ok\ncomponents:\n  schemas: {}\n'
        return Path('/Users/antonmoss/code/socrat-bot/scripts/render_wiki.py').read_text()

class Lab:
    def __init__(self):
        self.closed = []
        self.page = 'old'
    def read_page(self, ref='main'):
        return self.page, 'blob'
    def propose(self, after, markdown):
        self.written = markdown
        return {'status': 'created', 'number': 9, 'url': 'https://github.com/alchemmist/homelab/pull/9'}
    def automation_prs(self, keep):
        return [{'number': 4, 'title': 'docs: refresh Socrat Bot wiki page', 'body': '<!-- wiki-openapi-refresh -->', 'url': 'u'}]
    def close(self, number, survivor):
        self.closed.append((number, survivor))

class Flow(unittest.TestCase):
    def test_ignores_other_branches_without_github(self):
        bot = Bot([{'filename': 'openapi.yaml'}])
        self.assertEqual(stage('check', {'ref': 'refs/heads/dev', 'before': BEFORE, 'after': SHA}, bot=bot), [])
        self.assertEqual(bot.calls, 0)

    def test_ignores_push_that_does_not_touch_the_spec(self):
        event = {'ref': 'refs/heads/main', 'before': BEFORE, 'after': SHA}
        self.assertFalse(spec_changed(event, [{'filename': 'README.md'}]))
        self.assertEqual(stage('check', event, bot=Bot([{'filename': 'README.md'}])), [])

    def test_render_and_pr_and_close(self):
        event = {'ref': 'refs/heads/main', 'before': BEFORE, 'after': SHA}
        checked = stage('check', event, bot=Bot([{'filename': 'openapi.yaml'}]))
        rendered = stage('render', checked[0], bot=Bot([]))
        self.assertIn('POST /v1/messages', rendered[0]['markdown'])
        page_ok(rendered[0]['markdown'])
        lab = Lab()
        created = stage('create-pr', rendered[0], homelab=lab, write=True)
        self.assertEqual(created[0]['number'], 9)
        def decide(prompt, data):
            self.assertEqual(data['candidates'][0]['number'], 4)
            return {'close': [4, 9, 99]}
        done = stage('close-older', created[0], homelab=lab, call_model=decide, write=True)
        self.assertEqual(lab.closed, [(4, 9)])
        self.assertEqual(done[0]['closed'], [4])

    def test_model_cannot_close_unlisted_prs(self):
        self.assertEqual(select_closable({'close': [3, '4']}, [{'number': 3}], None), [3])

    def test_dry_run_does_not_close(self):
        lab = Lab()
        self.assertEqual(stage('close-older', {'status': 'dry_run', 'after': SHA}, homelab=lab, write=False), [])
        self.assertEqual(lab.closed, [])

    def test_bad_page_rejected(self):
        with self.assertRaises(UnsafeInput):
            page_ok('hello')

if __name__ == '__main__':
    unittest.main()
