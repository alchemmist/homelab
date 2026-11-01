"""In-memory-only installed vLLM decorator negative privacy test.

No exporter/network, real request, GPU engine or model. Only booleans leave the
process; the synthetic exception text/stack is not emitted or persisted.
"""
import contextlib
import io
import json
import logging


def run():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        from vllm.tracing import instrument
        memory = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(memory))
        trace.set_tracer_provider(provider)
        marker = 'OTEL_SYNTHETIC_EXCEPTION_CONTENT_MUST_NOT_BE_CAPTURED'
        @instrument(span_name='homelab.synthetic.vllm-exception-validation')
        def synthetic_failure():
            raise ValueError(marker)
        try:
            synthetic_failure()
        except ValueError:
            pass
        spans = memory.get_finished_spans()
        if len(spans) != 1:
            raise RuntimeError('Native exception instrumentation was not exercised')
        span = spans[0]
        status_found = marker in (span.status.description or '')
        event_found = any(marker in str(dict(event.attributes or {})) for event in span.events)
        provider.shutdown()
    print(json.dumps({'testCompleted': True, 'nativeDefaultDecoratorExercised': True,
                      'syntheticExceptionInStatusDescription': status_found,
                      'syntheticExceptionInSpanEvents': event_found,
                      'sourceExceptionPrivacyGatePassed': not (status_found or event_found),
                      'testedExceptionPathSafeBeforeExporter': not (status_found or event_found),
                      'sourceGuardFactoryActive': getattr(TracerProvider, '_homelab_source_privacy', False),
                      'productionEnablementApproved': False,
                      'inMemoryOnly': True, 'telemetryNetworkExporterCreated': False,
                      'exceptionTextOrStackLogged': False, 'gpuEngineStarted': False,
                      'productionDeploymentChanged': False}))


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(json.dumps({'testCompleted': False, 'errorType': type(error).__name__, 'exceptionTextOrStackLogged': False}))
        raise SystemExit(1)
