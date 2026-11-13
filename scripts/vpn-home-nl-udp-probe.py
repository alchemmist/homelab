#!/usr/bin/env python3
"""One-shot <=45s HOME/NL transport diagnostic; no route/firewall/VPN mutations.

Not a VPN/authentication test. The NL responder only echoes one small fixed-shape
packet from the configured HOME public IP, then exits. No user data or keys.
"""
import argparse
import json
import secrets
import socket
import time

HOME='109.173.40.247'
NL='109.120.141.60'
LAN='192.168.0.23'
PREFIX=b'hl-home-nl-v1:'
PORT=51843

def valid(data,peer):
    return peer[0]==HOME and len(data)==len(PREFIX)+16 and data.startswith(PREFIX)

def server(timeout=40):
    assert socket.gethostname()=='socrat-2'
    assert 1<=timeout<=45
    deadline=time.monotonic()+timeout
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        # No SO_REUSE*: unknown listener ownership is a hard stop.
        s.bind((NL,PORT));s.settimeout(timeout)
        while time.monotonic()<deadline:
            s.settimeout(max(.01,deadline-time.monotonic()))
            try:data,peer=s.recvfrom(128)
            except socket.timeout:break
            if valid(data,peer):
                s.sendto(data,peer)
                return {'received_home_datagram':True,'bytes':len(data),'port':PORT}
    raise TimeoutError('No valid HOME datagram in bounded window')

def client():
    assert socket.gethostname()=='socrat-0'
    payload=PREFIX+secrets.token_bytes(16)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
        s.bind((LAN,0));s.connect((NL,PORT));s.settimeout(4)
        for _ in range(3):
            s.send(payload)
            try:reply=s.recv(128)
            except socket.timeout:continue
            if reply==payload:
                return {'direct_home_nl_udp_roundtrip':True,'port':PORT,'bytes':len(reply),
                        'vpn_or_client_failover_acceptance':False}
    raise TimeoutError('No matching UDP response')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['server','client']);a=p.parse_args()
    try:print(json.dumps(server() if a.mode=='server' else client()))
    except (OSError,AssertionError):raise SystemExit('Bounded diagnostic failed; no existing network state changed.') from None
