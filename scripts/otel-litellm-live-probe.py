"""Run inside the new production LiteLLM pod; no credentials emitted.

One intentionally invalid model request tests the real HTTP auth/router/SDK
without inference, model switching, API charges or user data. A separate probe
process emits a clearly synthetic ERROR root so the global sampler retains the
correlated real server spans. Cross-process parenting can only use W3C headers.
"""
import contextlib
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import urllib.error
import urllib.request


def run():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.trace import Status, StatusCode
        provider = TracerProvider(resource=Resource.create({'service.name': 'homelab-live-sdk-probe'}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        tracer = provider.get_tracer('homelab.synthetic.production-sdk-validation')
        with tracer.start_as_current_span('homelab.synthetic.live-sdk-validation') as parent:
            parent.set_attribute('homelab.synthetic', True)
            parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory-sampling root; not a real service failure'))
            trace_id = format(parent.get_span_context().trace_id, '032x')
            parent_id = format(parent.get_span_context().span_id, '016x')
            body = json.dumps({'model': 'otel-sdk-validation-nonexistent-model', 'messages': [
                {'role': 'user', 'content': 'Synthetic SDK validation; no inference must occur.'}], 'max_tokens': 1}).encode()
            request = urllib.request.Request('http://127.0.0.1:4000/v1/chat/completions', data=body, headers={
                'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY'],
                'Content-Type': 'application/json', 'traceparent': '00-' + trace_id + '-' + parent_id + '-01'})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    status = response.status
            except urllib.error.HTTPError as error:
                status = error.code
        flushed = provider.force_flush(timeout_millis=10000)
        provider.shutdown()
    report = {'success': status in [400, 404] and flushed is True, 'traceId': trace_id, 'parentSpanId': parent_id,
              'httpStatus': status, 'syntheticExpectedInvalidModel': True, 'realLlmRequests': 0,
              'actualProductionHttpProcessCalled': True, 'w3cTraceparentSentAcrossProcesses': True,
              'mountedCertificateSHA256': hashlib.sha256(Path('/etc/otel-client/tls.crt').read_bytes()).hexdigest(),
              'privateKeysOrApiTokensPrinted': False, 'backendProductionServerChildVerificationStillRequired': True}
    print(json.dumps(report))
    if not report['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(json.dumps({'success': False, 'errorType': type(error).__name__, 'privateKeysOrApiTokensPrinted': False}))
        raise SystemExit(1)
