import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module():
    spec = importlib.util.spec_from_file_location('webui_profile', ROOT / 'scripts/otel-open-webui-source-profile.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixtures():
    calls = []
    class Native:
        def __init__(self, app, db_engine):
            self.app = app
            self.db_engine = db_engine
    class Http:
        def instrument(self):calls.append('http')
        def uninstrument(self):calls.append('http-stop')
    class FastApi:
        @staticmethod
        def instrument_app(**kwargs):calls.append(kwargs)
        @staticmethod
        def uninstrument_app(app):calls.append('fastapi-stop')
    native = SimpleNamespace(Instrumentor=Native, FastAPIInstrumentor=FastApi,
                             RequestsInstrumentor=Http, HTTPXClientInstrumentor=Http, AioHttpClientInstrumentor=Http)
    sdk = ModuleType('opentelemetry.sdk.trace')
    sdk.TracerProvider = type('GuardedProvider', (), {'_homelab_source_privacy': True})
    telemetry = ModuleType('open_webui.utils.telemetry')
    telemetry.instrumentors = native
    modules = {'opentelemetry': ModuleType('opentelemetry'), 'opentelemetry.sdk': ModuleType('opentelemetry.sdk'),
               'opentelemetry.sdk.trace': sdk, 'open_webui': ModuleType('open_webui'),
               'open_webui.utils': ModuleType('open_webui.utils'), 'open_webui.utils.telemetry': telemetry}
    return calls, native, sdk, modules


class OpenWebuiProfileTests(unittest.TestCase):
    def test_only_http_instrumentors_no_body_serializing_or_duplicate_signals(self):
        calls, native, sdk, modules = fixtures()
        with patch.dict(sys.modules, modules):
            module().activate()
            profile = native.Instrumentor('app', 'never-connected-db')
            profile._instrument()
            self.assertEqual(calls[0], {'app': 'app', 'http_capture_headers_server_request': [], 'http_capture_headers_server_response': []})
            self.assertEqual(calls[1:], ['http'] * 3)
            profile._uninstrument()
            self.assertEqual(calls[-4:], ['fastapi-stop'] + ['http-stop'] * 3)

    def test_guard_and_before_setup_order_required_no_late_fallback(self):
        calls, native, sdk, modules = fixtures()
        with patch.dict(sys.modules, modules):
            sdk.TracerProvider._homelab_source_privacy = False
            with self.assertRaises(ValueError):module().activate()
            sdk.TracerProvider._homelab_source_privacy = True
            with patch.dict(sys.modules, {'open_webui.utils.telemetry.setup': ModuleType('setup')}):
                with self.assertRaises(ValueError):module().activate()
            self.assertEqual(calls, [])
