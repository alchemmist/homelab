#!/usr/bin/env python3
"""One bounded unauthenticated HTTPS check. No retries, proxy changes or tunnel claims.
Run manually from approved Russian fixed/mobile and external vantage points.
Use public URLs only: NEVER supply subscription, share, API or credential URLs.
"""
import argparse
import datetime
import hashlib
import http.client
import json
import socket
import ssl
import time
import urllib.parse

ALLOWED_HOSTS = {'wiki.socrat.alchemmist.xyz', 'grafana.socrat.alchemmist.xyz', 'vpn.alchemmist.xyz'}
MAX_BYTES = 2 * 1024 * 1024


def endpoint(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(c in url for c in ('\r', '\n', '\x00'))):
        raise ValueError('Only approved public HTTPS endpoints on 443 without credentials/query/fragment')
    if parsed.hostname == 'vpn.alchemmist.xyz' and parsed.path not in ('', '/'):
        raise ValueError('VPN subscription/panel paths must not be used as diagnostic inputs')
    return parsed


def check(url, vantage, family=4):
    parsed = endpoint(url)
    result = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'vantage_label': vantage, 'family': family, 'host': parsed.hostname,
              'path_sha256': hashlib.sha256((parsed.path or '/').encode()).hexdigest(),
              'native_tunnel_test': False, 'automatic_recovery': False,
              'minimum_useful_transfer_bytes': 32768}
    stage = 'dns'
    start = time.monotonic()
    try:
        address = socket.getaddrinfo(parsed.hostname, 443, socket.AF_INET if family == 4 else socket.AF_INET6, socket.SOCK_STREAM)[0]
        result['address'] = address[4][0]
        stage = 'tcp'
        with socket.socket(address[0], socket.SOCK_STREAM) as raw:
            raw.settimeout(12)
            raw.connect(address[4])
            result['tcp_connected'] = True
            stage = 'tls'
            context = ssl.create_default_context()
            context.set_alpn_protocols(['http/1.1'])
            with context.wrap_socket(raw, server_hostname=parsed.hostname) as tls:
                result.update(tls_verified=True, tls_version=tls.version(), alpn=tls.selected_alpn_protocol())
                stage = 'https_transfer'
                request = 'GET ' + (parsed.path or '/') + ' HTTP/1.1\r\nHost: ' + parsed.hostname + '\r\nConnection: close\r\nUser-Agent: homelab-bounded-path-check/1\r\n\r\n'
                tls.sendall(request.encode('ascii'))
                with http.client.HTTPResponse(tls) as response:
                    response.begin()
                    result['http_status'] = response.status
                    try:
                        data = response.read(MAX_BYTES + 1)
                    except http.client.IncompleteRead as error:
                        result.update(received_bytes=len(error.partial), complete=False)
                        raise
                    result['received_bytes'] = len(data)
                    result['complete'] = len(data) <= MAX_BYTES and response.length in (None, 0)
                    result['complete_success_above_32k'] = bool(result['complete'] and len(data) > 32768 and response.status == 200)
        stage = None if result.get('complete') and result.get('http_status') == 200 else 'https_transfer'
    except Exception as error:
        result['error_type'] = type(error).__name__  # No raw response, URL or credentials.
    result['first_failed_stage'] = stage
    result['elapsed_seconds'] = round(time.monotonic() - start, 3)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://wiki.socrat.alchemmist.xyz/')
    parser.add_argument('--vantage', required=True, help='Non-sensitive ISP/ASN/network label, not a person identifier')
    parser.add_argument('--family', type=int, choices=(4, 6), default=4)
    args = parser.parse_args()
    print(json.dumps(check(args.url, args.vantage, args.family), sort_keys=True))


if __name__ == '__main__':
    main()
