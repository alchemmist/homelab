import importlib.util
import os
import stat
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
            fd=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as f:subprocess.run([sys.executable,str(SCRIPT),'--source',str(src),'--private-pvc-directory',d],stdout=f,check=True)
            self.assertEqual(stat.S_IMODE(dst.stat().st_mode),0o600)
            c=sqlite3.connect(dst);self.assertEqual(c.execute('SELECT * FROM ledger').fetchall(),[('unchanged',)]);self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok');c.close()
            self.assertEqual(list(Path(d).glob('.spi-prechange-*')),[])
    def test_bound_failure_cleans(self):
        spec=importlib.util.spec_from_file_location('backup',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source';c=sqlite3.connect(src);c.execute('CREATE TABLE x(a)');c.close()
            with self.assertRaises(RuntimeError):m.backup(str(src),d,max_bytes=1)
            self.assertEqual(list(Path(d).glob('.spi-prechange-*')),[])

class BackupDeadlineTests(unittest.TestCase):
    def run_failure(self, kind):
        import time
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source'
            c=sqlite3.connect(src)
            c.execute('CREATE TABLE x(a BLOB)')
            c.execute('INSERT INTO x VALUES(zeroblob(4194304))');c.commit()
            if kind=='busy':c.execute('BEGIN EXCLUSIVE')
            if kind=='open':src=Path(d)/'missing'
            cmd=[sys.executable,str(SCRIPT),'--source',str(src),'--private-pvc-directory',d,'--deadline-seconds','0.4']
            started=time.monotonic()
            proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                if kind=='broken':proc.stdout.close()
                # Deliberately never read stdout before exit: actual full pipe.
                status=proc.wait(timeout=4)
                self.assertNotEqual(status,0)
                self.assertLess(time.monotonic()-started,3)
                self.assertEqual(proc.stderr.read(),b'BACKUP_FAILED: output invalid; delete private host file\n')
                self.assertEqual(list(Path(d).glob('.spi-prechange-*')),[])
            finally:
                if proc.poll() is None:proc.kill();proc.wait(timeout=2)
                if not proc.stdout.closed:proc.stdout.close()
                proc.stderr.close();c.close()
    def test_actual_blocked_consumer(self):self.run_failure('blocked')
    def test_broken_pipe(self):self.run_failure('broken')
    def test_busy_source(self):self.run_failure('busy')
    def test_connection_open_cleanup(self):self.run_failure('open')
    def test_slow_integrity_deadline(self):
        # Real subprocess and real SQLite VM; progress callback intentionally
        # sleeps while integrity is running, not a mocked monotonic clock.
        code='''import importlib.util,sqlite3,sys,time
spec=importlib.util.spec_from_file_location('b',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=sqlite3.connect
class Slow(sqlite3.Connection):
 def set_progress_handler(self,callback,n):
  def slow():
   time.sleep(.03)
   return callback()
  super().set_progress_handler(slow,1)
def connect(*a,**kw):return original(*a,**kw,factory=Slow)
m.sqlite3.connect=connect
try:m.backup(sys.argv[2],sys.argv[3],deadline_seconds=.4)
except Exception:sys.exit(1)
'''
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source'
            c=sqlite3.connect(src);c.execute('CREATE TABLE x(a)');c.executemany('INSERT INTO x VALUES(?)',[(i,) for i in range(100)]);c.commit();c.close()
            result=subprocess.run([sys.executable,'-c',code,str(SCRIPT),str(src),d],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=4)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(list(Path(d).glob('.spi-prechange-*')),[])

    def test_alarm_restored_and_pvc_private(self):
        import signal
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location('backup',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        old=signal.getsignal(signal.SIGALRM)
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source';c=sqlite3.connect(src);c.execute('CREATE TABLE x(a)');c.close()
            original=m.sqlite3.connect
            def checked(path,*a,**kw):
                if not kw.get('uri'):
                    self.assertEqual(stat.S_IMODE(Path(path).stat().st_mode),0o600)
                    raise OSError('synthetic destination open failure')
                return original(path,*a,**kw)
            with patch.object(m.sqlite3,'connect',checked):
                with self.assertRaises(OSError):m.backup(str(src),d)
            self.assertEqual(list(Path(d).glob('.spi-prechange-*')),[])
            self.assertEqual(signal.getsignal(signal.SIGALRM),old)
            self.assertEqual(signal.getitimer(signal.ITIMER_REAL),(0.0,0.0))
