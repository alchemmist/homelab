"""Pinned-runtime SDK guard invariants; synthetic in-memory data only."""
import math


def check(guard):
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.sdk.util.instrumentation import InstrumentationScope
    from opentelemetry.trace import Link, SpanContext, SpanKind, Status, StatusCode, TraceFlags
    context = SpanContext(0x12345678901234567890123456789012, 0x1234567890123456, False, TraceFlags(1))
    parent = SpanContext(context.trace_id, 0x2234567890123456, True, TraceFlags(1))
    scope = InstrumentationScope('synthetic.native', '1.0')
    marker = 'OTEL_SYNTHETIC_PRIVATE_EXCEPTION_CONTENT'
    original = ReadableSpan(name='llm_request', context=context, parent=parent,
        resource=Resource({'service.name': 'synthetic-invariants', 'secret': marker}, schema_url='https://schema.test'),
        attributes={'normal': 'kept', 'zero': 0, 'false': False, 'negative_zero': -0.0,
                    'nan': float('nan'), 'exception.message': marker, 'http.url': 'https://user:password@example.test/path?token=value'},
        events=[Event('exception', {'exception.message': marker, 'exception.stacktrace': marker, 'exception.type': 'ValueError'}, timestamp=2000)],
        links=[Link(parent, {'normal': 1, 'authorization': marker})], kind=SpanKind.SERVER,
        status=Status(StatusCode.ERROR, marker), start_time=1000, end_time=5000, instrumentation_scope=scope)
    redacted = guard.redact_span(original)
    checks = {
        'contextIdentityPreserved': redacted.context == original.context,
        'parentIdentityPreserved': redacted.parent == original.parent,
        'timestampsPreserved': (redacted.start_time, redacted.end_time) == (1000, 5000),
        'spanNameKindAndErrorCodePreserved': redacted.name == original.name and redacted.kind == original.kind and redacted.status.status_code == StatusCode.ERROR,
        'ordinaryAttributesPreserved': redacted.attributes['normal'] == 'kept' and redacted.attributes['zero'] == 0 and redacted.attributes['false'] is False,
        'specialFloatValuesPreserved': math.copysign(1, redacted.attributes['negative_zero']) == -1 and math.isnan(redacted.attributes['nan']),
        'scopeAndResourceIdentityPreserved': redacted.instrumentation_scope is scope and redacted.resource.attributes['service.name'] == original.resource.attributes['service.name'] and redacted.resource.schema_url == original.resource.schema_url,
        'linkAndEventTimestampsPreserved': redacted.links[0].context == parent and redacted.events[0].timestamp == 2000,
        'privateFieldsAbsentBeforeDownstreamProcessor': marker not in redacted.to_json() and 'password' not in redacted.to_json() and 'token=value' not in redacted.to_json(),
        'originalNotMutated': original.status.description == marker and original.attributes['exception.message'] == marker,
    }
    if not all(checks.values()):
        raise ValueError('Pinned-runtime source privacy invariants failed')
    return checks
