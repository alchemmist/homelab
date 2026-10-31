import importlib.util
from pathlib import Path
import unittest
s=importlib.util.spec_from_file_location('engine', Path(__file__).resolve().parents[2]/'scripts/blog_updates/engine.py')
e=importlib.util.module_from_spec(s);s.loader.exec_module(e)

class EngineTests(unittest.TestCase):
    def test_self_update_skipped(self):
        self.assertIsNone(e.prepare({'files':[{'filename':e.UPDATES}]}, ''))
    def test_missing_diff_fails(self):
        with self.assertRaises(e.UnsafeInput):
            e.prepare({'files':[{'filename':'site/layouts/index.html','changes':5}]}, '')
    def test_large_file_list_fails(self):
        with self.assertRaises(e.UnsafeInput):
            e.prepare({'files':[{'filename':'a'}]*201}, '')
    def test_injection_rejected(self):
        for text in ['[click](https://evil.test)', '<script>', 'line\nline']:
            with self.assertRaises(e.UnsafeInput):
                e.validate_decision({'should_update':True,'reason':'x','entries':[{'text':text,'source_paths':['a']}]}, {'files':[{'filename':'a'}]})
    def test_unsubstantiated_rejected(self):
        with self.assertRaises(e.UnsafeInput):
            e.validate_decision({'should_update':True,'reason':'x','entries':[{'text':'News','source_paths':['other']}]}, {'files':[{'filename':'a'}]})
    def test_render_and_dedup(self):
        source='---\ntitle: Updates\n---\n- [x] old\n'
        entries=[{'text':'New poem.'}]
        result=e.render(source,entries,'2026-10-30T10:00:00Z')
        self.assertIn('2026-10-30 13:00',result)
        self.assertEqual(result,e.render(result,entries,'2026-10-30T11:00:00Z'))
        self.assertTrue(result.endswith('- [x] old\n'))
    def test_bad_event(self):
        with self.assertRaises(e.UnsafeInput):e.validate_event({})

if __name__=='__main__':unittest.main()
