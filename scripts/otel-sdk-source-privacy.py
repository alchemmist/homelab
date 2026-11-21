"""Opt-in in-process Python SDK processor guard; NOT a gateway or SDK fork.

Uses public SDK ReadableSpan/SpanProcessor/TracerProvider extension APIs.
A redacted copy is delivered to every registered downstream processor BEFORE
BatchSpanProcessor queue admission. Original exceptions may transiently exist
inside the application's SDK; never claim this prevents all in-memory creation.
Prototype only until pinned-runtime canaries and maintained bootstrap pass.
"""
import re
from urllib.parse import urlsplit, urlunsplit

PRIVATE_KEY = re.compile(r'authorization|password|secret|token|cookie|prompt|completion|request[.]body|response[.]body|gen_ai[.](input|output|system_instructions)|db[.](statement|query[.]text)|(?:exception|error)[.](message|stacktrace)', re.I)
URL_KEYS = {'url.full', 'http.url', 'http.target', 'url.query'}


def safe_url(value):
    if not isinstance(value, str):
        return value
    if value.startswith(('http://', 'https://')):
        try:
            parsed = urlsplit(value)
            host = parsed.hostname or ''
            if ':' in host:
                host = '[' + host + ']'
            if parsed.port is not None:
                host += ':' + str(parsed.port)
            return urlunsplit((parsed.scheme, host, parsed.path, '<redacted>' if parsed.query else '', ''))
        except ValueError:
            return '<redacted-invalid-url>'
    return value.split('?', 1)[0] + ('?<redacted>' if '?' in value else '')


def attributes(values):
    return {key: ('<redacted>' if key == 'url.query' else safe_url(value)) if key in URL_KEYS else value
            for key, value in (values or {}).items() if not PRIVATE_KEY.search(key)}


def safe_name(value):
    return re.sub(r'https?://[^\s]+', lambda match: safe_url(match.group()), value)


def redact_span(span):
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import Event, ReadableSpan
    from opentelemetry.trace import Link, Status
    return ReadableSpan(name=safe_name(span.name), context=span.context, parent=span.parent,
        resource=Resource(attributes(span.resource.attributes), schema_url=span.resource.schema_url),
        attributes=attributes(span.attributes),
        events=[Event(safe_name(event.name), attributes(event.attributes), event.timestamp) for event in span.events],
        links=[Link(link.context, attributes(link.attributes)) for link in span.links],
        kind=span.kind, status=Status(span.status.status_code), start_time=span.start_time, end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope)


def activate():
    from opentelemetry import trace
    from opentelemetry.sdk import trace as sdk
    if getattr(sdk.TracerProvider, '_homelab_source_privacy', False):
        return
    if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
        raise ValueError('Source privacy guard must activate before any real tracer provider')
    class BeforeQueuePrivacy(sdk.SpanProcessor):
        def __init__(self, downstream):
            self.downstream = downstream
        def on_start(self, span, parent_context=None):
            self.downstream.on_start(span, parent_context=parent_context)
        def on_end(self, span):
            # No exception fallback: never forward the original unredacted span.
            self.downstream.on_end(redact_span(span))
        def shutdown(self):
            self.downstream.shutdown()
        def force_flush(self, timeout_millis=30000):
            return self.downstream.force_flush(timeout_millis=timeout_millis)
    original = sdk.TracerProvider
    class SourcePrivateTracerProvider(original):
        _homelab_source_privacy = True
        def add_span_processor(self, processor):
            super().add_span_processor(BeforeQueuePrivacy(processor))
    # Factory substitution is deliberately explicit and must happen before app
    # imports. This changes application bootstrap, not any installed SDK files.
    sdk.TracerProvider = SourcePrivateTracerProvider
