import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class Deploy(unittest.TestCase):
    def test_safe_refusals_and_anchored_paths(self):
        source = Path(__file__).resolve().parents[1] / 'scripts/rustfs/deploy.sh'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'scripts/rustfs').mkdir(parents=True)
            script = root/'scripts/rustfs/deploy.sh'; script.write_bytes(source.read_bytes())
            chart = root/'charts/rustfs'; chart.mkdir(parents=True)
            tracked = chart/'values.yaml'; tracked.write_text('enabled: false\n')
            def git(*args): return subprocess.check_output(['git','-C',tmp,*args], stderr=subprocess.DEVNULL).decode().strip()
            git('init'); git('add','.'); git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','fixture')
            rev = git('rev-parse','HEAD')
            values = root/'private.yaml'; values.write_text('{}\n')
            binpath = root/'bin'; binpath.mkdir(); marker = root/'called'
            helm = binpath/'helm'; helm.write_text('#!/bin/sh\necho invoked >> "'+str(marker)+'"\n'); helm.chmod(0o755)
            env = dict(os.environ, PATH=str(binpath)+os.pathsep+os.environ['PATH'])
            def run(revision):
                return subprocess.run(['bash',str(script),'--apply',revision,str(values)],cwd='/',env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertNotEqual(run('0'*40).returncode,0); self.assertFalse(marker.exists())
            tracked.write_text('enabled: true\n')
            self.assertNotEqual(run(rev).returncode,0); self.assertFalse(marker.exists())
            git('checkout','--','charts/rustfs/values.yaml')
            templates = chart/'templates'; templates.mkdir()
            extra = templates/'extra.yaml'; extra.write_text('kind: Secret\n')
            self.assertNotEqual(run(rev).returncode,0); self.assertFalse(marker.exists())
            extra.unlink()
            exclude = root/git('rev-parse','--git-path','info/exclude')
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text('charts/rustfs/templates/ignored.yaml\n')
            ignored = templates/'ignored.yaml'; ignored.write_text('kind: Secret\n')
            self.assertNotEqual(run(rev).returncode,0); self.assertFalse(marker.exists())
            ignored.unlink()
            self.assertEqual(run(rev).returncode,0); self.assertEqual(len(marker.read_text().splitlines()),3)
