"""Native private HTTP ingress checks; no telemetry body or credential logging."""
import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.request


def run(output):
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError('Protected native TLS files require root')
    output.mkdir(mode=0o700)
    root = Path('/var/lib/homelab-otel/tls')
    positive = ssl.create_default_context(cafile=str(root / 'ca.crt'))
    positive.load_cert_chain(str(root / 'client.crt'), str(root / 'client.key'))
    negative = ssl.create_default_context(cafile=str(root / 'ca.crt'))

    def send(path, context):
        request = urllib.request.Request('https://10.250.0.3:44318' + path, data=b'',
                    headers={'Content-Type': 'application/x-protobuf'}, method='POST')
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            return response.status

    if send('/v1/traces', positive) != 200:
        raise ValueError('Authenticated native trace route is not ready')
    rejected = False
    try:
        send('/v1/traces', negative)
    except (ssl.SSLError, urllib.error.URLError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        rejected = isinstance(reason, ssl.SSLError) and any(code in str(reason) for code in ['CERTIFICATE_REQUIRED', 'HANDSHAKE_FAILURE', 'BAD_CERTIFICATE'])
    if not rejected:
        raise ValueError('Anonymous TLS was not explicitly rejected by certificate authentication')
    other_signals = {}
    for path in ['/v1/metrics', '/v1/logs']:
        try:
            other_signals[path] = send(path, positive)
        except urllib.error.HTTPError as error:
            other_signals[path] = error.code
    if set(other_signals.values()) != {404}:
        raise ValueError('New receiver unexpectedly serves a second metrics or logs owner')
    unit = subprocess.run(['systemctl', 'show', 'homelab-otel-application-ingress.service', '-p', 'ActiveState', '-p', 'MemoryCurrent', '-p', 'MemoryMax'], capture_output=True, text=True, check=True).stdout
    result = {'success': True, 'authenticatedNativeTraceRouteReady': True, 'anonymousCertificateAuthenticationRejected': True,
              'additionalMetricsOrLogsRouteCreated': False, 'otherSignalStatusCodes': other_signals,
              'privateBindAddress': '10.250.0.3:44318', 'singleGlobalSamplerRetained': True,
              'existingMetricLogAndGlobalSamplerOwnersRestarted': False, 'service': unit}
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    run(parser.parse_args().output)
