#!/usr/bin/env python3
"""One bounded credential-free probe per owned HTTPS entrance; never change DNS.

Forced entry IP preserves Host/SNI/certificate verification. This is NOT ordinary
DNS/failover proof. Self/public hairpin checks are explicitly local-only evidence.
"""
import argparse
import http.client
import json
import socket
import ssl
import time
import urllib.parse

HOST = 'auth.socrat.alchemmist.xyz'
PATH = '/application/o/rancher/.well-known/openid-configuration'
ISSUER = 'https://' + HOST + '/application/o/rancher/'
ENTRIES = {'home': '109.173.40.247', 'vps': '109.120.141.60', 'internal': '192.168.0.250'}


def valid_discovery(data):
    if not isinstance(data, dict) or data.get('issuer') != ISSUER: return False
    for key in ['authorization_endpoint', 'token_endpoint', 'jwks_uri']:
        value=data.get(key)
        if not isinstance(value, str): return False
        try:
            url=urllib.parse.urlsplit(value)
            if url.scheme != 'https' or url.hostname != HOST or url.username or url.password or url.port not in (None,443): return False
        except ValueError: return False
    return True


def probe(entry, vantage, timeout=3):
    if entry not in ENTRIES or vantage not in ['home', 'vps', 'workstation', 'external']:
        raise ValueError('Unknown owned entry or vantage')
    if entry=='internal' and vantage!='home': raise ValueError('Private LAN probe is home-only')
    started=time.monotonic(); raw=None; tls=None; response=None; phase='tcp'
    result={'entry':entry,'vantage':vantage,'checked_at':int(time.time()),'tcp_ok':False,'tls_ok':False,'http_ok':False,'backend_ok':False,
            'local_only':entry=='internal' or entry==vantage or vantage=='workstation',
            'evidence':'forced-ip-host-sni; not normal DNS or client-failover acceptance'}
    try:
        raw=socket.create_connection((ENTRIES[entry],443),timeout=timeout);result['tcp_ok']=True;phase='tls'
        tls=ssl.create_default_context().wrap_socket(raw,server_hostname=HOST);result['tls_ok']=True;phase='http'
        tls.sendall(('GET '+PATH+' HTTP/1.1\r\nHost: '+HOST+'\r\nConnection: close\r\nAccept: application/json\r\n\r\n').encode())
        response=http.client.HTTPResponse(tls);response.begin();result['http_status']=response.status
        result['http_ok']=response.status==200;phase='body';body=response.read(65537);result['body_bytes']=len(body)
        if len(body)>65536: result['failure_kind']='body_bound'
        elif not result['http_ok']: result['failure_kind']='http_status'
        else:
            phase='backend_schema';result['backend_ok']=valid_discovery(json.loads(body))
            if not result['backend_ok']:result['failure_kind']='unexpected_discovery'
    except ssl.SSLCertVerificationError:result['failure_kind']='tls_certificate'
    except ssl.SSLError:result['failure_kind']='tls_error'
    except TimeoutError:result['failure_kind']='timeout'
    except ConnectionRefusedError:result['failure_kind']='connection_refused'
    except (ValueError, TypeError):result['failure_kind']='invalid_json_or_schema'
    except (OSError,http.client.HTTPException):result['failure_kind']='transport_or_http_error'
    finally:
        if response:response.close()
        if tls:tls.close()
        elif raw:raw.close()
    if not result['backend_ok']:result['failure_phase']=phase
    result['duration_ms']=round((time.monotonic()-started)*1000)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vantage',required=True,choices=['home','vps','workstation','external'])
    p.add_argument('--entry',action='append',choices=ENTRIES)
    args=p.parse_args()
    entries=args.entry or (['home','vps','internal'] if args.vantage=='home' else ['home','vps'])
    results=[probe(entry,args.vantage) for entry in dict.fromkeys(entries)]
    print(json.dumps({'writes':False,'credentials_used':False,'results':results},sort_keys=True))


if __name__=='__main__':main()
