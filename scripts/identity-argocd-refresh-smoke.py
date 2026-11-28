#!/usr/bin/env python3
"""Explicit Argo CD native OIDC refresh acceptance with a temporary read-only observer.

Requires a reviewed refresh + end-to-end TLS deployment; fails closed before
creating fixtures when offline_access is absent. Expects renewed cookies to retain
Secure; Argo CD 3.5.6 server.insecure=true fails this check.
No real owner password/MFA is read or reset. No QR/secret/session traces are saved.
Requires Playwright + Chromium. Run from the owner Mac with --run.
"""

import argparse
from typing import Literal, TypedDict

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--run",
    action="store_true",
    help="Explicitly authorize temporary acceptance fixtures",
)
parser.add_argument(
    "--public-edge",
    choices=["109.173.40.247", "109.120.141.60"],
    default="109.173.40.247",
)
args = parser.parse_args()
if not args.run:
    parser.error("--run is required for a live fixture test")
import json
import subprocess
import urllib.error
import urllib.request

BASE = "https://auth.socrat.alchemmist.xyz"
HTTP_OK = 200
HTTP_CLIENT_ERROR = 400
MAX_TOKEN_LIFETIME_SECONDS = 305
PRIVILEGED_GROUP_DENYLIST = {"homelab-owner", "homelab-platform-operator"}
# Process-local public-edge resolution; keep verified TLS/SNI, no system DNS changes.
import socket

_original_getaddrinfo = socket.getaddrinfo


GaiResult = list[
    tuple[Literal[socket.AddressFamily.AF_INET], socket.SocketKind, int, str, tuple[str, int]]
    | tuple[
        Literal[socket.AddressFamily.AF_INET6],
        socket.SocketKind,
        int,
        str,
        tuple[str, int, int, int] | tuple[int, bytes],
    ]
]


