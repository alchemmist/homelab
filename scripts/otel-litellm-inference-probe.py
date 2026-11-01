"""One local, one-token successful production LiteLLM inference.

Require already loaded qwen3.8-27b; controller must independently fence the live
route to the local switcher. No model switches, external providers or body logs.
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
        authorization = 'Bearer ' + os.environ['VLLM_API_KEY']
        with urllib.request.urlopen(urllib.request.Request('http://vllm.llm.svc.cluster.local:8000/v1/models', headers={'Authorization': authorization}), timeout=10) as response:
            loaded = json.loads(response.read(65537)).get('data', [])
        if len(loaded) != 1 or loaded[0]['id'] != 'qwen3.8-27b':
            raise ValueError('Local model not already loaded; no switching allowed')
        valid_response = False
        completion_tokens = 0
        provider = TracerProvider(resource=Resource.create({'service.name': 'homelab-live-sdk-probe'}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        tracer = provider.get_tracer('homelab.synthetic.production-sdk-validation')
        with tracer.start_as_current_span('homelab.synthetic.live-sdk-validation') as parent:
            parent.set_attribute('homelab.synthetic', True)
            parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory-sampling root; not a real service failure'))
            trace_id = format(parent.get_span_context().trace_id, '032x')
            parent_id = format(parent.get_span_context().span_id, '016x')
            body = json.dumps({'model': 'qwen3.8-27b', 'messages': [
                {'role': 'user', 'content': 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED. Say OK.'}], 'max_tokens': 1, 'temperature': 0, 'stream': False}).encode()
            request = urllib.request.Request('http://127.0.0.1:4000/v1/chat/completions', data=body, headers={
                'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY'],
                'Content-Type': 'application/json', 'traceparent': '00-' + trace_id + '-' + parent_id + '-01'})
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    status = response.status
                    raw = response.read(65537)
                    if len(raw) > 65536:raise ValueError('Response inspection budget exceeded')
                    result = json.loads(raw)
                    completion_tokens = result.get('usage', {}).get('completion_tokens', 0)
                    valid_response = bool(result.get('choices')) and completion_tokens == 1
            except urllib.error.HTTPError as error:
                status = error.code
        flushed = provider.force_flush(timeout_millis=10000)
        provider.shutdown()
    report = {'success': status == 200 and valid_response and flushed is True, 'traceId': trace_id, 'parentSpanId': parent_id,
              'httpStatus': status, 'syntheticExpectedInvalidModel': False, 'syntheticLocalInferenceRequests': 1,
              'completionTokens': completion_tokens, 'modelChanged': False, 'externalInferenceProviderCalled': False,
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
