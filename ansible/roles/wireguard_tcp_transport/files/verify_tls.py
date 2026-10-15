import socket
import ssl
import struct
import sys


def connect(host, port, context, name):
    return context.wrap_socket(socket.create_connection((host, port), timeout=5), server_hostname=name)


def require_rejection(host, port, context, name):
    try:
        with connect(host, port, context, name):
            raise RuntimeError('Untrusted TLS connection unexpectedly succeeded')
    except ssl.SSLCertVerificationError:
        pass


def main():
    host, port, certificate, username = sys.argv[1:]
    port = int(port)
    name = 'wg-transport.socrat.internal'
    trusted = ssl.create_default_context(cafile=certificate)
    require_rejection(host, port, ssl.create_default_context(), name)
    require_rejection(host, port, trusted, 'invalid.test')
    user = username.encode()
    password = b'intentionally-invalid'
    auth = bytes([len(user)]) + user + bytes([len(password)]) + password
    feature = b'\x01' + struct.pack('!H', len(auth)) + auth
    for request in (b'\x01\x81\x00\x00', b'\x01\x81' + struct.pack('!H', len(feature)) + feature):
        with connect(host, port, trusted, name) as connection:
            connection.sendall(request)
            reply = b''
            while len(reply) < 4:
                chunk = connection.recv(4 - len(reply))
                if not chunk:
                    break
                reply += chunk
            if reply != b'\x01\x02\x00\x00':
                raise RuntimeError('Relay did not explicitly reject invalid authentication')
    print('TLS trust, hostname verification and relay authentication verified')


if __name__ == '__main__':
    main()
