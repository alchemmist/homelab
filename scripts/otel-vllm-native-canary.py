"""CPU-only installed vLLM native request-span/HTTP-mTLS canary.

Never starts an engine or loads a model. Calls the installed OutputProcessor
request tracing method with synthetic CPU state. Not production vLLM coverage;
loading/decorator error-path privacy and renewable credentials remain gates.
"""
import contextlib
import hashlib
import io
import json
import logging
import os
import ssl
from pathlib import Path
import time
from types import SimpleNamespace

MARKERS = ['OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED', 'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED']


def run():
    logging.disable(logging.CRITICAL)
    if os.environ.get('OTEL_EXPORTER_OTLP_TRACES_PROTOCOL') != 'http/protobuf':
        raise ValueError('vLLM ignores generic protocol for this selector; insecure gRPC path forbidden')
    renewal = os.environ.get('HOMELAB_AWAIT_LEAF_RENEWAL') == '1'
    loaded = []
    original_loader = ssl.SSLContext.load_cert_chain
    def observe_loader(context, certfile, keyfile=None, password=None):
        public_hash = hashlib.sha256(Path(certfile).read_bytes()).hexdigest()
        result = original_loader(context, certfile, keyfile, password)
        loaded.append(public_hash)
        return result
    if renewal:
        if os.environ.get('OTEL_EXPORTER_OTLP_HEADERS', '').lower() != 'connection=close':
            raise ValueError('Fresh native HTTP handshakes required')
        ssl.SSLContext.load_cert_chain = observe_loader
    def certificate_hash():
        return hashlib.sha256(Path('/etc/otel-client/tls.crt').read_bytes()).hexdigest()
    def progress(value):
        path = Path('/run/otel-test/renewal-progress.json')
        temporary = path.with_suffix('.new')
        temporary.write_text(json.dumps(value))
        temporary.replace(path)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import importlib.metadata
        from opentelemetry import trace
        from opentelemetry.sdk.trace import SpanProcessor
        from opentelemetry.trace import Status, StatusCode
        from vllm.tracing import init_tracer
        from vllm.tracing.otel import get_span_exporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from vllm.v1.engine.output_processor import OutputProcessor
        endpoint = 'https://10.250.0.3:44318/v1/traces'
        probe_exporter = get_span_exporter(endpoint)
        if not isinstance(probe_exporter, OTLPSpanExporter):
            raise ValueError('Installed vLLM selected a non-HTTP exporter')
        probe_exporter.shutdown()
        tracer = init_tracer('homelab.synthetic.vllm-request-validation', endpoint)
        provider = trace.get_tracer_provider()
        audit = {'endedSpans': 0, 'sensitiveSyntheticContentFoundAtSource': False, 'nativeLlmRequestSpanSeen': False}
        class Audit(SpanProcessor):
            def on_start(self, span, parent_context=None):
                pass
            def on_end(self, span):
                audit['endedSpans'] += 1
                audit['nativeLlmRequestSpanSeen'] |= span.name == 'llm_request'
                if any(marker in span.to_json() for marker in MARKERS):
                    audit['sensitiveSyntheticContentFoundAtSource'] = True
            def shutdown(self):
                pass
            def force_flush(self, timeout_millis=30000):
                return True
        provider.add_span_processor(Audit())
        def emit_request():
            with tracer.start_as_current_span('homelab.synthetic.vllm-validation') as parent:
                parent.set_attribute('homelab.synthetic', True)
                parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory sampling root'))
                trace_id = format(parent.get_span_context().trace_id, '032x')
                parent_id = format(parent.get_span_context().span_id, '016x')
                arrival = time.time() - 3
                statistics = SimpleNamespace(arrival_time=arrival, scheduled_ts=arrival + .1, queued_ts=arrival,
                             first_token_ts=arrival + .2, last_token_ts=arrival + 2.9, first_token_latency=.2, num_generation_tokens=1)
                request = SimpleNamespace(stats=statistics, prompt_token_ids=[1, 2], prompt_embeds=None,
                             external_req_id='homelab-synthetic-vllm', top_p=1.0, max_tokens_param=1, temperature=0.0, n=1,
                             prompt=MARKERS[0], output_text=MARKERS[1])
                output = SimpleNamespace(trace_headers={'traceparent': '00-' + trace_id + '-' + parent_id + '-01'})
                # Unmodified installed method; self is not used by this implementation.
                OutputProcessor.do_tracing(None, output, request, SimpleNamespace(iteration_timestamp=time.time()))
            return {'traceId': trace_id, 'parentSpanId': parent_id}
        before_hash = certificate_hash()
        first = emit_request()
        if not provider.force_flush(timeout_millis=10000):
            raise ValueError('Initial native SDK flush failed')
        traces = [first]
        if renewal:
            if before_hash not in loaded:
                raise ValueError('Initial leaf was not loaded by native HTTP client')
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
        trace_id, parent_id = first['traceId'], first['parentSpanId']
        flushed = provider.force_flush(timeout_millis=10000)
        provider.shutdown()
    if renewal:
        ssl.SSLContext.load_cert_chain = original_loader
    valid = flushed is True and audit['endedSpans'] == (4 if renewal else 2) and audit['nativeLlmRequestSpanSeen'] and not audit['sensitiveSyntheticContentFoundAtSource']
    reload_verified = renewal and before_hash != after_hash and before_hash in loaded and after_hash in loaded
    valid = valid and (not renewal or reload_verified)
    result = {'success': valid, 'traceId': trace_id, 'parentSpanId': parent_id, 'sourcePrivacyAudit': audit,
              'vllmVersion': importlib.metadata.version('vllm'), 'sdkHttpVersion': importlib.metadata.version('opentelemetry-exporter-otlp-proto-http'),
              'specificTraceProtocolSelected': 'http/protobuf', 'insecureGrpcExporterUsed': False,
              'installedOutputProcessorRequestTracingMethodCalled': True,
              'sourceGuardFactoryActive': getattr(type(provider), '_homelab_source_privacy', False),
              'sourceGuardInvariants': json.loads(os.environ.get('HOMELAB_SOURCE_GUARD_INVARIANTS', '{}')),
              'sameNativeProviderAndExporterInstance': renewal, 'sdkLeafReloadVerified': bool(reload_verified),
              'traces': traces, 'nativeHttpLoadedPublicCertificateHashes': sorted(set(loaded)),
              'beforeCertificateSHA256': before_hash, 'afterCertificateSHA256': after_hash,
              'mountedCertificateSHA256': hashlib.sha256(Path('/etc/otel-client/tls.crt').read_bytes()).hexdigest(),
              'gpuEngineStarted': False, 'modelLoaded': False, 'realInferenceRequests': 0,
              'productionVllmSdkCoverageVerified': False, 'decoratorExceptionPrivacyAndRenewalStillRequired': True,
              'backendNativeChildSpanVerificationStillRequired': True}
    if renewal:
        progress(dict(result, phase='completed'))
    print(json.dumps(result))
    if not valid:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(json.dumps({'success': False, 'errorType': type(error).__name__, 'privateKeysOrApiTokensLogged': False,
                          'productionVllmSdkCoverageVerified': False}))
        raise SystemExit(1)
