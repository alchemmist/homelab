import importlib.util
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/n8n/spi_private_backup.py'
class BackupTests(unittest.TestCase):
    def test_private_stream_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source';dst=Path(d)/'host'
            c=sqlite3.connect(src);c.execute('CREATE TABLE ledger(value TEXT)');c.execute("INSERT INTO ledger VALUES('unchanged')");c.commit();c.close()
            with open(dst,'wb') as f:subprocess.run([sys.executable,str(SCRIPT),'--source',str(src),'--private-pvc-directory',d],stdout=f,check=True)
            c=sqlite3.connect(dst);self.assertEqual(c.execute('SELECT * FROM ledger').fetchall(),[('unchanged',)]);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');c.close()
            self.assertEqual(list(Path(d).glob('.spi-prechange-*')),[])
    def test_bound_failure_cleans(self):
        spec=importlib.util.spec_from_file_location('backup',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source';c=sqlite3.connect(src);c.execute('CREATE TABLE x(a)');c.close()
            with self.assertRaises(RuntimeError):m.backup(str(src),d,max_bytes=1)
            self.assertEqual(list(Path(d).glob('.spi-prechange-*')),[])
