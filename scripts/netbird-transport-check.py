#!/usr/bin/env python3
"""Bounded independent relay payload / STUN tests, no NetBird enrollment.

Run on socrat-0. Uses the existing private relay key only in memory to mint a
60-second auth token. Two transient raw relay sessions exchange a random nonce
across the two TLS entrances, then close. Creates no management peers/setupkeys,
no WireGuard interfaces/routes or grants. STUN failure is reported, not hidden.
This does NOT certify a usable VPN and does not replace management readiness.
"""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import time
import yaml
HOST='netbird.socrat.alchemmist.xyz'
ENTRANCES=['109.173.40.247','109.120.141.60']


class WS:
    def __init__(self,address):
        self.s=ssl.create_default_context().wrap_socket(socket.create_connection((address,443),timeout=10),server_hostname=HOST)
        self.s.settimeout(10);self.buffer=b''
        key=base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(('GET /relay HTTP/1.1\r\nHost: '+HOST+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: '+key+'\r\n\r\n').encode())
        data=b''
        while b'\r\n\r\n' not in data:
            chunk=self.s.recv(4096)
            if not chunk:raise ValueError('closed handshake')
            data+=chunk
            if len(data)>32768:raise ValueError('oversized handshake')
        headers,self.buffer=data.split(b'\r\n\r\n',1)
        if not headers.startswith(b'HTTP/1.1 101'):raise ValueError('relay upgrade rejected')
        expected=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
        if expected.lower() not in headers.lower():raise ValueError('wrong WS accept')
    def send(self,data,opcode=2):
        n=len(data);mask=os.urandom(4)
        head=bytes([0x80|opcode,0x80|n]) if n<126 else bytes([0x80|opcode,0xfe])+struct.pack('!H',n)
        self.s.sendall(head+mask+bytes(b^mask[i%4] for i,b in enumerate(data)))
    def read(self,n):
        while len(self.buffer)<n:
            data=self.s.recv(4096)
            if not data:raise ValueError('relay session closed')
            self.buffer+=data
        data,self.buffer=self.buffer[:n],self.buffer[n:];return data
    def receive(self):
        for _ in range(8):
            head=self.read(2);opcode=head[0]&15;n=head[1]&127
            if n==126:n=struct.unpack('!H',self.read(2))[0]
            if n==127:n=struct.unpack('!Q',self.read(8))[0]
            if n>16384:raise ValueError('oversized relay frame')
            data=self.read(n)
            if opcode==9:self.send(data,10);continue
            if opcode!=2:raise ValueError('unexpected relay frame')
            return data
        raise ValueError('no relay payload')
    def close(self):
        try:self.send(b'',8)
        finally:self.s.close()


def main():
    os.umask(0o077)
    config=yaml.safe_load((Path.home()/'.local/state/netbird-internal-stage/config.yaml').read_text())
    secret=hashlib.sha256(config['server']['authSecret'].encode()).digest()
    payload=str(int(time.time())+60).encode()
    token=b'\x01'+hmac.new(secret,payload,hashlib.sha256).digest()+payload
    ids=[b'sha-'+hashlib.sha256(os.urandom(32)).digest() for _ in range(2)]
    sessions=[]
    result={'management_enrollment':False,'trusted_TLS':True,'relay':{},'stun':{}}
    try:
        for address,identity in zip(ENTRANCES,ids):
            ws=WS(address);sessions.append(ws)
            ws.send(b'\x01\x06\x21\x12\xa4\x42'+identity+token)
            response=ws.receive()
            if response[:2]!=b'\x01\x07':raise ValueError('relay auth response mismatch')
        nonce=os.urandom(32)
        for source,destination in [(0,1),(1,0)]:
            sessions[source].send(b'\x01\x03'+ids[destination]+nonce)
            actual=sessions[destination].receive()
            if actual!=b'\x01\x03'+ids[source]+nonce:raise ValueError('relay payload mismatch')
        result['relay']={'both_entrances_authenticated':True,'bidirectional_cross_entrance_payload':True,'transient_sessions_closed':True}
    finally:
        for ws in sessions:ws.close()
    for address in ENTRANCES:
        transaction=os.urandom(12);packet=struct.pack('!HHI',1,0,0x2112A442)+transaction
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:
            s.settimeout(3);s.sendto(packet,(address,3478))
            try:
                response,_=s.recvfrom(2048)
                ok=len(response)>=20 and response[:2]==b'\x01\x01' and response[4:20]==packet[4:20]
                result['stun'][address]='binding-response-valid' if ok else 'invalid-response'
            except (TimeoutError,OSError):result['stun'][address]='not-available'
    result['usable_VPN_accepted']=False
    print(json.dumps(result,indent=2))
    path=Path.home()/'.local/state/netbird-internal-stage/journal/stage4-transport-check.json'
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:json.dump(result,f)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('BLOCKED: transport check stopped: '+type(exc).__name__+'; inspect implementation, never blindly retry')
        raise SystemExit(2)
