import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_pointers',ROOT/'scripts/check_source_pointers.py')
pointers = importlib.util.module_from_spec(spec);spec.loader.exec_module(pointers)
REPO = 'https://github.com/alchemmist/homelab.git'

class SourcePointers(unittest.TestCase):
    def write(self,root,name,value):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(yaml.safe_dump(value))

    def fixture(self,directory):
        root=Path(directory)
        self.write(root,'charts/api/Chart.yaml',{'apiVersion':'v2','name':'api','version':'1.0.0'})
        self.write(root,'charts/api/values.yaml',{'persistence':{'existingClaim':'claim-current'}})
        self.write(root,'deploy/api.yaml',{'extra':'value'})
        app={'kind':'Application','metadata':{'name':'api','namespace':'argocd'},'spec':{'source':{
            'repoURL':REPO,'targetRevision':'main','path':'charts/api',
            'helm':{'valueFiles':['../../deploy/api.yaml']}}}}
        self.write(root,'deploy/argocd/apps/api.yaml',app)
        self.write(root,'deploy/argocd/root.yaml',{'spec':{'source':{
            'repoURL':REPO,'targetRevision':'main','path':'deploy/argocd/apps'}}})
        (root/'docs').mkdir()
        (root/'docs/current.md').write_text('Claim `claim-current`; [chart](../charts/api/Chart.yaml).\n')
        config={'schemaVersion':1,'repoURL':REPO,'applicationDirectory':'deploy/argocd/apps',
                'rootApplication':'deploy/argocd/root.yaml','documents':['docs/current.md'],
                'currentValues':[{'application':'api','source':'charts/api/values.yaml',
                                  'path':['persistence','existingClaim'],'documents':['docs/current.md']}]}
        p=root/'deploy/contracts/source-pointers.json';p.parent.mkdir();p.write_text(json.dumps(config))
        return root,app,config

    def test_real_current_sources_and_docs(self):
        count,values=pointers.check(ROOT)
        self.assertGreater(count,0);self.assertGreater(values,count)

    def test_valid_relative_values_and_docs_are_read_only(self):
        with tempfile.TemporaryDirectory() as d:
            root,app,c=self.fixture(d)
            before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(pointers.check(root),(1,2))
            self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_missing_values_rejected_even_when_ignored_by_argo(self):
        with tempfile.TemporaryDirectory() as d:
            root,app,c=self.fixture(d)
            app['spec']['source']['helm']['ignoreMissingValueFiles']=True
            self.write(root,'deploy/argocd/apps/api.yaml',app)
            (root/'deploy/api.yaml').unlink()
            with self.assertRaisesRegex(ValueError,'Missing local values'):
                pointers.check(root)

    def test_missing_source_or_chart_rejected(self):
        for name in ['source','chart']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                root,app,c=self.fixture(d)
                if name=='chart':(root/'charts/api/Chart.yaml').unlink()
                else:
                    app['spec']['source']['path']='charts/absent'
                    self.write(root,'deploy/argocd/apps/api.yaml',app)
                with self.assertRaisesRegex(ValueError,'Missing'):
                    pointers.check(root)

    def test_cross_source_values_resolve_from_repo_root_not_ref_path(self):
        with tempfile.TemporaryDirectory() as d:
            root,app,c=self.fixture(d)
            app['spec']={'sources':[
                {'repoURL':'https://charts.example.test','chart':'api','targetRevision':'1.0.0',
                 'helm':{'valueFiles':['$values/deploy/api.yaml']}},
                {'repoURL':REPO,'targetRevision':'main','ref':'values','path':'docs'}]}
            self.write(root,'deploy/argocd/apps/api.yaml',app)
            c['currentValues']=[]
            (root/'deploy/contracts/source-pointers.json').write_text(json.dumps(c))
            self.assertEqual(pointers.check(root),(1,2))

    def test_undefined_ref_and_repo_escape_rejected(self):
        for value,error in [('$unknown/file.yaml','Undefined'),('../../../../outside.yaml','escapes')]:
            with self.subTest(value=value),tempfile.TemporaryDirectory() as d:
                root,app,c=self.fixture(d)
                app['spec']['source']['helm']['valueFiles']=[value]
                self.write(root,'deploy/argocd/apps/api.yaml',app)
                with self.assertRaisesRegex(ValueError,error):pointers.check(root)

    def test_values_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as outside:
            root,app,c=self.fixture(d)
            for name in ['deploy/api.yaml','charts/api/Chart.yaml']:
                with self.subTest(name=name):
                    p=root/name;original=p.read_bytes();p.unlink()
                    p.symlink_to(Path(outside)/'outside.yaml')
                    with self.assertRaisesRegex(ValueError,'escapes'):pointers.check(root)
                    p.unlink();p.write_bytes(original)

    def test_duplicate_app_and_ambiguous_source_form_rejected(self):
        for mode in ['duplicate','ambiguous']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root,app,c=self.fixture(d)
                if mode=='duplicate':self.write(root,'deploy/argocd/apps/copy.yaml',app)
                else:
                    app['spec']['sources']=[app['spec']['source']]
                    self.write(root,'deploy/argocd/apps/api.yaml',app)
                with self.assertRaises(ValueError):pointers.check(root)

    def test_root_source_move_and_stale_doc_binding_rejected(self):
        for mode in ['root','binding','claim','link']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root,app,c=self.fixture(d)
                if mode=='root':
                    self.write(root,'deploy/argocd/root.yaml',{'spec':{'source':{
                        'repoURL':REPO,'targetRevision':'main','path':'other'}}})
                elif mode=='binding':
                    c['currentValues'][0]['application']='other'
                    (root/'deploy/contracts/source-pointers.json').write_text(json.dumps(c))
                elif mode=='claim':(root/'docs/current.md').write_text('`stale-claim`')
                else:(root/'docs/current.md').write_text('`claim-current` [missing](missing.md)')
                with self.assertRaises(ValueError):pointers.check(root)

    def test_duplicate_refs_and_nonmain_source_not_silently_accepted(self):
        for mode in ['refs','revision','absolute']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root,app,c=self.fixture(d)
                if mode=='refs':
                    source=app['spec'].pop('source')
                    app['spec']['sources']=[source,{'repoURL':REPO,'targetRevision':'main','ref':'values'},
                                            {'repoURL':REPO,'targetRevision':'main','ref':'values'}]
                elif mode=='revision':app['spec']['source']['targetRevision']='old-revision'
                else:app['spec']['source']['helm']['valueFiles']=[str(root/'deploy/api.yaml')]
                self.write(root,'deploy/argocd/apps/api.yaml',app)
                with self.assertRaises(ValueError):pointers.check(root)

if __name__=='__main__':unittest.main()
