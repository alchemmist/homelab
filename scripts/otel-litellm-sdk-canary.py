"""Isolated native LiteLLM SDK privacy/mTLS canary, not production SDK coverage.

Only a synthetic mock completion: no real LLM request, user data or API token.
SDK metric/event exporters stay disabled. The synthetic root is deliberately an
ERROR sampling canary, not an assertion that a real application failed.
"""
import contextlib
import io
import json
import logging
import time


def run():
    logging.disable(logging.CRITICAL)
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
            raise ValueError('Duplicate metrics or message events must not be enabled')
        source_audit = {'endedSpans': 0, 'sensitiveSyntheticContentFoundAtSource': False}
        class SourcePrivacyAudit(SpanProcessor):
            def on_start(self, span, parent_context=None):
                pass

            def on_end(self, span):
                source_audit['endedSpans'] += 1
                serialized = span.to_json()
                if any(marker in serialized for marker in ['OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED', 'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED', 'otel-canary-not-a-real-credential']):
                    source_audit['sensitiveSyntheticContentFoundAtSource'] = True

            def shutdown(self):
                pass

            def force_flush(self, timeout_millis=30000):
                return True
        handler._tracer_provider.add_span_processor(SourcePrivacyAudit())
        litellm.callbacks = [handler]
        tracer = trace.get_tracer('homelab.synthetic.litellm-validation')
        with tracer.start_as_current_span('homelab.synthetic.litellm-sdk-validation') as parent:
            parent.set_attribute('homelab.synthetic', True)
            parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory-sampling canary'))
            trace_id = format(parent.get_span_context().trace_id, '032x')
            parent_id = format(parent.get_span_context().span_id, '016x')
            litellm.completion(model='openai/gpt-4o-mini',
                               messages=[{'role': 'user', 'content': 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED'}],
                               mock_response='OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED',
                               api_key='otel-canary-not-a-real-credential',
                               metadata={'litellm_parent_otel_span': parent})
            # Give the library's bounded asynchronous logging callback a chance to finish.
            time.sleep(3)
        flushed = handler._tracer_provider.force_flush(timeout_millis=10000)
    valid = flushed is True and source_audit['endedSpans'] >= 2 and not source_audit['sensitiveSyntheticContentFoundAtSource']
    print(json.dumps({'success': valid, 'traceId': trace_id, 'parentSpanId': parent_id, 'sourcePrivacyAudit': source_audit,
                      'mockProviderOnly': True, 'realLlmRequests': 0, 'realApiTokensUsed': False,
                      'dedicatedClientMtlsCredentialUsed': True,
                      'productionApplicationSdkCoverageVerified': False,
                      'backendInternalChildSpanAndPrivacyVerificationStillRequired': True}))
    if not valid:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(json.dumps({'success': False, 'errorType': type(error).__name__, 'realLlmRequests': 0,
                          'productionApplicationSdkCoverageVerified': False}))
        raise SystemExit(1)
