"""Local-only Trojan/WebSocket compatibility fixture. Never use real profiles or routes."""

import re
from ipaddress import IPv4Address, IPv4Network

from ci.quality.moscow_www_split import VPN

ECHO = 19222
PATH = "/fixture-only"


def configs(password, wrong, peer):
    """Return ephemeral configs only; caller must keep all credentials out of output."""
    if password == wrong or not all(re.fullmatch(r"[0-9a-f]{64}", s) for s in (password, wrong)):
        msg = "expected distinct fixture credentials"
        raise ValueError(msg)
    address = IPv4Address(peer)
    if address not in IPv4Network("10.42.0.0/16"):
        msg = "expected disposable Pod address"
        raise ValueError(msg)
    stream = {"network": "ws", "security": "tls", "wsSettings": {"path": PATH}}
    server = {
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": 19443,
                "protocol": "trojan",
                "settings": {"clients": [{"password": password}]},
                "streamSettings": {
                    **stream,
                    "tlsSettings": {
                        "certificates": [
                            {"certificateFile": "/marker/vpn.crt", "keyFile": "/marker/vpn.key"}
                        ]
                    },
                },
            }
        ],
        "outbounds": [
            {"tag": "deny", "protocol": "blackhole"},
            {"tag": "echo", "protocol": "freedom"},
        ],
        "routing": {
            "rules": [
                {
                    "type": "field",
                    "ip": [str(address) + "/32"],
                    "port": str(ECHO),
                    "network": "tcp,udp",
                    "outboundTag": "echo",
                }
            ]
        },
    }

    def client(port, credential):
        return {
            "inbounds": [
                {
                    "listen": "127.0.0.1",
                    "port": port,
                    "protocol": "socks",
                    "settings": {"auth": "noauth", "udp": True, "ip": "127.0.0.1"},
                }
            ],
            "outbounds": [
                {
                    "protocol": "trojan",
                    "settings": {
                        "servers": [{"address": "127.0.0.1", "port": 18443, "password": credential}]
                    },
                    "streamSettings": {
                        **stream,
                        "tlsSettings": {
                            "serverName": VPN,
                            "disableSystemRoot": True,
                            "certificates": [
                                {"usage": "verify", "certificateFile": "/client/fixture-ca.crt"}
                            ],
                        },
                    },
                }
            ],
        }

    return server, client(19081, password), client(19082, wrong)
