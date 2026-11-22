#!/usr/bin/env python3
"""Real bounded UDP Binding + forbidden TURN Allocate probes. No credentials.

Run from an external caller AND both existing hosts. Expected source is the
observed source address at this listener, not an HTTPS proxy's egress address.
"""

import argparse
import ipaddress
import json
import os
import socket
import struct

COOKIE = 0x2112A442
PUBLIC = "109.120.141.60"
HOME = "109.173.40.247"


def request(method, attrs=b""):
    return struct.pack("!HHI", method, len(attrs), COOKIE) + os.urandom(12) + attrs


def parse_binding(packet, response):
    if (
        len(response) < 20
        or response[:2] != b"\x01\x01"
        or response[4:20] != packet[4:20]
        or len(response) != 20 + struct.unpack("!H", response[2:4])[0]
    ):
        msg = "invalid Binding response/transaction"
        raise ValueError(msg)
    offset = 20
    attrs = {}
    while offset < len(response):
        if offset + 4 > len(response):
            msg = "truncated attribute header"
            raise ValueError(msg)
        kind, length = struct.unpack("!HH", response[offset : offset + 4])
        if offset + 4 + length > len(response):
            msg = "truncated attribute value"
            raise ValueError(msg)
        attrs[kind] = response[offset + 4 : offset + 4 + length]
        offset += 4 + ((length + 3) // 4) * 4
    mapped = attrs.get(0x20, b"")
    if len(mapped) != 8 or mapped[:2] != b"\x00\x01":
        msg = "missing IPv4 XOR-MAPPED-ADDRESS"
        raise ValueError(msg)
    address = socket.inet_ntoa(
        bytes(v ^ c for v, c in zip(mapped[4:], struct.pack("!I", COOKIE), strict=True))
    )
    port = struct.unpack("!H", mapped[2:4])[0] ^ (COOKIE >> 16)
    return {"address": address, "port": port}


def exchange(address, packet, timeout):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (address, 3478))
        try:
            reply, remote = sock.recvfrom(2048)
            if remote != (address, 3478):
                msg = "reply from unexpected source"
                raise ValueError(msg)
            return reply
        except TimeoutError:
            return None


def check(expected=None, timeout=3):
    packet = request(1)
    response = exchange(PUBLIC, packet, timeout)
    if response is None:
        msg = "advertised STUN listener timed out"
        raise ValueError(msg)
    mapped = parse_binding(packet, response)
    ip = ipaddress.ip_address(mapped["address"])
    if not ip.is_global:
        msg = "STUN returned nonpublic source: investigate service SNAT/hairpin"
        raise ValueError(msg)
    if expected and mapped["address"] != expected:
        msg = "observed source differs from explicitly expected caller public IP"
        raise ValueError(msg)
    # RFC5766 REQUESTED-TRANSPORT=UDP. STUN-only must not allocate a TURN relay.
    allocate = request(3, struct.pack("!HHBBBB", 0x19, 4, 17, 0, 0, 0))
    result = exchange(PUBLIC, allocate, timeout)
    if result is not None:
        if len(result) < 20 or result[4:20] != allocate[4:20] or result[:2] != b"\x01\x13":
            msg = "TURN not demonstrably rejected (or unexpected response)"
            raise ValueError(msg)
    home = exchange(HOME, request(1), timeout)
    if home is not None:
        msg = "home entrance unexpectedly answered; inspect before advertising DNS"
        raise ValueError(msg)
    return {
        "advertised_uri": "stun:" + PUBLIC + ":3478",
        "binding_transaction_valid": True,
        "xor_mapped": mapped,
        "expected_caller_verified": expected is not None,
        "TURN_allocate": "ignored" if result is None else "error",
        "home_entrance": "timeout-not-advertised",
        "VPN_acceptance": False,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--expected-source", type=ipaddress.IPv4Address)
    a = p.parse_args()
    print(json.dumps(check(str(a.expected_source) if a.expected_source else None), indent=2))


if __name__ == "__main__":
    main()
