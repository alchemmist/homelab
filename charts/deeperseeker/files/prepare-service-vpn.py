import json
import os
import urllib.request
from urllib.parse import urlparse

ENDPOINT = os.environ["VPN_ENDPOINT"]
PORT = int(os.environ["VPN_PORT"])


def vless_outbounds(profiles: list[object]) -> list[dict[str, object]]:
    """Collect every VLESS outbound from the parsed service profiles."""
    outbounds: list[dict[str, object]] = []
    for profile in profiles:
        if isinstance(profile, dict):
            outbounds.extend(
                [item for item in profile.get("outbounds") or [] if item.get("protocol") == "vless"]
            )
    return outbounds


def reject_unsafe_tls(node: object) -> None:
    """Reject any insecure TLS setting (e.g. allowInsecure) in the config."""
    if isinstance(node, dict):
        for key, item in node.items():
            if key == "allowInsecure" and item is not False:
                raise SystemExit("TLS_POLICY")
            reject_unsafe_tls(item)
    elif isinstance(node, list):
        for item in node:
            reject_unsafe_tls(item)


def validate_profile(outbound: dict[str, object]) -> None:
    """Enforce the pinned endpoint and Reality policy on one outbound."""
    settings_value = outbound.get("settings")
    settings = settings_value if isinstance(settings_value, dict) else {}
    endpoint = (settings.get("vnext") or [{}])[0] or settings
    stream_value = outbound.get("streamSettings")
    stream = stream_value if isinstance(stream_value, dict) else {}
    if (
        endpoint.get("address") != ENDPOINT
        or endpoint.get("port") != PORT
        or stream.get("security") != "reality"
    ):
        raise SystemExit("PROFILE_POLICY")
    reject_unsafe_tls(outbound)
    if not isinstance((stream.get("realitySettings") or {}).get("publicKey"), str):
        raise SystemExit("REALITY_IDENTITY")


def prepare(value):
    profiles = value if isinstance(value, list) else [value]
    outbounds = vless_outbounds(profiles)
    if len(outbounds) != 1:
        raise SystemExit("PROFILE_COUNT")
    outbound = json.loads(json.dumps(outbounds[0]))
    validate_profile(outbound)
    outbound["tag"] = "service-vpn"
    return {
        "log": {"loglevel": "none"},
        "inbounds": [
            {
                "tag": "browser-socks",
                "listen": "127.0.0.1",
                "port": 1080,
                "protocol": "socks",
                "settings": {"udp": False, "auth": "noauth"},
            }
        ],
        "outbounds": [outbound],
    }


def main():
    raw = open("/vpn-identity/subscription-url", encoding="utf8").read().strip()
    url = urlparse(raw)
    if (
        url.scheme != "https"
        or url.hostname != "vpn.alchemmist.xyz"
        or url.port
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
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
    print("VPN_SUBSCRIPTION_PREPARED")  # noqa: T201


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        print("VPN_SUBSCRIPTION_PREPARE_FAILED")  # noqa: T201
        raise
    except Exception:
        print("VPN_SUBSCRIPTION_PREPARE_FAILED")  # noqa: T201
        raise SystemExit(1)