def public_auth(
    host: str | bytes | None,
    port: bytes | str | int | None = None,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> GaiResult:
    """Resolve reviewed public-edge hostnames to the pinned edge address."""
    target = (
        args.public_edge
        if host in ["auth.socrat.alchemmist.xyz", "argocd.socrat.alchemmist.xyz"]
        else host
    )
    return _original_getaddrinfo(target, port, family, type, proto, flags)


socket.getaddrinfo = public_auth
SSH = [
    "ssh",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "Hostname=109.173.40.247",
    "-o",
    "HostKeyAlias=[socrat.alchemmist.xyz]:2222",
    "socrat-0",
]
credential = json.loads(
    subprocess.check_output([*SSH, "cat ~/.cache/homelab-authentik/credentials.json"])
)


def api(method: str, path: str, data: dict[str, object] | None = None) -> dict[str, object]:
    """Perform the reviewed Authentik API request and return its decoded body."""
    req = urllib.request.Request(
        BASE + "/api/v3/" + path,
        method=method,
        headers={
            "Authorization": "Bearer " + str(credential["AUTHENTIK_BOOTSTRAP_TOKEN"]),
            "Content-Type": "application/json",
        },
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(req, timeout=45) as r:
        body = r.read()
        return json.loads(body) if body else {}


import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse
import uuid
from typing import cast

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Response, sync_playwright


def results_of(response: dict[str, object]) -> list[dict[str, object]]:
    """Return a reviewed API page body list as typed objects."""
    value = response["results"]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        reason = "API results payload must be an object list"
        raise TypeError(reason)
    return value


provider = next(
    x
    for x in results_of(api("GET", "providers/oauth2/?page_size=100"))
    if x["name"] == "homelab-argocd"
)
offline = [
    x
    for x in results_of(api("GET", "propertymappings/provider/scope/?page_size=100"))
    if x["scope_name"] == "offline_access"
]
mappings = provider["property_mappings"]
if len(offline) != 1 or not isinstance(mappings, list) or offline[0]["pk"] not in mappings:
    msg = "Refresh deployment not activated; no fixtures created"
    raise SystemExit(msg)
username = "argocd-refresh-smoke-" + uuid.uuid4().hex[:10]
password = secrets.token_urlsafe(32)
group = next(
    x
    for x in results_of(api("GET", "core/groups/?name=homelab-observer"))
    if x["name"] == "homelab-observer"
)
user = api(
    "POST",
    "core/users/",
    {
        "username": username,
        "name": "Temporary Argo CD acceptance probe",
        "email": username + "@example.invalid",
        "groups": [group["pk"]],
        "is_active": True,
    },
)
binding = None
fixture_id = user["uuid"]
try:
    app = next(
        a
        for a in results_of(api("GET", "core/applications/?superuser_full_list=true&page_size=100"))
        if a["slug"] == "argocd"
    )
    binding = api(
        "POST",
        "policies/bindings/",
        {
            "target": app["pk"],
            "user": user["pk"],
            "order": 90 + secrets.randbelow(100000),
            "enabled": True,
            "failure_result": False,
        },
    )
    api(
        "POST",
        "core/users/" + str(user["pk"]) + "/set_password/",
        {"password": password},
    )

    class Claims(TypedDict):
        """JWT payload fields asserted by this smoke test."""

        groups: list[str]
        exp: float
        sub: str

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=[
                "--host-resolver-rules=MAP auth.socrat.alchemmist.xyz "
                + args.public_edge
                + ", MAP argocd.socrat.alchemmist.xyz "
                + args.public_edge
            ]
        )
        page = browser.new_page(viewport={"width": 1440, "height": 960})
        last: dict[str, object] = {}
        totp_challenge: dict[str, object] = {}
        components: list[str] = []
        errors: list[str] = []

        def observe(response: Response) -> None:
            """Watch the login journey and record stage/API details for review."""
            if (
                urllib.parse.urlparse(response.url).hostname == "argocd.socrat.alchemmist.xyz"
                and urllib.parse.urlparse(response.url).path == "/auth/login"
                and response.status in [302, 303, 307]
            ):
                authorization = urllib.parse.parse_qs(
                    urllib.parse.urlparse(response.headers.get("location", "")).query
                )
                if "offline_access" not in authorization.get("scope", [""])[0].split():
                    msg = "Live authorization must request offline_access"
                    raise RuntimeError(msg)
            if (
                urllib.parse.urlparse(response.url).hostname == "argocd.socrat.alchemmist.xyz"
                and "/auth/callback" in response.url
            ):
                print("Argo CD callback HTTP status:", response.status)
                if response.status >= HTTP_CLIENT_ERROR:
                    try:
                        import re

                        err = json.dumps(response.json())
                        print(
                            "Callback error classifications:",
                            [
                                word
                                for word in [
                                    "client",
                                    "pkce",
                                    "state",
                                    "scope",
                                    "userinfo",
                                    "issuer",
                                    "csrf",
                                    "missing",
                                    "secret",
                                    "insecure",
                                    "token",
                                    "redirect",
                                    "SyntaxError",
                                    "AttributeError",
                                    "NameError",
                                    "TypeError",
                                    "invalid",
                                ]
                                if word.lower() in err.lower()
                            ],
                        )
                        print(
                            "Callback exception types:",
                            re.findall(r"\b[A-Z][A-Za-z]+(?:Error|Exception)\b", err),
                        )
                    except (
                        ValueError,
                        TypeError,
                        IndexError,
                        KeyError,
                        AttributeError,
                        PlaywrightError,
                    ):
                        pass
            if "/api/v3/flows/executor/" in response.url and response.status in [
                HTTP_OK,
                HTTP_CLIENT_ERROR,
            ]:
                try:
                    data = response.json()
                    last.clear()
                    last.update(data)
                    print(
                        "Executor result:",
                        response.status,
                        data.get("type"),
                        data.get("component"),
                        "errors:",
                        bool(data.get("response_errors")),
                    )
                    if data.get("component"):
                        components.append(data["component"])
                    if data.get("component") == "ak-stage-authenticator-totp":
                        totp_challenge.clear()
                        totp_challenge.update(data)
                except (
                    ValueError,
                    TypeError,
                    IndexError,
                    KeyError,
                    AttributeError,
                    PlaywrightError,
                ):
                    pass

        page.on("response", observe)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(
            "https://argocd.socrat.alchemmist.xyz/auth/login?return_url=https%3A%2F%2Fargocd.socrat.alchemmist.xyz%2Fapplications"
        )
        page.locator('input[name="uidField"]').wait_for()
        page.locator('input[name="uidField"]').fill(username)
        page.locator("input[type=password]").filter(visible=True).fill(password)
        page.locator("button[type=submit]").click()
        page.wait_for_timeout(2000)
        for _step in range(60):
            if page.locator("ak-stage-authenticator-totp").is_visible():
                print("Native TOTP enrollment presented")
                config_url = totp_challenge.get("config_url")
                if not isinstance(config_url, str):
                    config_url = ""
                secret = (
                    totp_challenge.get("secret")
                    or totp_challenge.get("secret_key")
                    or urllib.parse.parse_qs(urllib.parse.urlparse(config_url).query).get(
                        "secret", [None]
                    )[0]
                )
                if not isinstance(secret, str) or not secret:
                    msg = "TOTP setup data unavailable"
                    raise RuntimeError(msg)
                source = secret
                key = base64.b32decode(source.upper() + "=" * ((-len(source)) % 8))
                sig = hmac.new(
                    key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1
                ).digest()
                offset = sig[-1] & 15
                code = str(
                    (struct.unpack(">I", sig[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000
                ).zfill(6)
                stage = page.locator("ak-stage-authenticator-totp")
                stage.locator("input[name=code]").fill(code)
                stage.locator("button[type=submit]").click()
                stage.wait_for(state="hidden", timeout=30000)
            elif page.locator("ak-stage-consent").is_visible():
                print("Native consent presented")
                slug = urllib.parse.urlparse(page.url).path.strip("/").split("/")[-1]
                inspection = page.request.get(BASE + "/api/v3/flows/inspector/" + slug + "/")
                if inspection.status not in (403, 404):
                    msg = "Observer must not inspect flows"
                    raise RuntimeError(msg)
                if page.get_by_role("button", name="Open flow inspector").is_visible():
                    msg = "Observer must not see the inspector toggle"
                    raise RuntimeError(msg)
                print("Observer native inspector access denied:", inspection.status)
                stage = page.locator("ak-stage-consent")
                stage.locator("button[name=continue]").click()
                stage.wait_for(state="hidden", timeout=30000)
            elif (
                urllib.parse.urlparse(page.url).hostname == "argocd.socrat.alchemmist.xyz"
                and "/applications" in urllib.parse.urlparse(page.url).path
            ):

                def claims() -> Claims:
                    """Perform the claims operation."""
                    c = next(
                        c
                        for c in page.context.cookies("https://argocd.socrat.alchemmist.xyz")
                        if c["name"] == "argocd.token"
                    )
                    if not c["secure"]:
                        msg = "Session cookie must remain Secure"
                        raise RuntimeError(msg)
                    raw = c["value"].split(".")[1]
                    payload: Claims = json.loads(
                        base64.urlsafe_b64decode(raw + "=" * ((-len(raw)) % 4))
                    )
                    return payload

                old = claims()
                if "homelab-observer" not in old["groups"]:
                    msg = "Session must carry the observer group"
                    raise RuntimeError(msg)
                if set(old["groups"]) & PRIVILEGED_GROUP_DENYLIST:
                    msg = "Session must not carry privileged groups"
                    raise RuntimeError(msg)

                def api_page(path: str) -> dict[str, object]:
                    """Fetch a native Argo CD API page through the browser session."""
                    response = page.goto("https://argocd.socrat.alchemmist.xyz" + path)
                    if response.status != HTTP_OK:
                        msg = "Native API page request failed"
                        raise RuntimeError(msg)
                    return cast("dict[str, object]", response.json())

                info = api_page("/api/v1/session/userinfo")
                if info.get("loggedIn") is not True:
                    msg = "Initial native session must be authenticated"
                    raise RuntimeError(msg)
                if api_page("/api/v1/account/can-i/applications/create/*")["value"] != "no":
                    msg = "Observer must not gain application creation rights"
                    raise RuntimeError(msg)
                old = claims()
                lifetime = old["exp"] - time.time()
                if not 0 < lifetime <= MAX_TOKEN_LIFETIME_SECONDS:
                    msg = "Session token lifetime must stay within the reviewed bound"
                    raise RuntimeError(msg)
                page.goto("about:blank")
                # No application polls/heartbeats during the idle period. Wait beyond the REAL
                # five-minute expiry; do not forge a JWT or shorten a production token lifetime.
                delay = max(0, old["exp"] - time.time() + 8)
                print(
                    "Native MFA and read-only login passed; waiting past actual token expiry:",
                    round(delay),
                    "seconds",
                    flush=True,
                )
                page.wait_for_timeout(delay * 1000)
                auth_navigations: list[bool] = []
                page.on(
                    "request",
                    lambda req, auth_navigations=auth_navigations: (
                        auth_navigations.append(True)
                        if req.is_navigation_request()
                        and urllib.parse.urlparse(req.url).hostname == "auth.socrat.alchemmist.xyz"
                        else None
                    ),
                )
                if api_page("/api/v1/session/userinfo").get("loggedIn") is not True:
                    msg = "Native session lost authentication"
                    raise RuntimeError(msg)
                new = claims()
                if new["exp"] <= old["exp"]:
                    msg = "Token was not renewed after idle expiry"
                    raise RuntimeError(msg)
                if new["sub"] != old["sub"]:
                    msg = "Renewed token subject changed"
                    raise RuntimeError(msg)
                if auth_navigations:
                    msg = "Browser must not navigate to IdP for refresh"
                    raise RuntimeError(msg)
                if api_page("/api/v1/account/can-i/applications/create/*")["value"] != "no":
                    msg = "Observer must not gain application creation rights"
                    raise RuntimeError(msg)
                print(
                    "PASS: expired five-minute token renewed after idle; "
                    "Secure preserved, same subject, no IdP navigation or admin grant",
                    flush=True,
                )
                # Then prove preemptive refresh as well, without forging tokens or changing TTL.
                active = new
                deadline = active["exp"] + 15
                while time.time() < deadline:
                    page.wait_for_timeout(15000)
                    before_request = time.time()
                    if api_page("/api/v1/session/userinfo").get("loggedIn") is not True:
                        msg = "Native session lost authentication"
                        raise RuntimeError(msg)
                    candidate = claims()
                    if candidate["exp"] > active["exp"]:
                        if before_request >= active["exp"]:
                            msg = "Active refresh must occur BEFORE expiry"
                            raise RuntimeError(msg)
                        if candidate["sub"] != old["sub"]:
                            msg = "Preemptive token subject changed"
                            raise RuntimeError(msg)
                        if auth_navigations:
                            msg = "Browser must not navigate to IdP for refresh"
                            raise RuntimeError(msg)
                        print(
                            "PASS: active preemptive refresh before expiry; "
                            "Secure preserved; no browser IdP redirect",
                            flush=True,
                        )
                        break
                else:
                    msg = "Preemptive renewal was not observed"
                    raise RuntimeError(msg)
                if api_page("/api/v1/account/can-i/applications/create/*")["value"] != "no":
                    msg = "Observer must not gain application creation rights"
                    raise RuntimeError(msg)
                break
            page.wait_for_timeout(500)
        else:
            print(
                "Final browser location:",
                urllib.parse.urlparse(page.url).hostname,
                urllib.parse.urlparse(page.url).path,
            )
            msg = "Browser roundtrip did not complete"
            raise RuntimeError(msg)
        print("Browser JS errors:", len(errors))
        if errors:
            msg = "The live refresh probes must run without page errors"
            raise RuntimeError(msg)
        browser.close()
finally:
    try:
        if binding:
            api("DELETE", "policies/bindings/" + str(binding["pk"]) + "/")
    finally:
        api("DELETE", "core/users/" + str(user["pk"]) + "/")
    print("Temporary Argo CD admission binding and Authentik identity removed", flush=True)
