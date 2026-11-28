"""Read-only: distinguish bot listener reachability from Telegram's configured address.

Never contact Telegram, a webhook or the IdP, and never emit redirect parameters.
No claim about remote Telegram registration or actual event delivery.
"""

import ipaddress
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import yaml

from ci.quality.public_web import CATALOG, ROOT

NS = "socrat-bot"
HOST = "bot.socrat.alchemmist.xyz"
NAME = "socrat-bot"
URL = "https://" + HOST + "/telegram/webhook"


def require(ok):
    if not ok:
        msg = "unverified bot configuration"
        raise ValueError(msg)


def redirect(location):
    try:
        parsed = urlsplit(location)
        return (
            parsed.scheme == "https"
            and parsed.netloc == "auth.socrat.alchemmist.xyz"
            and parsed.path == "/application/o/authorize/"
            and bool(parsed.query)
            and not parsed.fragment
            and not any(ord(c) < 32 for c in location)
        )
    except ValueError:
        return False


def wire(ip):
    args = [
        "curl",
        "--disable",
        "--noproxy",
        "*",
        "--silent",
        "--proto",
        "=https",
        "--resolve",
        HOST + ":443:" + ip,
        "--connect-timeout",
        "4",
        "--max-time",
        "8",
        "--max-filesize",
        "8192",
    ]
    result = []
    for path in ("/", "/healthz"):
        try:
            r = subprocess.run(
                [
                    *args,
                    "--write-out",
                    "\\n%{response_code}\\n%header{location}",
                    "https://" + HOST + path,
                ],
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "transport-unverified"
        if r.returncode:
            return "transport-unverified"
        body, sep, tail = r.stdout.rpartition(b"\n")
        payload, sep2, code = body.rpartition(b"\n")
        result.append(
            bool(
                sep
                and sep2
                and (
                    code == b"302" and redirect(tail.decode("ascii", "replace"))
                    if path == "/"
                    else code == b"404" and not tail and payload == b"404 page not found\n"
                )
            )
        )
    return "matched" if all(result) else "unexpected-response"


def fields(resource, expr, selector=None):
    args = ["kubectl", "--context=Socrat", "--request-timeout=6s", "-n", NS, "get", resource]
    args += ["-l", selector] if selector else []
    return subprocess.check_output(
        [*args, "-o", "jsonpath=" + expr], text=True, timeout=9, stderr=subprocess.DEVNULL
    )


def snapshot():
    # Project only the two non-secret settings from the application container.
    def settings(prefix):
        return "".join(
            '{"|"}{'
            + prefix
            + '.containers[?(@.name=="socrat-bot")].env[?(@.name=="'
            + key
            + '")].value}'
            for key in ("TELEGRAM_WEBHOOK_URL", "TELEGRAM_WEBHOOK_IP")
        )

    dep = fields(
        "deployment/" + NAME,
        "{.metadata.uid}|{.metadata.generation}|{.status.observedGeneration}|{.spec.replicas}|{.status.updatedReplicas}|{.status.readyReplicas}"
        + settings(".spec.template.spec"),
    ).split("|")
    require(len(dep) == 8 and dep[0] and dep[1] == dep[2] and dep[3:6] == ["1"] * 3)
    pod = fields(
        "pods",
        '{range .items[*]}{.metadata.uid}|{.metadata.deletionTimestamp}|{.status.conditions[?(@.type=="Ready")].status}|{.metadata.ownerReferences[?(@.controller==true)].kind}|{.metadata.ownerReferences[?(@.controller==true)].name}|{.metadata.ownerReferences[?(@.controller==true)].uid}'
        + settings(".spec")
        + '{"\\n"}{end}',
        "app.kubernetes.io/name=socrat-bot,app.kubernetes.io/instance=socrat-bot",
    ).splitlines()
    require(len(pod) == 1)
    p = pod[0].split("|")
    require(
        len(p) == 8
        and p[0]
        and p[1:4] == ["", "True", "ReplicaSet"]
        and p[5]
        and p[-2:] == dep[-2:]
    )
    rs = fields(
        "replicaset/" + p[4],
        "{.metadata.uid}|{.metadata.ownerReferences[?(@.controller==true)].kind}|{.metadata.ownerReferences[?(@.controller==true)].uid}",
    )
    require(rs == "|".join([p[5], "Deployment", dep[0]]))
    return tuple(dep), tuple(p)


def pin(site_ips, values, settings):
    require(
        values["telegram"]["webhookURL"] == settings[0] == URL
        and values["telegram"]["webhookIP"] == settings[1]
    )
    sites = [s for s, ip in site_ips.items() if ip == settings[1]]
    require(len(sites) == 1)
    return sites[0]


def main():
    try:
        ips = {
            s: str(ipaddress.IPv4Address(v["publicIP"]))
            for s, v in yaml.safe_load(CATALOG.read_text())["replicas"].items()
        }
        require(set(ips) == {"home", "nl", "moscow"} and len(set(ips.values())) == 3)
        before = snapshot()
        site = pin(
            ips,
            yaml.safe_load((ROOT / "deploy/socrat-bot/values.yaml").read_text()),
            before[0][-2:],
        )
        with ThreadPoolExecutor(3) as pool:
            routes = dict(zip(ips, pool.map(wire, ips.values()), strict=True))
        require(snapshot() == before)
    except (ValueError, KeyError, IndexError, OSError, subprocess.SubprocessError):
        print('{"observation":"incomplete"}')
        return 1
    print(
        json.dumps(
            {
                "anonymousRoutes": routes,
                "configuredWebhookIPSite": site,
                "telegramRegistrationVerified": False,
                "eventDeliveryVerified": False,
            },
            sort_keys=True,
        )
    )
    return int(any(r != "matched" for r in routes.values()))


if __name__ == "__main__":
    raise SystemExit(main())
