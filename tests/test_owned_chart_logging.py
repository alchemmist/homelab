import contextlib
import importlib.util
import io
import json
import logging
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'charts/spi-triage/files'))


class OwnedLoggingTests(unittest.TestCase):
    def contract(self, row, service):
        self.assertEqual(row['service'], service)
        self.assertIn(row['level'], ['info', 'warn', 'error', 'debug'])
        self.assertTrue(row['ts'].endswith('Z'))
        datetime.fromisoformat(row['ts'].replace('Z', '+00:00'))
        self.assertNotIn('\n', row['msg'])

    def test_worker_allowlist(self):
        from service import log_event
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            log_event('stage_failed', 'error', stage='secret\nbody', code='SECRET\nTOKEN', body='private', issue_number=123)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        row = json.loads(output.getvalue())
        self.contract(row, 'spi-triage')
        self.assertNotIn('private', output.getvalue())
        self.assertNotIn('issue_number', row)
        self.assertEqual(row['stage'], 'REDACTED')
        self.assertEqual(row['code'], 'REDACTED')

    def test_js_allowlist(self):
        script = "const {logEvent}=require('./charts/n8n/extensions/event-log'); logEvent('yandex-calendar','announcement_failed',{code:'HTTP_500',body:'private',id:'private'});"
        output = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, check=True)
        row = json.loads(output.stderr)
        self.contract(row, 'n8n-extensions')
        self.assertEqual(row['level'], 'error')
        self.assertNotIn('private', output.stderr)

    def test_watchdog_exception_is_safe(self):
        spec = importlib.util.spec_from_file_location('watchdog_logging', ROOT / 'charts/open-terminal/files/browser_watchdog.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        try:
            raise ValueError('private\ncredential')
        except ValueError:
            record = logging.LogRecord('test', logging.ERROR, '', 0, 'private', (), sys.exc_info())
        raw = module.JsonFormatter().format(record)
        self.contract(json.loads(raw), 'open-terminal-browser-watchdog')
        self.assertNotIn('private', raw)
        self.assertEqual(len(raw.splitlines()), 1)
