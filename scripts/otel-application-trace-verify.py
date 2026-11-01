"""Verify isolated native SDK child spans and negative synthetic-content tests.

This is NOT certification of production application SDK coverage. Raw response
stays root-only; stdout contains only span names/counts, IDs and booleans.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import ssl
import urllib.request


def identifier(value):
    if re.fullmatch(r'[0-9a-fA-F]{16}|[0-9a-fA-F]{32}', value):
        return value.lower()
    return base64.b64decode(value, validate=True).hex()


def summarize(document, trace_id, parent_id, service_name='homelab-litellm-sdk-canary', root_name='homelab.synthetic.litellm-sdk-validation', child_name=None):
    text = json.dumps(document)
    forbidden = ['OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED',
                 'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED',
                 'otel-canary-not-a-real-credential']
    spans = []
    services = set()

    def walk(value):
        if isinstance(value, dict):
            for entry in value.get('attributes', []):
                if entry.get('key') == 'service.name':
                    service = entry.get('value', {}).get('stringValue')
                    if service:
                        services.add(service)
            if all(key in value for key in ['traceId', 'spanId', 'name']):
                spans.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(document)
    children = [span for span in spans if span.get('parentSpanId') and identifier(span['traceId']) == trace_id and identifier(span['parentSpanId']) == parent_id and span['name'] != root_name and (child_name is None or span['name'] == child_name)]
    roots = [span for span in spans if identifier(span['spanId']) == parent_id and identifier(span['traceId']) == trace_id and span['name'] == root_name]
    report = {'success': bool(roots and children) and service_name in services and not any(marker in text for marker in forbidden),
              'traceId': trace_id, 'parentSpanId': parent_id, 'spanCount': len(spans),
              'serviceNames': sorted(services), 'internalLibraryChildSpanNames': sorted({span['name'] for span in children}),
              'internalLibraryChildVerified': bool(children), 'sensitiveSyntheticContentFound': any(marker in text for marker in forbidden),
              'productionApplicationSdkCoverageVerified': False, 'mockProviderOnly': True,
              'dedicatedClientMtlsCredentialUsed': True, 'realLlmApiTokensUsed': False}
    return report


def summarize_production_litellm(document, trace_id, parent_id, inference=False):
    records = []
    def walk(value, service=None):
        if isinstance(value, dict):
            resource = value.get('resource', {})
            for attribute in resource.get('attributes', []):
                if attribute.get('key') == 'service.name':
                    service = attribute.get('value', {}).get('stringValue')
            if all(key in value for key in ['traceId', 'spanId', 'name']) and identifier(value['traceId']) == trace_id:
                records.append((value, service))
            for child in value.values():
                walk(child, service)
        elif isinstance(value, list):
            for child in value:
                walk(child, service)
    walk(document)
    by_id = {identifier(span['spanId']): span for span, _ in records}
    roots = [span for span, service in records if service == 'homelab-live-sdk-probe' and identifier(span['spanId']) == parent_id and span['name'] == 'homelab.synthetic.live-sdk-validation']
    def descendant(span):
        if identifier(span['spanId']) == parent_id:
            return False
        seen = {identifier(span['spanId'])}
        while span.get('parentSpanId'):
            parent = identifier(span['parentSpanId'])
            if parent == parent_id:
                return True
            if parent in seen or parent not in by_id:
                return False
            seen.add(parent)
            span = by_id[parent]
        return False
    children = [span for span, service in records if service == 'litellm' and descendant(span)]
    private_found = any(marker in json.dumps(document) for marker in ['OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED', 'OTEL_CANARY_PRIVATE_RESPONSE_MUST_NOT_BE_CAPTURED', 'otel-canary-not-a-real-credential'])
    native_vllm = [span for span, service in records if service == 'vllm' and span['name'] == 'llm_request' and descendant(span)]
    valid = len(roots) == 1 and len(by_id) == len(records) and bool(children) and not private_found and any(span['name'] == 'Received Proxy Server Request' for span in children)
    if inference:
        valid = valid and any(span['name'] == 'litellm_request' for span in children)
    return {'success': valid, 'traceId': trace_id, 'parentSpanId': parent_id,
            'spanCount': len(records), 'serviceNames': sorted({service for _, service in records if service}),
            'productionInternalChildSpanNames': sorted({span['name'] for span in children}),
            'productionLitellmHttpAuthRouterErrorPathVerified': valid and not inference,
            'sensitiveSyntheticContentFound': private_found,
            'nativeVllmDescendantInSameTraceVerified': bool(native_vllm) and valid,
            'crossProcessW3cParentChildVerified': valid, 'productionInferenceSuccessPathVerified': valid and inference,
            'allApplicationSdkCoverageComplete': False, 'ingressSpansUsedAsInternalSdkProof': False}



def summarize_native_production(document, trace_id, parent_id, root_service='homelab-live-vllm-probe', root_name='homelab.synthetic.production-vllm-request', target_service='vllm', target_name='llm_request', require_server_kind=False):
    records = []
    def walk(value, service=None):
        if isinstance(value, dict):
            for attribute in value.get('resource', {}).get('attributes', []):
                if attribute.get('key') == 'service.name':
                    service = attribute.get('value', {}).get('stringValue')
            if all(key in value for key in ['traceId', 'spanId', 'name']) and identifier(value['traceId']) == trace_id:
                records.append((value, service))
            for child in value.values():
                walk(child, service)
        elif isinstance(value, list):
            for child in value:
                walk(child, service)
    walk(document)
    roots = [span for span, service in records if service == root_service and identifier(span['spanId']) == parent_id and span['name'] == root_name]
    children = [span for span, service in records if service == target_service and span['name'] == target_name and span.get('parentSpanId') and identifier(span['parentSpanId']) == parent_id and (not require_server_kind or span.get('kind') in [2, 'SPAN_KIND_SERVER', 'SERVER'])]
    private_found = 'OTEL_CANARY_PRIVATE_CONTENT_MUST_NOT_BE_CAPTURED' in json.dumps(document)
    unique = len({identifier(span['spanId']) for span, _ in records}) == len(records)
    valid = len(roots) == 1 and bool(children) and unique and not private_found
    return {'success': valid, 'traceId': trace_id, 'parentSpanId': parent_id, 'spanCount': len(records),
            'serviceNames': sorted({service for _, service in records if service}),
            'productionNativeChildSpanNames': sorted({span['name'] for span in children}),
            'nativeRequestSpanKinds': sorted({str(span.get('kind')) for span in children}),
            'productionNativeRequestTracingVerified': valid, 'crossProcessW3cParentChildVerified': valid,
            'syntheticPromptFoundInBackend': private_found, 'allApplicationSdkCoverageComplete': False,
            'successfulHttpInferenceMustBeProvenSeparately': True, 'ingressSpansUsedAsInternalSdkProof': False}


def summarize_production_vllm(document, trace_id, parent_id):
    report = summarize_native_production(document, trace_id, parent_id)
    report['productionVllmNativeRequestTracingVerified'] = report['success']
    return report


def summarize_production_open_webui(document, trace_id, parent_id):
    report = summarize_native_production(document, trace_id, parent_id,
        'homelab-live-open-webui-probe', 'homelab.synthetic.production-open-webui-request', 'open-webui', 'GET /api/version', require_server_kind=True)
    report.update(productionOpenWebuiFastapiSdkPathVerified=report['success'], productionOpenWebuiInferencePathVerified=False)
    return report


def run(trace_id, parent_id, output, production_litellm=False, vllm_canary=False, production_vllm=False, open_webui_canary=False, production_open_webui=False, production_litellm_inference=False):
    os.umask(0o077)
    if os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{32}', trace_id) or not re.fullmatch('[0-9a-f]{16}', parent_id):
        raise ValueError('Protected valid SDK canary identity required')
    output.mkdir(mode=0o700)
    tls = Path('/var/lib/homelab-otel/tls')
    context = ssl.create_default_context(cafile=str(tls / 'ca.crt'))
    context.load_cert_chain(str(tls / 'client.crt'), str(tls / 'client.key'))
    request = urllib.request.Request('https://10.250.0.3:3200/api/traces/' + trace_id, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(request, context=context, timeout=20) as response:
        body = response.read(8 * 1024**2 + 1)
    if len(body) > 8 * 1024**2:
        raise ValueError('SDK canary trace exceeds bounded inspection budget')
    document = json.loads(body)
    (output / 'trace-private.json').write_text(json.dumps(document))
    if production_litellm_inference:
        report = summarize_production_litellm(document, trace_id, parent_id, inference=True)
    elif production_open_webui:
        report = summarize_production_open_webui(document, trace_id, parent_id)
    elif production_vllm:
        report = summarize_production_vllm(document, trace_id, parent_id)
    elif production_litellm:
        report = summarize_production_litellm(document, trace_id, parent_id)
    elif open_webui_canary:
        report = summarize(document, trace_id, parent_id, 'homelab-open-webui-sdk-canary', 'homelab.synthetic.open-webui-validation', 'POST /synthetic')
        report.update(productionOpenWebuiSdkCoverageVerified=False, isolatedNativeSetupOnly=True, realInferenceRequests=0)
    elif vllm_canary:
        report = summarize(document, trace_id, parent_id, 'homelab-vllm-sdk-canary', 'homelab.synthetic.vllm-validation', 'llm_request')
        report.update(mockProviderOnly=False, syntheticRequestStateOnly=True, productionVllmSdkCoverageVerified=False, gpuEngineStarted=False)
    else:
        report = summarize(document, trace_id, parent_id)
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    if not report['success']:
        raise ValueError('Internal SDK child or negative privacy proof did not pass')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--trace-id', required=True)
    parser.add_argument('--parent-id', required=True)
    parser.add_argument('--output', type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--production-litellm', action='store_true')
    modes.add_argument('--production-litellm-inference', action='store_true')
    modes.add_argument('--vllm-canary', action='store_true')
    modes.add_argument('--production-vllm', action='store_true')
    modes.add_argument('--open-webui-canary', action='store_true')
    modes.add_argument('--production-open-webui', action='store_true')
    args = parser.parse_args()
    run(args.trace_id, args.parent_id, args.output, args.production_litellm, args.vllm_canary, args.production_vllm, args.open_webui_canary, args.production_open_webui, args.production_litellm_inference)
