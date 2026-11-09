#!/usr/bin/env python3
"""Bounded native Signal bidi-header check over trusted public TLS (grpcio needed).

Sends HEADERS but no request DATA, like the real client. Unary GetServerKey alone
cannot catch HTTP/1.1 proxy fallback. Registers only a random transient Signal
identifier, cancels every stream, and never creates a management peer/setup key,
changes routes, reads credentials, or grants access. Does not certify VPN access.
"""
import argparse
import base64
import json
import os
import threading
import time

HOST = 'netbird.socrat.alchemmist.xyz'
ENTRANCES = ('109.173.40.247', '109.120.141.60')


def probe(address, timeout=6, grpc_module=None):
    if address not in ENTRANCES or not 1 <= timeout <= 10:
        raise ValueError('approved entrance and bounded timeout required')
    if grpc_module is None:
        import grpc as grpc_module
    grpc = grpc_module
    stop = threading.Event()

    def requests():
        # Keep the request side open WITHOUT yielding a message; do not half-close.
        stop.wait(timeout + 1)
        return
        yield b''

    channel = grpc.secure_channel(
        address + ':443', grpc.ssl_channel_credentials(),
        options=(('grpc.ssl_target_name_override', HOST), ('grpc.default_authority', HOST)))
    call = None
    start = time.monotonic()
    try:
        call = channel.stream_stream('/signalexchange.SignalExchange/ConnectStream')(
            requests(), metadata=(('x-wiretrustee-peer-id', base64.b64encode(os.urandom(32)).decode()),),
            timeout=timeout)
        metadata = call.initial_metadata()
        registered = any(k == 'x-wiretrustee-peer-registered' for k, _ in metadata)
        return {'entrance': address, 'registered_header': registered,
                'elapsed_s': round(time.monotonic() - start, 3),
                'rpc_code': 'OK' if registered else call.code().name}
    except grpc.RpcError as exc:
        return {'entrance': address, 'registered_header': False,
                'elapsed_s': round(time.monotonic() - start, 3), 'rpc_code': exc.code().name}
    finally:
        stop.set()
        if call is not None:
            call.cancel()
        channel.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entrance', action='append', choices=ENTRANCES)
    parser.add_argument('--timeout', type=int, choices=range(1, 11), default=6)
    args = parser.parse_args()
    results = [probe(address, args.timeout) for address in (args.entrance or ENTRANCES)]
    print(json.dumps({'signal_streams': results}))
    return 0 if all(r['registered_header'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
