#!/usr/bin/env python3
"""Turn one native 3x-ui JSON subscription into a loopback Xray client."""

import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "91.189.82.238"
PORT = 32053


def prepare(value, door):
    profiles = value if isinstance(value, list) else [value]
    candidates = []
    for profile in profiles:
        for outbound in (profile or {}).get("outbounds") or []:
            if outbound.get("protocol") == "vless":
                candidates.append(outbound)
    if len(candidates) != 1:
        raise RuntimeError("PROFILE_COUNT")
    outbound = json.loads(json.dumps(candidates[0]))
    settings = outbound.get("settings") or {}
    endpoint = (settings.get("vnext") or [settings])[0]
    stream = outbound.get("streamSettings") or {}
    if endpoint.get("address") != ENDPOINT or endpoint.get("port") != PORT:
        raise RuntimeError("PROFILE_POLICY")
    if stream.get("security") != "reality":
        raise RuntimeError("PROFILE_POLICY")
    if not isinstance((stream.get("realitySettings") or {}).get("publicKey"), str):
        raise RuntimeError("REALITY_IDENTITY")

    def check(item):
        if not isinstance(item, dict):
            return
        for key, nested in item.items():
            if key == "allowInsecure" and nested is not False:
                raise RuntimeError("TLS_POLICY")
            check(nested)

    check(outbound)
    outbound["tag"] = "service-vpn"
    if door:
        inbound = {
            "tag": "door",
            "listen": "127.0.0.1",
            "port": 18443,
            "protocol": "dokodemo-door",
            "settings": {"address": door, "port": 443, "network": "tcp"},
        }
    else:
        inbound = {
            "tag": "proxy",
            "listen": "127.0.0.1",
            "port": 18443,
            "protocol": "http",
        }
    return {"log": {"loglevel": "none"}, "inbounds": [inbound], "outbounds": [outbound]}


def main():
    raw = Path("/vpn-identity/subscription-url").read_text().strip()
    url = urllib.parse.urlparse(raw)
    if (
        url.scheme != "https"
        or url.hostname != "vpn.alchemmist.xyz"
        or url.port
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise RuntimeError("SUBSCRIPTION_POLICY")

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise RuntimeError("SUBSCRIPTION_REDIRECT")

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        NoRedirect(),
    )
    request = urllib.request.Request(raw, headers={"User-Agent": "homelab-service-vpn"})
    with opener.open(request, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError("SUBSCRIPTION_HTTP")
        body = response.read(262145)
    if len(body) > 262144:
        raise RuntimeError("SUBSCRIPTION_SIZE")
    config = prepare(json.loads(body), os.environ.get("VPN_DOOR") or "")
    temporary = Path("/vpn-runtime/client.json.tmp")
    temporary.write_text(json.dumps(config))
    os.chmod(temporary, 0o600)
    temporary.replace(Path("/vpn-runtime/client.json"))
    print("VPN_SUBSCRIPTION_PREPARED")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("VPN_SUBSCRIPTION_PREPARE_FAILED")
        raise SystemExit(1)
