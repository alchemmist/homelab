"""Same-instance native HTTP SDK leaf reload canary, no Deployment patch rights.

Connection: close forces fresh handshakes. A transparent test-only observation
of SSLContext.load_cert_chain records only the public PEM hash; normal certificate
loading/verification is never replaced. Model responses are synthetic mocks.
"""
import contextlib
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import ssl
import time

PROGRESS = Path('/run/otel-test/renewal-progress.json')
MARKERS = ['OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED',
           'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED', 'otel-canary-not-a-real-credential']


def certificate_hash():
    return hashlib.sha256(Path('/etc/otel-client/tls.crt').read_bytes()).hexdigest()


def record(value):
    temporary = PROGRESS.with_suffix('.new')
    temporary.write_text(json.dumps(value))
    temporary.replace(PROGRESS)


def run():
    logging.disable(logging.CRITICAL)
    if os.environ.get('OTEL_EXPORTER_OTLP_HEADERS', '').lower() != 'connection=close':
        raise ValueError('Fresh native HTTP client handshakes required for leaf reload proof')
    loaded = []
    original_loader = ssl.SSLContext.load_cert_chain
    def observe_loader(context, certfile, keyfile=None, password=None):
        public_hash = hashlib.sha256(Path(certfile).read_bytes()).hexdigest()
        result = original_loader(context, certfile, keyfile, password)
        loaded.append(public_hash)
        return result
    ssl.SSLContext.load_cert_chain = observe_loader
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import litellm
        from litellm.integrations.opentelemetry import OpenTelemetry
        from opentelemetry import trace
        from opentelemetry.sdk.trace import SpanProcessor
        from opentelemetry.trace import Status, StatusCode
        litellm.turn_off_message_logging = True
        litellm.set_verbose = False
        handler = OpenTelemetry()
        if handler.config.enable_metrics or handler.config.enable_events:
            raise ValueError('SDK metrics/events must remain disabled')
        audit = {'endedSpans': 0, 'sensitiveSyntheticContentFoundAtSource': False}
        class PrivacyAudit(SpanProcessor):
            def on_start(self, span, parent_context=None):
                pass
            def on_end(self, span):
                audit['endedSpans'] += 1
                if any(marker in span.to_json() for marker in MARKERS):
                    audit['sensitiveSyntheticContentFoundAtSource'] = True
            def shutdown(self):
                pass
            def force_flush(self, timeout_millis=30000):
                return True
        provider = handler._tracer_provider
        provider.add_span_processor(PrivacyAudit())
        litellm.callbacks = [handler]
        tracer = trace.get_tracer('homelab.synthetic.sdk-leaf-renewal')
        traces = []
        def completion():
            with tracer.start_as_current_span('homelab.synthetic.litellm-sdk-validation') as parent:
                parent.set_attribute('homelab.synthetic', True)
                parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory-sampling canary'))
                entry = {'traceId': format(parent.get_span_context().trace_id, '032x'),
                         'parentSpanId': format(parent.get_span_context().span_id, '016x')}
                litellm.completion(model='openai/gpt-4o-mini', messages=[{'role': 'user', 'content': MARKERS[0]}],
                                   mock_response=MARKERS[1], api_key=MARKERS[2], metadata={'litellm_parent_otel_span': parent})
                time.sleep(3)
            if not provider.force_flush(timeout_millis=10000):
                raise ValueError('Native SDK flush did not complete')
            traces.append(entry)
        old = certificate_hash()
        completion()
        if old not in loaded:
            raise ValueError('Initial native SDK handshake did not load the mounted leaf')
        record({'phase': 'await-new-projected-leaf', 'oldCertificateSHA256': old, 'traces': traces})
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            new = certificate_hash()
            if new != old:
                break
            time.sleep(2)
        else:
            raise ValueError('Projected mirror leaf did not change before deadline')
        # The provider/exporter/session was not recreated between batches.
        completion()
        if new not in loaded or handler._tracer_provider is not provider or audit['sensitiveSyntheticContentFoundAtSource'] or audit['endedSpans'] < 4:
            raise ValueError('Same-instance native SDK credential reload/source privacy failed')
    ssl.SSLContext.load_cert_chain = original_loader
    result = {'success': True, 'sameNativeSdkProviderAndExporterInstance': True,
              'oldCertificateSHA256': old, 'newCertificateSHA256': new,
              'oldAndNewLeafLoadedByNativeTlsStack': old in loaded and new in loaded,
              'connectionCloseEnabled': True, 'sourcePrivacyAudit': audit, 'traces': traces,
              'applicationDeploymentsPatched': False, 'privateKeysSavedOrLogged': False,
              'realLlmRequests': 0, 'productionApplicationSdkCoverageVerified': False,
              'backendProofForBothTracesStillRequired': True}
    record(result)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        result = {'success': False, 'errorType': type(error).__name__, 'privateKeysSavedOrLogged': False,
                  'productionApplicationSdkCoverageVerified': False}
        record(result)
        print(json.dumps(result))
        raise SystemExit(1)
