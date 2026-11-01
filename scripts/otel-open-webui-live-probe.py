"""Separate-process W3C production Open WebUI version-route probe.

No login/user data, model calls, DB changes or response bodies fetched/logged.
Native app SERVER spans require independent Tempo verification.
"""
import contextlib
import io
import json
import logging
import urllib.request


def run():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.trace import Status, StatusCode
        from open_webui.utils.telemetry import instrumentors
        if not getattr(TracerProvider, '_homelab_source_privacy', False) or not getattr(instrumentors.Instrumentor, '_homelab_http_only_profile', False):
            raise ValueError('Early source-safe bootstrap absent')
        provider = TracerProvider(resource=Resource.create({'service.name': 'homelab-live-open-webui-probe'}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        tracer = provider.get_tracer('homelab.synthetic.production-open-webui')
        with tracer.start_as_current_span('homelab.synthetic.production-open-webui-request') as parent:
            parent.set_attribute('homelab.synthetic', True)
            parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory sampling root; not service failure'))
            trace_id = format(parent.get_span_context().trace_id, '032x')
            parent_id = format(parent.get_span_context().span_id, '016x')
            request = urllib.request.Request('http://127.0.0.1:8080/api/version', headers={'traceparent': '00-' + trace_id + '-' + parent_id + '-01'})
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
        flushed = provider.force_flush(timeout_millis=10000)
        provider.shutdown()
    report = {'success': status == 200 and flushed is True, 'httpStatus': status,
              'traceId': trace_id, 'parentSpanId': parent_id, 'actualProductionHttpProcessCalled': True,
              'w3cParentSentAcrossProcesses': True, 'userDataUsed': False,
              'modelCallsOrDatabaseChanges': False, 'responseBodiesFetched': False,
              'sourceSafeBootstrapVerified': True, 'privateKeysApiTokensOrBodiesPrinted': False,
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
