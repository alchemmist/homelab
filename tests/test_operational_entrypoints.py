import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('entrypoints',ROOT/'scripts/check_operational_entrypoints.py')
entrypoints=importlib.util.module_from_spec(spec);spec.loader.exec_module(entrypoints)

class OperationalEntrypoints(unittest.TestCase):
    def fixture(self,d):
        root=Path(d);(root/'ansible').mkdir();(root/'deploy/contracts').mkdir(parents=True)
        (root/'ansible/demo.yml').write_text('command: helm upgrade demo ./chart\n')
        c={'schemaVersion':1,'entries':[{'path':'ansible/demo.yml','status':'review-required','owners':[],
                                       'reason':'Known competing entrypoint, not permission to execute.'}]}
        self.save(root,c);return root,c

    def save(self,root,c):
        (root/'deploy/contracts/operational-entrypoints.json').write_text(json.dumps(c))

    def test_current_inventory_is_read_only(self):
        self.assertEqual(entrypoints.check(ROOT),(23,15))
        with tempfile.TemporaryDirectory() as d:
            root,c=self.fixture(d);before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(entrypoints.check(root),(1,1))
            self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_new_unclassified_helm_entrypoint_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root,c=self.fixture(d)
            (root/'ansible/other.yml').write_text('command: helm install other ./chart\n')
            with self.assertRaisesRegex(ValueError,'Unclassified'):entrypoints.check(root)

    def test_duplicate_or_stale_classification_fails(self):
        for mode in ['duplicate','stale','invalid']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root,c=self.fixture(d)
                if mode=='duplicate':c['entries']*=2
                elif mode=='stale':(root/'ansible/demo.yml').write_text('tasks: []\n')
                else:c['entries'][0]['status']='safe-to-run'
                self.save(root,c)
                with self.assertRaises(ValueError):entrypoints.check(root)

    def test_retired_import_or_remote_action_fails(self):
        for mode in ['import','command']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root,c=self.fixture(d);c['entries'][0]['status']='retired';self.save(root,c)
                play={'name':'refuse','hosts':'socrat-0','gather_facts':False,'become':False,
                      'any_errors_fatal':True,'tasks':[{'name':'refuse','ansible.builtin.fail':{'msg':'retired'},'tags':['always']}]}
                p=root/'ansible/demo.yml';p.write_text(yaml.safe_dump([play]))
                self.assertEqual(entrypoints.check(root),(1,0))
                if mode=='import':p.write_text(yaml.safe_dump([play,{'import_playbook':'later.yml'}]))
                else:
                    play['tasks'].append({'ansible.builtin.command':'true'});p.write_text(yaml.safe_dump([play]))
                with self.assertRaises(ValueError):entrypoints.check(root)

    def test_missing_owner_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root,c=self.fixture(d);c['entries'][0]['owners']=['missing'];self.save(root,c)
            with self.assertRaisesRegex(ValueError,'Missing operational source owner'):entrypoints.check(root)

    def test_scan_symlink_escape_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as other:
            root,c=self.fixture(d)
            (root/'ansible/outside.yml').symlink_to(Path(other)/'nonexistent-private.yml')
            with self.assertRaisesRegex(ValueError,'symlink escapes'):entrypoints.check(root)

if __name__=='__main__':unittest.main()
