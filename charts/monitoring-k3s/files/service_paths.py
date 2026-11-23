"""Read-only Service and control-plane probes. Never export response bodies or tokens."""

import http.client
import ipaddress
import json
import os
import socket
import ssl
import threading
import time
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import override

SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
SLICE = "/apis/discovery.k8s.io/v1/namespaces/socrat-bot/endpointslices?labelSelector=kubernetes.io%2Fservice-name%3Dsocrat-bot"
SERVICE = "socrat-bot.socrat-bot.svc"
TARGETS = ("10.250.0.1", "10.250.0.3", "10.250.0.41")


def api(host: str, port: int, path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPSConnection(
        host,
        port,
        timeout=2,
        context=ssl.create_default_context(cafile=str(SA / "ca.crt")),
    )
    try:
        conn.request(
            "GET",
            path,
            headers={"Authorization": "Bearer " + (SA / "token").read_text().strip()},
        )
        res = conn.getresponse()
        return res.status, res.read(262145)
    finally:
        conn.close()


def snapshot() -> tuple[list[tuple[str, str]], list[tuple[str, int]]]:
    status, raw = api("kubernetes.default.svc", 443, SLICE)
    if status != 200 or len(raw) > 262144:
        msg = "discovery unavailable"
        raise ValueError(msg)
    items = json.loads(raw)["items"]
    targets: set[tuple[str, int]] = set()
    for item in items:
        if item["addressType"] != "IPv4":
            continue
        for port in item["ports"]:
            if port["name"] != "http" or port["protocol"] != "TCP":
                continue
            for ep in item["endpoints"]:
                if ep["conditions"].get("ready") is True and not ep["conditions"].get(
                    "terminating"
                ):
                    targets.update(
                        (str(ipaddress.IPv4Address(addr)), port["port"]) for addr in ep["addresses"]
                    )
    return sorted((x["metadata"]["uid"], x["metadata"]["resourceVersion"]) for x in items), sorted(
        targets
    )


def health(host: str, port: int) -> str:
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("GET", "/healthz")
        return "ok" if conn.getresponse().status == 200 else "failed"
    except socket.gaierror:
        return "dns"
    except (OSError, http.client.HTTPException):
        return "failed"
    finally:
        conn.close()


def pair() -> str:
    for _ in range(2):
        version, targets = snapshot()
        if not targets:
            return "no_endpoint"
        try:
            vip = socket.gethostbyname(SERVICE)
        except socket.gaierror:
            return "service_dns"
        expected = os.environ.get("BOT_SERVICE_VIP", "").strip()
        if not expected:
            return "probe_config_error"
        if vip != expected:
            return "service_vip_policy_mismatch"
        via = health(SERVICE, 8080)
        direct = [health(*addr) for addr in targets]
        if (version, targets) != snapshot():
            continue
        if via == "dns":
            return "service_dns"
        if any(x != "ok" for x in direct):
            return "endpoint_failed"
        return "ok" if via == "ok" else "service_only_failed"
    return "changing"


def control(host: str, path: str) -> str:
    try:
        code, raw = api(host, 6443, path)
        if code in (401, 403):
            return "authorization"
        if code != 200:
            return "http_error"
        if path == "/readyz":
            valid = raw.strip() == b"ok"
        else:
            valid = json.loads(raw)["data"]["canary"] == "service-path-v1"
        return "ok" if valid else "invalid_response"
    except ssl.SSLError:
        return "tls"
    except (OSError, http.client.HTTPException):
        return "transport"
    except (ValueError, KeyError):
        return "invalid_response"


metrics: dict[str, str] = {}
lock = threading.Lock()


def observe(key: str, lines: Iterable[str]) -> None:
    with lock:
        metrics[key] = "\n".join(lines)


def service_loop() -> None:
    streak = 0
    while True:
        start = time.monotonic()
        try:
            state = pair()
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            state = "discovery_error"
        streak = streak + 1 if state == "service_only_failed" else 0
        observe(
            "pair",
            [
                f'socrat_service_path_state{{state="{state}"}} 1',
                f"socrat_service_path_divergence_streak {streak}",
                f"socrat_service_path_sample_seconds {time.time()}",
            ],
        )
        time.sleep(max(0, 15 - (time.monotonic() - start)))


def control_loop(host: str) -> None:
    while True:
        start = time.monotonic()
        lines = []
        for check, path in [
            ("ready", "/readyz"),
            ("read", "/api/v1/namespaces/automation/configmaps/socrat-api-read-canary"),
        ]:
            state = control(host, path)
            lines.append(
                f'socrat_control_path_state{{target="{host}",check="{check}",state="{state}"}} 1'
            )
        observe(host, lines)
        time.sleep(max(0, 15 - (time.monotonic() - start)))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/metrics":
            self.send_error(404)
            return
        with lock:
            body = ("\n".join(metrics.values()) + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    @override
    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    threading.Thread(target=service_loop, daemon=True).start()
    if os.environ["SOURCE"] == "socrat-3":
        for target in TARGETS:
            threading.Thread(target=control_loop, args=(target,), daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", 9119), Handler).serve_forever()
