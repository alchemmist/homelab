"""Bounded anonymous OpenHands auth observations, never follow or emit OAuth material."""

import hashlib
import ipaddress
import re
import subprocess
from urllib.parse import parse_qsl, urlsplit

HOST = "openhands.socrat.alchemmist.xyz"
CALLBACK = "https://" + HOST + "/oauth2/callback"


def challenge(location):
    if (
        not isinstance(location, str)
        or len(location) > 4096
        or not location.isascii()
        or any(ord(c) <= 32 or ord(c) == 127 for c in location)
    ):
        raise ValueError("invalid authorization redirect")
    url = urlsplit(location)
    if (url.scheme, url.netloc, url.path, url.fragment) != (
        "https",
        "auth.socrat.alchemmist.xyz",
        "/application/o/authorize/",
        "",
    ):
        raise ValueError("unexpected authorization endpoint")
    pairs = parse_qsl(url.query, strict_parsing=True, keep_blank_values=True, max_num_fields=10)
    q = dict(pairs)
    if (
        len(pairs) != len(q)
        or set(q)
        != {
            "approval_prompt",
            "client_id",
            "code_challenge",
            "code_challenge_method",
            "redirect_uri",
            "response_type",
            "scope",
            "state",
        }
        or q["redirect_uri"] != CALLBACK
        or q["response_type"] != "code"
        or q["code_challenge_method"] != "S256"
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", q["code_challenge"])
        or not q["state"]
        or not q["client_id"]
        or sorted(q["scope"].split()) != ["groups", "offline_access", "openid", "profile"]
    ):
        raise ValueError("unexpected authorization contract")
    return tuple(hashlib.sha256(q[key].encode()).digest() for key in ("state", "code_challenge"))


def request(ip, path):
    if path not in ("/", "/oauth2/auth"):
        raise ValueError("unsupported auth probe")
    result = subprocess.run(
        [
            "curl",
            "--disable",
            "--noproxy",
            "*",
            "--proto",
            "=https",
            "--silent",
            "--max-filesize",
            "8192",
            "--connect-timeout",
            "4",
            "--max-time",
            "7",
            "--resolve",
            f"{HOST}:443:{ipaddress.IPv4Address(ip)}",
            "--write-out",
            "\\n%{response_code}\\n%header{location}",
            "https://" + HOST + path,
        ],
        capture_output=True,
        timeout=9,
    )
    if result.returncode:
        raise ValueError("incomplete HTTPS request")
    parts = result.stdout.rsplit(b"\n", 2)
    if len(parts) != 3:
        raise ValueError("incomplete response")
    body, status, location = parts
    if path == "/" and status == b"302":
        return challenge(location.decode("ascii"))
    if (
        path == "/oauth2/auth"
        and status == b"401"
        and not location
        and body in (b"Unauthorized", b"Unauthorized\n", b"Unauthorized\r\n")
    ):
        return True
    raise ValueError("unexpected anonymous response")


def check(ip):
    try:
        first = request(ip, "/")
        second = request(ip, "/")
        denied = request(ip, "/oauth2/auth")
        if first[0] == second[0] or first[1] == second[1] or denied is not True:
            return "unexpected-authorization-flow"
    except (OSError, subprocess.SubprocessError, ValueError):
        return "authorization-flow-unverified"
    return "matched"
