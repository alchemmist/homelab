import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/blog_updates'))
from github import GitHub
from engine import UnsafeInput

class Fake(GitHub):
    def __init__(self,existing=None,main=None):
        self.calls=[];self.existing=existing or [];self.main=main or 'a'*40
    def api(self,method,path,body=None):
        self.calls.append((method,path,body))
        if path.startswith('pulls?'):return self.existing
        if path=='git/ref/heads/main':return {'object':{'sha':self.main}}
        if method=='POST' and path=='pulls':return {'html_url':'https://github.com/alchemmist/blog/pull/1'}
        return {}
    def read_updates(self,ref):return 'original','file-sha'

class WriterTests(unittest.TestCase):
    def test_closed_pr_not_reopened(self):
        g=Fake(existing=[{'html_url':'closed-pr','state':'closed'}])
        self.assertEqual(g.propose('a'*40,'new','why')['status'],'existing')
        self.assertTrue(all(c[0]=='GET' for c in g.calls))
    def test_advanced_main_refused(self):
        g=Fake(main='b'*40)
        with self.assertRaises(UnsafeInput):g.propose('a'*40,'new','why')
        self.assertTrue(all(c[0]=='GET' for c in g.calls))
    def test_only_updates_written(self):
        g=Fake();r=g.propose('a'*40,'new','why')
        self.assertEqual(r['status'],'created')
        writes=[c for c in g.calls if c[0]=='PUT']
        self.assertEqual([c[1] for c in writes],['contents/site/content/updates.md'])
        self.assertEqual(writes[0][2]['branch'],'automation/blog-updates-'+'a'*40)
        self.assertFalse(any('merge' in c[1] for c in g.calls))
    def test_no_change_no_branch(self):
        g=Fake();self.assertEqual(g.propose('a'*40,'original','why')['status'],'no_change')
        self.assertTrue(all(c[0]=='GET' for c in g.calls))
