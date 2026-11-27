"""Recognize the two reviewed status routes and their shared read-only policy proxy."""

import hashlib
import json
import subprocess

import yaml

from ci.quality.public_web import ROOT

NS = "uptime-kuma"
PROXY = "public-web-kuma-proxy"
# Canonical JSON of the reviewed owner render. Re-review on any proxy change;
# do not pin the changing Gatus monitor inventory or turn it into a destination.
POLICY = {
    (
        "ConfigMap",
        "public-web-kuma-policy",
    ): "6bcc9661604132aca587cdffa2d3d7f5a19c96eb73df6f4d2fd09f0859e86400",
    ("Deployment", PROXY): "9f2a8fe63addefbb8f65687e478f74732d73c18e0a2241bedceb6d666a16e0cf",
    ("Service", PROXY): "54a8c444d13caea50afed9fdee711eb3b63ba81f644d66e9a17b85a6e4da186d",
}
SPREAD_DIGEST = "f84b64d3493f8fb797df29b90ac5f35c1b1bd9ad758163fba03bd5b566606750"
SPREAD = "publicEntry.kumaPolicyProxy.spreadAcrossEntrances"
STATUS = "status.alchemmist.xyz"
LEGACY = "kuma.socrat.alchemmist.xyz"
ROUTES = {
    STATUS: (
        "closedStatus",
        NS,
        "uptime-kuma-tls",
        "dda9eaab147a9a38e5398ce2376009b743467f76be9135f4a0f339cf7bfcbbce",
    ),
    LEGACY: (
        "closedStatusRedirect",
        "kuma-admin-browser",
        "public-web-kuma-admin-tls",
        "0cadee1a84bd1fc1f8b2fe9ce553cc9c026d3dea0e947ccb0264e56bfca4d4a5",
    ),
}


def admission(rows, catalog):
    result = {bit: False for bit, *_ in ROUTES.values()}
    hashes = {}
    seen = set()
    monitored = set(POLICY) | {("Ingress", name) for _, name, _, _ in ROUTES.values()}
    claims = {}
    for obj in rows:
        kind = obj["kind"]
        meta = obj["metadata"]
        key = kind, meta["name"]
        if key in seen or kind not in {
            "Ingress",
            "ConfigMap",
            "Deployment",
            "Service",
            "ServiceAccount",
        }:
            return result
        seen.add(key)
        if key in monitored:
            hashes[key] = hashlib.sha256(
                json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        if kind == "Ingress":
            if key not in monitored or "defaultBackend" in obj["spec"]:
                return result
            for rule in obj["spec"]["rules"]:
                if rule.get("host") not in ROUTES:
                    return result
                claims.setdefault(rule["host"], []).append(key)
        if (
            kind == "Deployment"
            and key != ("Deployment", PROXY)
            and obj["spec"]["template"].get("metadata", {}).get("labels", {}).get("app") == PROXY
        ):
            return result
    if not all(
        hashes.get(k) in ({v, SPREAD_DIGEST} if k == ("Deployment", PROXY) else {v})
        for k, v in POLICY.items()
    ):
        return result
    for host, (bit, ing, pin, digest) in ROUTES.items():
        key = "Ingress", ing
        result[bit] = (
            catalog["hosts"].get(NS, {}).get(host) == {"dns": "managed", "tlsSourceName": pin}
            and claims.get(host) == [key]
            and hashes.get(key) == digest
        )
    return result


def owner_objects():
    spec = yaml.safe_load((ROOT / "deploy/argocd/apps/uptime-kuma.yaml").read_text())["spec"]
    src = spec["source"]
    helm = src.get("helm", {})
    params = helm.get("parameters", [])
    if (
        "sources" in spec
        or src
        != {
            "repoURL": "https://github.com/alchemmist/homelab.git",
            "targetRevision": "main",
            "path": "charts/uptime-kuma",
            "helm": {"releaseName": NS, "parameters": params},
        }
        or spec["destination"] != {"namespace": NS, "server": "https://kubernetes.default.svc"}
        or not isinstance(params, list)
        or any(
            p
            not in [
                {"name": "publicStatusHost", "value": STATUS},
                {"name": "publicStatusHost", "value": ""},
                {"name": SPREAD, "value": "true"},
                {"name": SPREAD, "value": "false"},
            ]
            for p in params
        )
        or len({p["name"] for p in params}) != len(params)
    ):
        raise ValueError("unreviewed status release inputs")
    args = ["helm", "template", NS, str(ROOT / src["path"]), "-n", NS]
    for p in params:
        args += ["--set", p["name"] + "=" + p["value"]]
    return [d for d in yaml.safe_load_all(subprocess.check_output(args)) if d]


def render_status(catalog):
    return admission(owner_objects(), catalog)
