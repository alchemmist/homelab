"""Opt-in pinned Open WebUI source-safe HTTP-only instrumentation profile.

Replaces the native Instrumentor factory BEFORE native setup imports it, not
installed application files. Uses official HTTP instrumentors without native
Redis-command/SQL-statement/full-URL/error-message hooks. Not blanket unsupported
coverage: DB/Redis tracing is intentionally disabled pending source-safe hooks.
SDK source privacy guard must already be active before this module installs.
"""
import sys


def activate():
    from opentelemetry.sdk.trace import TracerProvider
    if not getattr(TracerProvider, '_homelab_source_privacy', False):
        raise ValueError('Early before-export source guard must be active first')
    if 'open_webui.utils.telemetry.setup' in sys.modules:
        raise ValueError('Native setup already imported; never allow late unsafe-hook fallback')
    from open_webui.utils.telemetry import instrumentors as native
    if getattr(native.Instrumentor, '_homelab_http_only_profile', False):
        return
    class SourceSafeHttpInstrumentor(native.Instrumentor):
        _homelab_http_only_profile = True
        def _instrument(self, **kwargs):
            self.instrumentors = []
            native.FastAPIInstrumentor.instrument_app(app=self.app,
                http_capture_headers_server_request=[], http_capture_headers_server_response=[])
            for cls in [native.RequestsInstrumentor, native.HTTPXClientInstrumentor, native.AioHttpClientInstrumentor]:
                instrumentor = cls()
                instrumentor.instrument()
                self.instrumentors.append(instrumentor)
        def _uninstrument(self, **kwargs):
            native.FastAPIInstrumentor.uninstrument_app(self.app)
            for instrumentor in getattr(self, 'instrumentors', []):
                instrumentor.uninstrument()
    native.Instrumentor = SourceSafeHttpInstrumentor
