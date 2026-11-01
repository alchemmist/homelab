"""Isolated native Open WebUI setup with source-safe HTTP profile.

SQLite/data are disposable isolated paths, never production DB. No real model,
Redis/SQL tracing, network inference, application credentials or user bodies.
An in-process mock HTTP backend exercises actual stock client instrumentation.
"""
import contextlib
import io
import hashlib
import json
import logging
import os
from pathlib import Path
import ssl
import time

MARKERS = ['OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED',
           'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED', 'otel-canary-not-a-real-credential']


def run():
    logging.disable(logging.CRITICAL)
    renewal = os.environ.get('HOMELAB_AWAIT_LEAF_RENEWAL') == '1'
    loaded = []
    original_loader = ssl.SSLContext.load_cert_chain
    def certificate_hash():
        return hashlib.sha256(Path('/etc/otel-client/tls.crt').read_bytes()).hexdigest()
    def observe_loader(context, certfile, keyfile=None, password=None):
        public_hash = hashlib.sha256(Path(certfile).read_bytes()).hexdigest()
        result = original_loader(context, certfile, keyfile, password)
        loaded.append(public_hash)
        return result
    def progress(value):
        path = Path('/run/otel-test/renewal-progress.json')
        temporary = path.with_suffix('.new')
        temporary.write_text(json.dumps(value))
        temporary.replace(path)
    if renewal:
        ssl.SSLContext.load_cert_chain = observe_loader
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import source_privacy
        import open_webui_source_profile
        if os.environ.get('HOMELAB_REQUIRE_EARLY_PROFILE') == '1':
            from opentelemetry.sdk.trace import TracerProvider
            from open_webui.utils.telemetry import instrumentors as early_native
            if not getattr(TracerProvider, '_homelab_source_privacy', False) or not getattr(early_native.Instrumentor, '_homelab_http_only_profile', False):
                raise ValueError('Required early bootstrap absent; no late/manual fallback')
        else:
            source_privacy.activate()
            open_webui_source_profile.activate()
        import httpx
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from opentelemetry import trace
        from opentelemetry.sdk.trace import SpanProcessor
        from opentelemetry.trace import Status, StatusCode
        from open_webui.utils.telemetry import setup as native
        from open_webui.utils.telemetry import instrumentors
        constructed = []
        original_exporter = native.HttpOTLPSpanExporter
        class ObservedExporter(original_exporter):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                constructed.append(self._session.headers.get('Connection', '').lower() == 'close')
        native.HttpOTLPSpanExporter = ObservedExporter
        import http.server
        import threading
        class Backend(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                length = int(self.headers.get('Content-Length', '0'))
                if length > 65536:
                    raise ValueError('Synthetic backend budget exceeded')
                self.rfile.read(length)
                body = json.dumps({'synthetic': MARKERS[1]}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        backend = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Backend)
        worker = threading.Thread(target=backend.serve_forever, daemon=True)
        worker.start()
        app = FastAPI()
        async def route(request: Request):
            payload = await request.json()
            async with httpx.AsyncClient() as client:
                await client.post('http://127.0.0.1:' + str(backend.server_port) + '/completions?api_key=' + MARKERS[2],
                                  headers={'Authorization': 'Bearer ' + MARKERS[2]}, json=payload)
            raise HTTPException(status_code=500, detail=MARKERS[1])
        app.add_api_route('/synthetic', route, methods=['POST'])
        native.setup(app, create_engine('sqlite:///:memory:'))
        if not getattr(instrumentors.Instrumentor, '_homelab_http_only_profile', False):
            raise ValueError('Unsafe native factory was not replaced before setup import')
        disabled = {name: not cls().is_instrumented_by_opentelemetry for name, cls in [
            ('redis', instrumentors.RedisInstrumentor), ('sqlalchemy', instrumentors.SQLAlchemyInstrumentor),
            ('systemMetrics', instrumentors.SystemMetricsInstrumentor), ('logging', instrumentors.LoggingInstrumentor)]}
        if not all(disabled.values()):
            raise ValueError('Unsafe or duplicate signal instrumentor active')
        provider = trace.get_tracer_provider()
        audit = {'endedSpans': 0, 'sensitiveSyntheticContentFoundBeforeDownstreamProcessor': False,
                 'httpClientSpanSeen': False, 'serverSpanSeen': False}
        class Audit(SpanProcessor):
            def on_start(self, span, parent_context=None):
                pass
            def on_end(self, span):
                audit['endedSpans'] += 1
                audit['sensitiveSyntheticContentFoundBeforeDownstreamProcessor'] |= any(marker in span.to_json() for marker in MARKERS)
                audit['httpClientSpanSeen'] |= span.kind.name == 'CLIENT'
                audit['serverSpanSeen'] |= span.kind.name == 'SERVER'
            def shutdown(self):
                pass
            def force_flush(self, timeout_millis=30000):
                return True
        provider.add_span_processor(Audit())
        tracer = trace.get_tracer('homelab.synthetic.open-webui-profile')
        def emit_request():
            with tracer.start_as_current_span('homelab.synthetic.open-webui-validation') as parent:
                parent.set_attribute('homelab.synthetic', True)
                parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory sampling root'))
                trace_id = format(parent.get_span_context().trace_id, '032x')
                parent_id = format(parent.get_span_context().span_id, '016x')
                # TestClient propagates Python context into its ASGI thread. Clear
                # it so server instrumentation must extract the explicit W3C header,
                # as it would for an actual remote caller, not create INTERNAL spans.
                from opentelemetry.context import Context, attach, detach
                token = attach(Context())
                try:
                    with TestClient(app, raise_server_exceptions=False) as client:
                        response = client.post('/synthetic?secret=' + MARKERS[2], json={'prompt': MARKERS[0]},
                            headers={'Authorization': 'Bearer ' + MARKERS[2], 'traceparent': '00-' + trace_id + '-' + parent_id + '-01'})
                        status = response.status_code
                finally:
                    detach(token)
            return {'traceId': trace_id, 'parentSpanId': parent_id, 'httpStatus': status}
        before_hash = certificate_hash()
        first = emit_request()
        if not provider.force_flush(timeout_millis=10000):
            raise ValueError('Initial native source SDK flush failed')
        traces = [first]
        if renewal:
            if before_hash not in loaded:
                raise ValueError('Native HTTP client did not load initial leaf')
            progress({'phase': 'await-renewal', 'beforeCertificateSHA256': before_hash, 'beforeTrace': first})
            deadline = time.monotonic() + 600
            while certificate_hash() == before_hash:
                if time.monotonic() >= deadline:
                    raise ValueError('Projected leaf renewal deadline exceeded')
                time.sleep(2)
            after_hash = certificate_hash()
            traces.append(emit_request())
        else:
            after_hash = before_hash
        trace_id, parent_id, status = first['traceId'], first['parentSpanId'], first['httpStatus']
        flushed = provider.force_flush(timeout_millis=10000)
        provider.shutdown()
        backend.shutdown()
        backend.server_close()
    if renewal:
        ssl.SSLContext.load_cert_chain = original_loader
    reload_verified = renewal and before_hash != after_hash and before_hash in loaded and after_hash in loaded
    success = (not renewal or reload_verified) and all(item['httpStatus'] == 500 for item in traces) and status == 500 and flushed is True and all(disabled.values()) and constructed == [True] and audit['endedSpans'] >= 3 and audit['serverSpanSeen'] and audit['httpClientSpanSeen'] and not audit['sensitiveSyntheticContentFoundBeforeDownstreamProcessor']
    report = {'success': success, 'traceId': trace_id, 'parentSpanId': parent_id, 'httpStatus': status,
              'nativeSetupFunctionCalled': True,
              'earlyBootstrapRequiredWithoutManualFallback': os.environ.get('HOMELAB_REQUIRE_EARLY_PROFILE') == '1',
              'sameNativeProviderAndExporterInstance': renewal, 'sdkLeafReloadVerified': bool(reload_verified),
              'traces': traces, 'beforeCertificateSHA256': before_hash, 'afterCertificateSHA256': after_hash,
              'nativeHttpLoadedPublicCertificateHashes': sorted(set(loaded)), 'nativeFactoryReplacedBeforeSetupImport': True,
              'unsafeAndDuplicateInstrumentorsDisabled': disabled, 'nativeHttpConstructorPreservedConnectionClose': constructed,
              'sourcePrivacyAudit': audit, 'productionDatabaseOrModelCalled': False, 'productionDeploymentChanged': False,
              'profile': 'stock-http-only-no-redis-no-sql-no-systemmetrics-no-log-export',
              'productionApplicationSdkCoverageVerified': False, 'backendAndSdkRenewalProofStillRequired': True}
    if renewal:
        progress(dict(report, phase='completed'))
    print(json.dumps(report))
    if not success:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(json.dumps({'success': False, 'errorType': type(error).__name__, 'missingModule': getattr(error, 'name', None), 'privateKeysApiTokensOrBodiesPrinted': False,
                          'productionDeploymentChanged': False}))
        raise SystemExit(1)
