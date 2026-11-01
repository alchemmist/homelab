"""Synthetic HTTP/ASGI native LiteLLM proxy canary; no production deployment change."""
import asyncio
import contextlib
import io
import json
import logging
from pathlib import Path


async def run():
    logging.disable(logging.CRITICAL)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import httpx
        import litellm
        from litellm.integrations.opentelemetry import OpenTelemetry
        from litellm.proxy import proxy_server
        from opentelemetry import trace
        from opentelemetry.sdk.trace import SpanProcessor
        from opentelemetry.trace import Status, StatusCode
        config = {'model_list': [{'model_name': 'otel-synthetic', 'litellm_params': {
                  'model': 'openai/gpt-4o-mini', 'api_key': 'otel-canary-not-a-real-credential',
                  'mock_response': 'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED'}}],
                  'general_settings': {'master_key': 'sk-otel-canary-not-a-real-credential'},
                  'litellm_settings': {'turn_off_message_logging': True, 'telemetry': False}}
        path = Path('/run/otel-test/proxy-canary-config.json')
        path.write_text(json.dumps(config))
        await proxy_server.initialize(config=str(path))
        litellm.turn_off_message_logging = True
        handler = OpenTelemetry()
        if handler.config.enable_metrics or handler.config.enable_events:
            raise ValueError('Duplicate metrics or message events must remain disabled')
        audit = {'endedSpans': 0, 'sensitiveSyntheticContentFoundAtSource': False}
        class PrivacyAudit(SpanProcessor):
            def on_start(self, span, parent_context=None):
                pass
            def on_end(self, span):
                audit['endedSpans'] += 1
                data = span.to_json()
                if any(marker in data for marker in ['OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED', 'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED', 'otel-canary-not-a-real-credential']):
                    audit['sensitiveSyntheticContentFoundAtSource'] = True
            def shutdown(self):
                pass
            def force_flush(self, timeout_millis=30000):
                return True
        handler._tracer_provider.add_span_processor(PrivacyAudit())
        litellm.callbacks = [handler]
        with trace.get_tracer('homelab.synthetic.proxy-validation').start_as_current_span('homelab.synthetic.litellm-sdk-validation') as parent:
            parent.set_attribute('homelab.synthetic', True)
            parent.set_status(Status(StatusCode.ERROR, 'synthetic mandatory-sampling canary'))
            trace_id = format(parent.get_span_context().trace_id, '032x')
            parent_id = format(parent.get_span_context().span_id, '016x')
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy_server.app), base_url='http://otel-canary.local') as client:
                response = await client.post('/v1/chat/completions', headers={
                    'Authorization': 'Bearer sk-otel-canary-not-a-real-credential',
                    'traceparent': '00-' + trace_id + '-' + parent_id + '-01'},
                    json={'model': 'otel-synthetic', 'messages': [{'role': 'user', 'content': 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED'}]})
                status = response.status_code
            await asyncio.sleep(3)
        flushed = handler._tracer_provider.force_flush(timeout_millis=10000)
    valid = status == 200 and flushed is True and audit['endedSpans'] >= 2 and not audit['sensitiveSyntheticContentFoundAtSource']
    print(json.dumps({'success': valid, 'traceId': trace_id, 'parentSpanId': parent_id, 'httpStatus': status,
                      'sourcePrivacyAudit': audit, 'realLlmRequests': 0, 'realApiTokensUsed': False,
                      'actualProxyAsgiRouteExercised': True, 'productionApplicationSdkCoverageVerified': False}))
    if not valid:
        raise SystemExit(1)


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except Exception as error:
        print(json.dumps({'success': False, 'errorType': type(error).__name__, 'realLlmRequests': 0,
                          'productionApplicationSdkCoverageVerified': False}))
        raise SystemExit(1)
