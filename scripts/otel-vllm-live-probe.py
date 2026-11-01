"""One synthetic one-token local production inference and cross-process W3C probe.

Run in ready production vLLM pod as a separate lightweight Python process.
Never imports/starts an engine, changes a model, logs a body/key, or calls an
external provider. Native app spans must be independently verified in Tempo.
"""
import contextlib
import io
import json
import logging
import os
import urllib.request


def run():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.trace import Status, StatusCode
        if not getattr(TracerProvider, '_homelab_source_privacy', False):
            raise ValueError('Early source privacy bootstrap absent')
        authorization = 'Bearer ' + os.environ['VLLM_API_KEY']
        with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/v1/models', headers={'Authorization': authorization}), timeout=10) as response:
            document = json.loads(response.read(65537))
        models = document.get('data', [])
        if len(models) != 1:
            raise ValueError('Expected one already loaded model; never switch models')
        provider = TracerProvider(resource=Resource.create({'service.name': 'homelab-live-vllm-probe'}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        tracer = provider.get_tracer('homelab.synthetic.production-vllm-validation')
        with tracer.start_as_current_span('homelab.synthetic.production-vllm-request') as parent:
            parent.set_attribute('homelab.synthetic', True)
            parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory-sampling root; not a real service failure'))
            trace_id = format(parent.get_span_context().trace_id, '032x')
            parent_id = format(parent.get_span_context().span_id, '016x')
            payload = {'model': models[0]['id'], 'messages': [{'role': 'user', 'content': 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED. Say OK.'}],
                       'max_tokens': 1, 'temperature': 0, 'stream': False}
            request = urllib.request.Request('http://127.0.0.1:8000/v1/chat/completions', data=json.dumps(payload).encode(), headers={
                'Authorization': authorization, 'Content-Type': 'application/json',
                'traceparent': '00-' + trace_id + '-' + parent_id + '-01'})
            with urllib.request.urlopen(request, timeout=180) as response:
                status = response.status
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError('Response inspection budget exceeded')
            result = json.loads(raw)
            completion_tokens = result.get('usage', {}).get('completion_tokens', 0)
            valid_response = bool(result.get('choices')) and completion_tokens == 1
        flushed = provider.force_flush(timeout_millis=10000)
        provider.shutdown()
    report = {'success': status == 200 and valid_response and flushed is True, 'httpStatus': status,
              'traceId': trace_id, 'parentSpanId': parent_id, 'syntheticInferenceRequests': 1,
              'completionTokens': completion_tokens, 'modelChanged': False, 'userDataUsed': False,
              'externalInferenceProviderCalled': False, 'privateKeysApiTokensOrBodiesPrinted': False,
              'sourceGuardFactoryActive': True, 'crossProcessW3cHeaderSent': True,
              'backendProductionNativeSpanVerificationStillRequired': True}
    print(json.dumps(report))
    if not report['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(json.dumps({'success': False, 'errorType': type(error).__name__, 'privateKeysApiTokensOrBodiesPrinted': False}))
        raise SystemExit(1)
