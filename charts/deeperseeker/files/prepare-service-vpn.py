import json, os, urllib.request
from urllib.parse import urlparse

ENDPOINT = os.environ["VPN_ENDPOINT"]
PORT = int(os.environ["VPN_PORT"])

def prepare(value: object) -> dict[str, object]:
    profiles = value if isinstance(value, list) else [value]
    outbounds = []
    for profile in profiles:
        if isinstance(profile, dict):
            outbounds.extend([item for item in profile.get("outbounds") or [] if item.get("protocol") == "vless"])
    if len(outbounds) != 1:
        raise SystemExit("PROFILE_COUNT")
    outbound = json.loads(json.dumps(outbounds[0]))
    settings = outbound.get("settings") or {}
    endpoint = (settings.get("vnext") or [{}])[0] or settings
    stream = outbound.get("streamSettings") or {}
    if endpoint.get("address") != ENDPOINT or endpoint.get("port") != PORT or stream.get("security") != "reality":
        raise SystemExit("PROFILE_POLICY")
    def check(node: object) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key == "allowInsecure" and item is not False:
                    raise SystemExit("TLS_POLICY")
                check(item)
        elif isinstance(node, list):
            for item in node:
                check(item)
    check(outbound)
    if not isinstance((stream.get("realitySettings") or {}).get("publicKey"), str):
        raise SystemExit("REALITY_IDENTITY")
    outbound["tag"] = "service-vpn"
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "tag": "browser-socks",
            "listen": "127.0.0.1",
            "port": 1080,
            "protocol": "socks",
            "settings": {"udp": False, "auth": "noauth"},
        }],
        "outbounds": [outbound],
    }

def main():
    raw = open("/vpn-identity/subscription-url", encoding="utf8").read().strip()
    url = urlparse(raw)
    if url.scheme != "https" or url.hostname != "vpn.alchemmist.xyz" or url.port or url.username or url.password or url.query or url.fragment:
        raise SystemExit("SUBSCRIPTION_POLICY")
    req = urllib.request.Request(raw, method="GET")
    with urllib.request.urlopen(req, timeout=8) as response:
        if response.status != 200:
            raise SystemExit("SUBSCRIPTION_HTTP")
        body = response.read(262145)
    if len(body) > 262144:
        raise SystemExit("SUBSCRIPTION_SIZE")
    config = prepare(json.loads(body.decode()))
    tmp = "/vpn-runtime/client.json.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(config, handle)
    os.rename(tmp, "/vpn-runtime/client.json")
    print("VPN_SUBSCRIPTION_PREPARED")

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        print("VPN_SUBSCRIPTION_PREPARE_FAILED")
        raise
    except Exception:
        print("VPN_SUBSCRIPTION_PREPARE_FAILED")
        raise SystemExit(1)
